"""
core/custom_topology.py — 自定义拓扑（用户上传节点表+边表）

设计目标：让"矩阵法故障定位"这套已经验证过的算法，不需要改一行就能跑在任意
用户上传的拓扑上。做法是在真实上传的完整物理图（可能含未装监测点的纯结构杆塔）
和算法实际消费的"仅监测点树"之间加一层折叠转换：

  完整图（用户上传，含所有物理节点/边，用于渲染和参数录入）
        │  build_monitor_view()
        ▼
  监测点树（只含 is_monitor_point=True 的节点；两个监测点之间跳过的
           非监测节点的 length/R/X 被累加到这一段虚拟边上）
        │
        ▼
  core.fault_locator 直接消费（和 nodes.csv/edges.csv 加载出来的形状完全一致）

一次性计算、不缓存——自定义拓扑的节点/边/监测点标记会被用户随时修改，
数据量也小（预期几十到几百个节点），没必要为了省这点计算引入缓存失效的复杂度。
"""
from __future__ import annotations
import csv
import io
from collections import defaultdict, deque
from typing import Optional

from .models import NodeModel, EdgeModel, CustomNodeRaw, CustomEdgeRaw


# ════════════════════════════════════════════════
# CSV 解析（容错：Excel在中文Windows上另存CSV经常是GBK编码，不是UTF-8）
# ════════════════════════════════════════════════

def decode_csv_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_nodes_csv(text: str) -> list[dict]:
    """期望列：node_id[,label]。label缺省时用node_id。"""
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        nid = row.get("node_id") or row.get("id") or row.get("节点id") or row.get("杆号")
        if not nid:
            continue
        label = row.get("label") or row.get("名称") or row.get("标签") or nid
        out.append({"node_id": nid, "label": label})
    return out


def derive_nodes_from_edges(edges: list[dict]) -> list[dict]:
    """
    节点表是可选的——很多真实拓扑数据本来就只有一张"起点/终点[/长度]"的线路表
    （节点是隐含在这张表里的，不需要单独再列一遍），这种情况下节点表和边表
    实际上可以合二为一，直接从边表出现过的所有id反推出节点列表，label默认用id本身。
    """
    seen = []
    seen_set = set()
    for e in edges:
        for nid in (e["from_id"], e["to_id"]):
            if nid not in seen_set:
                seen_set.add(nid)
                seen.append(nid)
    return [{"node_id": nid, "label": nid} for nid in seen]


def parse_edges_csv(text: str) -> list[dict]:
    """
    期望列：from_id,to_id[,length_km 或 length_m 或 length_ft]。
    长度列可选——很多真实拓扑图纸导出的"线路表"本身就是 起点/终点/长度 一张表
    （比如IEEE标准测试馈线文档里的"Line Segment Data"），没必要强制用户先传一份
    只有连接关系的边表、再回头单独逐条补长度，这里直接在边表里认这几种常见列名，
    传了哪个就用哪个（单位统一换算成km存进去）。
    """
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        f = row.get("from_id") or row.get("from") or row.get("起点") or row.get("node a") or row.get("node_a")
        t = row.get("to_id") or row.get("to") or row.get("终点") or row.get("node b") or row.get("node_b")
        if not f or not t:
            continue
        length_km = None
        for key, factor in (("length_km", 1.0), ("length_m", 0.001), ("length_ft", 0.0003048), ("length(ft.)", 0.0003048)):
            if row.get(key):
                try:
                    length_km = float(row[key]) * factor
                except ValueError:
                    pass
                break
        if length_km is not None:
            out.append({"from_id": f, "to_id": t, "length_km": length_km})
            continue
        out.append({"from_id": f, "to_id": t})
    return out


# ════════════════════════════════════════════════
# 树结构校验与构建
# ════════════════════════════════════════════════

def validate_and_build_tree(
    nodes: list[dict], edges: list[dict]
) -> tuple[Optional[str], dict[str, Optional[str]], dict[str, int], list[str]]:
    """
    返回 (root_id, parent_map, depth_map, errors)。
    errors非空时前三者不可信，调用方应先检查errors。
    """
    errors: list[str] = []
    node_ids = {n["node_id"] for n in nodes}

    dup_check = [n["node_id"] for n in nodes]
    dups = {x for x in dup_check if dup_check.count(x) > 1}
    if dups:
        errors.append(f"节点表里有重复的node_id: {sorted(dups)}")

    for e in edges:
        if e["from_id"] not in node_ids:
            errors.append(f"边引用了节点表里不存在的node_id: {e['from_id']}")
        if e["to_id"] not in node_ids:
            errors.append(f"边引用了节点表里不存在的node_id: {e['to_id']}")
        if e["from_id"] == e["to_id"]:
            errors.append(f"边不能首尾相连到同一个节点: {e['from_id']}")
    if errors:
        return None, {}, {}, errors

    children: dict[str, list[str]] = defaultdict(list)
    has_incoming: set[str] = set()
    for e in edges:
        children[e["from_id"]].append(e["to_id"])
        has_incoming.add(e["to_id"])

    roots = sorted(node_ids - has_incoming)
    if len(roots) == 0:
        errors.append("找不到根节点——每个节点都至少有一条入边，可能存在环路")
        return None, {}, {}, errors
    if len(roots) > 1:
        errors.append(
            f"发现{len(roots)}个没有入边的节点：{roots}——本版本只支持单一电源根节点的树形结构，"
            f"请检查是否有节点漏连边，或存在多个独立的图"
        )
        return None, {}, {}, errors

    root = roots[0]
    parent_map: dict[str, Optional[str]] = {root: None}
    depth_map: dict[str, int] = {root: 0}
    visited = {root}
    queue = deque([root])
    while queue:
        cur = queue.popleft()
        for ch in children.get(cur, []):
            if ch in visited:
                errors.append(f"节点 {ch} 有多个父节点或存在环路，树形结构要求每个节点只能有一个父节点")
                continue
            visited.add(ch)
            parent_map[ch] = cur
            depth_map[ch] = depth_map[cur] + 1
            queue.append(ch)

    unreached = node_ids - visited
    if unreached:
        errors.append(f"以下节点从根节点出发无法到达（孤立分支）：{sorted(unreached)}")

    return root, parent_map, depth_map, errors


def get_full_view(topo_id: str) -> tuple[list[CustomNodeRaw], list[CustomEdgeRaw], list[str]]:
    """完整物理图（管理页表格/渲染用），附带树校验结果里的depth/parent_id。"""
    from . import db
    raw_nodes = db.get_custom_nodes(topo_id)
    raw_edges = db.get_custom_edges(topo_id)
    root, parent_map, depth_map, errors = validate_and_build_tree(raw_nodes, raw_edges)

    node_out = [
        CustomNodeRaw(
            node_id=n["node_id"], label=n["label"],
            is_monitor_point=bool(n["is_monitor_point"]),
            depth=depth_map.get(n["node_id"], -1),
            parent_id=parent_map.get(n["node_id"]),
        )
        for n in raw_nodes
    ]
    edge_out = [
        CustomEdgeRaw(
            from_id=e["from_id"], to_id=e["to_id"],
            length_km=e["length_km"], resistance_ohm=e["resistance_ohm"],
            reactance_ohm=e["reactance_ohm"],
        )
        for e in raw_edges
    ]
    return node_out, edge_out, errors


# ════════════════════════════════════════════════
# 监测点折叠：完整图 → 故障定位算法直接消费的"监测点树"
# ════════════════════════════════════════════════

def build_monitor_view(topo_id: str) -> tuple[list[NodeModel], list[EdgeModel]]:
    """
    树校验失败或该拓扑不存在时返回 ([], [])——和 electrical_inference 的"找不到就静默
    降级"风格保持一致，不抛异常打断上层的故障定位主流程。
    """
    from . import db
    raw_nodes = db.get_custom_nodes(topo_id)
    if not raw_nodes:
        return [], []
    raw_edges = db.get_custom_edges(topo_id)
    root, parent_map, depth_map, errors = validate_and_build_tree(raw_nodes, raw_edges)
    if errors or root is None:
        return [], []

    monitor_set = {n["node_id"] for n in raw_nodes if n["is_monitor_point"]}
    label_of = {n["node_id"]: n["label"] for n in raw_nodes}
    edge_params = {(e["from_id"], e["to_id"]): e for e in raw_edges}

    children: dict[str, list[str]] = defaultdict(list)
    for nid, p in parent_map.items():
        if p is not None:
            children[p].append(nid)

    monitor_parent: dict[str, Optional[str]] = {}
    monitor_params: dict[str, dict] = {}

    def dfs(node_id: str, nearest_monitor: Optional[str], acc_len: float, acc_r: float, acc_x: float):
        for ch in children.get(node_id, []):
            e = edge_params.get((node_id, ch), {})
            new_len = acc_len + float(e.get("length_km", 0) or 0)
            new_r = acc_r + float(e.get("resistance_ohm", 0) or 0)
            new_x = acc_x + float(e.get("reactance_ohm", 0) or 0)
            if ch in monitor_set:
                monitor_parent[ch] = nearest_monitor
                monitor_params[ch] = {"length_km": new_len, "resistance_ohm": new_r, "reactance_ohm": new_x}
                dfs(ch, ch, 0.0, 0.0, 0.0)
            else:
                dfs(ch, nearest_monitor, new_len, new_r, new_x)

    if root in monitor_set:
        monitor_parent[root] = None
        monitor_params[root] = {"length_km": 0.0, "resistance_ohm": 0.0, "reactance_ohm": 0.0}
        dfs(root, root, 0.0, 0.0, 0.0)
    else:
        dfs(root, None, 0.0, 0.0, 0.0)

    # 折叠后树里的深度（监测点祖先个数），和原始物理图深度是两回事
    depth_out: dict[str, int] = {}
    mchildren: dict[str, list[str]] = defaultdict(list)
    for nid, p in monitor_parent.items():
        if p is not None:
            mchildren[p].append(nid)
    for mroot in [nid for nid, p in monitor_parent.items() if p is None]:
        depth_out[mroot] = 0
        q = deque([mroot])
        while q:
            cur = q.popleft()
            for ch in mchildren.get(cur, []):
                depth_out[ch] = depth_out[cur] + 1
                q.append(ch)

    node_models = [
        NodeModel(
            id=nid, orig_pole=label_of.get(nid, nid), line=topo_id,
            depth=depth_out.get(nid, 0), parent_id=p,
            sides_observed="-", load_kva=0.0, status="normal", is_monitor_point=True,
        )
        for nid, p in monitor_parent.items()
    ]

    edge_models = []
    for nid, p in monitor_parent.items():
        params = monitor_params.get(nid, {})
        from_id = p if p is not None else "SOURCE"
        from_label = label_of.get(p, "SOURCE") if p is not None else "SOURCE"
        edge_models.append(EdgeModel(
            line=topo_id, from_id=from_id, to_id=nid,
            label=f"{from_label} -> {label_of.get(nid, nid)}",
            length_km=params.get("length_km", 0.0),
            resistance_ohm=params.get("resistance_ohm", 0.0),
            reactance_ohm=params.get("reactance_ohm", 0.0),
        ))

    return node_models, edge_models


def seed_sp_hl_topologies_if_needed() -> None:
    """自动播种10kV松坪线和火龙线拓扑（若尚未存在），确保样例历史数据能立即复现定位。"""
    from pathlib import Path
    import pandas as pd
    from . import db

    topos = {t["id"]: t["name"] for t in db.list_custom_topologies()}
    nodes_csv = Path("output/nodes.csv")
    edges_csv = Path("output/edges.csv")
    if not nodes_csv.exists() or not edges_csv.exists():
        return

    try:
        nodes_df = pd.read_csv(nodes_csv)
        edges_df = pd.read_csv(edges_csv)
    except Exception:
        return

    # 1. 松坪线
    if "ct_sp" not in topos and not any("松坪" in name for name in topos.values()):
        sp_nodes_df = nodes_df[nodes_df["clean_id"].str.startswith("SP-")]
        nodes = [{"node_id": "SOURCE", "label": "变电站"}] + [
            {"node_id": r["clean_id"], "label": str(r["orig_pole"])}
            for _, r in sp_nodes_df.iterrows()
        ]
        sp_edges_df = edges_df[(edges_df["from_id"].str.startswith("SP-") | (edges_df["from_id"] == "SOURCE")) & (edges_df["to_id"].str.startswith("SP-"))]
        edges = [{"from_id": r["from_id"], "to_id": r["to_id"], "length_km": 1.0} for _, r in sp_edges_df.iterrows()]
        db.create_custom_topology("ct_sp", "10kV 松坪线", nodes, edges)
        monitor_ids = [r["clean_id"] for _, r in sp_nodes_df.iterrows()]
        db.update_custom_monitor_points("ct_sp", monitor_ids, True)

    # 2. 火龙线
    if "ct_hl" not in topos and not any("火龙" in name for name in topos.values()):
        hl_nodes_df = nodes_df[nodes_df["clean_id"].str.startswith("HL-")]
        nodes = [{"node_id": "SOURCE", "label": "变电站"}] + [
            {"node_id": r["clean_id"], "label": str(r["orig_pole"])}
            for _, r in hl_nodes_df.iterrows()
        ]
        hl_edges_df = edges_df[(edges_df["from_id"].str.startswith("HL-") | (edges_df["from_id"] == "SOURCE")) & (edges_df["to_id"].str.startswith("HL-"))]
        edges = [{"from_id": r["from_id"], "to_id": r["to_id"], "length_km": 1.0} for _, r in hl_edges_df.iterrows()]
        db.create_custom_topology("ct_hl", "10kV 火龙线", nodes, edges)
        monitor_ids = [r["clean_id"] for _, r in hl_nodes_df.iterrows()]
        db.update_custom_monitor_points("ct_hl", monitor_ids, True)

