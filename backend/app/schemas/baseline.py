from datetime import datetime

from pydantic import BaseModel


class BaselineBuildResult(BaseModel):
    network_id: str
    monitors_with_baseline: int
    baseline_rows: int


class BaselineStatOut(BaseModel):
    monitor_id: str
    canonical_name: str
    signal: str
    count: int
    mean: float | None
    std: float | None
    median: float | None
    start_time: datetime | None
    end_time: datetime | None


class ReadinessItem(BaseModel):
    key: str
    label: str
    passed: bool
    detail: str | None = None


class NetworkReadiness(BaseModel):
    network_id: str
    ready: bool
    items: list[ReadinessItem]
