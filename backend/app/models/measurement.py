from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base

SIGNAL_FIELDS = [
    "Va",
    "Vb",
    "Vc",
    "Ia",
    "Ib",
    "Ic",
    "phase_Va",
    "phase_Vb",
    "phase_Vc",
    "phase_Ia",
    "phase_Ib",
    "phase_Ic",
]


class MeasurementFieldMapping(Base):
    __tablename__ = "measurement_field_mappings"

    network_id: Mapped[str] = mapped_column(String, ForeignKey("networks.network_id"), primary_key=True)
    target_field: Mapped[str] = mapped_column(String, primary_key=True)
    source_column: Mapped[str] = mapped_column(String, nullable=False)


class MeasurementRecord(Base):
    __tablename__ = "measurement_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_id: Mapped[str] = mapped_column(String, ForeignKey("networks.network_id"), nullable=False)

    monitor_name_raw: Mapped[str] = mapped_column(String, nullable=False)
    monitor_id: Mapped[str | None] = mapped_column(String, ForeignKey("monitors.monitor_id"), nullable=True)
    match_status: Mapped[str] = mapped_column(String, nullable=False, default="unmatched")
    # matched / unmatched / ignored

    device_type: Mapped[str | None] = mapped_column(String, nullable=True)
    terminal_status: Mapped[str | None] = mapped_column(String, nullable=True)
    line_status: Mapped[str | None] = mapped_column(String, nullable=True)
    warning_status: Mapped[str | None] = mapped_column(String, nullable=True)

    Va: Mapped[float | None] = mapped_column(Float, nullable=True)
    Vb: Mapped[float | None] = mapped_column(Float, nullable=True)
    Vc: Mapped[float | None] = mapped_column(Float, nullable=True)
    Ia: Mapped[float | None] = mapped_column(Float, nullable=True)
    Ib: Mapped[float | None] = mapped_column(Float, nullable=True)
    Ic: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Va: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Vb: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Vc: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Ia: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Ib: Mapped[float | None] = mapped_column(Float, nullable=True)
    phase_Ic: Mapped[float | None] = mapped_column(Float, nullable=True)

    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
