from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.models import BaselineStat, Edge, LineModel, Monitor, Network, Node


def test_next_id_is_sequential_and_padded(db_session: Session) -> None:
    first = next_id(db_session, "N")
    second = next_id(db_session, "N")
    db_session.commit()

    assert first == "N000001"
    assert second == "N000002"


def test_next_id_counters_are_independent_per_prefix(db_session: Session) -> None:
    node_id = next_id(db_session, "N")
    edge_id = next_id(db_session, "E")
    db_session.commit()

    assert node_id == "N000001"
    assert edge_id == "E000001"


def test_network_node_edge_line_model_crud(db_session: Session) -> None:
    network = Network(network_id=next_id(db_session, "NET"), name="Test Feeder", voltage_kv=10.0)
    db_session.add(network)
    db_session.flush()

    node_a = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#1")
    node_b = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#2")
    db_session.add_all([node_a, node_b])
    db_session.flush()

    line_model = LineModel(
        line_model_id=next_id(db_session, "LM"),
        line_type="overhead",
        model_name="JKLYJ-120",
        r_ohm_per_km=0.253,
        x_ohm_per_km=0.35,
        c_nf_per_km=9.6,
        source="custom",
    )
    db_session.add(line_model)
    db_session.flush()

    edge = Edge(
        edge_id=next_id(db_session, "E"),
        network_id=network.network_id,
        edge_key="L001",
        node_a_id=node_a.node_id,
        node_b_id=node_b.node_id,
        status="closed",
        line_model_id=line_model.line_model_id,
        length_km=0.32,
    )
    db_session.add(edge)

    network.source_node_id = node_a.node_id
    db_session.commit()

    fetched_network = db_session.get(Network, network.network_id)
    assert fetched_network is not None
    assert fetched_network.status == "DRAFT"
    assert fetched_network.source_node_id == node_a.node_id

    fetched_edge = db_session.get(Edge, edge.edge_id)
    assert fetched_edge is not None
    assert fetched_edge.node_a_id == node_a.node_id
    assert fetched_edge.node_b_id == node_b.node_id
    assert fetched_edge.line_model_id == line_model.line_model_id


def test_monitor_and_baseline_stat_crud(db_session: Session) -> None:
    network = Network(network_id=next_id(db_session, "NET"), name="Test Feeder")
    db_session.add(network)
    db_session.flush()

    node = Node(node_id=next_id(db_session, "N"), network_id=network.network_id, node_key="#67")
    db_session.add(node)
    db_session.flush()

    monitor = Monitor(
        monitor_id=next_id(db_session, "M"),
        network_id=network.network_id,
        node_id=node.node_id,
        canonical_name="10kV火龙线#67.7支",
        aliases=["火龙线#67.7支", "10kV火龙线67.7支"],
    )
    db_session.add(monitor)
    db_session.flush()

    baseline = BaselineStat(
        monitor_id=monitor.monitor_id,
        signal="Va",
        count=100,
        mean=10.01,
        std=0.05,
        median=10.0,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    db_session.add(baseline)
    db_session.commit()

    fetched_monitor = db_session.get(Monitor, monitor.monitor_id)
    assert fetched_monitor is not None
    assert fetched_monitor.aliases == ["火龙线#67.7支", "10kV火龙线67.7支"]

    fetched_baseline = db_session.get(BaselineStat, (monitor.monitor_id, "Va"))
    assert fetched_baseline is not None
    assert fetched_baseline.count == 100
    assert fetched_baseline.mean == 10.01


def test_health_endpoint(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
