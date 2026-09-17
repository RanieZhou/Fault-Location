from pydantic import BaseModel, ConfigDict


class NetworkCreate(BaseModel):
    name: str
    voltage_kv: float | None = None
    frequency_hz: float = 50.0


class NetworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    network_id: str
    name: str
    voltage_kv: float | None
    frequency_hz: float
    source_node_id: str | None
    status: str
