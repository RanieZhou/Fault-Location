# -*- coding: utf-8 -*-
"""web/routers/fault.py — 故障定位API（接入 core 层真实引擎）"""
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

from core.fault_locator import locate_fault
from core.data_loader import load_history_events
from core.models import FaultLocateRequest, HistoryEvent
from core import db as _db
from core.electrical_inference import (
    ingest_production_monitoring_file,
    reproduce_monitoring_event,
    seed_sample_monitoring_data_if_empty,
)

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


# ════════════════════════════════════════════════
# 生产级监测数据管理与自动复现定位
# ════════════════════════════════════════════════

@router.post("/monitoring/upload")
async def upload_monitoring_data_api(
    file: UploadFile = File(...),
    topology_id: Optional[str] = Form(None),
):
    """
    上传生产级监测数据（.xlsx / .xls / .csv），解析10大核心字段并分组落库。
    可指定关联拓扑，若不指定则根据监测点名称自动关联拓扑。
    """
    content = await file.read()
    if not content:
        raise HTTPException(400, "上传的文件内容为空")
    try:
        res = ingest_production_monitoring_file(content, file.filename or "data.xlsx", topology_id)
        return res
    except Exception as e:
        raise HTTPException(400, f"监测数据解析失败: {e}")


@router.get("/monitoring/records")
async def query_monitoring_records_api(
    topology_id: Optional[str] = None,
    device_type: Optional[str] = None,
    line_status: Optional[str] = None,
    terminal_status: Optional[str] = None,
    warning_status: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
):
    """历史数据页用：不按事件批次分组，把所有10列监测记录打平按量测时间倒序分页查询，
    支持按枚举字段筛选、按监测点名称模糊搜索。"""
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    items, total = _db.query_monitoring_records(
        topology_id=topology_id, device_type=device_type, line_status=line_status,
        terminal_status=terminal_status, warning_status=warning_status, search=search,
        page=page, page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/monitoring/records/filter-options")
async def get_monitoring_filter_options_api(topology_id: Optional[str] = None):
    """历史数据页的筛选下拉框选项——从实际数据里取当前出现过的取值，不写死枚举"""
    return _db.list_monitoring_filter_options(topology_id)


@router.get("/monitoring/events")
async def list_monitoring_events_api(topology_id: Optional[str] = None):
    """获取所有监测事件列表（包含时间戳、监测点数量、故障简述、自动识别的报警点）"""
    events = _db.list_monitoring_events(topology_id)
    return {"total": len(events), "events": events}


@router.get("/monitoring/events/{event_id}")
async def get_monitoring_event_details_api(event_id: str):
    """获取单次监测事件的详细信息及所属的全部10列标准监测数据记录"""
    event = _db.get_monitoring_event(event_id)
    if not event:
        raise HTTPException(404, f"事件不存在: {event_id}")
    records = _db.get_monitoring_records(event_id)
    return {"event": event, "records": records}


@router.post("/monitoring/events/{event_id}/reproduce")
async def reproduce_monitoring_event_api(event_id: str):
    """
    根据事件ID执行一键复现定位：
    自动提取该事件判定出的报警监测点，自动调用拓扑矩阵法完成区段定位，
    并将定位结果持久化到历史故障事件库中（带实时标签）。
    """
    try:
        res = reproduce_monitoring_event(event_id)
        fl = res.get("fault_locate")
        if fl and fl.get("alarmed_node_ids"):
            cand_str = " / ".join(
                s.get("to_pole") if s.get("to_pole") != "(末端)" else "(无)"
                for s in fl.get("candidate_sections", [])
            ) or "(无)"
            _db.insert_event(HistoryEvent(
                event_id=fl.get("event_id", f"rep_{event_id}"),
                line=res["topology_id"],
                time=res["timestamp"] or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                fault_types=res.get("fault_summary", ""),
                alarmed_points=", ".join(res.get("inferred_poles", [])),
                frontier=" / ".join(fl.get("frontier_points", [])),
                candidate_sections=cand_str,
                confidence=fl.get("confidence", "medium"),
                note=fl.get("note", "根据监测数据自动研判复现"),
                source="live",
            ))
        return res
    except Exception as e:
        raise HTTPException(400, f"复现定位失败: {e}")


@router.post("/monitoring/seed-sample")
async def seed_sample_monitoring_data_api():
    """从本地样例数据（data/历史数据/异常数据.xlsx）一键载入15条真实故障监测记录"""
    res = seed_sample_monitoring_data_if_empty()
    return res


@router.delete("/monitoring/clear")
async def clear_monitoring_data_api(topology_id: Optional[str] = None):
    """清空监测数据记录"""
    _db.clear_monitoring_records(topology_id)
    return {"ok": True}

