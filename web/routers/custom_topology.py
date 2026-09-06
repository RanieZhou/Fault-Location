# -*- coding: utf-8 -*-
"""
web/routers/custom_topology.py — 自定义拓扑上传/管理API

用户上传节点表(node_id,label)+边表(from_id,to_id) → 校验成树 → 存SQLite。
之后可以标记哪些节点是监测点、给线段批量设参数；这些数据经
core.custom_topology.build_monitor_view() 折叠后，能直接喂给现成的矩阵法
故障定位算法（core.fault_locator 完全不用改）。
"""
import secrets
from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from typing import Optional
from core import db
from core.custom_topology import (
    decode_csv_bytes, parse_nodes_csv, parse_edges_csv, derive_nodes_from_edges,
    validate_and_build_tree, get_full_view, build_monitor_view,
)
from core.electrical_inference import upload_historical_data, infer_fault_from_event
from core.models import SetMonitorPointsRequest, SetEdgeParamsRequest

router = APIRouter()


@router.get("/")
async def list_topologies():
    return {"topologies": db.list_custom_topologies()}


@router.post("/upload")
async def upload_topology(
    name: str = Form(...),
    nodes_file: Optional[UploadFile] = File(None),
    edges_file: UploadFile = File(...),
):
    """
    edges_file: CSV，列 from_id,to_id[,length_km 或 length_m 或 length_ft]——很多真实
                线路表本身就是"起点/终点/长度"一张表，长度列可选，传了就直接落库。
    nodes_file: CSV，列 node_id[,label]，可选——不传时节点列表直接从边表里出现过的
                所有id反推（label默认用id本身），这是大多数情况下更省事的用法；
                只有需要给节点起一个和id不同的展示名称时才需要单独传这张表。
    校验通过后落库；is_monitor_point 初始全部为False，需要上传后单独设置。
    """
    name = name.strip()
    if not name:
        raise HTTPException(400, "请填写拓扑名称")

    edges_text = decode_csv_bytes(await edges_file.read())
    edges = parse_edges_csv(edges_text)
    if not edges:
        raise HTTPException(400, "边表为空或格式不对——需要至少包含 from_id,to_id 两列")

    if nodes_file is not None:
        nodes_text = decode_csv_bytes(await nodes_file.read())
        nodes = parse_nodes_csv(nodes_text)
        if not nodes:
            raise HTTPException(400, "节点表为空或格式不对——需要至少包含 node_id 列")
    else:
        nodes = derive_nodes_from_edges(edges)

    _, _, _, errors = validate_and_build_tree(nodes, edges)
    if errors:
        raise HTTPException(400, "拓扑校验未通过：\n" + "\n".join(errors))

    topo_id = "ct_" + secrets.token_hex(4)
    db.create_custom_topology(topo_id, name, nodes, edges)

    return {
        "ok": True, "id": topo_id, "name": name,
        "node_count": len(nodes), "edge_count": len(edges), "warnings": [],
    }


@router.get("/{topo_id}")
async def get_topology_detail(topo_id: str):
    """完整物理图（管理页用）：全部节点(含is_monitor_point/depth/parent_id)+全部边(含参数)。"""
    meta = db.get_custom_topology_meta(topo_id)
    if not meta:
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    nodes, edges, errors = get_full_view(topo_id)
    return {
        "id": topo_id, "name": meta["name"],
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
        "tree_errors": errors,
    }


@router.get("/{topo_id}/preview")
async def preview_monitor_view(topo_id: str):
    """折叠后的监测点树——即故障定位算法实际会看到的样子，格式和 /api/topology/{line_code} 一致。"""
    meta = db.get_custom_topology_meta(topo_id)
    if not meta:
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    nodes, edges = build_monitor_view(topo_id)
    return {
        "id": topo_id, "name": meta["name"],
        "node_count": len(nodes), "edge_count": len(edges),
        "nodes": [
            {
                "id": n.id, "orig_pole": n.orig_pole, "line": n.line,
                "depth": n.depth, "parent_id": n.parent_id,
                "sides_observed": n.sides_observed, "load_kva": n.load_kva, "status": n.status,
            }
            for n in nodes
        ],
        "edges": [
            {
                "line": e.line, "from_id": e.from_id, "to_id": e.to_id, "label": e.label,
                "length_km": e.length_km, "resistance_ohm": e.resistance_ohm, "reactance_ohm": e.reactance_ohm,
            }
            for e in edges
        ],
    }


@router.patch("/{topo_id}/nodes")
async def set_monitor_points(topo_id: str, req: SetMonitorPointsRequest):
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    if not req.node_ids:
        raise HTTPException(400, "node_ids 不能为空")
    db.update_custom_monitor_points(topo_id, req.node_ids, req.is_monitor_point)
    return {"ok": True, "updated": len(req.node_ids)}


@router.patch("/{topo_id}/edges")
async def set_edge_params(topo_id: str, req: SetEdgeParamsRequest):
    """
    批量设置线路参数——同规格线路（相同导线的每公里电阻/电抗）一次性设置，不用逐条填。
    每条边的总电阻/电抗 = 每公里值 × 该边自己的长度，所以同一批边长度不同也不会算错。
    """
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    if not req.edges:
        raise HTTPException(400, "edges 不能为空")
    if req.length_km is None and req.resistance_ohm_per_km is None and req.reactance_ohm_per_km is None:
        raise HTTPException(400, "至少要提供一个要设置的参数字段")

    current = {(e["from_id"], e["to_id"]): e for e in db.get_custom_edges(topo_id)}
    updated = 0
    for f, t in req.edges:
        cur = current.get((f, t))
        if not cur:
            continue
        effective_length = req.length_km if req.length_km is not None else cur["length_km"]
        new_r = req.resistance_ohm_per_km * effective_length if req.resistance_ohm_per_km is not None else None
        new_x = req.reactance_ohm_per_km * effective_length if req.reactance_ohm_per_km is not None else None
        db.update_custom_edge_params(
            topo_id, [(f, t)],
            length_km=req.length_km, resistance_ohm=new_r, reactance_ohm=new_x,
        )
        updated += 1
    return {"ok": True, "updated": updated}


@router.delete("/{topo_id}")
async def delete_topology(topo_id: str):
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    db.delete_custom_topology(topo_id)
    return {"ok": True}


# ════════════════════════════════════════════════
# 历史电气量数据（基线+事件）—— 电气量分析/自动推理的数据来源
# ════════════════════════════════════════════════

@router.post("/{topo_id}/historical-data/upload")
async def upload_historical_data_api(
    topo_id: str,
    baseline_file: Optional[UploadFile] = File(None),
    event_file: Optional[UploadFile] = File(None),
):
    """
    baseline_file: CSV，列 node_id,phase,voltage_kv[,current_a]——正常运行时的读数，
                   同一监测点多行用于统计均值/方差，作为判断"异常"的基准。
    event_file:    CSV，列 event_id,timestamp,node_id,phase,voltage_kv[,current_a]——
                   历史真实故障发生时刻各监测点的原始读数快照，同一event_id为一次事件。
    两个文件都可选，但至少要传一个；重新上传会清空该拓扑之前的历史电气量数据。
    """
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    if not baseline_file and not event_file:
        raise HTTPException(400, "至少要上传基线数据或事件数据中的一个")

    baseline_text = decode_csv_bytes(await baseline_file.read()) if baseline_file else None
    event_text = decode_csv_bytes(await event_file.read()) if event_file else None

    result = upload_historical_data(topo_id, baseline_text, event_text)
    if not result.ok:
        raise HTTPException(400, result.error or "上传失败")
    return result.model_dump()


@router.get("/{topo_id}/historical-data/events")
async def list_historical_events_api(topo_id: str):
    """列出该拓扑已上传的历史事件快照（供前端选择"运行推理"用）"""
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    return {"events": db.list_topology_events(topo_id)}


@router.post("/{topo_id}/historical-data/events/{event_id}/infer")
async def infer_event_api(topo_id: str, event_id: str):
    """
    自动推理：不需要人工先指定报警点，直接从这次事件快照的原始电压/电流读数里
    自动判断哪些监测点异常，再用现成的矩阵法算出故障区段。
    """
    if not db.get_custom_topology_meta(topo_id):
        raise HTTPException(404, f"拓扑不存在: {topo_id}")
    result = infer_fault_from_event(topo_id, event_id)

    # 推理成功且确实定位出了结果时，也记入历史事件库，和手动定位保持一致的行为
    if result.ok and result.fault_locate and result.fault_locate.alarmed_node_ids:
        from datetime import datetime
        from core.models import HistoryEvent
        fr = result.fault_locate
        cand_str = " / ".join(
            s.to_pole if s.to_pole != "(末端)" else "(无)" for s in fr.candidate_sections
        ) or "(无)"
        db.insert_event(HistoryEvent(
            event_id=fr.event_id, line=topo_id,
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            fault_types="", alarmed_points=", ".join(fr.alarm_points),
            frontier=" / ".join(fr.frontier_points), candidate_sections=cand_str,
            confidence=fr.confidence, note=fr.note, source="live",
        ))

    return result.model_dump()
