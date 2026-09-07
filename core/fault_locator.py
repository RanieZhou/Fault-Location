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

# 电气量证据判定阈值：最高分至少要到这个绝对水平，且比次高分拉开这么多，
# 才认为"这份评分真的能区分出哪条分支更可能故障"，否则视为噪声、不采信。
_SEVERITY_MIN_SCORE = 8.0
_SEVERITY_GAP = 15.0


def _get_candidate_sections(
    frontier_ids: list[str],
    children_map: dict[str, list[str]],
    nodes: dict[str, NodeModel],
    severity_map: dict[str, float] | None = None,
) -> tuple[list[FaultSection], str, str]:
    """
    对每个前沿节点，其下游第一段即为候选故障区段。
    severity_map（可选）：{node_id: 电气量异常评分0-100}，覆盖范围可以是任意监测点
    （不限于报警点本身）——同一前沿下有多个未报警的候选分支、纯拓扑结构无法区分时，
    用这份评分挑出真正偏离得更明显的那条分支。不提供、或分支之间评分没有明确区分度
    （见 _SEVERITY_MIN_SCORE/_SEVERITY_GAP）时，完全退化为原来的纯拓扑判断。
    返回 (sections, confidence, note)
    """
    severity_map = severity_map or {}
    sections: list[FaultSection] = []
    evidence_notes: list[str] = []
    all_groups_resolved = True

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
            all_groups_resolved = False
            continue

        branch_sections = [
            FaultSection(
                from_pole=fnode.orig_pole,
                to_pole=cnode.orig_pole,
                from_id=fid,
                to_id=cid,
                confidence="high" if len(children) == 1 else "medium",
                severity_score=severity_map.get(cid),
            )
            for cid in children if (cnode := nodes.get(cid))
        ]

        if len(branch_sections) > 1:
            scored = [s for s in branch_sections if s.severity_score is not None]
            scored.sort(key=lambda s: s.severity_score, reverse=True)
            if (
                len(scored) >= 2
                and scored[0].severity_score >= _SEVERITY_MIN_SCORE
                and scored[0].severity_score - scored[1].severity_score >= _SEVERITY_GAP
            ):
                # 有明确区分度：电气量证据挑出的分支排最前、置信度提到high，
                # 其余分支降级为low（不是排除，只是变得不太可能）
                top_id = scored[0].to_id
                branch_sections.sort(key=lambda s: 0 if s.to_id == top_id else 1)
                for s in branch_sections:
                    s.confidence = "high" if s.to_id == top_id else "low"
                evidence_notes.append(
                    f"{fnode.orig_pole}下游有{len(branch_sections)}条分支，"
                    f"其中{nodes[top_id].orig_pole}"
                    f"电气量异常评分（{scored[0].severity_score:.0f}）明显高于其他分支"
                    f"（次高{scored[1].severity_score:.0f}），判断为最可能的故障区段"
                )
            else:
                all_groups_resolved = False
        sections.extend(branch_sections)

    if not sections:
        note = "无法推断候选区段"
        conf = "low"
    elif evidence_notes and all_groups_resolved:
        conf = "high"
        note = "；".join(evidence_notes)
    elif evidence_notes:
        conf = "medium"
        note = "；".join(evidence_notes) + "；其余候选区段电气量证据不足以区分，仍建议人工巡查确认"
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
        frontier_ids, children_map, nodes_map, severity_map=req.alarm_severity
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
