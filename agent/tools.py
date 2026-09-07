"""
agent/tools.py — Agent 工具函数（供 LLM function calling 使用）
所有工具调用 core 层，不直接读取文件。

系统不再有任何硬编码的固定线路——"line"参数在所有工具里都是指用户上传的
自定义拓扑的 topology_id。LLM 一般不会预先知道有哪些拓扑，所以新增了
list_topologies 工具，Agent 应该在需要具体拓扑id时先调用它查一遍
（系统提示词里会强调这一点）。
"""
from __future__ import annotations
from typing import Any

from core.topology import get_topology, get_node_by_pole
from core.fault_locator import locate_fault
from core.data_loader import load_history_events, get_line_nodes
from core.models import FaultLocateRequest


# ════════════════════════════════════════════════
# 标准工具返回信封：{"ok", "error", "summary", **具体字段}
# summary 是给人看的一句话中文摘要，graph.py 的 _preview() 直接读它
# 生成 SSE 里的 result_preview，不用再为每个新工具单独写特判。
# ════════════════════════════════════════════════

def tool_ok(summary: str, **fields: Any) -> dict:
    return {"ok": True, "error": None, "summary": summary, **fields}


def tool_error(message: str, **fields: Any) -> dict:
    return {"ok": False, "error": message, "summary": None, **fields}


# ════════════════════════════════════════════════
# OpenAI function calling 格式的工具定义
# ════════════════════════════════════════════════

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_topologies",
            "description": "列出系统里已上传的所有拓扑（线路），返回每个拓扑的id、名称、监测点数量。"
                           "调用其他需要 line 参数的工具之前，如果不确定拓扑id，应该先调用这个工具查一遍。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_topology",
            "description": "查询指定拓扑的结构，返回所有监测点（编号、深度、父节点、负荷）和连接关系。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id），不确定时先调用 list_topologies 查询"},
                },
                "required": ["line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "locate_fault_from_alarms",
            "description": "根据故障指示器报警的监测点列表，用矩阵法/报警前沿法确定故障区段。返回候选故障区段和置信度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id）"},
                    "alarm_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "报警监测点列表（node_id 或 label），如 [\"814\", \"824\"]",
                    },
                    "fault_type": {
                        "type": "string",
                        "description": "已知故障类型（可选），如 'A相接地'、'BC两相短路'",
                    },
                },
                "required": ["line", "alarm_points"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "infer_fault_from_event",
            "description": "不需要人工先指定报警点：直接从该拓扑已上传的一次历史事件快照的原始电压/电流数据里，"
                           "自动判断哪些监测点异常，再用矩阵法给出故障区段。需要先知道 event_id"
                           "（用 list_topology_events 查询）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id）"},
                    "event_id": {"type": "string", "description": "历史事件的event_id"},
                },
                "required": ["line", "event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_topology_events",
            "description": "列出指定拓扑已上传的历史电气量事件快照（event_id、时间、涉及的监测点），"
                           "供 infer_fault_from_event 使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id）"},
                },
                "required": ["line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_similar_history",
            "description": "在历史故障事件库中搜索与当前情况相似的历史案例，返回最相关的历史事件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id）"},
                    "alarm_poles": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本次报警监测点，用于模糊匹配历史记录",
                    },
                    "fault_type_keyword": {
                        "type": "string",
                        "description": "故障类型关键词（可选），如 'B相'、'三相'",
                    },
                },
                "required": ["line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_info",
            "description": "获取指定监测点的详细信息：位置（拓扑、深度）、父节点、子节点、本地负荷估算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pole": {"type": "string", "description": "监测点标识（node_id 或 label）"},
                    "line": {"type": "string", "description": "拓扑id（可选，有助于区分不同拓扑间碰巧重名的标识）"},
                },
                "required": ["pole"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_dispatch_suggestion",
            "description": "根据故障定位结果生成标准化的派工建议，包含巡线路径和注意事项。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（topology_id）"},
                    "fault_from_pole": {"type": "string", "description": "故障区段起点（报警前沿节点）"},
                    "fault_to_pole": {"type": "string", "description": "故障区段终点（下游节点）"},
                    "fault_type": {"type": "string", "description": "故障类型（可选），如 'B相短路'"},
                },
                "required": ["line", "fault_from_pole"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_history_events",
            "description": "查询历史故障事件列表，可按拓扑过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "line": {"type": "string", "description": "拓扑id（可选）"},
                    "limit": {"type": "integer", "description": "返回条数限制，默认5"},
                },
                "required": [],
            },
        },
    },
]


# ════════════════════════════════════════════════
# 工具执行器
# ════════════════════════════════════════════════

def execute_tool(name: str, args: dict) -> dict:
    """根据工具名和参数执行对应工具，返回统一信封 {ok, error, summary, **字段}（见 tool_ok/tool_error）"""
    if name == "list_topologies":
        return _list_topologies()
    elif name == "query_topology":
        return _query_topology(**args)
    elif name == "locate_fault_from_alarms":
        return _locate_fault(**args)
    elif name == "infer_fault_from_event":
        return _infer_fault_from_event(**args)
    elif name == "list_topology_events":
        return _list_topology_events(**args)
    elif name == "search_similar_history":
        return _search_similar_history(**args)
    elif name == "get_node_info":
        return _get_node_info(**args)
    elif name == "generate_dispatch_suggestion":
        return _generate_dispatch(**args)
    elif name == "list_history_events":
        return _list_history(**args)
    else:
        return tool_error(f"未知工具: {name}")


# ════════════════════════════════════════════════
# 工具实现
# ════════════════════════════════════════════════

def _list_topologies() -> dict:
    from core import db
    topos = db.list_custom_topologies()
    if not topos:
        return tool_ok("系统里还没有任何拓扑，需要用户先在\"自定义拓扑\"页上传节点/边表。", topologies=[])
    return tool_ok(
        f"共 {len(topos)} 个拓扑：" + "、".join(f"{t['name']}({t['monitor_point_count']}个监测点)" for t in topos),
        topologies=[
            {
                "id": t["id"], "name": t["name"],
                "node_count": t["node_count"], "monitor_point_count": t["monitor_point_count"],
            }
            for t in topos
        ],
    )


def _query_topology(line: str) -> dict:
    topo = get_topology(line)
    if topo.node_count == 0:
        return tool_error(f"拓扑 {line} 不存在，或还没有标记任何监测点（无法用于故障定位）。可以先调用 list_topologies 确认拓扑id。")
    nodes_brief = [
        {
            "id": n.id,
            "pole": n.orig_pole,
            "depth": n.depth,
            "parent_id": n.parent_id,
            "load_kva": round(n.load_kva, 1),
        }
        for n in topo.nodes
    ]
    summary_lines = [f"拓扑 {line}（{topo.node_count}个监测点）："]
    for n in topo.nodes:
        children = [o for o in topo.nodes if o.parent_id == n.id]
        child_str = f" → [{', '.join(c.orig_pole for c in children)}]" if children else " (末端)"
        summary_lines.append(f"  {'  ' * n.depth}{n.orig_pole}(深度{n.depth}){child_str}")

    return tool_ok(
        f"{line} 共 {topo.node_count} 个监测点",
        line=line,
        node_count=topo.node_count,
        nodes=nodes_brief,
        topology_summary="\n".join(summary_lines[:30]),  # 限制长度
    )


def _locate_fault(line: str, alarm_points: list[str], fault_type: str = None) -> dict:
    req = FaultLocateRequest(line=line, alarm_points=alarm_points, fault_type=fault_type)
    result = locate_fault(req)

    sections = [s.model_dump() for s in result.candidate_sections]
    if sections:
        top = result.candidate_sections[0]
        to_str = top.to_pole if top.to_pole and top.to_pole != "(末端)" else "线路末端"
        summary = f"候选故障区段 {top.from_pole} → {to_str}（置信度：{top.confidence}），共 {len(sections)} 个候选区段"
    else:
        summary = "未找到候选故障区段"

    payload = tool_ok(
        summary,
        line=line,
        alarm_points=alarm_points,
        frontier_points=result.frontier_points,
        candidate_sections=sections,
        confidence=result.confidence,
        note=result.note,
        alarmed_node_ids=result.alarmed_node_ids,
    )

    ea = result.electrical_analysis
    if ea and ea.matched:
        payload["electrical_analysis"] = ea.model_dump()

    return payload


def _infer_fault_from_event(line: str, event_id: str) -> dict:
    from core.electrical_inference import infer_fault_from_event
    result = infer_fault_from_event(line, event_id)

    if not result.ok:
        return tool_error(result.note, inferred_alarm_points=result.inferred_alarm_points)

    if not result.fault_locate:
        # 推理跑通了，但没有判断出异常监测点——合法结果，不是失败
        return tool_ok(result.note, inferred_alarm_points=result.inferred_alarm_points)

    fr = result.fault_locate
    sections = [s.model_dump() for s in fr.candidate_sections]
    if sections:
        top = fr.candidate_sections[0]
        to_str = top.to_pole if top.to_pole and top.to_pole != "(末端)" else "线路末端"
        summary = f"自动推理出异常点 {', '.join(result.inferred_alarm_points)}，候选故障区段 {top.from_pole} → {to_str}（置信度：{top.confidence}）"
    else:
        summary = f"自动推理出异常点 {', '.join(result.inferred_alarm_points)}，但未找到候选故障区段"

    return tool_ok(
        summary,
        inferred_alarm_points=result.inferred_alarm_points,
        note=result.note,
        frontier_points=fr.frontier_points,
        candidate_sections=sections,
        confidence=fr.confidence,
    )


def _list_topology_events(line: str) -> dict:
    from core import db
    events = db.list_topology_events(line)
    return tool_ok(f"共 {len(events)} 条历史事件", line=line, events=events)


def _search_similar_history(
    line: str,
    alarm_poles: list[str] = None,
    fault_type_keyword: str = None,
    limit: int = 3,
) -> dict:
    events = load_history_events()
    candidates = [e for e in events if e.line == line]

    scored = []
    for ev in candidates:
        score = 0
        if alarm_poles:
            for pole in alarm_poles:
                if pole in ev.alarmed_points:
                    score += 2
                elif any(pole[:3] in ap for ap in ev.alarmed_points.split(",")):
                    score += 1
        if fault_type_keyword and fault_type_keyword in ev.fault_types:
            score += 1
        scored.append((score, ev))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

    results = []
    for score, ev in top:
        results.append({
            "event_id": ev.event_id,
            "time": ev.time,
            "fault_types": ev.fault_types,
            "alarmed_points": ev.alarmed_points,
            "frontier": ev.frontier,
            "candidate_sections": ev.candidate_sections,
            "confidence": ev.confidence,
            "note": ev.note,
            "similarity_score": score,
        })

    return tool_ok(
        f"找到 {len(results)} 条相似历史记录（该拓扑共 {len(candidates)} 条历史事件）",
        line=line,
        similar_events=results,
        total_history=len(candidates),
    )


def _get_node_info(pole: str, line: str = None) -> dict:
    matched = get_node_by_pole(pole.strip(), line=line)
    if not matched:
        return tool_error(f"未找到监测点 {pole}。可以先调用 list_topologies / query_topology 确认拓扑id和监测点标识。")

    all_nodes = get_line_nodes(matched.line)
    by_id = {n.id: n for n in all_nodes}
    children = [n for n in all_nodes if n.parent_id == matched.id]
    siblings = [n for n in all_nodes if n.parent_id == matched.parent_id and n.id != matched.id] if matched.parent_id else []
    kind = "末端节点" if len(children) == 0 else "分支节点" if len(children) > 1 else "中间节点"

    return tool_ok(
        f"{matched.orig_pole}，深度{matched.depth}，{kind}",
        id=matched.id,
        pole=matched.orig_pole,
        line=matched.line,
        depth=matched.depth,
        parent_id=matched.parent_id,
        parent_pole=by_id[matched.parent_id].orig_pole if matched.parent_id and matched.parent_id in by_id else "电源侧",
        children=[{"id": c.id, "pole": c.orig_pole} for c in children],
        siblings=[{"id": s.id, "pole": s.orig_pole} for s in siblings],
        load_kva=round(matched.load_kva, 1),
        is_leaf=len(children) == 0,
        is_branch_point=len(children) > 1,
    )


def _generate_dispatch(
    line: str,
    fault_from_pole: str,
    fault_to_pole: str = None,
    fault_type: str = None,
) -> dict:
    """生成标准化巡线派工建议"""
    fault_type_str = f"（{fault_type}）" if fault_type else ""
    section_str = f"{fault_from_pole} → {fault_to_pole}" if fault_to_pole and fault_to_pole != "(末端)" else f"{fault_from_pole} 末端"

    type_advice = ""
    if fault_type:
        if "接地" in fault_type:
            type_advice = "单相接地故障，重点检查绝缘子、导线对地距离，注意树竹挂线和雷击痕迹。"
        elif "三相" in fault_type:
            type_advice = "三相短路故障，通常为严重碰线或外力破坏，优先检查导线断线和异物搭线。"
        elif "两相" in fault_type or "AB" in fault_type or "BC" in fault_type or "AC" in fault_type:
            type_advice = "两相短路故障，检查导线弧垂过大、导线碰触或金具损坏情况。"

    suggestion = f"""**派工建议 — {line} {section_str}{fault_type_str}**

**故障区段：** {section_str}
**故障类型：** {fault_type or '待核实'}

**巡线任务：**
1. 派出巡线人员，从 **{fault_from_pole}** 出发
2. 沿线路向 **{fault_to_pole or '末端'}** 方向逐点检查
3. 重点排查：
   - 导线断线、弧垂异常
   - 绝缘子闪络放电痕迹
   - 树竹挂线、外力破坏
   - 跌落式熔断器状态

**注意事项：**
- {type_advice if type_advice else '全面检查各类故障隐患'}
- 发现故障点后立即上报调度，勿擅自处理
- 如需停电隔离，通过调度操作

**预计巡查：** 建议携带望远镜、照相机，做好记录。"""

    return tool_ok(
        "派工建议已生成",
        line=line,
        fault_section=section_str,
        fault_type=fault_type,
        suggestion=suggestion,
    )


def _list_history(line: str = None, limit: int = 5) -> dict:
    events = load_history_events()
    if line:
        events = [e for e in events if e.line == line]
    recent = events[-limit:][::-1]
    return tool_ok(
        f"共 {len(events)} 条历史事件（{line or '全部拓扑'}），返回最近 {len(recent)} 条",
        total=len(events),
        line=line or "全部",
        events=[
            {
                "event_id": e.event_id,
                "line": e.line,
                "time": e.time,
                "fault_types": e.fault_types,
                "alarmed_points": e.alarmed_points,
                "frontier": e.frontier,
                "candidate_sections": e.candidate_sections,
                "confidence": e.confidence,
            }
            for e in recent
        ],
    )
