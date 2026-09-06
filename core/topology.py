"""
拓扑查询接口 — 供 API 路由和 Agent 工具调用。
系统里的"线路"就是用户上传的自定义拓扑（topology_id），没有任何硬编码的固定线路。
"""
from __future__ import annotations
from .data_loader import get_line_nodes, get_line_edges, load_all_monitor_nodes
from .models import TopologyResponse, NodeModel


def get_topology(line: str) -> TopologyResponse:
    """返回指定拓扑（topology_id）的完整拓扑数据"""
    nodes = get_line_nodes(line)
    edges = get_line_edges(line)
    return TopologyResponse(
        line=line,
        nodes=nodes,
        edges=edges,
        node_count=len(nodes),
        edge_count=len(edges),
    )


def get_all_topology() -> dict[str, TopologyResponse]:
    """返回所有已上传拓扑的数据"""
    from . import db
    return {t["id"]: get_topology(t["id"]) for t in db.list_custom_topologies()}


def get_node(node_id: str, line: str | None = None) -> NodeModel | None:
    """按 node_id 获取节点详情；line（topology_id）已知时精确查找，避免跨拓扑重名误命中"""
    if line:
        return next((n for n in get_line_nodes(line) if n.id == node_id), None)
    return load_all_monitor_nodes().get(node_id)


def get_node_by_pole(orig_pole: str, line: str | None = None) -> NodeModel | None:
    """按原始杆号/母线号查找节点"""
    pole_norm = orig_pole.strip()
    if line:
        return next((n for n in get_line_nodes(line) if n.orig_pole == pole_norm), None)
    for n in load_all_monitor_nodes().values():
        if n.orig_pole == pole_norm:
            return n
    return None
