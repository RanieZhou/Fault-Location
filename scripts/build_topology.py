# -*- coding: utf-8 -*-
"""
仅用监测点原始编号(不依赖单线图矢量解析)重建两条线路的树形拓扑,
并为每个监测点分配一套规范化的清洁编号(如 HL-0001),导出:
  output/nodes_<line>.csv   节点表(清洁编号/原始编号/深度/父节点/观测到的大小侧)
  output/edges_<line>.csv   边表(from_id,to_id,via)
  output/name_mapping.csv   49个原始监测点名称 -> 清洁边/节点编号 的映射
用真实故障事件重新做一次一致性校验(基于真实构建出的树,而不是启发式两两比较)。
"""
import sys, os
from collections import defaultdict
from datetime import datetime
import openpyxl

sys.path.insert(0, os.path.dirname(__file__))
from common import parse_monitor_name, path_sort_key, LINE_CODE

DATA_DIR = r'D:\Desktop\故障定位\data\历史数据'
OUT_DIR = r'D:\Desktop\故障定位\output'
IN_SCOPE_LINES = ['松坪线', '火龙线']

SOURCE = ('__SOURCE__',)


def load_all_names():
    names = set()
    for fname in ['正常数据.xlsx', '异常数据.xlsx']:
        wb = openpyxl.load_workbook(os.path.join(DATA_DIR, fname), read_only=True, data_only=True)
        ws = wb['Sheet1']
        header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        idx = header.index('监测点名称1')
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[idx]:
                names.add(row[idx])
        wb.close()
    return names


def build_tree(paths):
    """paths: set of path tuples (不含SOURCE). 返回 parent[path] = parent_path (SOURCE代表根)。

    递归地"剥离共同前缀分段、按段分组、递归处理更深层",这样即使某条支线的
    根杆本身没装监测点(如只有#74.3而没有单独的#74),更深的节点依然会按数值
    大小挂到正确的干线顺序位置上,而不是被孤立地直接挂到SOURCE下面。
    """
    parent = {}

    def helper(pathset, anchor, depth):
        groups = defaultdict(list)
        for p in pathset:
            groups[p[depth]].append(p)
        for seg_val in sorted(groups.keys(), key=lambda s: path_sort_key((s,))):
            group_paths = groups[seg_val]
            exact = [p for p in group_paths if len(p) == depth + 1]
            deeper = [p for p in group_paths if len(p) > depth + 1]
            if exact:
                node = exact[0]
                parent[node] = anchor
                anchor = node  # 后续兄弟/更深分支都接在这个真实节点之后
            if deeper:
                helper(deeper, anchor, depth + 1)
        return anchor

    helper(set(paths), SOURCE, 0)
    return parent


def to_dt(v):
    if isinstance(v, datetime):
        return v
    return datetime.strptime(str(v).strip(), '%Y-%m-%d %H:%M:%S')


def ancestors_of(node, parent):
    chain = []
    cur = node
    while cur in parent:
        cur = parent[cur]
        if cur == SOURCE:
            break
        chain.append(cur)
    return chain


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    raw_names = load_all_names()

    parsed_by_line = defaultdict(dict)  # line -> path -> {'sides': set(), 'raws': []}
    skipped = []
    for n in raw_names:
        info = parse_monitor_name(n)
        if info is None or info['line'] not in IN_SCOPE_LINES:
            skipped.append(n)
            continue
        rec = parsed_by_line[info['line']].setdefault(info['path'], {'sides': set(), 'raws': []})
        rec['sides'].add(info['side'])
        rec['raws'].append(n)

    print('跳过(不在两条目标线路范围内或无法解析):')
    for s in skipped:
        print('  ', repr(s))
    print()

    all_nodes_out = []
    all_edges_out = []
    mapping_out = []
    clean_id_of = {}  # (line, path) -> clean_id

    for line in IN_SCOPE_LINES:
        paths = set(parsed_by_line[line].keys())
        parent = build_tree(paths)

        # 按 BFS 层序(从SOURCE开始,每层内部按 path_sort_key)分配清洁编号,保证越靠近电源编号越小
        children = defaultdict(list)
        for node, par in parent.items():
            children[par].append(node)
        for k in children:
            children[k].sort(key=path_sort_key)

        code = LINE_CODE[line]
        order = []
        stack = list(reversed(children.get(SOURCE, [])))
        while stack:
            cur = stack.pop()
            order.append(cur)
            stack.extend(reversed(children.get(cur, [])))
        # DFS 前序遍历(child 已按大小排序),越靠近电源编号越小

        for i, node in enumerate(order, 1):
            clean_id_of[(line, node)] = f'{code}-{i:04d}'

        for node in order:
            cid = clean_id_of[(line, node)]
            par = parent[node]
            par_cid = 'SOURCE' if par == SOURCE else clean_id_of[(line, par)]
            depth = len(ancestors_of(node, parent))
            sides = parsed_by_line[line][node]['sides']
            all_nodes_out.append({
                'line': line, 'clean_id': cid, 'orig_pole': '.'.join(node),
                'depth': depth, 'parent_clean_id': par_cid,
                'sides_observed': '/'.join(sorted(s for s in sides if s)) or '-',
            })
            all_edges_out.append({
                'line': line, 'from_id': par_cid, 'to_id': cid,
                'edge_label': f"{'.'.join(par) if par != SOURCE else 'SOURCE'} -> {'.'.join(node)}",
            })
            for raw in parsed_by_line[line][node]['raws']:
                mapping_out.append({'raw_name': raw, 'line': line, 'clean_id': cid, 'orig_pole': '.'.join(node)})

        # 打印缩进树,人工目检
        print(f'=== {line} 拓扑树(共 {len(order)} 个监测点) ===')
        def print_tree(node, prefix=''):
            cid = clean_id_of[(line, node)]
            sides = '/'.join(sorted(s for s in parsed_by_line[line][node]['sides'] if s)) or '-'
            print(f"{prefix}{'.'.join(node)}  [{cid}]  侧别观测:{sides}")
            for ch in children.get(node, []):
                print_tree(ch, prefix + '  ')
        for top in children.get(SOURCE, []):
            print_tree(top)
        print()

    # 导出CSV
    import csv
    with open(os.path.join(OUT_DIR, 'nodes.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['line', 'clean_id', 'orig_pole', 'depth', 'parent_clean_id', 'sides_observed'])
        w.writeheader(); w.writerows(all_nodes_out)
    with open(os.path.join(OUT_DIR, 'edges.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['line', 'from_id', 'to_id', 'edge_label'])
        w.writeheader(); w.writerows(all_edges_out)
    with open(os.path.join(OUT_DIR, 'name_mapping.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['raw_name', 'line', 'clean_id', 'orig_pole'])
        w.writeheader(); w.writerows(mapping_out)

    print(f'已导出: {OUT_DIR}\\nodes.csv ({len(all_nodes_out)}行), edges.csv, name_mapping.csv ({len(mapping_out)}行)\n')

    # ---- 用真实故障事件重新校验(基于真实树的祖先关系) ----
    print('=== 用真实构建的树重新校验历史故障事件 ===')
    wb = openpyxl.load_workbook(os.path.join(DATA_DIR, '异常数据.xlsx'), read_only=True, data_only=True)
    ws = wb['Sheet1']
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    abn_rows = [dict(zip(header, r)) for r in ws.iter_rows(min_row=2, values_only=True)]
    wb.close()

    parsed = []
    for r in abn_rows:
        info = parse_monitor_name(r['监测点名称1'])
        if info is None or info['line'] not in IN_SCOPE_LINES:
            continue
        info['time'] = to_dt(r['量测时间'])
        parsed.append(info)
    parsed.sort(key=lambda x: (x['line'], x['time']))

    events, cur = [], []
    for p in parsed:
        if cur and p['line'] == cur[-1]['line'] and abs((p['time'] - cur[-1]['time']).total_seconds()) <= 15:
            cur.append(p)
        else:
            if cur:
                events.append(cur)
            cur = [p]
    if cur:
        events.append(cur)

    ok, bad = 0, 0
    for i, ev in enumerate(events, 1):
        line = ev[0]['line']
        parent = build_tree(set(parsed_by_line[line].keys()))
        paths = sorted({p['path'] for p in ev}, key=path_sort_key)
        deepest = paths[-1]
        chain = set(ancestors_of(deepest, parent)) | {deepest}
        missing = [p for p in paths if p not in chain]
        status = 'OK ' if not missing else 'BAD'
        if not missing:
            ok += 1
        else:
            bad += 1
        print(f"[{i:02d}] {status} {line} {ev[0]['time']}  报警点:{[('.'.join(p)) for p in paths]}"
              + ('' if not missing else f"  不在'最深点祖先链'内的点:{[('.'.join(p)) for p in missing]}"))

    print(f'\n一致: {ok}/{len(events)}, 不一致: {bad}/{len(events)}')


if __name__ == '__main__':
    main()
