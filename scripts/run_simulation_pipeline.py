# -*- coding: utf-8 -*-
"""
scripts/run_simulation_pipeline.py
端到端跑通仿真流程：
1. 上传拓扑（节点表+边表）构建 10kV春华线
2. 上传模拟监测数据（5个工况场景）
3. 依次执行一键自动复现与区段定位
4. 评估算法输出，展示当前定位效果与潜在瓶颈
"""
import os
import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_pipeline():
    session = requests.Session()

    # 登录获取 session
    login_resp = session.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "admin"})
    if not login_resp.json().get("ok"):
        print(f"[!] 登录失败: {login_resp.text}")
        return
    print("[+] 登录成功，已获取认证Session")

    print("=" * 60)
    print("步骤 1: 上传构建 10kV春华线 仿真拓扑")
    print("=" * 60)

    # 检查是否已存在同名拓扑，若有先清理以保证幂等
    r = session.get(f"{BASE_URL}/api/custom-topology/")
    topos = r.json().get("topologies", [])
    for t in topos:
        if t["name"] == "10kV春华线":
            print(f"[*] 清理旧拓扑: {t['id']}")
            session.delete(f"{BASE_URL}/api/custom-topology/{t['id']}")

    nodes_path = "data/simulation/simulated_nodes.csv"
    edges_path = "data/simulation/simulated_edges.csv"

    with open(nodes_path, "rb") as fn, open(edges_path, "rb") as fe:
        files = {
            "nodes_file": ("simulated_nodes.csv", fn, "text/csv"),
            "edges_file": ("simulated_edges.csv", fe, "text/csv"),
        }
        data = {"name": "10kV春华线"}
        resp = session.post(f"{BASE_URL}/api/custom-topology/upload", data=data, files=files)
        upload_res = resp.json()

    if not upload_res.get("ok"):
        print(f"[!] 拓扑上传失败: {upload_res}")
        return

    topo_id = upload_res["id"]
    print(f"[+] 拓扑上传成功! ID={topo_id}, 节点数={upload_res['node_count']}, 边数={upload_res['edge_count']}")

    # 验证折叠后的监测点树
    resp = session.get(f"{BASE_URL}/api/custom-topology/{topo_id}/preview")
    preview = resp.json()
    print(f"[+] 折叠后监测点树包含 {preview['node_count']} 个监测节点, {preview['edge_count']} 条虚拟边:")
    for edge in preview["edges"]:
        print(f"    - {edge['from_id']} -> {edge['to_id']} (长: {edge['length_km']} km, 阻抗: {edge['resistance_ohm']:.3f}+j{edge['reactance_ohm']:.3f} Ω)")

    print("\n" + "=" * 60)
    print("步骤 2: 上传模拟监测数据 (含正常工况与4类故障场景)")
    print("=" * 60)

    excel_path = "data/simulation/simulated_monitoring_data.xlsx"
    with open(excel_path, "rb") as fe:
        files = {"file": ("simulated_monitoring_data.xlsx", fe, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        data = {"topology_id": topo_id}
        resp = session.post(f"{BASE_URL}/api/fault/monitoring/upload", data=data, files=files)
        mon_res = resp.json()

    print(f"[+] 监测数据解析完成! 生成 {mon_res.get('event_count')} 个事件批次, 共 {mon_res.get('record_count')} 条监测记录")

    # 获取事件列表
    resp = session.get(f"{BASE_URL}/api/fault/monitoring/events?topology_id={topo_id}")
    events = resp.json().get("events", [])

    print("\n" + "=" * 60)
    print("步骤 3: 运行算法自动复现与区段定位，评估当前效果")
    print("=" * 60)

    scenario_names = [
        "场景1: 全网正常运行工况",
        "场景2: 主干中段短路 (N02 -> N04 之间故障)",
        "场景3: T接工业支线故障 (N02 -> B1_02 之间故障)",
        "场景4: 多分支农业支线明确短路 (B3_01 下游故障)",
        "场景5: 多分支盲区歧义测试 (N04 下游3分支辨识)",
    ]

    # /monitoring/events 接口按时间倒序返回，这里按时间戳升序重排后再对应场景名，
    # 不能直接按接口返回顺序假设是场景1→5。
    events_sorted = sorted(events, key=lambda e: e["timestamp"])
    for i, ev in enumerate(events_sorted):
        eid = ev["event_id"]
        s_name = scenario_names[i] if i < len(scenario_names) else f"事件 {i+1}"
        print(f"\n[测试] [{s_name}] (Event ID: {eid})")
        print(f"  - 时间: {ev['timestamp']}")
        print(f"  - 自动识别报警点: {ev['inferred_poles'] or '无'}")
        print(f"  - 故障简述: {ev['fault_summary']}")

        rep_resp = session.post(f"{BASE_URL}/api/fault/monitoring/events/{eid}/reproduce")
        rep = rep_resp.json()

        fl = rep.get("fault_locate")
        if not fl:
            print("  - 定位结果: 无故障或未触发定位（正常工况）")
            continue

        frontiers = fl.get("frontier_points", [])
        sections = fl.get("candidate_sections", [])
        conf = fl.get("confidence", "unknown")
        note = fl.get("note", "")

        print(f"  - 算法报警前沿点 (Frontier): {frontiers}")
        print(f"  - 算法候选区段 (Candidate Sections):")
        for s in sections:
            print(f"      * {s.get('from_pole')}  ->  {s.get('to_pole')} (置信度: {s.get('confidence')})")
        print(f"  - 全局置信度: {conf}")
        print(f"  - 算法研判备注: {note}")

if __name__ == "__main__":
    test_pipeline()
