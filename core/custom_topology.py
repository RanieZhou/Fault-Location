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
    """期望列：node_id[,label,is_monitor_point]。label缺省时用node_id。"""
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        nid = row.get("node_id") or row.get("id") or row.get("节点id") or row.get("杆号")
        if not nid:
            continue
        label = row.get("label") or row.get("名称") or row.get("标签") or nid
        # 支持在节点表里直接指定监测点（1/true/yes/是）
        is_mon_raw = row.get("is_monitor_point") or row.get("is_monitored") or row.get("是否监测点") or row.get("监测点") or "0"
        is_mon = str(is_mon_raw).lower() in ("1", "true", "yes", "t", "y", "是")
        out.append({"node_id": nid, "label": label, "is_monitor_point": is_mon})
    return out


def derive_nodes_from_edges(edges: list[dict]) -> list[dict]:
    """
    节点表是可选的——很多真实拓扑数据本来就只有一张"起点/终点[/长度]"的线路表
    （节点是隐含在这张表里的，不需要单独再列一遍），这种情况下节点表和边表
    实际上可以合二为一，直接从边表出现过的所有id反推出节点列表，label默认用id本身。
    is_monitor_point 同理从边表里的 from_is_monitor/to_is_monitor 标记反推——
    同一个node_id可能在多条边里出现（比如既是某条边的to_id又是另一条边的
    from_id），只要任意一条边标记它是监测点，就认为它是（OR语义，避免某一条
    边漏标把之前正确的标记覆盖掉）。
    """
    seen = []
    seen_set = set()
    is_monitor: dict[str, bool] = {}
    for e in edges:
        for nid, mon_key in ((e["from_id"], "from_is_monitor"), (e["to_id"], "to_is_monitor")):
            if nid not in seen_set:
                seen_set.add(nid)
                seen.append(nid)
            if e.get(mon_key):
                is_monitor[nid] = True
    return [{"node_id": nid, "label": nid, "is_monitor_point": is_monitor.get(nid, False)} for nid in seen]


def parse_edges_csv(text: str) -> list[dict]:
    """
    期望列：from_id,to_id[,length_km 或 length_m 或 length_ft][,resistance_ohm][,reactance_ohm]
    [,from_is_monitor][,to_is_monitor]。
    长度/阻抗列可选，传了哪个就用哪个（单位统一换算成km存进去）。
    from_is_monitor/to_is_monitor 同样可选（1/true/yes/是）——不传单独的节点表时，
    这是唯一能在边表里直接标出"这个端点装了监测设备"的地方，配合
    derive_nodes_from_edges 使用，省掉上传后再手动逐个勾选监测点这一步。
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
        res_ohm = None
        for key in ("resistance_ohm", "resistance", "r", "电阻"):
            if row.get(key):
                try:
                    res_ohm = float(row[key])
                except ValueError:
                    pass
                break
        react_ohm = None
        for key in ("reactance_ohm", "reactance", "x", "电抗"):
            if row.get(key):
                try:
                    react_ohm = float(row[key])
                except ValueError:
                    pass
                break

        def _is_true(v: str) -> bool:
            return v.lower() in ("1", "true", "yes", "t", "y", "是")

        from_mon = _is_true(row.get("from_is_monitor") or row.get("起点监测点") or row.get("起点是否监测点") or "")
        to_mon = _is_true(row.get("to_is_monitor") or row.get("终点监测点") or row.get("终点是否监测点") or "")

        edge_item = {"from_id": f, "to_id": t, "from_is_monitor": from_mon, "to_is_monitor": to_mon}
        if length_km is not None:
            edge_item["length_km"] = length_km
        if res_ohm is not None:
            edge_item["resistance_ohm"] = res_ohm
        if react_ohm is not None:
            edge_item["reactance_ohm"] = react_ohm
        out.append(edge_item)
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

