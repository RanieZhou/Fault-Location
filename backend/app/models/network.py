from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Network(Base):
    __tablename__ = "networks"

    network_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    voltage_kv: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequency_hz: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)

    # Not a ForeignKey: Node.network_id already points back at this table, and
    # SQLite/SQLAlchemy handle that mutual reference poorly at create_all time.
    # The referenced node is validated at the service layer instead.
    source_node_id: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="DRAFT")
    # DRAFT / CONFIGURING / READY

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
