from pydantic import BaseModel

from app.schemas.mapping import ValidationIssue


class SourceSetRequest(BaseModel):
    node_id: str


class GraphNode(BaseModel):
    node_id: str
    node_key: str
    label: str | None = None
    is_source: bool = False
    has_monitor: bool = False


class GraphEdge(BaseModel):
    edge_id: str
    edge_key: str | None
    node_a_id: str
    node_b_id: str
    source_node_id: str | None
    target_node_id: str | None
    status: str
    line_model_id: str | None
    length_km: float | None
    line_type: str | None = None
    model_name: str | None = None
    r_ohm: float | None = None
    x_ohm: float | None = None
    c_nf: float | None = None


class NetworkGraph(BaseModel):
    network_id: str
    source_node_id: str | None
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class TopologyValidationSummary(BaseModel):
    network_id: str
    nodes: int
    edges: int
    components: int
    cycles: int
    open_edges: int
    source_set: bool
    warnings: list[ValidationIssue]
