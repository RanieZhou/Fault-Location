from pydantic import BaseModel


class EdgeConfigUpdate(BaseModel):
    line_model_id: str | None = None
    length_km: float | None = None


class EdgeBatchConfigRequest(BaseModel):
    edge_ids: list[str]
    line_model_id: str
    apply_length: bool = False
    length_km: float | None = None


class EdgeOut(BaseModel):
    edge_id: str
    edge_key: str | None
    node_a_id: str
    node_b_id: str
    source_node_id: str | None
    target_node_id: str | None
    status: str
    line_model_id: str | None
    length_km: float | None


class EdgeTableRow(BaseModel):
    edge_id: str
    edge_key: str | None
    node_a_key: str
    node_b_key: str
    status: str
    line_model_id: str | None
    line_type: str | None
    model_name: str | None
    length_km: float | None
    configured: bool
