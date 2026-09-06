"""
数据加载器 —— 系统里所有拓扑数据都来自用户上传的自定义拓扑（core.custom_topology +
SQLite），不存在任何硬编码的固定线路/固定数据文件。这个模块只保留两类通用能力：
  1. 跨拓扑的节点查找（resolve_pole / load_all_monitor_nodes）
  2. 历史故障事件读取（load_history_events，实际数据在 core.db）
"""
from __future__ import annotations
from typing import Optional

from .models import NodeModel, EdgeModel, HistoryEvent


# ════════════════════════════════════════════════
# 拓扑数据（按拓扑id查，或跨拓扑聚合查找）
# ════════════════════════════════════════════════

def get_line_nodes(line: str) -> list[NodeModel]:
    """返回指定拓扑（topology_id）折叠后的监测点节点列表（BFS序）"""
    from .custom_topology import build_monitor_view
    nodes, _ = build_monitor_view(line)
    nodes.sort(key=lambda n: (n.depth, n.id))
    return nodes


def get_line_edges(line: str) -> list[EdgeModel]:
    """返回指定拓扑（topology_id）折叠后的边（虚拟边，已聚合跳过的结构杆塔参数）"""
    from .custom_topology import build_monitor_view
    _, edges = build_monitor_view(line)
    return edges


def load_all_monitor_nodes() -> dict[str, NodeModel]:
    """
    聚合所有自定义拓扑的监测点节点，返回 {node_id: NodeModel}。
    注意：不同拓扑各自独立上传，node_id 理论上可能重名——这里按遍历顺序覆盖，
    跨拓扑全局查找遇到重名只能拿到其中一个。需要精确结果时应传入 line（topology_id）
    走 get_line_nodes(line) 而不是这个全局聚合视图。
    """
    from . import db
    from .custom_topology import build_monitor_view
    result: dict[str, NodeModel] = {}
    for topo in db.list_custom_topologies():
        nodes, _ = build_monitor_view(topo["id"])
        for n in nodes:
            result[n.id] = n
    return result


# ════════════════════════════════════════════════
# 历史故障事件
# ════════════════════════════════════════════════

def load_history_events() -> list[HistoryEvent]:
    """
    返回历史故障事件（按时间正序）。数据源为 SQLite（core.db），
    随 /api/fault/locate 的实际调用持续增长，因此不做缓存。
    """
    from . import db
    return db.get_all_events()


# ════════════════════════════════════════════════
# 监测点标识解析
# ════════════════════════════════════════════════

def resolve_pole(raw: str, line: Optional[str] = None) -> Optional[tuple[str, str, str]]:
    """
    将用户输入的监测点标识（node_id 或 label）解析为 (topology_id, node_id, label)。
    line: 可选，已知目标拓扑（topology_id）时传入，只在该拓扑内精确匹配，避免不同
    拓扑碰巧重名导致误匹配；不传时跨所有自定义拓扑查找。
    返回 None 表示未找到。
    """
    from . import db
    pole_norm = raw.strip()

    if line:
        if not db.get_custom_topology_meta(line):
            return None
        for n in db.get_custom_nodes(line):
            if n["node_id"] == pole_norm or n["label"] == pole_norm:
                return (line, n["node_id"], n["label"])
        return None

    for topo in db.list_custom_topologies():
        for n in db.get_custom_nodes(topo["id"]):
            if n["node_id"] == pole_norm or n["label"] == pole_norm:
                return (topo["id"], n["node_id"], n["label"])
    return None
