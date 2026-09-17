from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Monitor(Base):
    __tablename__ = "monitors"

    monitor_id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(String, ForeignKey("networks.network_id"), nullable=False)
    node_id: Mapped[str] = mapped_column(String, ForeignKey("nodes.node_id"), nullable=False)

    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
