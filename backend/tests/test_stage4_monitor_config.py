import io

from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.models import Network, Node
from app.services.monitor_service import MonitorError, delete_node

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


def test_create_monitor_binds_to_node_and_flags_graph(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    node_id = graph["nodes"][0]["node_id"]

    response = client.post(
        f"/api/networks/{network_id}/monitors",
        json={"node_id": node_id, "canonical_name": "10kV火龙线#67.7支", "aliases": ["火龙线#67.7支"]},
    )
    assert response.status_code == 200
    monitor = response.json()
    assert monitor["node_id"] == node_id
    assert monitor["aliases"] == ["火龙线#67.7支"]

    listed = client.get(f"/api/networks/{network_id}/monitors").json()
    assert len(listed) == 1

    updated_graph = client.get(f"/api/networks/{network_id}/graph").json()
    flagged_node = next(n for n in updated_graph["nodes"] if n["node_id"] == node_id)
    assert flagged_node["has_monitor"] is True


def test_duplicate_canonical_name_in_network_is_rejected(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    node_a, node_b = graph["nodes"][0]["node_id"], graph["nodes"][1]["node_id"]

    client.post(f"/api/networks/{network_id}/monitors", json={"node_id": node_a, "canonical_name": "M-A"})
    response = client.post(f"/api/networks/{network_id}/monitors", json={"node_id": node_b, "canonical_name": "M-A"})
    assert response.status_code == 400


def test_update_and_delete_monitor(client: TestClient) -> None:
    network_id, graph = _create_network_with_edges(client, [("L001", "#1", "#2", "closed", "")])
    node_id = graph["nodes"][0]["node_id"]

    created = client.post(
        f"/api/networks/{network_id}/monitors", json={"node_id": node_id, "canonical_name": "M-A"}
    ).json()

    updated = client.patch(
        f"/api/monitors/{created['monitor_id']}",
        json={"aliases": ["Alias1", "Alias2"], "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["aliases"] == ["Alias1", "Alias2"]
    assert updated.json()["enabled"] is False

    delete_resp = client.delete(f"/api/monitors/{created['monitor_id']}")
    assert delete_resp.status_code == 204

    listed = client.get(f"/api/networks/{network_id}/monitors").json()
    assert listed == []

    graph_after = client.get(f"/api/networks/{network_id}/graph").json()
    flagged_node = next(n for n in graph_after["nodes"] if n["node_id"] == node_id)
    assert flagged_node["has_monitor"] is False


def test_delete_node_guard_rejects_monitor_source_and_edge_references(db_session: Session) -> None:
    network = Network(network_id=next_id(db_session, "NET"), name="Guard Test")
    db_session.add(network)
    db_session.flush()

    monitored_node = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#1")
    source_node = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#2")
    isolated_node = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#3")
    db_session.add_all([monitored_node, source_node, isolated_node])
    db_session.flush()

    from app.models import Edge, Monitor

    monitor = Monitor(
        monitor_id=next_id(db_session, "M"),
        network_id=network.network_id,
        node_id=monitored_node.node_id,
        canonical_name="M-1",
        aliases=[],
    )
    edge = Edge(
        edge_id=next_id(db_session, "E"),
        network_id=network.network_id,
        node_a_id=monitored_node.node_id,
        node_b_id=source_node.node_id,
        status="closed",
    )
    network.source_node_id = source_node.node_id
    db_session.add_all([monitor, edge])
    db_session.commit()

    try:
        delete_node(db_session, network, monitored_node.node_id)
        assert False, "expected MonitorError for monitor-referenced node"
    except MonitorError:
        pass

    try:
        delete_node(db_session, network, source_node.node_id)
        assert False, "expected MonitorError for source node"
    except MonitorError:
        pass

    # isolated_node has no monitor, isn't the source, and has no edges -> deletable.
    delete_node(db_session, network, isolated_node.node_id)
    assert db_session.get(Node, isolated_node.node_id) is None
