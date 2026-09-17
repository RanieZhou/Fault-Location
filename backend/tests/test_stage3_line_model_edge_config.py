import io

from fastapi.testclient import TestClient
from openpyxl import Workbook

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


def _create_network_with_edges(client: TestClient, rows: list[tuple]) -> tuple[str, dict]:
    response = client.post("/api/networks", json={"name": "Test Feeder"})
    network_id = response.json()["network_id"]
    file_bytes = _make_workbook_bytes(rows)
    client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )
    graph = client.get(f"/api/networks/{network_id}/graph").json()
    return network_id, graph


def _create_line_model(client: TestClient, **overrides) -> dict:
    payload = {
        "line_type": "overhead",
        "model_name": "JKLYJ-120",
        "r_ohm_per_km": 0.253,
        "x_ohm_per_km": 0.35,
        "c_nf_per_km": 9.6,
    }
    payload.update(overrides)
    response = client.post("/api/line-models", json=payload)
    assert response.status_code == 200
    return response.json()


def test_line_model_crud(client: TestClient) -> None:
    created = _create_line_model(client)
    assert created["source"] == "custom"
    assert created["enabled"] is True

    listed = client.get("/api/line-models").json()
    assert any(lm["line_model_id"] == created["line_model_id"] for lm in listed)

    updated = client.patch(f"/api/line-models/{created['line_model_id']}", json={"enabled": False})
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    enabled_only = client.get("/api/line-models", params={"enabled_only": True}).json()
    assert all(lm["line_model_id"] != created["line_model_id"] for lm in enabled_only)

    delete_resp = client.delete(f"/api/line-models/{created['line_model_id']}")
    assert delete_resp.status_code == 204


def test_delete_line_model_referenced_by_edge_is_rejected(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    line_model = _create_line_model(client)
    edge_id = graph["edges"][0]["edge_id"]

    client.patch(f"/api/edges/{edge_id}", json={"line_model_id": line_model["line_model_id"], "length_km": 0.5})

    delete_resp = client.delete(f"/api/line-models/{line_model['line_model_id']}")
    assert delete_resp.status_code == 409


def test_edge_single_config_computes_physics(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    line_model = _create_line_model(client, r_ohm_per_km=0.2, x_ohm_per_km=0.4, c_nf_per_km=10.0)
    edge_id = graph["edges"][0]["edge_id"]

    response = client.patch(
        f"/api/edges/{edge_id}", json={"line_model_id": line_model["line_model_id"], "length_km": 2.0}
    )
    assert response.status_code == 200

    updated_graph = client.get(f"/api/networks/{network_id}/graph").json()
    edge = next(e for e in updated_graph["edges"] if e["edge_id"] == edge_id)
    assert edge["r_ohm"] == 0.4
    assert edge["x_ohm"] == 0.8
    assert edge["c_nf"] == 20.0
    assert edge["line_type"] == "overhead"


def test_edge_config_rejects_disabled_or_missing_line_model(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    line_model = _create_line_model(client)
    client.patch(f"/api/line-models/{line_model['line_model_id']}", json={"enabled": False})
    edge_id = graph["edges"][0]["edge_id"]

    disabled_resp = client.patch(
        f"/api/edges/{edge_id}", json={"line_model_id": line_model["line_model_id"], "length_km": 1.0}
    )
    assert disabled_resp.status_code == 400

    missing_resp = client.patch(f"/api/edges/{edge_id}", json={"line_model_id": "LM999999", "length_km": 1.0})
    assert missing_resp.status_code == 400


def test_batch_config_applies_model_but_not_length_unless_requested(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(
        client,
        [
            ("L001", "#1", "#2", "closed", ""),
            ("L002", "#2", "#3", "closed", ""),
        ],
    )
    line_model = _create_line_model(client)
    edge_ids = [e["edge_id"] for e in graph["edges"]]

    response = client.post(
        "/api/edges/batch-config",
        json={"edge_ids": edge_ids, "line_model_id": line_model["line_model_id"]},
    )
    assert response.status_code == 200
    for edge in response.json():
        assert edge["line_model_id"] == line_model["line_model_id"]
        assert edge["length_km"] is None

    response2 = client.post(
        "/api/edges/batch-config",
        json={
            "edge_ids": edge_ids,
            "line_model_id": line_model["line_model_id"],
            "apply_length": True,
            "length_km": 0.75,
        },
    )
    assert response2.status_code == 200
    for edge in response2.json():
        assert edge["length_km"] == 0.75


def test_edges_table_view_reports_configured_state(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(
        client,
        [
            ("L001", "#1", "#2", "closed", ""),
            ("L002", "#2", "#3", "closed", ""),
        ],
    )
    line_model = _create_line_model(client)
    edge_id = graph["edges"][0]["edge_id"]
    client.patch(f"/api/edges/{edge_id}", json={"line_model_id": line_model["line_model_id"], "length_km": 1.2})

    table = client.get(f"/api/networks/{network_id}/edges").json()
    assert len(table) == 2
    configured_row = next(r for r in table if r["edge_id"] == edge_id)
    assert configured_row["configured"] is True
    assert configured_row["model_name"] == "JKLYJ-120"
    unconfigured_row = next(r for r in table if r["edge_id"] != edge_id)
    assert unconfigured_row["configured"] is False
