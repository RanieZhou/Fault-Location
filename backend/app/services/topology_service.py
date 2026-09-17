import networkx as nx
from sqlalchemy.orm import Session

from app.models import Edge, LineModel, Monitor, Network, Node
from app.schemas.edge import EdgeTableRow
from app.schemas.mapping import ValidationIssue
from app.schemas.topology import GraphEdge, GraphNode, NetworkGraph, TopologyValidationSummary


class TopologyError(ValueError):
    pass


def _closed_graph(edges: list[Edge]) -> nx.Graph:
    graph = nx.Graph()
    for edge in edges:
        if edge.status == "closed":
            graph.add_edge(edge.node_a_id, edge.node_b_id)
    return graph


def set_source(db: Session, network: Network, node_id: str) -> Network:
    node = db.get(Node, node_id)
    if node is None or node.network_id != network.network_id:
        raise TopologyError("指定的 Source 节点不存在于该 Network 中")

    network.source_node_id = node_id
    if network.status == "DRAFT":
        network.status = "CONFIGURING"

    edges = db.query(Edge).filter(Edge.network_id == network.network_id).all()
    graph = _closed_graph(edges)
    distances = nx.single_source_shortest_path_length(graph, node_id) if node_id in graph else {}

    for edge in edges:
        if edge.status != "closed":
            edge.source_node_id = None
            edge.target_node_id = None
            continue

        dist_a = distances.get(edge.node_a_id)
        dist_b = distances.get(edge.node_b_id)

        if dist_a is None or dist_b is None:
            # Not reachable from Source over closed edges (other component).
            edge.source_node_id = None
            edge.target_node_id = None
        elif dist_a == dist_b:
            # Cycle-closing edge joining two nodes at equal BFS depth: no
            # natural direction exists, so break the tie deterministically.
            near, far = sorted((edge.node_a_id, edge.node_b_id))
            edge.source_node_id, edge.target_node_id = near, far
        elif dist_a < dist_b:
            edge.source_node_id, edge.target_node_id = edge.node_a_id, edge.node_b_id
        else:
            edge.source_node_id, edge.target_node_id = edge.node_b_id, edge.node_a_id

    db.commit()
    db.refresh(network)
    return network


def _build_graph_edge(edge: Edge, line_models: dict[str, LineModel]) -> GraphEdge:
    line_model = line_models.get(edge.line_model_id) if edge.line_model_id else None
    has_physics = line_model is not None and edge.length_km is not None
    return GraphEdge(
        edge_id=edge.edge_id,
        edge_key=edge.edge_key,
        node_a_id=edge.node_a_id,
        node_b_id=edge.node_b_id,
        source_node_id=edge.source_node_id,
        target_node_id=edge.target_node_id,
        status=edge.status,
        line_model_id=edge.line_model_id,
        length_km=edge.length_km,
        line_type=line_model.line_type if line_model else None,
        model_name=line_model.model_name if line_model else None,
        r_ohm=line_model.r_ohm_per_km * edge.length_km if has_physics else None,
        x_ohm=line_model.x_ohm_per_km * edge.length_km if has_physics else None,
        c_nf=line_model.c_nf_per_km * edge.length_km if has_physics else None,
    )


def get_graph(db: Session, network: Network) -> NetworkGraph:
    nodes = db.query(Node).filter(Node.network_id == network.network_id).all()
    edges = db.query(Edge).filter(Edge.network_id == network.network_id).all()
    line_models = {lm.line_model_id: lm for lm in db.query(LineModel).all()}
    monitored_node_ids = {
        m.node_id for m in db.query(Monitor.node_id).filter(Monitor.network_id == network.network_id).all()
    }

    return NetworkGraph(
        network_id=network.network_id,
        source_node_id=network.source_node_id,
        nodes=[
            GraphNode(
                node_id=n.node_id,
                node_key=n.node_key,
                label=n.label,
                is_source=(n.node_id == network.source_node_id),
                has_monitor=n.node_id in monitored_node_ids,
            )
            for n in nodes
        ],
        edges=[_build_graph_edge(e, line_models) for e in edges],
    )


def get_validation_summary(db: Session, network: Network) -> TopologyValidationSummary:
    nodes = db.query(Node).filter(Node.network_id == network.network_id).all()
    edges = db.query(Edge).filter(Edge.network_id == network.network_id).all()

    graph = _closed_graph(edges)
    graph.add_nodes_from(n.node_id for n in nodes)

    components = nx.number_connected_components(graph) if graph.number_of_nodes() else 0
    cyclomatic = graph.number_of_edges() - graph.number_of_nodes() + components if graph.number_of_nodes() else 0
    open_edges = sum(1 for e in edges if e.status == "open")

    warnings: list[ValidationIssue] = []
    if components > 1:
        warnings.append(
            ValidationIssue(level="WARNING", code="multiple_components", message=f"存在 {components} 个连通分量")
        )
    if cyclomatic > 0:
        warnings.append(
            ValidationIssue(level="WARNING", code="cycle_detected", message=f"图中存在 {cyclomatic} 个独立环路")
        )
    if open_edges:
        warnings.append(ValidationIssue(level="WARNING", code="open_edge", message="存在 open Edge"))
    if not network.source_node_id:
        warnings.append(ValidationIssue(level="WARNING", code="source_not_set", message="尚未选择 Source"))

    return TopologyValidationSummary(
        network_id=network.network_id,
        nodes=len(nodes),
        edges=len(edges),
        components=components,
        cycles=cyclomatic,
        open_edges=open_edges,
        source_set=network.source_node_id is not None,
        warnings=warnings,
    )


def _validate_line_model_assignment(db: Session, line_model_id: str | None) -> None:
    if line_model_id is None:
        return
    line_model = db.get(LineModel, line_model_id)
    if line_model is None:
        raise TopologyError("指定的线路型号不存在")
    if not line_model.enabled:
        raise TopologyError("指定的线路型号已停用，无法引用")


def get_edge_or_404(db: Session, edge_id: str) -> Edge:
    edge = db.get(Edge, edge_id)
    if edge is None:
        raise TopologyError("Edge not found")
    return edge


def update_edge_config(db: Session, edge: Edge, line_model_id: str | None, length_km: float | None) -> Edge:
    _validate_line_model_assignment(db, line_model_id)
    edge.line_model_id = line_model_id
    edge.length_km = length_km
    db.commit()
    db.refresh(edge)
    return edge


def batch_update_edge_config(
    db: Session,
    network: Network,
    edge_ids: list[str],
    line_model_id: str,
    apply_length: bool,
    length_km: float | None,
) -> list[Edge]:
    _validate_line_model_assignment(db, line_model_id)

    edges = db.query(Edge).filter(Edge.network_id == network.network_id, Edge.edge_id.in_(edge_ids)).all()
    found_ids = {e.edge_id for e in edges}
    missing = set(edge_ids) - found_ids
    if missing:
        raise TopologyError(f"以下 Edge 不属于该 Network：{', '.join(sorted(missing))}")

    for edge in edges:
        edge.line_model_id = line_model_id
        if apply_length:
            edge.length_km = length_km

    db.commit()
    for edge in edges:
        db.refresh(edge)
    return edges


def list_edges_table(db: Session, network: Network) -> list[EdgeTableRow]:
    edges = db.query(Edge).filter(Edge.network_id == network.network_id).all()
    node_keys = {n.node_id: n.node_key for n in db.query(Node).filter(Node.network_id == network.network_id).all()}
    line_models = {lm.line_model_id: lm for lm in db.query(LineModel).all()}

    rows: list[EdgeTableRow] = []
    for e in edges:
        line_model = line_models.get(e.line_model_id) if e.line_model_id else None
        rows.append(
            EdgeTableRow(
                edge_id=e.edge_id,
                edge_key=e.edge_key,
                node_a_key=node_keys.get(e.node_a_id, e.node_a_id),
                node_b_key=node_keys.get(e.node_b_id, e.node_b_id),
                status=e.status,
                line_model_id=e.line_model_id,
                line_type=line_model.line_type if line_model else None,
                model_name=line_model.model_name if line_model else None,
                length_km=e.length_km,
                configured=bool(e.line_model_id and e.length_km),
            )
        )
    return rows
