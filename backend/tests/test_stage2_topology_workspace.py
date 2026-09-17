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


def _import_example_7bus(client: TestClient) -> str:
    network_id = _create_network(client)
    file_bytes = TEMPLATE_PATH.read_bytes()
    response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("Topology_Mapping_Template.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
        data={"sheet_name": "Example_7Bus"},
    )
    assert response.json()["imported"] is True
    return network_id


def _graph(client: TestClient, network_id: str) -> dict:
    response = client.get(f"/api/networks/{network_id}/graph")
    assert response.status_code == 200
    return response.json()


def _node_id_by_key(graph: dict, node_key: str) -> str:
    for node in graph["nodes"]:
        if node["node_key"] == node_key:
            return node["node_id"]
    raise AssertionError(f"node_key {node_key} not found")


def _edge_direction_by_key(graph: dict, edge_key: str) -> tuple[str, str]:
    node_key_by_id = {n["node_id"]: n["node_key"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        if edge["edge_key"] == edge_key:
            return node_key_by_id[edge["source_node_id"]], node_key_by_id[edge["target_node_id"]]
    raise AssertionError(f"edge_key {edge_key} not found")


def test_source_set_orients_edges_away_from_source(client: TestClient) -> None:
    network_id = _import_example_7bus(client)
    graph = _graph(client, network_id)
    source_node_id = _node_id_by_key(graph, "SOURCE")

    response = client.post(f"/api/networks/{network_id}/source", json={"node_id": source_node_id})
    assert response.status_code == 200
    assert response.json()["source_node_id"] == source_node_id
    assert response.json()["status"] == "CONFIGURING"

    graph = _graph(client, network_id)
    assert _edge_direction_by_key(graph, "L001") == ("SOURCE", "#1")
    assert _edge_direction_by_key(graph, "L002") == ("#1", "#2")
    assert _edge_direction_by_key(graph, "L003") == ("#2", "#3")
    assert _edge_direction_by_key(graph, "L004") == ("#2", "#2.1")
    assert _edge_direction_by_key(graph, "L005") == ("#2.1", "#2.2")
    assert _edge_direction_by_key(graph, "L006") == ("#2", "#2.3")


def test_changing_source_recomputes_direction(client: TestClient) -> None:
    network_id = _import_example_7bus(client)
    graph = _graph(client, network_id)
    source_node_id = _node_id_by_key(graph, "SOURCE")
    client.post(f"/api/networks/{network_id}/source", json={"node_id": source_node_id})

    new_source_id = _node_id_by_key(graph, "#3")
    response = client.post(f"/api/networks/{network_id}/source", json={"node_id": new_source_id})
    assert response.status_code == 200
    assert response.json()["source_node_id"] == new_source_id

    graph = _graph(client, network_id)
    assert _edge_direction_by_key(graph, "L003") == ("#3", "#2")
    assert _edge_direction_by_key(graph, "L002") == ("#2", "#1")
    assert _edge_direction_by_key(graph, "L001") == ("#1", "SOURCE")
    assert _edge_direction_by_key(graph, "L004") == ("#2", "#2.1")
    assert _edge_direction_by_key(graph, "L006") == ("#2", "#2.3")
    assert _edge_direction_by_key(graph, "L005") == ("#2.1", "#2.2")


def test_open_edge_excluded_from_running_graph_direction(client: TestClient) -> None:
    network_id = _create_network(client)
    file_bytes = _make_workbook_bytes(
        [
            ("L001", "#1", "#2", "closed", ""),
            ("L002", "#2", "#3", "open", "tie switch"),
            ("L003", "#3", "#4", "closed", ""),
        ]
    )
    import_response = client.post(
        f"/api/networks/{network_id}/mapping/import",
        files={"file": ("mapping.xlsx", file_bytes, XLSX_CONTENT_TYPE)},
    )
    assert import_response.json()["imported"] is True

    graph = _graph(client, network_id)
    source_node_id = _node_id_by_key(graph, "#1")
    client.post(f"/api/networks/{network_id}/source", json={"node_id": source_node_id})

    graph = _graph(client, network_id)
    assert _edge_direction_by_key(graph, "L001") == ("#1", "#2")

    node_key_by_id = {n["node_id"]: n["node_key"] for n in graph["nodes"]}
    open_edge = next(e for e in graph["edges"] if e["edge_key"] == "L002")
    assert open_edge["source_node_id"] is None
    assert open_edge["target_node_id"] is None

    # #3/#4 are only reachable through the open tie switch, so they stay undirected.
    closed_far_edge = next(e for e in graph["edges"] if e["edge_key"] == "L003")
    assert closed_far_edge["source_node_id"] is None
    assert closed_far_edge["target_node_id"] is None
    del node_key_by_id


def test_validation_endpoint_reflects_source_state(client: TestClient) -> None:
    network_id = _import_example_7bus(client)

    response = client.get(f"/api/networks/{network_id}/validation")
    assert response.status_code == 200
    body = response.json()
    assert body["source_set"] is False
    assert any(w["code"] == "source_not_set" for w in body["warnings"])

    graph = _graph(client, network_id)
    source_node_id = _node_id_by_key(graph, "SOURCE")
    client.post(f"/api/networks/{network_id}/source", json={"node_id": source_node_id})

    response = client.get(f"/api/networks/{network_id}/validation")
    body = response.json()
    assert body["source_set"] is True
    assert not any(w["code"] == "source_not_set" for w in body["warnings"])
