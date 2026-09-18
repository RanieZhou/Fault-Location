import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.services.measurement_adapter import DEFAULT_FIELD_MAPPING

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PRODUCTION_HEADER = list(DEFAULT_FIELD_MAPPING.values())


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


def _measurement_row(monitor_name: str, va: float, timestamp: str, **overrides) -> list:
    base = {
        "监测点名称1": monitor_name,
        "设备类型": "配电线路",
        "终端状态": "正常",
        "线路状态": "正常",
        "预警状态": "正常",
        "A相电压(kV)": va,
        "B相电压(kV)": 10.02,
        "C相电压(kV)": 10.03,
        "A相电流(A)": 5.1,
        "B相电流(A)": 5.2,
        "C相电流(A)": 5.3,
        "A相电压相位": 0.0,
        "B相电压相位": -120.0,
        "C相电压相位": 120.0,
        "A相电流相位": 1.0,
        "B相电流相位": -119.0,
        "C相电流相位": 121.0,
        "量测时间": timestamp,
    }
    base.update(overrides)
    return [base.get(col) for col in PRODUCTION_HEADER]


def _make_measurement_workbook(rows: list[list]) -> bytes:
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Sheet1"
    sheet.append(PRODUCTION_HEADER)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _fully_configure_network(client: TestClient) -> tuple[str, str]:
    """Builds a minimal 2-node/1-edge network through every stage up to (but
    not including) baseline build, and returns (network_id, monitor_id)."""
    network_id = client.post("/api/networks", json={"name": "Readiness Test"}).json()["network_id"]

    mapping_bytes = _make_workbook_bytes([("L001", "#1", "#2", "closed", "")])
    import_resp = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", mapping_bytes, XLSX_CONTENT_TYPE)},
    )
    assert import_resp.json()["imported"] is True

    graph = client.get(f"/api/networks/{network_id}/graph").json()
    node_a = graph["nodes"][0]["node_id"]
    edge_id = graph["edges"][0]["edge_id"]

    source_resp = client.post(f"/api/networks/{network_id}/source", json={"node_id": node_a})
    assert source_resp.status_code == 200

    line_model = client.post(
        "/api/line-models",
        json={
            "line_type": "overhead",
            "model_name": "JKLYJ-120",
            "r_ohm_per_km": 0.253,
            "x_ohm_per_km": 0.35,
            "c_nf_per_km": 9.6,
        },
    ).json()
    edge_config_resp = client.patch(
        f"/api/edges/{edge_id}", json={"line_model_id": line_model["line_model_id"], "length_km": 0.5}
    )
    assert edge_config_resp.status_code == 200

    monitor = client.post(
        f"/api/networks/{network_id}/monitors", json={"node_id": node_a, "canonical_name": "M-READY"}
    ).json()

    return network_id, monitor["monitor_id"]


def test_readiness_fails_when_incomplete(client: TestClient) -> None:
    network_id = client.post("/api/networks", json={"name": "Empty"}).json()["network_id"]
    response = client.get(f"/api/networks/{network_id}/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False

    items_by_key = {item["key"]: item["passed"] for item in body["items"]}
    # A brand new network has no topology, no source, no monitor, and no
    # baseline -- those must fail outright. edge_config/line_models/
    # measurement_mapping are vacuously true with zero edges/models/records,
    # which is correct: the topology/monitor/baseline checks are what catch
    # an empty network, not those vacuous ones.
    assert items_by_key["topology"] is False
    assert items_by_key["source"] is False
    assert items_by_key["monitor_exists"] is False
    assert items_by_key["baseline"] is False


def test_full_pipeline_reaches_network_ready(client: TestClient) -> None:
    network_id, monitor_id = _fully_configure_network(client)

    readiness_before_data = client.get(f"/api/networks/{network_id}/readiness").json()
    assert readiness_before_data["ready"] is False
    baseline_item = next(i for i in readiness_before_data["items"] if i["key"] == "baseline")
    assert baseline_item["passed"] is False

    rows = [
        _measurement_row("M-READY", 10.00, "2026-01-01 00:00:00"),
        _measurement_row("M-READY", 10.02, "2026-01-01 00:15:00"),
        _measurement_row("M-READY", 9.98, "2026-01-01 00:30:00"),
        # Should be excluded from baseline: warning_status not normal.
        _measurement_row("M-READY", 99.0, "2026-01-01 00:45:00", **{"预警状态": "异常"}),
    ]
    measurement_bytes = _make_measurement_workbook(rows)
    import_resp = client.post(
        f"/api/networks/{network_id}/measurements/import",
        files={"file": ("prod.xlsx", measurement_bytes, XLSX_CONTENT_TYPE)},
    )
    assert import_resp.json()["matched"] == 4
    assert import_resp.json()["unmatched"] == 0

    build_resp = client.post(f"/api/networks/{network_id}/baseline/build")
    assert build_resp.status_code == 200
    build_result = build_resp.json()
    assert build_result["monitors_with_baseline"] == 1
    assert build_result["baseline_rows"] == 12  # all 12 signals have data

    baseline = client.get(f"/api/networks/{network_id}/baseline").json()
    va_stat = next(b for b in baseline if b["signal"] == "Va")
    assert va_stat["monitor_id"] == monitor_id
    assert va_stat["count"] == 3  # the abnormal-warning row must be excluded
    assert abs(va_stat["mean"] - 10.0) < 1e-9

    readiness = client.get(f"/api/networks/{network_id}/readiness").json()
    assert readiness["ready"] is True
    assert all(item["passed"] for item in readiness["items"])

    network = client.get(f"/api/networks/{network_id}").json()
    assert network["status"] == "READY"


def test_readiness_blocked_by_pending_unmatched_measurement(client: TestClient) -> None:
    network_id, _monitor_id = _fully_configure_network(client)

    rows = [_measurement_row("Some-Unknown-Device", 10.0, "2026-01-01 00:00:00")]
    client.post(
        f"/api/networks/{network_id}/measurements/import",
        files={"file": ("prod.xlsx", _make_measurement_workbook(rows), XLSX_CONTENT_TYPE)},
    )
    client.post(f"/api/networks/{network_id}/baseline/build")

    readiness = client.get(f"/api/networks/{network_id}/readiness").json()
    assert readiness["ready"] is False
    mapping_item = next(i for i in readiness["items"] if i["key"] == "measurement_mapping")
    assert mapping_item["passed"] is False


def test_phase_baseline_uses_circular_mean_not_arithmetic_mean(client: TestClient) -> None:
    network_id, _monitor_id = _fully_configure_network(client)

    # 359 deg and 1 deg are 2 deg apart on the circle; the correct mean is
    # ~0 deg. A plain arithmetic mean would wrongly give (359+1)/2 = 180 deg.
    rows = [
        _measurement_row("M-READY", 10.0, "2026-01-01 00:00:00", **{"A相电压相位": 359.0}),
        _measurement_row("M-READY", 10.0, "2026-01-01 00:15:00", **{"A相电压相位": 1.0}),
    ]
    client.post(
        f"/api/networks/{network_id}/measurements/import",
        files={"file": ("prod.xlsx", _make_measurement_workbook(rows), XLSX_CONTENT_TYPE)},
    )
    build_resp = client.post(f"/api/networks/{network_id}/baseline/build")
    assert build_resp.status_code == 200

    baseline = client.get(f"/api/networks/{network_id}/baseline").json()
    phase_stat = next(b for b in baseline if b["signal"] == "phase_Va")
    assert phase_stat["count"] == 2
    assert abs(phase_stat["mean"]) < 1e-6
    assert abs(phase_stat["std"] - 1.0) < 0.01

    # Magnitude signals must be completely unaffected by the phase-only branch.
    va_stat = next(b for b in baseline if b["signal"] == "Va")
    assert abs(va_stat["mean"] - 10.0) < 1e-9
