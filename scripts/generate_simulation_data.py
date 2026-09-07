# -*- coding: utf-8 -*-
"""
scripts/generate_simulation_data.py
模拟生成典型 10kV 配电网拓扑（节点表、边表）与多场景监测数据（Excel）。
"""
import os
import csv
import pandas as pd

# 目录准备
OUT_DIR = "data/simulation"
os.makedirs(OUT_DIR, exist_ok=True)

# ════════════════════════════════════════════════
# 1. 模拟拓扑定义：10kV春华线
# ════════════════════════════════════════════════
# 13个节点，7个监测点
NODES = [
    # 主干线
    {"node_id": "N00", "label": "10kV春华线#00变电站出线", "is_monitor_point": 1},
    {"node_id": "N01", "label": "10kV春华线#01水泥杆", "is_monitor_point": 0},
    {"node_id": "N02", "label": "10kV春华线#02分段开关", "is_monitor_point": 1},
    {"node_id": "N03", "label": "10kV春华线#03铁塔", "is_monitor_point": 0},
    {"node_id": "N04", "label": "10kV春华线#04分段开关", "is_monitor_point": 1},
    {"node_id": "N05", "label": "10kV春华线#05水泥杆", "is_monitor_point": 0},
    {"node_id": "N06", "label": "10kV春华线#06末端环网柜", "is_monitor_point": 1},
    # 支线1（工业支线，T接于N02）
    {"node_id": "B1_01", "label": "10kV春华线工业支#01杆", "is_monitor_point": 0},
    {"node_id": "B1_02", "label": "10kV春华线工业支#02开关", "is_monitor_point": 1},
    {"node_id": "B1_03", "label": "10kV春华线工业支#03箱变", "is_monitor_point": 0},
    # 支线2（居民支线，T接于N04）
    {"node_id": "B2_01", "label": "10kV春华线居民支#01杆", "is_monitor_point": 0},
    {"node_id": "B2_02", "label": "10kV春华线居民支#02箱变", "is_monitor_point": 1},
    # 支线3（农业支线，T接于N04）
    {"node_id": "B3_01", "label": "10kV春华线农业支#01开关", "is_monitor_point": 1},
    {"node_id": "B3_02", "label": "10kV春华线农业支#02抽水变", "is_monitor_point": 0},
]

# 12条边（含线路长度与阻抗参数）
EDGES = [
    # 主干线
    {"from_id": "N00", "to_id": "N01", "length_km": 1.2, "resistance_ohm": 0.324, "reactance_ohm": 0.456},
    {"from_id": "N01", "to_id": "N02", "length_km": 0.8, "resistance_ohm": 0.216, "reactance_ohm": 0.304},
    {"from_id": "N02", "to_id": "N03", "length_km": 1.5, "resistance_ohm": 0.405, "reactance_ohm": 0.570},
    {"from_id": "N03", "to_id": "N04", "length_km": 1.0, "resistance_ohm": 0.270, "reactance_ohm": 0.380},
    {"from_id": "N04", "to_id": "N05", "length_km": 1.3, "resistance_ohm": 0.351, "reactance_ohm": 0.494},
    {"from_id": "N05", "to_id": "N06", "length_km": 0.7, "resistance_ohm": 0.189, "reactance_ohm": 0.266},
    # 工业支线（接N02）
    {"from_id": "N02", "to_id": "B1_01", "length_km": 0.6, "resistance_ohm": 0.198, "reactance_ohm": 0.246},
    {"from_id": "B1_01", "to_id": "B1_02", "length_km": 0.9, "resistance_ohm": 0.297, "reactance_ohm": 0.369},
    {"from_id": "B1_02", "to_id": "B1_03", "length_km": 0.5, "resistance_ohm": 0.165, "reactance_ohm": 0.205},
    # 居民支线（接N04）
    {"from_id": "N04", "to_id": "B2_01", "length_km": 0.8, "resistance_ohm": 0.264, "reactance_ohm": 0.328},
    {"from_id": "B2_01", "to_id": "B2_02", "length_km": 0.7, "resistance_ohm": 0.231, "reactance_ohm": 0.287},
    # 农业支线（接N04）
    {"from_id": "N04", "to_id": "B3_01", "length_km": 1.1, "resistance_ohm": 0.363, "reactance_ohm": 0.451},
    {"from_id": "B3_01", "to_id": "B3_02", "length_km": 1.4, "resistance_ohm": 0.462, "reactance_ohm": 0.574},
]

def export_topology():
    nodes_csv = os.path.join(OUT_DIR, "simulated_nodes.csv")
    edges_csv = os.path.join(OUT_DIR, "simulated_edges.csv")

    with open(nodes_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["node_id", "label", "is_monitor_point"])
        writer.writeheader()
        writer.writerows(NODES)

    with open(edges_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["from_id", "to_id", "length_km", "resistance_ohm", "reactance_ohm"])
        writer.writeheader()
        writer.writerows(EDGES)

    print(f"[+] 拓扑数据生成完成:\n  - 节点表: {nodes_csv}\n  - 边表: {edges_csv}")


# ════════════════════════════════════════════════
# 2. 模拟监测数据：覆盖5类典型工况
# ════════════════════════════════════════════════
# 对应所有装有监测终端的7个监测点
MONITOR_POINTS = [
    ("N00", "10kV春华线#00变电站出线", "出线保护FTU"),
    ("N02", "10kV春华线#02分段开关", "分段负荷开关FTU"),
    ("N04", "10kV春华线#04分段开关", "分段负荷开关FTU"),
    ("N06", "10kV春华线#06末端环网柜", "环网柜DTU"),
    ("B1_02", "10kV春华线工业支#02开关", "分支分段开关FTU"),
    ("B2_02", "10kV春华线居民支#02箱变", "箱变TTU"),
    ("B3_01", "10kV春华线农业支#01开关", "分支分段开关FTU"),
]

def make_record(
    idx, node_id, node_name, dev_type,
    term_status, line_status, warn_status,
    ua, ub, uc,
    ia, ib, ic,
    pa, pb, pc,
    time_str
):
    return {
        "序号": idx,
        "监测点名称1": node_name,
        "设备类型": dev_type,
        "终端状态": term_status,
        "线路状态": line_status,
        "预警状态": warn_status,
        "A相电压(kV)": ua,
        "A相电压原始值(V)": ua * 1000.0 if ua > 0 else -9999.0,
        "A相电压相位": pa,
        "A相电流(A)": ia,
        "A相电流相位": pa,
        "B相电压(kV)": ub,
        "B相电压原始值(V)": ub * 1000.0 if ub > 0 else -9999.0,
        "B相电压相位": pb,
        "B相电流(A)": ib,
        "B相电流相位": pb,
        "C相电压(kV)": uc,
        "C相电压原始值(V)": uc * 1000.0 if uc > 0 else -9999.0,
        "C相电压相位": pc,
        "C相电流(A)": ic,
        "C相电流相位": pc,
        "温度(℃)": 23.5,
        "湿度(%)": 65.0,
        "量测时间": time_str,
    }

def generate_monitoring_scenarios():
    records = []
    r_id = 1

    # ─────────────────────────────────────────────
    # 场景1：全网正常运行工况 (2026-09-07 08:00:00)
    # ─────────────────────────────────────────────
    t1 = "2026-09-07 08:00:00"
    for nid, nname, dtype in MONITOR_POINTS:
        # 电压对称 ~10.2kV，电流负荷梯度递减
        cur = 45.0 if "00" in nid else (30.0 if "02" in nid else 15.0)
        records.append(make_record(
            r_id, nid, nname, dtype,
            "正常", "正常", "正常",
            10.22, 10.19, 10.25,
            cur, cur * 0.98, cur * 1.02,
            0.0, -120.0, 120.0,
            t1
        ))
        r_id += 1

    # ─────────────────────────────────────────────
    # 场景2：主干线中段短路（N02与N04之间，B相接地短路） (2026-09-07 09:15:20)
    # 故障位于 N02 -> N04，N00和N02流经短路电流，B相电压近零
    # ─────────────────────────────────────────────
    t2 = "2026-09-07 09:15:20"
    for nid, nname, dtype in MONITOR_POINTS:
        if nid in ("N00", "N02"):
            # 上游监测点：感受到短路电流，B相低电压，短路报警
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "短路:B相", "低电压:B相",
                10.15, 0.003, 10.18,
                25.0, 680.5 if nid == "N00" else 645.2, 26.1,
                0.0, -85.5, 120.0,
                t2
            ))
        elif nid == "B1_02":
            # N02处引出的工业支线：未流经短路电流，电流正常
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "正常", "正常",
                10.12, 5.82, 10.16,
                18.2, 17.9, 18.5,
                0.0, -118.0, 120.0,
                t2
            ))
        else:
            # 下游监测点 (N04, N06, B2_02, B3_01)：位于故障点下游，无短路电流
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "正常", "正常",
                10.05, 10.02, 10.08,
                0.1, 0.1, 0.1,
                0.0, -120.0, 120.0,
                t2
            ))
        r_id += 1

    # ─────────────────────────────────────────────
    # 场景3：T接工业支线故障（B1_01 -> B1_02之间发生A-B相间短路） (2026-09-07 10:30:15)
    # 故障位于工业支线，N00、N02流经短路电流，B1_02检测到失压和故障波及
    # ─────────────────────────────────────────────
    t3 = "2026-09-07 10:30:15"
    for nid, nname, dtype in MONITOR_POINTS:
        if nid in ("N00", "N02"):
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "短路:A相 B相", "低电压:A相 B相",
                4.85, 4.91, 10.20,
                820.4, 815.7, 30.2,
                -30.0, -90.0, 120.0,
                t3
            ))
        elif nid == "B1_02":
            # 支线监测点报短路
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "短路:A相 B相", "低电压:A相 B相",
                -9.999, -9.999, 9.85,
                "---", "---", 0.1,
                "---", "---", 120.0,
                t3
            ))
        else:
            # 主干下游正常
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "正常", "正常",
                6.50, 6.45, 10.15,
                15.2, 14.8, 15.5,
                0.0, -120.0, 120.0,
                t3
            ))
        r_id += 1

    # ─────────────────────────────────────────────
    # 场景4：多分支农业支线明确故障（B3_01后发生C相接地短路） (2026-09-07 11:45:00)
    # N00, N02, N04, B3_01均报短路
    # ─────────────────────────────────────────────
    t4 = "2026-09-07 11:45:00"
    for nid, nname, dtype in MONITOR_POINTS:
        if nid in ("N00", "N02", "N04", "B3_01"):
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "短路:C相", "低电压:C相",
                10.18, 10.12, 0.002,
                22.0, 21.5, 520.0,
                0.0, -120.0, 95.0,
                t4
            ))
        else:
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "正常", "正常",
                10.15, 10.10, 5.80,
                12.0, 11.5, 12.2,
                0.0, -120.0, 120.0,
                t4
            ))
        r_id += 1

    # ─────────────────────────────────────────────
    # 场景5：经典多分支盲区歧义（B3支线短路但B3_01未上报短路） (2026-09-07 14:00:00)
    # 报警前沿为 N04，N04下游有3个分支：N06(主干), B2_02(居民), B3_01(农业)
    # 考验算法结合电气量压降与负荷电流突变进行分支鉴别！
    # ─────────────────────────────────────────────
    t5 = "2026-09-07 14:00:00"
    for nid, nname, dtype in MONITOR_POINTS:
        if nid in ("N00", "N02", "N04"):
            # N04报短路
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "短路:A相", "低电压:A相",
                0.005, 10.15, 10.20,
                580.0, 25.0, 24.5,
                45.0, -120.0, 120.0,
                t5
            ))
        elif nid == "B3_01":
            # B3_01处于故障支线中段，虽然终端状态故障/未触发报警报文，但电压严重跌落且相位突变
            records.append(make_record(
                r_id, nid, nname, dtype,
                "异常", "正常", "低电压:A相",
                0.001, 10.05, 10.10,
                0.0, 5.0, 4.8,
                98.0, -120.0, 120.0,
                t5
            ))
        elif nid in ("N06", "B2_02"):
            # 另外两个分支正常，三相电压未跌到零，电流正常
            records.append(make_record(
                r_id, nid, nname, dtype,
                "正常", "正常", "正常",
                6.20, 10.10, 10.15,
                12.0, 11.8, 12.5,
                0.0, -120.0, 120.0,
                t5
            ))
        r_id += 1

    df = pd.DataFrame(records)
    excel_path = os.path.join(OUT_DIR, "simulated_monitoring_data.xlsx")
    df.to_excel(excel_path, index=False)
    print(f"[+] 模拟监测数据生成完成: {excel_path} (共 {len(df)} 条记录, 5个事件场景)")

if __name__ == "__main__":
    export_topology()
    generate_monitoring_scenarios()
