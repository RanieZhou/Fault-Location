"""
core/db.py — SQLite 持久化：拓扑/监测点/线路参数/历史电气量数据/故障事件历史。

设计：
  - 系统不再有任何硬编码的固定线路，所有拓扑都是用户上传的自定义拓扑（custom_topologies
    及相关表），历史电气量数据（custom_baseline_readings / custom_events /
    custom_event_readings）也按拓扑各自上传、各自隔离。
  - fault_events 表随 /api/fault/locate 的实际调用持续增长（source='live'）。
  - 不做连接池/ORM：数据量小（几十到几百行级别），每次操作开箱即用地开关连接即可。
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH
from .models import HistoryEvent

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fault_events (
    event_id           TEXT PRIMARY KEY,
    line                TEXT NOT NULL,
    time                TEXT NOT NULL,
    fault_types         TEXT NOT NULL DEFAULT '',
    alarmed_points      TEXT NOT NULL DEFAULT '',
    frontier            TEXT NOT NULL DEFAULT '',
    candidate_sections  TEXT NOT NULL DEFAULT '',
    confidence          TEXT NOT NULL DEFAULT 'unknown',
    note                TEXT NOT NULL DEFAULT '',
    source              TEXT NOT NULL DEFAULT 'live',
    created_at          TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fault_events_line ON fault_events(line);
CREATE INDEX IF NOT EXISTS idx_fault_events_time ON fault_events(time);

CREATE TABLE IF NOT EXISTS llm_provider_config (
    provider    TEXT PRIMARY KEY,
    api_key     TEXT NOT NULL DEFAULT '',
    base_url    TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS custom_topologies (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS custom_nodes (
    topology_id       TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    label             TEXT NOT NULL DEFAULT '',
    is_monitor_point  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (topology_id, node_id)
);

CREATE TABLE IF NOT EXISTS custom_edges (
    topology_id     TEXT NOT NULL,
    from_id         TEXT NOT NULL,
    to_id           TEXT NOT NULL,
    length_km       REAL NOT NULL DEFAULT 0,
    resistance_ohm  REAL NOT NULL DEFAULT 0,
    reactance_ohm   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (topology_id, from_id, to_id)
);

-- 基线（正常）读数：用来算每个监测点每相的正常电压/电流均值方差，是电气量推理的基准
CREATE TABLE IF NOT EXISTS custom_baseline_readings (
    topology_id  TEXT NOT NULL,
    node_id      TEXT NOT NULL,
    phase        TEXT NOT NULL,
    voltage_kv   REAL,
    current_a    REAL
);
CREATE INDEX IF NOT EXISTS idx_baseline_topo_node ON custom_baseline_readings(topology_id, node_id);

-- 历史事件快照：一次真实故障发生时刻，各监测点的原始三相读数
CREATE TABLE IF NOT EXISTS custom_events (
    event_id     TEXT PRIMARY KEY,
    topology_id  TEXT NOT NULL,
    timestamp    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_topo ON custom_events(topology_id);

CREATE TABLE IF NOT EXISTS custom_event_readings (
    event_id    TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    phase       TEXT NOT NULL,
    voltage_kv  REAL,
    current_a   REAL
);
CREATE INDEX IF NOT EXISTS idx_event_readings_event ON custom_event_readings(event_id);
"""


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """建表（幂等）+ 从.env迁移已有LLM配置。应用启动时调用一次。"""
    with _conn() as conn:
        conn.executescript(_SCHEMA)
        llm_count = conn.execute("SELECT COUNT(*) FROM llm_provider_config").fetchone()[0]
        if llm_count == 0:
            _migrate_llm_config_from_env(conn)


def _migrate_llm_config_from_env(conn: sqlite3.Connection) -> None:
    """
    一次性迁移：LLM配置此前写在 .env 里（旧实现），这里改成 SQLite 之后，
    把 .env 里已有的配置导进来，避免用户之前保存过的配置在这次架构调整后
    "凭空消失"。只在 llm_provider_config 表为空时触发一次，此后以SQLite为准。
    """
    from .config import settings

    providers = {
        "deepseek": (settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model),
        "qwen": (settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model),
        "openai": (settings.openai_api_key, settings.openai_base_url, settings.openai_model),
        "custom": (settings.custom_api_key, settings.custom_base_url, settings.custom_model),
    }
    migrated = []
    for prov, (api_key, base_url, model) in providers.items():
        if api_key:  # 只迁移真正配置过Key的provider，避免插入一堆空记录
            conn.execute(
                """INSERT OR IGNORE INTO llm_provider_config (provider, api_key, base_url, model)
                   VALUES (?, ?, ?, ?)""",
                (prov, api_key, base_url, model),
            )
            migrated.append(prov)

    active = settings.llm_provider
    if active:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES ('active_llm_provider', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (active,),
        )
    if migrated:
        print(f"[db] 已从 .env 迁移 {len(migrated)} 个LLM provider配置到SQLite: {migrated}")


def insert_event(event: HistoryEvent) -> None:
    """追加一条事件记录（source 由调用方在 event.source 中指定，通常为 'live'）。"""
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO fault_events
               (event_id, line, time, fault_types, alarmed_points, frontier,
                candidate_sections, confidence, note, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id, event.line, event.time, event.fault_types,
                event.alarmed_points, event.frontier, event.candidate_sections,
                event.confidence, event.note, event.source,
            ),
        )


# ════════════════════════════════════════════════
# LLM 提供商配置（取代此前写 .env 的方式——.env 是纯文本KV，用字符串拼接读写，
# 遇到含特殊字符的key容易出问题；SQLite更规范，且和历史事件用同一套持久化风格）
# ════════════════════════════════════════════════

def save_llm_provider_config(provider: str, api_key: str, base_url: str, model: str) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO llm_provider_config (provider, api_key, base_url, model, updated_at)
               VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
               ON CONFLICT(provider) DO UPDATE SET
                 api_key=excluded.api_key, base_url=excluded.base_url,
                 model=excluded.model, updated_at=excluded.updated_at""",
            (provider, api_key, base_url, model),
        )


def get_llm_provider_config(provider: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT provider, api_key, base_url, model FROM llm_provider_config WHERE provider = ?",
            (provider,),
        ).fetchone()
    return dict(row) if row else None


def get_all_llm_provider_configs() -> dict[str, dict]:
    """返回 {provider: {provider, api_key, base_url, model}}，供前端表单回填用（明文，非脱敏——
    这个函数只在受登录保护的 /api/settings/llm/all 内部调用，不对外裸露）。"""
    with _conn() as conn:
        rows = conn.execute("SELECT provider, api_key, base_url, model FROM llm_provider_config").fetchall()
    return {r["provider"]: dict(r) for r in rows}


def set_app_setting(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


def get_app_setting(key: str, default: str = "") -> str:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_all_events(line: str | None = None) -> list[HistoryEvent]:
    """按时间正序返回事件（可选按线路过滤）。"""
    sql = "SELECT * FROM fault_events"
    args: tuple = ()
    if line:
        sql += " WHERE line = ?"
        args = (line,)
    sql += " ORDER BY time ASC"
    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [
        HistoryEvent(
            event_id=r["event_id"], line=r["line"], time=r["time"],
            fault_types=r["fault_types"], alarmed_points=r["alarmed_points"],
            frontier=r["frontier"], candidate_sections=r["candidate_sections"],
            confidence=r["confidence"], note=r["note"], source=r["source"],
        )
        for r in rows
    ]


# ════════════════════════════════════════════════
# 自定义拓扑（用户上传节点/边表——系统里唯一的拓扑来源）
# ════════════════════════════════════════════════

def create_custom_topology(
    topo_id: str, name: str,
    nodes: list[dict],   # [{"node_id":..., "label":...}, ...]
    edges: list[dict],   # [{"from_id":..., "to_id":..., "length_km": 可选}, ...]
) -> None:
    """新建一个自定义拓扑并写入全部节点/边（一次性写入，upload接口用）。
    边表如果自带length_km（比如原始表格本身就是"起点/终点/长度"三列一起给的），
    直接落库，不用上传完拓扑再回头单独补一遍长度。"""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO custom_topologies (id, name) VALUES (?, ?)", (topo_id, name)
        )
        conn.executemany(
            "INSERT INTO custom_nodes (topology_id, node_id, label, is_monitor_point) VALUES (?, ?, ?, 0)",
            [(topo_id, n["node_id"], n.get("label") or n["node_id"]) for n in nodes],
        )
        conn.executemany(
            "INSERT INTO custom_edges (topology_id, from_id, to_id, length_km) VALUES (?, ?, ?, ?)",
            [(topo_id, e["from_id"], e["to_id"], e.get("length_km") or 0.0) for e in edges],
        )


def list_custom_topologies() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.name, t.created_at,
                      (SELECT COUNT(*) FROM custom_nodes n WHERE n.topology_id = t.id) AS node_count,
                      (SELECT COUNT(*) FROM custom_edges e WHERE e.topology_id = t.id) AS edge_count,
                      (SELECT COUNT(*) FROM custom_nodes n WHERE n.topology_id = t.id AND n.is_monitor_point = 1) AS monitor_point_count
               FROM custom_topologies t ORDER BY t.created_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def get_custom_topology_meta(topo_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name, created_at FROM custom_topologies WHERE id = ?", (topo_id,)
        ).fetchone()
    return dict(row) if row else None


def get_custom_nodes(topo_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT node_id, label, is_monitor_point FROM custom_nodes WHERE topology_id = ?",
            (topo_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_custom_edges(topo_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT from_id, to_id, length_km, resistance_ohm, reactance_ohm
               FROM custom_edges WHERE topology_id = ?""",
            (topo_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_custom_monitor_points(topo_id: str, node_ids: list[str], is_monitor_point: bool) -> None:
    with _conn() as conn:
        conn.executemany(
            "UPDATE custom_nodes SET is_monitor_point = ? WHERE topology_id = ? AND node_id = ?",
            [(1 if is_monitor_point else 0, topo_id, nid) for nid in node_ids],
        )


def update_custom_edge_params(
    topo_id: str, edges: list[tuple[str, str]],
    length_km: float | None = None,
    resistance_ohm: float | None = None,
    reactance_ohm: float | None = None,
) -> None:
    """只更新传入的字段（None表示不改），供批量设置参数用。"""
    sets, args_tail = [], []
    if length_km is not None:
        sets.append("length_km = ?"); args_tail.append(length_km)
    if resistance_ohm is not None:
        sets.append("resistance_ohm = ?"); args_tail.append(resistance_ohm)
    if reactance_ohm is not None:
        sets.append("reactance_ohm = ?"); args_tail.append(reactance_ohm)
    if not sets:
        return
    sql = f"UPDATE custom_edges SET {', '.join(sets)} WHERE topology_id = ? AND from_id = ? AND to_id = ?"
    with _conn() as conn:
        conn.executemany(sql, [(*args_tail, topo_id, f, t) for f, t in edges])


def delete_custom_topology(topo_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM custom_nodes WHERE topology_id = ?", (topo_id,))
        conn.execute("DELETE FROM custom_edges WHERE topology_id = ?", (topo_id,))
        event_ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM custom_events WHERE topology_id = ?", (topo_id,)
        ).fetchall()]
        for eid in event_ids:
            conn.execute("DELETE FROM custom_event_readings WHERE event_id = ?", (eid,))
        conn.execute("DELETE FROM custom_events WHERE topology_id = ?", (topo_id,))
        conn.execute("DELETE FROM custom_baseline_readings WHERE topology_id = ?", (topo_id,))
        conn.execute("DELETE FROM custom_topologies WHERE id = ?", (topo_id,))
        conn.execute("DELETE FROM fault_events WHERE line = ?", (topo_id,))


# ════════════════════════════════════════════════
# 历史电气量数据（用户为每个自定义拓扑各自上传：基线读数 + 事件快照）
# 供 core.electrical_inference 使用——自动从原始电压/电流推断报警点，
# 不需要人工先给出报警监测点列表。
# ════════════════════════════════════════════════

def clear_topology_historical_data(topo_id: str) -> None:
    """重新上传时先清空该拓扑之前的历史电气量数据，避免新旧数据混在一起。"""
    with _conn() as conn:
        conn.execute("DELETE FROM custom_baseline_readings WHERE topology_id = ?", (topo_id,))
        event_ids = [r[0] for r in conn.execute(
            "SELECT event_id FROM custom_events WHERE topology_id = ?", (topo_id,)
        ).fetchall()]
        for eid in event_ids:
            conn.execute("DELETE FROM custom_event_readings WHERE event_id = ?", (eid,))
        conn.execute("DELETE FROM custom_events WHERE topology_id = ?", (topo_id,))


def insert_baseline_readings(topo_id: str, rows: list[dict]) -> None:
    with _conn() as conn:
        conn.executemany(
            """INSERT INTO custom_baseline_readings (topology_id, node_id, phase, voltage_kv, current_a)
               VALUES (?, ?, ?, ?, ?)""",
            [(topo_id, r["node_id"], r["phase"], r.get("voltage_kv"), r.get("current_a")) for r in rows],
        )


def get_baseline_readings(topo_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT node_id, phase, voltage_kv, current_a FROM custom_baseline_readings WHERE topology_id = ?",
            (topo_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def insert_event_with_readings(topo_id: str, event_id: str, timestamp: str, readings: list[dict]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO custom_events (event_id, topology_id, timestamp) VALUES (?, ?, ?)",
            (event_id, topo_id, timestamp),
        )
        conn.execute("DELETE FROM custom_event_readings WHERE event_id = ?", (event_id,))
        conn.executemany(
            """INSERT INTO custom_event_readings (event_id, node_id, phase, voltage_kv, current_a)
               VALUES (?, ?, ?, ?, ?)""",
            [(event_id, r["node_id"], r["phase"], r.get("voltage_kv"), r.get("current_a")) for r in readings],
        )


def list_topology_events(topo_id: str) -> list[dict]:
    """返回该拓扑下所有历史事件快照的概要（event_id/timestamp/涉及的监测点）。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT event_id, timestamp FROM custom_events WHERE topology_id = ? ORDER BY timestamp",
            (topo_id,),
        ).fetchall()
        result = []
        for r in rows:
            node_ids = [x[0] for x in conn.execute(
                "SELECT DISTINCT node_id FROM custom_event_readings WHERE event_id = ?", (r["event_id"],)
            ).fetchall()]
            result.append({"event_id": r["event_id"], "timestamp": r["timestamp"], "node_ids": node_ids})
    return result


def get_event_meta(event_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT event_id, topology_id, timestamp FROM custom_events WHERE event_id = ?", (event_id,)
        ).fetchone()
    return dict(row) if row else None


def get_event_readings(event_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT node_id, phase, voltage_kv, current_a FROM custom_event_readings WHERE event_id = ?",
            (event_id,),
        ).fetchall()
    return [dict(r) for r in rows]
