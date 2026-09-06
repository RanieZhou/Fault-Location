# -*- coding: utf-8 -*-
"""web/routers/fault.py — 故障定位API（接入 core 层真实引擎）"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.fault_locator import locate_fault
from core.data_loader import load_history_events
from core.models import FaultLocateRequest, HistoryEvent
from core import db as _db

router = APIRouter()


# ── 请求/响应模型 ──────────────────────────────────────────────

class LocateRequest(BaseModel):
    line_code: str              # 自定义拓扑的 topology_id（/api/custom-topology 上传后返回的id）
    alarm_poles: list[str]      # 报警监测点列表（node_id 或 label）
    fault_type: Optional[str] = None
    event_time: Optional[str] = None  # 该事件发生时间，可选——用于精确关联电气量原始记录（"复现历史事件"时传入）


# ── 路由 ──────────────────────────────────────────────────────

@router.post("/locate")
async def locate_fault_api(req: LocateRequest):
    """故障区段定位。输入报警监测点列表，返回候选故障区段和置信度。"""
    line_name = req.line_code
    if not _db.get_custom_topology_meta(line_name):
        raise HTTPException(400, f"拓扑不存在: {line_name}")
    if not req.alarm_poles:
        raise HTTPException(400, "报警节点列表不能为空")

    core_req = FaultLocateRequest(
        line=line_name,
        alarm_points=req.alarm_poles,
        fault_type=req.fault_type,
        event_time=req.event_time,
    )
    result = locate_fault(core_req)

    # 序列化为前端友好格式
    sections_out = []
    for s in result.candidate_sections:
        sections_out.append({
            "from_pole": s.from_pole,
            "to_pole": s.to_pole,
            "from_id": s.from_id,
            "to_id": s.to_id,
            "confidence": s.confidence,
        })

    # 持久化为一条新的历史事件（source='live'）——只在确实解析出报警点时记录，
    # 避免把无效/查询失败的请求也计入历史事件库
    if result.alarmed_node_ids:
        cand_str = " / ".join(
            s.to_pole if s.to_pole != "(末端)" else "(无)" for s in result.candidate_sections
        ) or "(无)"
        _db.insert_event(HistoryEvent(
            event_id=result.event_id,
            line=line_name,
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            fault_types=req.fault_type or "",
            alarmed_points=", ".join(result.alarm_points),
            frontier=" / ".join(result.frontier_points),
            candidate_sections=cand_str,
            confidence=result.confidence,
            note=result.note,
            source="live",
        ))

    return {
        "event_id": result.event_id,
        "line_code": req.line_code,
        "line_name": line_name,
        "alarm_poles": result.alarm_points,
        "frontier_points": result.frontier_points,
        "candidate_sections": sections_out,
        "confidence": result.confidence,
        "note": result.note,
        "alarmed_node_ids": result.alarmed_node_ids,
        "method": "matrix_frontier",
        "electrical_analysis": result.electrical_analysis.model_dump() if result.electrical_analysis else None,
    }


@router.get("/history")
async def get_history(
    line: Optional[str] = None,
    fault_type: Optional[str] = None,
    search: Optional[str] = None,
):
    """获取历史故障事件列表，支持按拓扑（topology_id）/故障类型/关键词过滤。"""
    events = load_history_events()

    if line:
        events = [e for e in events if e.line == line]
    if fault_type:
        events = [e for e in events if fault_type in e.fault_types]
    if search:
        s = search.lower()
        events = [
            e for e in events
            if s in e.alarmed_points.lower()
            or s in e.fault_types.lower()
            or s in e.candidate_sections.lower()
            or s in e.note.lower()
        ]

    return {
        "total": len(events),
        "events": [e.model_dump() for e in events],
    }


@router.get("/history/{event_id}")
async def get_history_event(event_id: str):
    """获取单条历史故障事件详情"""
    events = load_history_events()
    matched = [e for e in events if e.event_id == event_id]
    if not matched:
        raise HTTPException(404, f"事件不存在: {event_id}")
    return {"events": [e.model_dump() for e in matched]}
