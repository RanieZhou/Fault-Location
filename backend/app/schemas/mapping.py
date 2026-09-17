from pydantic import BaseModel


class ValidationIssue(BaseModel):
    level: str  # ERROR / WARNING / INFO
    code: str
    message: str
    rows: list[int] | None = None


class MappingImportResult(BaseModel):
    imported: bool
    network_id: str
    nodes: int
    edges: int
    components: int
    cycles: int
    open_edges: int
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
