import io
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

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
