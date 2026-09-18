import math
import statistics

import networkx as nx
from sqlalchemy.orm import Session

from app.models import BaselineStat, Edge, LineModel, MeasurementRecord, Monitor, Network, Node
from app.models.measurement import SIGNAL_FIELDS
from app.schemas.baseline import BaselineBuildResult, BaselineStatOut, NetworkReadiness, ReadinessItem

NORMAL_FILTER = {
    "device_type": "配电线路",
    "terminal_status": "正常",
    "line_status": "正常",
    "warning_status": "正常",
}


def _circular_mean_std_deg(values_deg: list[float]) -> tuple[float, float]:
    """Mean/std for angular data (phase_* signals), per Mardia & Jupp's
    circular statistics -- a plain arithmetic mean/std is wrong near the
    0/360 wrap (e.g. mean(359, 1) should be ~0 deg, not the arithmetic 180).

    mean = atan2(mean(sin theta), mean(cos theta))
    std  = sqrt(-2 * ln(R)), R = mean resultant length, in the same "degrees"
    scale as the input (matches scipy.stats.circstd's high/low rescaling).
    """
    radians = [math.radians(v) for v in values_deg]
    n = len(radians)
    mean_sin = sum(math.sin(r) for r in radians) / n
    mean_cos = sum(math.cos(r) for r in radians) / n
    mean_deg = math.degrees(math.atan2(mean_sin, mean_cos))
    r_bar = min(math.sqrt(mean_sin**2 + mean_cos**2), 1.0)
    r_bar = max(r_bar, 1e-9)  # avoid log(0) for a perfectly uniform spread
    std_deg = math.degrees(math.sqrt(-2 * math.log(r_bar)))
    return mean_deg, std_deg


def build_baseline(db: Session, network: Network) -> BaselineBuildResult:
    monitors = db.query(Monitor).filter(Monitor.network_id == network.network_id).all()
    monitor_ids = [m.monitor_id for m in monitors]

    if monitor_ids:
        db.query(BaselineStat).filter(BaselineStat.monitor_id.in_(monitor_ids)).delete(synchronize_session=False)

    records = (
        db.query(MeasurementRecord)
        .filter(
            MeasurementRecord.network_id == network.network_id,
            MeasurementRecord.match_status == "matched",
            MeasurementRecord.device_type == NORMAL_FILTER["device_type"],
            MeasurementRecord.terminal_status == NORMAL_FILTER["terminal_status"],
            MeasurementRecord.line_status == NORMAL_FILTER["line_status"],
            MeasurementRecord.warning_status == NORMAL_FILTER["warning_status"],
        )
        .all()
    )

    by_monitor: dict[str, list[MeasurementRecord]] = {}
    for record in records:
        if record.monitor_id:
            by_monitor.setdefault(record.monitor_id, []).append(record)

    baseline_rows = 0
    monitors_with_baseline = 0

    for monitor_id, monitor_records in by_monitor.items():
        wrote_any = False
        for signal in SIGNAL_FIELDS:
            values = [getattr(r, signal) for r in monitor_records if getattr(r, signal) is not None]
            if not values:
                continue
            timestamps = [r.timestamp for r in monitor_records if getattr(r, signal) is not None and r.timestamp]

            if signal.startswith("phase_"):
                mean_value, std_value = _circular_mean_std_deg(values)
            else:
                mean_value = statistics.mean(values)
                std_value = statistics.pstdev(values) if len(values) > 1 else 0.0

            db.add(
                BaselineStat(
                    monitor_id=monitor_id,
                    signal=signal,
                    count=len(values),
                    mean=mean_value,
                    std=std_value,
                    # NOTE: median is left as the plain linear median even for
                    # phase_* signals. A rigorous circular median exists but
                    # has no single standard closed form (unlike circular
                    # mean/std) -- out of scope for this MVP fix, which only
                    # targets the mean/std computation the spec calls out.
                    median=statistics.median(values),
                    start_time=min(timestamps) if timestamps else None,
                    end_time=max(timestamps) if timestamps else None,
                )
            )
            baseline_rows += 1
            wrote_any = True
        if wrote_any:
            monitors_with_baseline += 1

    db.commit()
    return BaselineBuildResult(
        network_id=network.network_id, monitors_with_baseline=monitors_with_baseline, baseline_rows=baseline_rows
    )


def get_baseline(db: Session, network: Network) -> list[BaselineStatOut]:
    rows = (
        db.query(BaselineStat, Monitor.canonical_name)
        .join(Monitor, Monitor.monitor_id == BaselineStat.monitor_id)
        .filter(Monitor.network_id == network.network_id)
        .order_by(BaselineStat.monitor_id, BaselineStat.signal)
        .all()
    )
    return [
        BaselineStatOut(
            monitor_id=stat.monitor_id,
            canonical_name=canonical_name,
            signal=stat.signal,
            count=stat.count,
            mean=stat.mean,
            std=stat.std,
            median=stat.median,
            start_time=stat.start_time,
            end_time=stat.end_time,
        )
        for stat, canonical_name in rows
    ]


def get_network_readiness(db: Session, network: Network) -> NetworkReadiness:
    nodes = db.query(Node).filter(Node.network_id == network.network_id).all()
    edges = db.query(Edge).filter(Edge.network_id == network.network_id).all()
    closed_edges = [e for e in edges if e.status == "closed"]

    graph = nx.Graph()
    graph.add_nodes_from(n.node_id for n in nodes)
    for e in closed_edges:
        graph.add_edge(e.node_a_id, e.node_b_id)
    single_component = graph.number_of_nodes() > 0 and nx.number_connected_components(graph) == 1

    line_models = {lm.line_model_id: lm for lm in db.query(LineModel).all()}
    edges_configured = all(
        e.line_model_id in line_models and e.length_km is not None and e.length_km > 0 for e in closed_edges
    )
    line_models_valid = all(
        lm.r_ohm_per_km is not None and lm.x_ohm_per_km is not None and lm.c_nf_per_km is not None
        for lm in line_models.values()
    )

    monitors = db.query(Monitor).filter(Monitor.network_id == network.network_id).all()

    unmatched_count = (
        db.query(MeasurementRecord)
        .filter(MeasurementRecord.network_id == network.network_id, MeasurementRecord.match_status == "unmatched")
        .count()
    )

    baseline_count = (
        db.query(BaselineStat)
        .join(Monitor, Monitor.monitor_id == BaselineStat.monitor_id)
        .filter(Monitor.network_id == network.network_id)
        .count()
    )

    items = [
        ReadinessItem(key="topology", label="拓扑映射为单一连通分量", passed=single_component),
        ReadinessItem(key="source", label="唯一 Source 已设置", passed=network.source_node_id is not None),
        ReadinessItem(key="edge_config", label="所有 closed Edge 已配置线路型号与长度", passed=edges_configured),
        ReadinessItem(key="line_models", label="引用的线路型号 R/X/C 有效", passed=line_models_valid),
        ReadinessItem(key="monitor_exists", label="至少配置 1 个 Monitor", passed=len(monitors) > 0),
        ReadinessItem(
            key="measurement_mapping",
            label="历史数据 Monitor 映射已完成",
            passed=unmatched_count == 0,
            detail=None if unmatched_count == 0 else f"还有 {unmatched_count} 条未匹配记录待确认",
        ),
        ReadinessItem(key="baseline", label="已生成至少一组有效 Baseline", passed=baseline_count > 0),
    ]

    ready = all(item.passed for item in items)

    if ready:
        network.status = "READY"
    elif network.status == "READY":
        network.status = "CONFIGURING"
    db.commit()

    return NetworkReadiness(network_id=network.network_id, ready=ready, items=items)
