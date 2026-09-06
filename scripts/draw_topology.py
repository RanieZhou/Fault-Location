# -*- coding: utf-8 -*-
"""仿IEEE标准馈线示意图风格,把 nodes.csv/edges.csv 的拓扑画成单线图。"""
import csv
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

OUT_DIR = r'D:\Desktop\故障定位\output'

# 找一个支持中文的字体,避免中文标签变方块
CN_FONT = None
for name in ['Microsoft YaHei', 'SimHei', 'SimSun', 'Noto Sans CJK SC']:
    matches = [f for f in fm.fontManager.ttflist if f.name == name]
    if matches:
        CN_FONT = name
        break


def load_tree(linecode):
    nodes = {}
    children = defaultdict(list)
    with open(f'{OUT_DIR}\\nodes.csv', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row['clean_id'].startswith(linecode):
                nodes[row['clean_id']] = row
                children[row['parent_clean_id']].append(row['clean_id'])
    for k in children:
        children[k].sort(key=lambda nid: nodes[nid]['clean_id'])
    return nodes, children


def subtree_size(nid, children, cache={}):
    if nid in cache:
        return cache[nid]
    s = 1 + sum(subtree_size(c, children, cache) for c in children.get(nid, []))
    cache[nid] = s
    return s


X_STEP = 1.6
Y_STEP = 1.3


def compute_layout(nodes, children, root='SOURCE'):
    """每个叶子分配一个全局唯一的行号(先序遍历,主干子节点排最后/最先都行,
    这里主干排最后使它贴着上一层已分配到的行走,不会和别的支路撞行),
    内部节点的行号取它"主干子节点"的行号,这样主干天然走直线,
    支路各自占独立行,不会出现不同支路共用同一格子的问题。"""
    pos = {}
    edges_draw = []
    cache = {}
    next_row = [0]
    row = {}

    def assign_row2(nid):
        kids = list(children.get(nid, []))
        if not kids:
            row[nid] = next_row[0]
            next_row[0] += 1
            return row[nid]
        kids.sort(key=lambda c: -subtree_size(c, children, cache))
        main = kids[0]
        others = kids[1:]
        for c in others:
            assign_row2(c)
        row[nid] = assign_row2(main)
        return row[nid]

    assign_row2(root)

    def layout(nid, x):
        pos[nid] = (x, row[nid])
        kids = list(children.get(nid, []))
        if not kids:
            return
        kids.sort(key=lambda c: -subtree_size(c, children, cache))
        main = kids[0]
        others = kids[1:]
        for c in others:
            edges_draw.append(('branch', x, row[nid], row[c]))
            layout(c, x + X_STEP)
        edges_draw.append(('main', x, row[nid], x + X_STEP))
        layout(main, x + X_STEP)

    layout(root, 0)
    pos = {nid: (x, y * Y_STEP) for nid, (x, y) in pos.items()}
    edges_draw = [(k, x, y1 * Y_STEP, (y2 * Y_STEP if k == 'branch' else y2)) for k, x, y1, y2 in edges_draw]
    return pos, edges_draw


def draw(linecode, title, root_label):
    nodes, children = load_tree(linecode)
    pos, edges_draw = compute_layout(nodes, children)

    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    width = max(10, (max(xs) - min(xs)) * 0.9 + 2)
    height = max(6, (max(ys) - min(ys)) * 0.9 + 3)

    fig, ax = plt.subplots(figsize=(width, height))

    for kind, x, y, x2_or_y2 in edges_draw:
        if kind == 'main':
            ax.plot([x, x2_or_y2], [y, y], color='black', linewidth=1.2, zorder=1)
        else:
            by = x2_or_y2
            ax.plot([x, x], [y, by], color='black', linewidth=1.2, zorder=1)
            ax.plot([x, x + X_STEP], [by, by], color='black', linewidth=1.2, zorder=1)

    # 电源母线(左端一根竖线,仿IEEE图的"800"母线画法)
    all_x = [p[0] for p in pos.values()]
    all_y = [p[1] for p in pos.values()]
    src_y_min, src_y_max = min(all_y) - 0.5, max(all_y) + 0.5
    ax.plot([-0.3, -0.3], [src_y_min, src_y_max], color='black', linewidth=4, zorder=2)
    kw_cn = {'fontname': CN_FONT} if CN_FONT else {}
    ax.text(-0.3, src_y_min - 0.6, root_label, ha='center', va='top', fontsize=10, **kw_cn)

    for nid, (x, y) in pos.items():
        if nid == 'SOURCE':
            continue
        ax.plot(x, y, 'o', color='black', markersize=4, zorder=3)
        orig = nodes[nid]['orig_pole']
        ax.text(x, y + 0.35, orig, ha='center', va='bottom', fontsize=9, **kw_cn)
        ax.text(x, y - 0.35, nid, ha='center', va='top', fontsize=6.5, color='#555555')

    ax.set_title(title, fontsize=15, fontweight='bold', **kw_cn)
    ax.set_xlim(-1.5, max(xs) + 1)
    ax.set_ylim(min(ys) - 1.8, max(ys) + 1.8)
    ax.axis('off')

    out_path = f'{OUT_DIR}\\topology_{linecode}.png'
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'{linecode}: {len(nodes)} 节点, 已保存 {out_path}')


draw('SP', '10kV松坪线 拓扑示意图', '110kV变电站')
draw('HL', '10kV火龙线 拓扑示意图', '110kV变电站')
