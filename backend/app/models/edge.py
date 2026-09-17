from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base


class Edge(Base):
    __tablename__ = "edges"

    edge_id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(String, ForeignKey("networks.network_id"), nullable=False)

    edge_key: Mapped[str | None] = mapped_column(String, nullable=True)

    node_a_id: Mapped[str] = mapped_column(String, ForeignKey("nodes.node_id"), nullable=False)
    node_b_id: Mapped[str] = mapped_column(String, ForeignKey("nodes.node_id"), nullable=False)

    # Directed endpoints derived from the network's Source via BFS/DFS.
    # Null until a Source is set, or if this edge is unreachable (open / other component).
    source_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_node_id: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, nullable=False, default="closed")
    # closed / open

    line_model_id: Mapped[str | None] = mapped_column(String, ForeignKey("line_models.line_model_id"), nullable=True)
    length_km: Mapped[float | None] = mapped_column(Float, nullable=True)

    remark: Mapped[str | None] = mapped_column(String, nullable=True)
