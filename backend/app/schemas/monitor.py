from pydantic import BaseModel, ConfigDict


class MonitorCreate(BaseModel):
    node_id: str
    canonical_name: str
    aliases: list[str] = []


class MonitorUpdate(BaseModel):
    canonical_name: str | None = None
    aliases: list[str] | None = None
    enabled: bool | None = None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    monitor_id: str
    network_id: str
    node_id: str
    canonical_name: str
    aliases: list[str]
    enabled: bool
