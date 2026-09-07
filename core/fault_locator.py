"""
故障定位引擎 — 矩阵法 + 报警前沿算法
修复Bug3：事件分组改为滑动窗口（任意两条时间差 <= 阈值）
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta
from typing import Optional

from .config import settings
from .data_loader import get_line_nodes, resolve_pole
from .models import (
    NodeModel, FaultLocateRequest, FaultLocateResponse, FaultSection
)


# ════════════════════════════════════════════════
# 拓扑祖先关系构建
# ════════════════════════════════════════════════

def _build_ancestor_map(line: str) -> dict[str, set[str]]:
    """
    返回 {node_id: {所有祖先 node_id 集合}}
    SOURCE 不在集合内
    """
    nodes = {n.id: n for n in get_line_nodes(line)}
    ancestor_map: dict[str, set[str]] = {}

    def _get_ancestors(nid: str) -> set[str]:
        if nid in ancestor_map:
            return ancestor_map[nid]
        node = nodes.get(nid)
        if not node or not node.parent_id:
            ancestor_map[nid] = set()
            return set()
        parent_ancestors = _get_ancestors(node.parent_id)
        result = parent_ancestors | {node.parent_id}
        ancestor_map[nid] = result
        return result

    for nid in nodes:
        _get_ancestors(nid)
    return ancestor_map


def _build_children_map(line: str) -> dict[str, list[str]]:
    """返回 {node_id: [直接子节点列表]}"""
    nodes = get_line_nodes(line)
    children: dict[str, list[str]] = {n.id: [] for n in nodes}
    for node in nodes:
        if node.parent_id and node.parent_id in children:
            children[node.parent_id].append(node.id)
    return children


# ════════════════════════════════════════════════
# 报警前沿算法
# ════════════════════════════════════════════════

def _find_frontier(alarmed_ids: set[str], ancestor_map: dict[str, set[str]]) -> list[str]:
    """
    报警前沿：报警节点中，其下游（子孙）没有任何其他报警节点的那些节点。
    即：A is frontier if no B in alarmed_ids where A is ancestor of B
    """
    frontier = []
    for nid in alarmed_ids:
        is_ancestor_of_another = any(
            nid in ancestor_map.get(other, set())
            for other in alarmed_ids if other != nid
        )
        if not is_ancestor_of_another:
            frontier.append(nid)
    return frontier


# ════════════════════════════════════════════════
# 候选区段推断
# ════════════════════════════════════════════════

def _get_candidate_sections(
    frontier_ids: list[str],
    children_map: dict[str, list[str]],
    nodes: dict[str, NodeModel],
) -> tuple[list[FaultSection], str, str]:
    """
    对每个前沿节点，其下游第一段即为候选故障区段。
    返回 (sections, confidence, note)
    """
    sections = []
    for fid in frontier_ids:
        children = children_map.get(fid, [])
        fnode = nodes.get(fid)
        if not fnode:
            continue
        if not children:
            # 已是末端节点，无法进一步缩小
            sections.append(FaultSection(
                from_pole=fnode.orig_pole,
                to_pole="(末端)",
                from_id=fid,
                to_id="",
                confidence="low",
            ))
        else:
            for cid in children:
                cnode = nodes.get(cid)
                if cnode:
                    sections.append(FaultSection(
                        from_pole=fnode.orig_pole,
                        to_pole=cnode.orig_pole,
                        from_id=fid,
                        to_id=cid,
                        confidence="high" if len(children) == 1 else "medium",
                    ))

    if not sections:
        note = "无法推断候选区段"
        conf = "low"
    elif len(sections) == 1:
        only = sections[0]
        if only.confidence == "high":
            note = "单一候选区段，较有把握"
            conf = "high"
        else:
            # 前沿节点已是该分支末端监测点，没有更下游的点可供缩小范围
            note = "该分支已无更下游监测点，无法进一步缩小，建议对该点下游全线巡查"
            conf = "low"
    elif len(sections) > 2:
        note = f"前沿节点下游有 {len(sections)} 条候选区段，建议结合电气量进一步判断"
        conf = "low"
    else:
        note = f"存在 {len(sections)} 条候选区段"
        conf = "medium"

    return sections, conf, note


# ════════════════════════════════════════════════
# 主定位接口
# ════════════════════════════════════════════════

def locate_fault(req: FaultLocateRequest) -> FaultLocateResponse:
    """
    核心故障定位函数。
    输入：线路名 + 报警杆号列表
    输出：FaultLocateResponse（含候选区段、置信度、高亮节点ID）
    """
    nodes_map = {n.id: n for n in get_line_nodes(req.line)}
    ancestor_map = _build_ancestor_map(req.line)
    children_map = _build_children_map(req.line)

    # 1. 解析报警杆号 → node_id
    alarmed_ids: set[str] = set()
    unresolved: list[str] = []
    for raw_pole in req.alarm_points:
        result = resolve_pole(raw_pole.strip(), line=req.line)
        clean_id = result[1] if result and result[1] in nodes_map else None
        if not clean_id:
            raw_s = raw_pole.strip()
            import re
            clean_s = re.sub(r"^(?:\d+\s*k+v)?", "", raw_s, flags=re.I).strip()
            clean_s = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9]+?(?:线|支线|干线)?#?", "", clean_s).strip()
            clean_s = re.sub(r"[大小支杆开关箱变出线环网柜]+$", "", clean_s).strip()

            for nid, n in nodes_map.items():
                if nid.lower() == raw_s.lower() or n.orig_pole == raw_s:
                    clean_id = nid
                    break
                if clean_s and (nid.lower() == clean_s.lower() or clean_s in n.orig_pole):
                    clean_id = nid
                    break
                if nid in raw_s or (n.orig_pole and (raw_s in n.orig_pole or n.orig_pole in raw_s)):
                    clean_id = nid
                    break
        if clean_id:
            alarmed_ids.add(clean_id)
        else:
            unresolved.append(raw_pole)

    if not alarmed_ids:
        return FaultLocateResponse(
            event_id=str(uuid.uuid4())[:8],
            line=req.line,
            alarm_points=req.alarm_points,
            frontier_points=[],
            candidate_sections=[],
            confidence="low",
            note=f"未能识别任何报警节点。未识别杆号：{unresolved}",
            alarmed_node_ids=[],
        )

    # 2. 找报警前沿
    frontier_ids = _find_frontier(alarmed_ids, ancestor_map)

    # 3. 推断候选区段
    sections, conf, note = _get_candidate_sections(
        frontier_ids, children_map, nodes_map
    )

    if unresolved:
        note += f"  （未识别杆号：{', '.join(unresolved)}）"

    # 4. 电气量分析（可选增强层：找不到匹配的原始电气量记录时静默跳过，不影响矩阵法主结论）
    electrical = None
    try:
        from .electrical_inference import analyze_event
        electrical = analyze_event(req.line, req.alarm_points, req.event_time)
    except Exception:
        electrical = None

    # 5. 组装响应
    frontier_poles = [nodes_map[fid].orig_pole for fid in frontier_ids if fid in nodes_map]
    return FaultLocateResponse(
        event_id=str(uuid.uuid4())[:8],
        line=req.line,
        alarm_points=req.alarm_points,
        frontier_points=frontier_poles,
        candidate_sections=sections,
        confidence=conf,
        note=note,
        alarmed_node_ids=list(alarmed_ids),
        electrical_analysis=electrical,
    )


# ════════════════════════════════════════════════
# 事件分组（滑动窗口，Bug3修复版）
# ════════════════════════════════════════════════

def group_alarms_into_events(
    alarms: list[dict],
    time_window_s: Optional[int] = None,
) -> list[list[dict]]:
    """
    将原始报警记录按时间窗口分组为事件。
    Bug3修复：改为滑动窗口——同组内任意两条时间差 <= 阈值。
    
    alarms 格式: [{"line": ..., "pole": ..., "time": datetime, ...}, ...]
    """
    window = timedelta(seconds=time_window_s or settings.fault_time_window_s)
    # 先按线路+时间排序
    alarms_sorted = sorted(alarms, key=lambda x: (x["line"], x["time"]))

    events: list[list[dict]] = []
    for alarm in alarms_sorted:
        placed = False
        for event in reversed(events):
            # 同线路
            if event[0]["line"] != alarm["line"]:
                continue
            # 滑动窗口：与组内所有记录的时间差都 <= window
            max_diff = max(abs((alarm["time"] - a["time"]).total_seconds()) for a in event)
            if max_diff <= window.total_seconds():
                event.append(alarm)
                placed = True
                break
        if not placed:
            events.append([alarm])

    return events
