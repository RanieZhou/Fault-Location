from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (UniqueConstraint("network_id", "node_key", name="uq_node_network_key"),)

    node_id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(String, ForeignKey("networks.network_id"), nullable=False)
    node_key: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
