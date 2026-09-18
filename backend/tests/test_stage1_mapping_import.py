import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.models import BaselineStat, Edge, LineModel, MeasurementFieldMapping, MeasurementRecord, Monitor, Node

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "templates" / "Topology_Mapping_Template.xlsx"

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _make_workbook_bytes(rows: list[tuple], header=("edge_key", "node_1", "node_2", "status", "remark")) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Edges"
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _create_network(client: TestClient) -> str:
    response = client.post("/api/networks", json={"name": "Test Feeder"})
    assert response.status_code == 200
    return response.json()["network_id"]


def test_list_networks_returns_all_created_networks(client: TestClient) -> None:
    first_id = _create_network(client)
    second_id = client.post("/api/networks", json={"name": "Second Feeder"}).json()["network_id"]

    response = client.get("/api/networks")
    assert response.status_code == 200
    ids = {n["network_id"] for n in response.json()}
    assert {first_id, second_id} <= ids


def test_example_7bus_recovers_correct_nodes_and_edges(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = TEMPLATE_PATH.read_bytes()

    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("Topology_Mapping_Template.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
        data={"sheet_name": "Example_7Bus"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["imported"] is True
    assert result["errors"] == []
    assert result["nodes"] == 7
    assert result["edges"] == 6
    assert result["components"] == 1
    assert result["cycles"] == 0
    assert result["open_edges"] == 0


def test_duplicate_reverse_edge_blocks_import(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes(
        [
            ("L001", "#1", "#2", "closed", ""),
            ("L002", "#2", "#1", "closed", ""),
        ]
    )

    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["imported"] is False
    codes = {issue["code"] for issue in result["errors"]}
    assert "duplicate_edge" in codes


def test_self_loop_blocks_import(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes([("L001", "#1", "#1", "closed", "")])

    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )

    result = response.json()
    assert result["imported"] is False
    codes = {issue["code"] for issue in result["errors"]}
    assert "self_loop" in codes


def test_missing_node_blocks_import(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes([("L001", "", "#2", "closed", "")])

    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )

    result = response.json()
    assert result["imported"] is False
    codes = {issue["code"] for issue in result["errors"]}
    assert "missing_node_1" in codes


def test_multiple_components_and_cycle_are_warnings_not_errors(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes(
        [
            ("L001", "#1", "#2", "closed", ""),
            ("L002", "#2", "#3", "closed", ""),
            ("L003", "#3", "#1", "closed", ""),  # closes a cycle
            ("L004", "#10", "#11", "closed", ""),  # separate component
        ]
    )

    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )

    result = response.json()
    assert result["imported"] is True
    assert result["errors"] == []
    assert result["components"] == 2
    assert result["cycles"] == 1
    codes = {issue["code"] for issue in result["warnings"]}
    assert "multiple_components" in codes
    assert "cycle_detected" in codes
    assert "source_not_set" in codes


def test_reimport_into_existing_network_is_rejected(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes([("L001", "#1", "#2", "closed", "")])

    first = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )
    assert first.json()["imported"] is True

    second = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )
    assert second.status_code == 400


def test_delete_network_cascades_but_keeps_shared_line_models(client: TestClient, db_session: Session) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes([("L001", "#1", "#2", "closed", "")])
    client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )
    graph = client.get(f"/api/networks/{network_id}/graph").json()
    node_a = graph["nodes"][0]["node_id"]
    edge_id = graph["edges"][0]["edge_id"]
    client.post(f"/api/networks/{network_id}/source", json={"node_id": node_a})

    line_model_id = client.post(
        "/api/line-models",
        json={
            "line_type": "overhead",
            "model_name": "JKLYJ-120",
            "r_ohm_per_km": 0.253,
            "x_ohm_per_km": 0.35,
            "c_nf_per_km": 9.6,
        },
    ).json()["line_model_id"]
    client.patch(f"/api/edges/{edge_id}", json={"line_model_id": line_model_id, "length_km": 0.5})

    monitor_id = client.post(
        f"/api/networks/{network_id}/monitors", json={"node_id": node_a, "canonical_name": "M-DEL"}
    ).json()["monitor_id"]
    client.post(f"/api/networks/{network_id}/measurements/mapping", json={"mapping": {"monitor_name": "监测点名称1"}})

    measurement_wb = Workbook()
    sheet = measurement_wb.active
    sheet.append(["监测点名称1", "设备类型", "终端状态", "线路状态", "预警状态", "A相电压(kV)", "量测时间"])
    sheet.append(["M-DEL", "配电线路", "正常", "正常", "正常", 10.0, "2026-01-01 00:00:00"])
    buffer = io.BytesIO()
    measurement_wb.save(buffer)
    client.post(
        f"/api/networks/{network_id}/measurements/import",
        files={"file": ("prod.xlsx", buffer.getvalue(), XLSX_CONTENT_TYPE)},
    )
    client.post(f"/api/networks/{network_id}/baseline/build")

    # Sanity check: every child table actually has a row scoped to this network before deleting.
    assert db_session.query(Node).filter(Node.network_id == network_id).count() > 0
    assert db_session.query(Edge).filter(Edge.network_id == network_id).count() > 0
    assert db_session.query(Monitor).filter(Monitor.network_id == network_id).count() > 0
    assert db_session.query(MeasurementFieldMapping).filter(MeasurementFieldMapping.network_id == network_id).count() > 0
    assert db_session.query(MeasurementRecord).filter(MeasurementRecord.network_id == network_id).count() > 0
    assert db_session.query(BaselineStat).filter(BaselineStat.monitor_id == monitor_id).count() > 0

    response = client.delete(f"/api/networks/{network_id}")
    assert response.status_code == 204

    assert client.get(f"/api/networks/{network_id}").status_code == 404
    assert network_id not in {n["network_id"] for n in client.get("/api/networks").json()}

    db_session.expire_all()
    assert db_session.query(Node).filter(Node.network_id == network_id).count() == 0
    assert db_session.query(Edge).filter(Edge.network_id == network_id).count() == 0
    assert db_session.query(Monitor).filter(Monitor.network_id == network_id).count() == 0
    assert db_session.query(MeasurementFieldMapping).filter(MeasurementFieldMapping.network_id == network_id).count() == 0
    assert db_session.query(MeasurementRecord).filter(MeasurementRecord.network_id == network_id).count() == 0
    assert db_session.query(BaselineStat).filter(BaselineStat.monitor_id == monitor_id).count() == 0

    # The line model is a shared catalog entry, not owned by this network -- it must survive.
    assert db_session.get(LineModel, line_model_id) is not None


def test_delete_missing_network_returns_404(client: TestClient) -> None:
    response = client.delete("/api/networks/NET999999")
    assert response.status_code == 404
