# -*- coding: utf-8 -*-
"""共享的名称解析工具:把监测点原始名称拆成 (线路, 编号路径, 侧别)。"""
import re

LINE_ALIASES = {
    '松坪线': '松坪线', '松平线': '松坪线',  # 已知typo
    '火龙线': '火龙线',
    '北冲线': '北冲线',
    '邵九线': '邵九线',
    '极乐村线': '极乐村线',
}

LINE_CODE = {
    '松坪线': 'SP',
    '火龙线': 'HL',
    '北冲线': 'BC',
    '邵九线': 'SJ',
    '极乐村线': 'JL',
}

# 匹配: 10kV/10 kV/10KkV + 线名 + (#)编号(可含.和+) + (号)? + 侧别/杆/支 等后缀
NAME_PAT = re.compile(
    r'^\s*10\s*[kK][kK]?[vV]\s*'
    r'(?P<line>[一-鿿]+线)\s*'
    r'#?\s*'
    r'(?P<pole>[0-9]+(?:\.[0-9]+)*(?:\+[0-9]+)?)'
    r'\s*(?:号)?\s*'
    r'(?P<suffix>杆塔|杆支线|支线|大号侧|小号侧|大|小|支|杆)?'
)


def parse_monitor_name(raw: str):
    """返回 dict(line, pole_path:tuple[str], side, raw) 或 None(无法解析,如光伏点)。"""
    if raw is None:
        return None
    m = NAME_PAT.search(raw.strip())
    if not m:
        return None
    line = LINE_ALIASES.get(m.group('line'))
    if line is None:
        return None
    pole = m.group('pole')
    suffix = (m.group('suffix') or '').strip()
    if suffix in ('大', '大号侧'):
        side = '大'
    elif suffix in ('小', '小号侧'):
        side = '小'
    else:
        side = None  # 支/杆/杆塔/杆支线/无后缀 -> 不带方向,视为节点本身
    # pole_path: 用 '.' 切分主链, 但 '+1' 这种补杆保留在最后一段里
    path = tuple(pole.split('.'))
    return {
        'raw': raw,
        'line': line,
        'pole': pole,
        'path': path,
        'side': side,
        'suffix': suffix,
    }


def path_sort_key(path):
    """把路径各段转成 (数值, 是否带+补杆, 原字符串) 便于排序。"""
    key = []
    for seg in path:
        if '+' in seg:
            base, extra = seg.split('+', 1)
            key.append((float(base), 1, int(extra)))
        else:
            key.append((float(seg), 0, 0))
    return tuple(key)


def is_ancestor(parent_path, child_path):
    """parent_path 是否是 child_path 的前缀(严格祖先,不含自身)。"""
    if len(parent_path) >= len(child_path):
        return False
    return child_path[:len(parent_path)] == parent_path
