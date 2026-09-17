from sqlalchemy.orm import Session

from app.db.id_generator import next_id
from app.models import Monitor, Network, Node
from app.schemas.monitor import MonitorUpdate


class MonitorError(ValueError):
    pass


class MonitorNotFoundError(MonitorError):
    pass


def _ensure_unique_canonical_name(
    db: Session, network_id: str, canonical_name: str, exclude_monitor_id: str | None = None
) -> None:
    query = db.query(Monitor).filter(Monitor.network_id == network_id, Monitor.canonical_name == canonical_name)
    if exclude_monitor_id:
        query = query.filter(Monitor.monitor_id != exclude_monitor_id)
    if query.first() is not None:
        raise MonitorError("该监测点标准名称已被使用")


def create_monitor(db: Session, network: Network, node_id: str, canonical_name: str, aliases: list[str]) -> Monitor:
    node = db.get(Node, node_id)
    if node is None or node.network_id != network.network_id:
        raise MonitorError("指定的 Node 不存在于该 Network 中")

    _ensure_unique_canonical_name(db, network.network_id, canonical_name)

    monitor = Monitor(
        monitor_id=next_id(db, "M"),
        network_id=network.network_id,
        node_id=node_id,
        canonical_name=canonical_name,
        aliases=aliases,
        enabled=True,
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)
    return monitor


def list_monitors(db: Session, network: Network) -> list[Monitor]:
    return db.query(Monitor).filter(Monitor.network_id == network.network_id).order_by(Monitor.monitor_id).all()


def get_monitor_or_404(db: Session, monitor_id: str) -> Monitor:
    monitor = db.get(Monitor, monitor_id)
    if monitor is None:
        raise MonitorNotFoundError("Monitor not found")
    return monitor


def update_monitor(db: Session, monitor_id: str, payload: MonitorUpdate) -> Monitor:
    monitor = get_monitor_or_404(db, monitor_id)
    data = payload.model_dump(exclude_unset=True)
    if "canonical_name" in data and data["canonical_name"] != monitor.canonical_name:
        _ensure_unique_canonical_name(db, monitor.network_id, data["canonical_name"], exclude_monitor_id=monitor_id)
    for field, value in data.items():
        setattr(monitor, field, value)
    db.commit()
    db.refresh(monitor)
    return monitor


def delete_monitor(db: Session, monitor_id: str) -> None:
    monitor = get_monitor_or_404(db, monitor_id)
    db.delete(monitor)
    db.commit()


def delete_node(db: Session, network: Network, node_id: str) -> None:
    """Guarded node deletion: not part of the MVP UI (nodes come from mapping
    import), but kept as a tested invariant per the spec's Stage 4 PASS
    criteria for when this becomes reachable (e.g. future re-import/cleanup).
    """
    from app.models import Edge  # local import to avoid a topology<->monitor service cycle

    node = db.get(Node, node_id)
    if node is None or node.network_id != network.network_id:
        raise MonitorError("指定的 Node 不存在于该 Network 中")

    if node_id == network.source_node_id:
        raise MonitorError("不能删除当前 Source 节点")

    monitor_count = db.query(Monitor).filter(Monitor.node_id == node_id).count()
    if monitor_count > 0:
        raise MonitorError("该节点已绑定 Monitor，无法删除，请先删除关联的 Monitor")

    edge_count = db.query(Edge).filter((Edge.node_a_id == node_id) | (Edge.node_b_id == node_id)).count()
    if edge_count > 0:
        raise MonitorError("该节点仍被 Edge 引用，无法删除")

    db.delete(node)
    db.commit()
