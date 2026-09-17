from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class BaselineStat(Base):
    __tablename__ = "baseline_stats"

    monitor_id: Mapped[str] = mapped_column(String, ForeignKey("monitors.monitor_id"), primary_key=True)
    signal: Mapped[str] = mapped_column(String, primary_key=True)

    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    std: Mapped[float | None] = mapped_column(Float, nullable=True)
    median: Mapped[float | None] = mapped_column(Float, nullable=True)

    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
