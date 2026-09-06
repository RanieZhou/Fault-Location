"""
core/electrical_inference.py — 电气量分析 + 自动故障推理（通用版，取代旧的
core/electrical_analyzer.py——旧版本绑定死了两份固定Excel文件，这一版对任意
自定义拓扑通用，数据来自用户为该拓扑各自上传的历史电气量数据）。

两种用法：
  1. analyze_event(topo_id, alarm_points, event_time)：人工已经给出报警点（比如从
     故障指示器报警文本录入）时，找该次事件对应的原始电气量记录，作为矩阵法结论的
     辅助佐证——这是旧版本原有的能力，原样保留。
  2. infer_fault_from_event(topo_id, event_id)：全新能力——不需要人工先给报警点，
     直接从一次历史事件快照的原始电压/电流读数里自动判断哪些监测点异常（推断报警点），
     再复用现成的矩阵法算出故障区段。这是"上传历史数据→算法直接给出定位"这条新流程
     的核心。

沿用旧版本的启发式规则和设计取舍（样本量通常有限，MVP阶段用简单可解释规则，不是
训练出的模型）：
  - 电压读数缺失/为哨兵值，是判断"故障相"最直接的信号（该相电压跌破保护动作阈值）。
  - 不用电流做判据——现场传感器上报的电流量级通常和配电网真实短路电流量级对不上，
    强行用会给出没有数据支撑的结论。
  - 所有输出都诚实标注"启发式规则分析，仅供辅助参考，不替代矩阵法主结论"。
"""
from __future__ import annotations
import csv
import io
from datetime import datetime

from .models import (
    PhaseReading, NodeElectricalAnalysis, EventElectricalAnalysis, InferResult,
    UploadHistoricalDataResult,
)

_PHASES = ["A", "B", "C"]
_LOW_VOLTAGE_DEVIATION_PCT = -15.0  # 相电压相对该点正常基准偏低超过此比例，判定为异常
_EVENT_TIME_WINDOW_S = 60


def _to_float(v) -> float | None:
    """统一把哨兵值（字符串'-9.999'/'---'/空、负数原始值）转成None（=无有效读数）"""
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v in ("", "---", "-", "NA", "N/A", "null"):
            return None
        try:
            v = float(v)
        except ValueError:
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= -9:  # 覆盖 -9.999 / -9999 两种常见哨兵写法
        return None
    return f


def _compute_baseline(topo_id: str) -> dict[str, dict]:
    """{node_id: {"A": {"v_mean":..., "v_std":..., "n":...}, "B": {...}, "C": {...}}}"""
    from . import db
    rows = db.get_baseline_readings(topo_id)
    buckets: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        nid = r["node_id"]
        ph = r["phase"]
        if ph not in _PHASES:
            continue
        v = _to_float(r.get("voltage_kv"))
        if v is not None:
            buckets.setdefault(nid, {"A": [], "B": [], "C": []})[ph].append(v)

    baseline: dict[str, dict] = {}
    for nid, phases in buckets.items():
        entry = {}
        for ph in _PHASES:
            vals = phases[ph]
            if vals:
                mean = sum(vals) / len(vals)
                var = sum((x - mean) ** 2 for x in vals) / len(vals)
                entry[ph] = {"v_mean": mean, "v_std": var ** 0.5, "n": len(vals)}
        baseline[nid] = entry
    return baseline


def _analyze_node_readings(node_id: str, pole: str, readings: list[dict], baseline: dict) -> NodeElectricalAnalysis:
    """readings: 该节点在某一时刻的若干条phase读数（同一event_id下按node_id过滤出来的）"""
    by_phase = {r["phase"]: r for r in readings if r["phase"] in _PHASES}
    node_baseline = baseline.get(node_id, {})
    phases: list[PhaseReading] = []
    faulted: list[str] = []

    for ph in _PHASES:
        r = by_phase.get(ph, {})
        v = _to_float(r.get("voltage_kv"))
        i = _to_float(r.get("current_a"))
        is_faulted = v is None
        deviation = None
        if v is not None and ph in node_baseline and node_baseline[ph]["v_mean"] > 0:
            deviation = (v - node_baseline[ph]["v_mean"]) / node_baseline[ph]["v_mean"] * 100
            if deviation < _LOW_VOLTAGE_DEVIATION_PCT:
                is_faulted = True
        if is_faulted:
            faulted.append(ph)
        phases.append(PhaseReading(
            phase=ph, voltage_kv=v, current_a=i, is_faulted=is_faulted,
            deviation_pct=round(deviation, 1) if deviation is not None else None,
        ))

    valid_voltages = [p.voltage_kv for p in phases if p.voltage_kv is not None]
    imbalance = None
    if len(valid_voltages) >= 2:
        avg = sum(valid_voltages) / len(valid_voltages)
        if avg > 0:
            imbalance = round((max(valid_voltages) - min(valid_voltages)) / avg * 100, 1)

    severity = min(100.0, len(faulted) * 30 + sum(
        max(0, -p.deviation_pct) for p in phases if p.deviation_pct is not None
    ))

    return NodeElectricalAnalysis(
        pole=pole, node_id=node_id,
        phases=phases, faulted_phases=faulted,
        imbalance_ratio=imbalance, severity_score=round(severity, 1),
    )


def _summarize(node_analyses: list[NodeElectricalAnalysis]) -> EventElectricalAnalysis:
    if not node_analyses:
        return EventElectricalAnalysis(
            matched=False,
            note="未找到对应的原始电气量记录，电气量分析暂不可用，本次仅提供矩阵法定位结果。",
        )
    all_faulted: set[str] = set()
    for na in node_analyses:
        all_faulted.update(na.faulted_phases)
    max_severity = max((na.severity_score for na in node_analyses), default=0.0)
    severity_label = "high" if max_severity >= 60 else "medium" if max_severity >= 25 else "low"
    note = (
        f"共分析 {len(node_analyses)} 个监测点的原始电气量记录，"
        f"综合推断故障相：{'、'.join(sorted(all_faulted)) if all_faulted else '未见明显异常相'}。"
        "（基于历史电气量数据的启发式规则分析，样本量取决于已上传的历史数据多少，仅供辅助参考，不替代矩阵法主结论）"
    )
    return EventElectricalAnalysis(
        matched=True, node_analyses=node_analyses,
        inferred_fault_phases=sorted(all_faulted), severity_label=severity_label, note=note,
    )


# ════════════════════════════════════════════════
# 用法1：人工已给报警点，查电气量作为佐证（原有能力，数据源换成通用表）
# ════════════════════════════════════════════════

def analyze_event(topo_id: str, alarm_points: list[str], event_time: str | None = None) -> EventElectricalAnalysis:
    from . import db
    from .data_loader import resolve_pole

    baseline = _compute_baseline(topo_id)
    events = db.list_topology_events(topo_id)
    node_analyses: list[NodeElectricalAnalysis] = []

    for raw_pole in alarm_points:
        resolved = resolve_pole(raw_pole.strip(), line=topo_id)
        if not resolved:
            continue
        _, node_id, orig_pole = resolved

        # 找出现过该node_id读数的事件，挑时间最匹配的一个（同一节点历史上可能有多次不同事件）
        candidate_events = [e for e in events if node_id in e["node_ids"]]
        picked = _pick_event_for_time(candidate_events, event_time)
        if not picked:
            continue
        readings = [r for r in db.get_event_readings(picked["event_id"]) if r["node_id"] == node_id]
        if readings:
            node_analyses.append(_analyze_node_readings(node_id, orig_pole, readings, baseline))

    return _summarize(node_analyses)


def _pick_event_for_time(events: list[dict], event_time: str | None) -> dict | None:
    if not events:
        return None
    parsed = []
    for e in events:
        try:
            dt = datetime.fromisoformat(e["timestamp"]) if e["timestamp"] else None
        except ValueError:
            dt = None
        parsed.append((dt, e))

    if event_time:
        try:
            target = datetime.fromisoformat(event_time)
        except ValueError:
            target = None
        if target:
            in_window = [(dt, e) for dt, e in parsed if dt and abs((dt - target).total_seconds()) <= _EVENT_TIME_WINDOW_S]
            if in_window:
                in_window.sort(key=lambda x: abs((x[0] - target).total_seconds()))
                return in_window[0][1]
            return None
        return None

    with_time = [(dt, e) for dt, e in parsed if dt]
    if with_time:
        with_time.sort(key=lambda x: x[0], reverse=True)
        return with_time[0][1]
    return events[-1]


# ════════════════════════════════════════════════
# 用法2（新增）：不需要人工先给报警点，直接从一次事件快照自动推断
# ════════════════════════════════════════════════

def infer_fault_from_event(topo_id: str, event_id: str) -> InferResult:
    """
    自动推理入口：拿一次已上传的历史事件快照，自动判断哪些监测点异常（推断出报警点），
    再调用现成的矩阵法（core.fault_locator）算出故障区段——不需要人工先手动指定报警点，
    这是"上传历史数据→算法直接给出定位"这条新流程的核心。
    """
    from . import db
    from .fault_locator import locate_fault
    from .models import FaultLocateRequest

    event_meta = db.get_event_meta(event_id)
    if not event_meta or event_meta["topology_id"] != topo_id:
        return InferResult(ok=False, note=f"事件不存在: {event_id}")

    readings = db.get_event_readings(event_id)
    if not readings:
        return InferResult(ok=False, note="该事件没有任何读数数据")

    baseline = _compute_baseline(topo_id)
    nodes_meta = {n["node_id"]: n for n in db.get_custom_nodes(topo_id)}

    by_node: dict[str, list[dict]] = {}
    for r in readings:
        by_node.setdefault(r["node_id"], []).append(r)

    node_analyses: list[NodeElectricalAnalysis] = []
    inferred_alarm_points: list[str] = []
    for node_id, node_readings in by_node.items():
        meta = nodes_meta.get(node_id)
        label = meta["label"] if meta else node_id
        analysis = _analyze_node_readings(node_id, label, node_readings, baseline)
        node_analyses.append(analysis)
        if analysis.faulted_phases:
            inferred_alarm_points.append(label)

    if not inferred_alarm_points:
        return InferResult(
            ok=True, inferred_alarm_points=[],
            note="该事件快照里所有监测点电压均在正常范围内，未能自动识别出异常点——"
                 "可能故障发生在没有上传电气量数据的监测点，或本次事件本身电气量变化不明显。",
        )

    fault_result = locate_fault(FaultLocateRequest(
        line=topo_id, alarm_points=inferred_alarm_points, event_time=event_meta["timestamp"] or None,
    ))
    # 用刚算好的电气量分析直接覆盖，避免 locate_fault 内部再重新查一遍
    fault_result.electrical_analysis = _summarize(node_analyses)

    return InferResult(
        ok=True,
        inferred_alarm_points=inferred_alarm_points,
        fault_locate=fault_result,
        note=f"从 {len(by_node)} 个有读数的监测点中自动识别出 {len(inferred_alarm_points)} 个异常点，"
             f"已用矩阵法算出候选故障区段。",
    )


# ════════════════════════════════════════════════
# 历史数据上传（基线CSV + 事件CSV）
# ════════════════════════════════════════════════

def parse_baseline_csv(text: str) -> list[dict]:
    """期望列：node_id,phase,voltage_kv[,current_a]。phase不区分大小写，自动转大写。"""
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        nid = row.get("node_id") or row.get("id")
        phase = (row.get("phase") or "").upper()
        if not nid or phase not in _PHASES:
            continue
        out.append({
            "node_id": nid, "phase": phase,
            "voltage_kv": row.get("voltage_kv") or row.get("voltage") or None,
            "current_a": row.get("current_a") or row.get("current") or None,
        })
    return out


def parse_event_csv(text: str) -> list[dict]:
    """期望列：event_id,timestamp,node_id,phase,voltage_kv[,current_a]"""
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        eid = row.get("event_id")
        nid = row.get("node_id") or row.get("id")
        phase = (row.get("phase") or "").upper()
        if not eid or not nid or phase not in _PHASES:
            continue
        out.append({
            "event_id": eid,
            "timestamp": row.get("timestamp") or row.get("time") or "",
            "node_id": nid, "phase": phase,
            "voltage_kv": row.get("voltage_kv") or row.get("voltage") or None,
            "current_a": row.get("current_a") or row.get("current") or None,
        })
    return out


def upload_historical_data(topo_id: str, baseline_csv_text: str | None, event_csv_text: str | None) -> UploadHistoricalDataResult:
    """
    两个文件都可选，各自独立解析写入——允许用户只先传基线、后面再补事件数据，或反过来。
    重新上传会先清空该拓扑之前的历史电气量数据，避免新旧数据混在一起产生错误的基线统计。
    """
    from . import db

    valid_node_ids = {n["node_id"] for n in db.get_custom_nodes(topo_id)}
    warnings: list[str] = []
    db.clear_topology_historical_data(topo_id)

    baseline_rows = 0
    if baseline_csv_text:
        parsed = parse_baseline_csv(baseline_csv_text)
        unknown = {r["node_id"] for r in parsed} - valid_node_ids
        if unknown:
            warnings.append(f"基线数据里有 {len(unknown)} 个node_id不属于该拓扑，已跳过：{sorted(unknown)[:10]}")
        parsed = [r for r in parsed if r["node_id"] in valid_node_ids]
        if parsed:
            db.insert_baseline_readings(topo_id, parsed)
        baseline_rows = len(parsed)

    event_count, event_rows = 0, 0
    if event_csv_text:
        parsed = parse_event_csv(event_csv_text)
        unknown = {r["node_id"] for r in parsed} - valid_node_ids
        if unknown:
            warnings.append(f"事件数据里有 {len(unknown)} 个node_id不属于该拓扑，已跳过：{sorted(unknown)[:10]}")
        parsed = [r for r in parsed if r["node_id"] in valid_node_ids]

        by_event: dict[str, list[dict]] = {}
        timestamps: dict[str, str] = {}
        for r in parsed:
            by_event.setdefault(r["event_id"], []).append(r)
            if r["timestamp"]:
                timestamps[r["event_id"]] = r["timestamp"]

        for eid, rows in by_event.items():
            db.insert_event_with_readings(topo_id, eid, timestamps.get(eid, ""), rows)
        event_count = len(by_event)
        event_rows = len(parsed)

    if baseline_rows == 0 and event_rows == 0:
        return UploadHistoricalDataResult(ok=False, warnings=warnings, error="没有解析出任何有效数据行，请检查CSV列名和内容")

    return UploadHistoricalDataResult(
        ok=True, baseline_rows=baseline_rows, event_count=event_count, event_rows=event_rows, warnings=warnings,
    )


# ════════════════════════════════════════════════
# 生产级监测数据导入与复现（10列标准数据模型）
# ════════════════════════════════════════════════

import re
from typing import Any

def clean_pole_identifier(raw: Any) -> str:
    """从监测点原始名称（如'10kV松平线27.3.88.2.2.1小'）提取规范杆号/母线名"""
    s = str(raw or "").strip()
    s = re.sub(r"^(?:10\s*k+v)?(?:松平线|松坪线|火龙线|北冲线|极乐村线|邵九线)?#?", "", s, flags=re.I).strip()
    s = re.sub(r"[大小支杆]+$", "", s).strip()
    return s or str(raw or "").strip()


def _match_col(cols: list[str], keywords: list[str]) -> str | None:
    for c in cols:
        c_clean = str(c).lower().replace(" ", "").replace("_", "")
        for kw in keywords:
            if kw in c_clean:
                return c
    return None


def ingest_production_monitoring_file(
    file_bytes: bytes,
    filename: str,
    topology_id: Optional[str] = None,
) -> dict:
    """
    解析生产级监测数据文件（.xlsx / .xls / .csv），提取10大核心字段并分组落库：
    1. 编号 (自动生成序号)
    2. 监测点名称 (监测点名称1)
    3. 设备类型
    4. 终端状态
    5. 线路状态 (如 短路:B相)
    6. 预警状态 (如 低电压:A相)
    7. 三相电压 (Ua, Ub, Uc，负数哨兵值统一处理)
    8. 三相电流 (Ia, Ib, Ic)
    9. 三相相位 (电压相位/电流相位)
    10. 量测时间
    
    按量测时间滑动窗口（60s）自动聚合成多个事件批次，并识别出动作的异常监测点。
    """
    from . import db
    from .custom_topology import seed_sp_hl_topologies_if_needed
    seed_sp_hl_topologies_if_needed()

    df = None
    fn = filename.lower()
    if fn.endswith((".xlsx", ".xls")):
        import pandas as pd
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        import pandas as pd
        for enc in ("utf-8-sig", "gb18030", "gbk", "utf-8"):
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
                break
            except Exception:
                continue
        if df is None:
            raise ValueError("无法解析该文件，请确保文件编码为 UTF-8 或 GBK")

    cols = df.columns.tolist()
    node_name_col = _match_col(cols, ["监测点名称1", "监测点名称", "监测点", "node_name", "nodename", "name", "杆号"])
    device_type_col = _match_col(cols, ["设备类型", "devicetype", "type"])
    terminal_status_col = _match_col(cols, ["终端状态", "terminalstatus", "terminal"])
    line_status_col = _match_col(cols, ["线路状态", "linestatus", "line_state"])
    warning_status_col = _match_col(cols, ["预警状态", "warningstatus", "warning", "alarmstatus"])
    ua_col = _match_col(cols, ["a相电压(kv)", "a相电压", "ua", "voltage_a", "voltagea"])
    ub_col = _match_col(cols, ["b相电压(kv)", "b相电压", "ub", "voltage_b", "voltageb"])
    uc_col = _match_col(cols, ["c相电压(kv)", "c相电压", "uc", "voltage_c", "voltagec"])
    ia_col = _match_col(cols, ["a相电流(a)", "a相电流", "ia", "current_a", "currenta"])
    ib_col = _match_col(cols, ["b相电流(a)", "b相电流", "ib", "current_b", "currentb"])
    ic_col = _match_col(cols, ["c相电流(a)", "c相电流", "ic", "current_c", "currentc"])
    phase_a_col = _match_col(cols, ["a相电压相位", "a相电流相位", "a相相位", "phase_a", "phasea"])
    phase_b_col = _match_col(cols, ["b相电压相位", "b相电流相位", "b相相位", "phase_b", "phaseb"])
    phase_c_col = _match_col(cols, ["c相电压相位", "c相电流相位", "c相相位", "phase_c", "phasec"])
    time_col = _match_col(cols, ["量测时间", "测量时间", "时间", "time", "timestamp", "datetime"])

    if not node_name_col or not time_col:
        raise ValueError("数据表必须包含'监测点名称'和'量测时间'两列")

    import pandas as pd
    df["_parsed_time"] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.dropna(subset=["_parsed_time"]).sort_values("_parsed_time")

    topos = {t["id"]: t["name"] for t in db.list_custom_topologies()}

    time_diff = df["_parsed_time"].diff().dt.total_seconds().abs()
    event_groups = (time_diff > _EVENT_TIME_WINDOW_S).cumsum()

    created_events = []
    total_records = 0

    for group_idx, (_, group_df) in enumerate(df.groupby(event_groups)):
        first_time = group_df[time_col].iloc[0]
        target_topo = topology_id
        if not target_topo or target_topo not in topos:
            sample_name = str(group_df[node_name_col].iloc[0])
            if any(k in sample_name for k in ("松平", "松坪")):
                target_topo = "ct_sp" if "ct_sp" in topos else (list(topos.keys())[0] if topos else "ct_sp")
            elif any(k in sample_name for k in ("火龙", "HL")):
                target_topo = "ct_hl" if "ct_hl" in topos else (list(topos.keys())[0] if topos else "ct_hl")
            else:
                target_topo = list(topos.keys())[0] if topos else "default"

        topo_name = topos.get(target_topo, target_topo)
        clean_time_str = str(first_time).replace("-", "").replace(":", "").replace(" ", "_")
        event_id = f"evt_{clean_time_str}_{group_idx+1}"

        records = []
        abnormal_poles = []
        summaries = []

        for row_idx, (_, r) in enumerate(group_df.iterrows()):
            node_name = str(r[node_name_col]).strip()
            clean_pole = clean_pole_identifier(node_name)
            device_type = str(r[device_type_col]).strip() if device_type_col else "配电线路"
            terminal_status = str(r[terminal_status_col]).strip() if terminal_status_col else "正常"
            line_status = str(r[line_status_col]).strip() if line_status_col else "正常"
            warning_status = str(r[warning_status_col]).strip() if warning_status_col else "正常"
            ua = _to_float(r[ua_col]) if ua_col else None
            ub = _to_float(r[ub_col]) if ub_col else None
            uc = _to_float(r[uc_col]) if uc_col else None
            ia = _to_float(r[ia_col]) if ia_col else None
            ib = _to_float(r[ib_col]) if ib_col else None
            ic = _to_float(r[ic_col]) if ic_col else None
            phase_a = _to_float(r[phase_a_col]) if phase_a_col else None
            phase_b = _to_float(r[phase_b_col]) if phase_b_col else None
            phase_c = _to_float(r[phase_c_col]) if phase_c_col else None
            measure_time = str(r[time_col]).strip()

            is_abnormal = False
            reasons = []
            if any(k in line_status for k in ("短路", "接地", "故障", "告警")):
                is_abnormal = True
                reasons.append(line_status)
                if line_status not in summaries:
                    summaries.append(line_status)
            if warning_status and warning_status not in ("正常", "-", "---", ""):
                is_abnormal = True
                reasons.append(warning_status)
                if warning_status not in summaries:
                    summaries.append(warning_status)
            for ph, val in [("A", ua), ("B", ub), ("C", uc)]:
                if val is None:
                    is_abnormal = True
                    reasons.append(f"{ph}相缺相/无电压")
                elif val <= 0.5:
                    is_abnormal = True
                    reasons.append(f"{ph}相严重低电压({val}kV)")

            if is_abnormal:
                abnormal_poles.append(clean_pole)

            records.append({
                "record_no": row_idx + 1,
                "node_id": clean_pole,
                "node_name": node_name,
                "device_type": device_type,
                "terminal_status": terminal_status,
                "line_status": line_status,
                "warning_status": warning_status,
                "ua": ua,
                "ub": ub,
                "uc": uc,
                "ia": ia,
                "ib": ib,
                "ic": ic,
                "phase_a": phase_a,
                "phase_b": phase_b,
                "phase_c": phase_c,
                "measure_time": measure_time,
                "is_abnormal": is_abnormal,
                "abnormal_reason": " / ".join(reasons) if reasons else "",
            })

        unique_inferred = list(dict.fromkeys(abnormal_poles))
        fault_summary = "；".join(summaries) if summaries else ("多处监测点电压异常" if unique_inferred else "正常工况")

        event_meta = {
            "event_id": event_id,
            "topology_id": target_topo,
            "topology_name": topo_name,
            "timestamp": str(first_time),
            "record_count": len(records),
            "abnormal_count": len(unique_inferred),
            "fault_summary": fault_summary,
            "inferred_poles": ", ".join(unique_inferred),
        }
        db.save_monitoring_event_and_records(event_meta, records)
        created_events.append(event_meta)
        total_records += len(records)

    return {
        "ok": True,
        "event_count": len(created_events),
        "record_count": total_records,
        "events": created_events,
    }


def reproduce_monitoring_event(event_id: str) -> dict:
    """
    根据事件ID执行自动复现定位：
    1. 调出该事件的所有监测记录及已自动判别的报警监测点
    2. 调用核心矩阵法定夺故障候选区段
    3. 整合电气量证据返回前端
    """
    from . import db
    from .fault_locator import locate_fault
    from .models import FaultLocateRequest

    event_meta = db.get_monitoring_event(event_id)
    if not event_meta:
        raise ValueError(f"未找到事件: {event_id}")

    records = db.get_monitoring_records(event_id)
    raw_inferred = [s.strip() for s in (event_meta.get("inferred_poles") or "").split(",") if s.strip()]

    if not raw_inferred:
        raw_inferred = list(dict.fromkeys([r["node_id"] for r in records if r.get("is_abnormal")]))

    topo_id = event_meta["topology_id"]
    timestamp = event_meta["timestamp"]

    locate_res = None
    if raw_inferred:
        req = FaultLocateRequest(
            line=topo_id,
            alarm_points=raw_inferred,
            event_time=timestamp,
        )
        locate_res = locate_fault(req)

    return {
        "ok": True,
        "event_id": event_id,
        "topology_id": topo_id,
        "topology_name": event_meta.get("topology_name", topo_id),
        "timestamp": timestamp,
        "inferred_poles": raw_inferred,
        "fault_summary": event_meta.get("fault_summary", ""),
        "record_count": len(records),
        "records": records,
        "fault_locate": locate_res.model_dump() if locate_res else None,
    }


def seed_sample_monitoring_data_if_empty() -> dict:
    """如果当前监测数据库为空且data/历史数据/异常数据.xlsx存在，则自动载入样例数据"""
    from pathlib import Path
    from . import db
    existing = db.list_monitoring_events()
    if existing:
        return {"ok": True, "message": "已有监测事件，跳过自动载入", "event_count": len(existing)}

    sample_path = Path("data/历史数据/异常数据.xlsx")
    if not sample_path.exists():
        return {"ok": False, "message": "样例数据文件不存在"}

    try:
        content = sample_path.read_bytes()
        res = ingest_production_monitoring_file(content, "异常数据.xlsx")
        return {"ok": True, "message": "已成功载入样例监测数据", **res}
    except Exception as e:
        return {"ok": False, "message": f"载入样例数据失败: {e}"}

