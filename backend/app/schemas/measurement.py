from pydantic import BaseModel


class FieldMappingOut(BaseModel):
    network_id: str
    mapping: dict[str, str]  # target_field -> source_column


class FieldMappingUpdate(BaseModel):
    mapping: dict[str, str]


class MeasurementImportResult(BaseModel):
    network_id: str
    total_rows: int
    matched: int
    unmatched: int
    unmatched_names: list[str]


class UnmatchedNameRow(BaseModel):
    monitor_name_raw: str
    count: int


class ResolveUnmatchedRequest(BaseModel):
    monitor_name_raw: str
    monitor_id: str | None = None  # None + ignore=True to mark as ignored without binding
    ignore: bool = False


class ResolveUnmatchedResult(BaseModel):
    monitor_name_raw: str
    updated_records: int
    status: str
