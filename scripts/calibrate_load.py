# -*- coding: utf-8 -*-
"""
用正常数据.xlsx里每个监测点的真实三相电压/电流均值,反推每个区段末端的"本地负荷"。

关键点:监测点测的是"流经该点的电流"(该点往下游所有负荷的合计),不是"该点自己
挂的负荷"。所以要按拓扑树从叶子往根方向做减法(KCL):
    本地负荷电流(X) = 该点均值电流(X) - sum(子节点均值电流(children of X))
减出来的才是"挂在X和它的下游子节点之间(但没被更下游监测点计入)"的那部分本地负荷。
减出负数(不同点位测量时刻不同步、有噪声导致)的,截断到一个很小的正数下限并标记。
"""
import sys, os, csv
sys.path.insert(0, os.path.dirname(__file__))
import openpyxl
from collections import defaultdict
from common import parse_monitor_name, path_sort_key, LINE_CODE
from build_topology import build_tree, SOURCE, IN_SCOPE_LINES, DATA_DIR, OUT_DIR

PHASES = ['A', 'B', 'C']
FLOOR_I = 0.1  # 安培,本地负荷电流下限


def is_valid(v):
    if v is None:
        return False
    if isinstance(v, str):
        s = v.strip()
        if s in ('---', '') :
            return False
        try:
            v = float(s)
        except ValueError:
            return False
    try:
        v = float(v)
    except (TypeError, ValueError):
        return False
    return v > -100  # 过滤 -9.999 / -9999 这类哨兵值


def to_float(v):
    return float(str(v).strip())


def main():
    wb = openpyxl.load_workbook(os.path.join(DATA_DIR, '正常数据.xlsx'), read_only=True, data_only=True)
    ws = wb['Sheet1']
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    col = {name: i for i, name in enumerate(header)}

    # 累加器: (line, path) -> phase -> [sum_V, cnt_V, sum_I, cnt_I]
    acc = defaultdict(lambda: {p: [0.0, 0, 0.0, 0] for p in PHASES})

    for row in ws.iter_rows(min_row=2, values_only=True):
        info = parse_monitor_name(row[col['监测点名称1']])
        if info is None or info['line'] not in IN_SCOPE_LINES:
            continue
        key = (info['line'], info['path'])
        for p in PHASES:
            v = row[col[f'{p}相电压(kV)']]
            i = row[col[f'{p}相电流(A)']]
            a = acc[key][p]
            if is_valid(v):
                a[0] += to_float(v); a[1] += 1
            if is_valid(i):
                a[2] += to_float(i); a[3] += 1
    wb.close()

    avg = {}  # key -> phase -> (avg_V, avg_I, n_V, n_I)
    for key, phases in acc.items():
        avg[key] = {}
        for p in PHASES:
            sv, cv, si, ci = phases[p]
            avg[key][p] = (sv / cv if cv else None, si / ci if ci else None, cv, ci)

    out_rows = []
    for line in IN_SCOPE_LINES:
        paths = {k[1] for k in avg if k[0] == line}
        parent = build_tree(paths)
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
        clean_id = {node: f'{code}-{i:04d}' for i, node in enumerate(order, 1)}

        # 自底向上(reverse of DFS前序,子节点必然排在父节点后面,倒序即可保证子先算)
        local_I = {node: {p: None for p in PHASES} for node in order}
        flags = {node: False for node in order}
        for node in reversed(order):
            for p in PHASES:
                self_I = avg[(line, node)][p][1]
                if self_I is None:
                    continue
                child_sum = 0.0
                for ch in children.get(node, []):
                    ci = local_I.get(ch, {}).get(p)
                    # 子节点的本地负荷不影响这里,这里要用子节点的"通过电流"(自身均值),
                    # 而不是子节点减完的本地负荷 —— 用avg而不是local_I
                    self_child_through = avg[(line, ch)][p][1]
                    if self_child_through is not None:
                        child_sum += self_child_through
                val = self_I - child_sum
                if val < 0:
                    flags[node] = True
                    val = FLOOR_I
                local_I[node][p] = round(max(val, FLOOR_I), 3)

        for node in order:
            row = {'line': line, 'clean_id': clean_id[node], 'orig_pole': '.'.join(node)}
            total_S = 0.0
            for p in PHASES:
                v, i, nv, ni = avg[(line, node)][p]
                row[f'avg_V{p}_kV'] = round(v, 3) if v is not None else ''
                row[f'through_I{p}_A'] = round(i, 2) if i is not None else ''
                row[f'local_I{p}_A'] = local_I[node][p] if local_I[node][p] is not None else ''
                if v is not None and local_I[node][p] is not None:
                    s = round(v * local_I[node][p], 3)
                    row[f'local_S{p}_kVA'] = s
                    total_S += s
                else:
                    row[f'local_S{p}_kVA'] = ''
            row['local_S_total_kVA'] = round(total_S, 2)
            row['negative_flag'] = flags[node]
            out_rows.append(row)

    fields = ['line', 'clean_id', 'orig_pole']
    for p in PHASES:
        fields += [f'avg_V{p}_kV', f'through_I{p}_A', f'local_I{p}_A', f'local_S{p}_kVA']
    fields += ['local_S_total_kVA', 'negative_flag']

    out_path = os.path.join(OUT_DIR, 'node_loads.csv')
    with open(out_path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out_rows)

    n_flag = sum(1 for r in out_rows if r['negative_flag'])
    total_kva = sum(r['local_S_total_kVA'] for r in out_rows if r['local_S_total_kVA'])
    print(f'已导出: {out_path} ({len(out_rows)}行)')
    print(f'减出负值(测量不同步/噪声导致,已截断到{FLOOR_I}A)的点位: {n_flag}/{len(out_rows)}')
    print(f'两条线路本地负荷合计约 {total_kva:.0f} kVA (含被截断的下限值,仅供仿真参考,不是精确负荷普查)')


if __name__ == '__main__':
    main()
