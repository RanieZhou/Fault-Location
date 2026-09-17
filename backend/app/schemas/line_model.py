from pydantic import BaseModel, ConfigDict


class LineModelCreate(BaseModel):
    line_type: str  # overhead / cable
    model_name: str
    r_ohm_per_km: float
    x_ohm_per_km: float
    c_nf_per_km: float
    remark: str | None = None


class LineModelUpdate(BaseModel):
    model_name: str | None = None
    r_ohm_per_km: float | None = None
    x_ohm_per_km: float | None = None
    c_nf_per_km: float | None = None
    enabled: bool | None = None
    remark: str | None = None


class LineModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line_model_id: str
    line_type: str
    model_name: str
    r_ohm_per_km: float
    x_ohm_per_km: float
    c_nf_per_km: float
    source: str
    enabled: bool
    remark: str | None
