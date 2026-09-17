from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class LineModel(Base):
    __tablename__ = "line_models"

    line_model_id: Mapped[str] = mapped_column(String, primary_key=True)

    line_type: Mapped[str] = mapped_column(String, nullable=False)
    # overhead / cable

    model_name: Mapped[str] = mapped_column(String, nullable=False)

    r_ohm_per_km: Mapped[float] = mapped_column(Float, nullable=False)
    x_ohm_per_km: Mapped[float] = mapped_column(Float, nullable=False)
    c_nf_per_km: Mapped[float] = mapped_column(Float, nullable=False)

    source: Mapped[str] = mapped_column(String, nullable=False, default="custom")
    # preset / custom

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    remark: Mapped[str | None] = mapped_column(String, nullable=True)
