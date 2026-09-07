"""
core/db.py — MySQL 持久化：拓扑/监测点/线路参数/历史电气量数据/故障事件历史。

设计：
  - 系统不再有任何硬编码的固定线路，所有拓扑都是用户上传的自定义拓扑（custom_topologies
    及相关表），历史电气量数据（custom_baseline_readings / custom_events /
    custom_event_readings）也按拓扑各自上传、各自隔离。
  - fault_events 表随 /api/fault/locate 的实际调用持续增长（source='live'）。
  - 不做连接池/ORM：数据量小（几十到几百行级别），每次操作开箱即用地开关连接即可。
  - 原来用SQLite单文件（data/app.db），这版改成MySQL——之所以留意这一点：MySQL的
    TEXT/BLOB列不允许设DEFAULT（哪怕是DEFAULT ''），SQLite里大量"TEXT NOT NULL
    DEFAULT ''"字段搬过来统一改成允许NULL的TEXT；被当主键或建了索引的字段从TEXT
    改成VARCHAR（MySQL的索引要求字段有确定长度）；CREATE INDEX不支持IF NOT EXISTS，
    单独用_ensure_index()处理；参数占位符从?换成%s；INSERT OR REPLACE/IGNORE、
    ON CONFLICT...DO UPDATE 都换成MySQL自己的等价语法。
"""
from __future__ import annotations
import pymysql
import pymysql.cursors
from contextlib import contextmanager
from datetime import datetime

from .config import settings
from .models import HistoryEvent


def _now() -> str:
    """MySQL的TEXT列不能设DEFAULT，created_at/updated_at这类字段需要应用层显式生成——
    格式跟原来SQLite的 datetime('now','localtime') 保持一致（'YYYY-MM-DD HH:MM:SS'），
    不影响下游依赖这个字符串格式（比如datetime.fromisoformat）的代码。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS fault_events (
        event_id            VARCHAR(64) PRIMARY KEY,
        line                VARCHAR(128) NOT NULL,
        time                VARCHAR(32) NOT NULL,
        fault_types         TEXT,
        alarmed_points      TEXT,
        frontier            TEXT,
        candidate_sections  TEXT,
        confidence          VARCHAR(32) NOT NULL DEFAULT 'unknown',
        note                TEXT,
        source              VARCHAR(32) NOT NULL DEFAULT 'live',
        created_at          VARCHAR(32)
    )""",
    """CREATE TABLE IF NOT EXISTS llm_provider_config (
        provider    VARCHAR(32) PRIMARY KEY,
        api_key     TEXT,
        base_url    TEXT,
        model       TEXT,
        updated_at  VARCHAR(32)
    )""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        `key`   VARCHAR(64) PRIMARY KEY,
        `value` TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS custom_topologies (
        id          VARCHAR(64) PRIMARY KEY,
        name        TEXT,
        created_at  VARCHAR(32)
    )""",
    """CREATE TABLE IF NOT EXISTS custom_nodes (
        topology_id       VARCHAR(64) NOT NULL,
        node_id           VARCHAR(255) NOT NULL,
        label             TEXT,
        is_monitor_point  INT NOT NULL DEFAULT 0,
        PRIMARY KEY (topology_id, node_id)
    )""",
    """CREATE TABLE IF NOT EXISTS custom_edges (
        topology_id     VARCHAR(64) NOT NULL,
        from_id         VARCHAR(255) NOT NULL,
        to_id           VARCHAR(255) NOT NULL,
        length_km       DOUBLE NOT NULL DEFAULT 0,
        resistance_ohm  DOUBLE NOT NULL DEFAULT 0,
        reactance_ohm   DOUBLE NOT NULL DEFAULT 0,
        PRIMARY KEY (topology_id, from_id, to_id)
    )""",
    # 基线（正常）读数：用来算每个监测点每相的正常电压/电流均值方差，是电气量推理的基准
    """CREATE TABLE IF NOT EXISTS custom_baseline_readings (
        topology_id  VARCHAR(64) NOT NULL,
        node_id      VARCHAR(255) NOT NULL,
        phase        VARCHAR(8) NOT NULL,
        voltage_kv   DOUBLE,
        current_a    DOUBLE
    )""",
    # 历史事件快照：一次真实故障发生时刻，各监测点的原始三相读数
    """CREATE TABLE IF NOT EXISTS custom_events (
        event_id     VARCHAR(64) PRIMARY KEY,
        topology_id  VARCHAR(64) NOT NULL,
        timestamp    VARCHAR(32) NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS custom_event_readings (
        event_id    VARCHAR(64) NOT NULL,
        node_id     VARCHAR(255) NOT NULL,
        phase       VARCHAR(8) NOT NULL,
        voltage_kv  DOUBLE,
        current_a   DOUBLE
    )""",
    # 生产级监测数据记录（10列标准展示：编号、监测点名称、设备类型、终端状态、线路状态、预警状态、三相电压、三相电流、三相相位、时间）
    """CREATE TABLE IF NOT EXISTS monitoring_records (
        id                INT AUTO_INCREMENT PRIMARY KEY,
        event_id          VARCHAR(64) NOT NULL,
        topology_id       VARCHAR(64) NOT NULL,
        record_no         INT NOT NULL,
        node_id           TEXT,
        node_name         TEXT,
        device_type       TEXT,
        terminal_status   TEXT,
        line_status       TEXT,
        warning_status    TEXT,
        ua                DOUBLE,
        ub                DOUBLE,
        uc                DOUBLE,
        ia                DOUBLE,
        ib                DOUBLE,
        ic                DOUBLE,
        phase_a           DOUBLE,
        phase_b           DOUBLE,
        phase_c           DOUBLE,
        measure_time      VARCHAR(32) NOT NULL,
        is_abnormal       INT NOT NULL DEFAULT 0,
        abnormal_reason   TEXT,
        created_at        VARCHAR(32)
    )""",
    """CREATE TABLE IF NOT EXISTS monitoring_events (
        event_id          VARCHAR(64) PRIMARY KEY,
        topology_id       VARCHAR(64) NOT NULL,
        topology_name     TEXT,
        timestamp         VARCHAR(32) NOT NULL,
        record_count      INT NOT NULL DEFAULT 0,
        abnormal_count    INT NOT NULL DEFAULT 0,
        fault_summary     TEXT,
        inferred_poles    TEXT,
        created_at        VARCHAR(32)
    )""",
]

# MySQL的CREATE INDEX不支持IF NOT EXISTS，单独列出来逐条创建、忽略"已存在"错误
_INDEX_STATEMENTS = [
    ("idx_fault_events_line", "CREATE INDEX idx_fault_events_line ON fault_events(line)"),
    ("idx_fault_events_time", "CREATE INDEX idx_fault_events_time ON fault_events(time)"),
    ("idx_baseline_topo_node", "CREATE INDEX idx_baseline_topo_node ON custom_baseline_readings(topology_id, node_id)"),
    ("idx_events_topo", "CREATE INDEX idx_events_topo ON custom_events(topology_id)"),
    ("idx_event_readings_event", "CREATE INDEX idx_event_readings_event ON custom_event_readings(event_id)"),
    ("idx_mon_rec_event", "CREATE INDEX idx_mon_rec_event ON monitoring_records(event_id)"),
    ("idx_mon_rec_topo", "CREATE INDEX idx_mon_rec_topo ON monitoring_records(topology_id)"),
    ("idx_mon_rec_time", "CREATE INDEX idx_mon_rec_time ON monitoring_records(measure_time)"),
    ("idx_mon_evt_topo", "CREATE INDEX idx_mon_evt_topo ON monitoring_events(topology_id)"),
    ("idx_mon_evt_time", "CREATE INDEX idx_mon_evt_time ON monitoring_events(timestamp)"),
]


@contextmanager
def _conn():
    conn = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """建表（幂等）+ 从.env迁移已有LLM配置。应用启动时调用一次。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            for stmt in _SCHEMA_STATEMENTS:
                cur.execute(stmt)
            for name, stmt in _INDEX_STATEMENTS:
                try:
                    cur.execute(stmt)
                except pymysql.err.OperationalError as e:
                    if e.args and e.args[0] == 1061:  # Duplicate key name——索引已存在，忽略
                        continue
                    raise
            cur.execute("SELECT COUNT(*) AS cnt FROM llm_provider_config")
            llm_count = cur.fetchone()["cnt"]
        if llm_count == 0:
            _migrate_llm_config_from_env(conn)


def _migrate_llm_config_from_env(conn) -> None:
    """
    一次性迁移：LLM配置此前写在 .env 里（旧实现），这里改成数据库之后，
    把 .env 里已有的配置导进来，避免用户之前保存过的配置在这次架构调整后
    "凭空消失"。只在 llm_provider_config 表为空时触发一次，此后以数据库为准。
    """
    providers = {
        "deepseek": (settings.deepseek_api_key, settings.deepseek_base_url, settings.deepseek_model),
        "qwen": (settings.qwen_api_key, settings.qwen_base_url, settings.qwen_model),
        "openai": (settings.openai_api_key, settings.openai_base_url, settings.openai_model),
        "custom": (settings.custom_api_key, settings.custom_base_url, settings.custom_model),
    }
    migrated = []
    with conn.cursor() as cur:
        for prov, (api_key, base_url, model) in providers.items():
            if api_key:  # 只迁移真正配置过Key的provider，避免插入一堆空记录
                cur.execute(
                    """INSERT IGNORE INTO llm_provider_config (provider, api_key, base_url, model, updated_at)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (prov, api_key, base_url, model, _now()),
                )
                migrated.append(prov)

        active = settings.llm_provider
        if active:
            cur.execute(
                """INSERT INTO app_settings (`key`, `value`) VALUES ('active_llm_provider', %s)
                   ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)""",
                (active,),
            )
    if migrated:
        print(f"[db] 已从 .env 迁移 {len(migrated)} 个LLM provider配置到数据库: {migrated}")


def insert_event(event: HistoryEvent) -> None:
    """追加一条事件记录（source 由调用方在 event.source 中指定，通常为 'live'）。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """REPLACE INTO fault_events
                   (event_id, line, time, fault_types, alarmed_points, frontier,
                    candidate_sections, confidence, note, source, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event.event_id, event.line, event.time, event.fault_types,
                    event.alarmed_points, event.frontier, event.candidate_sections,
                    event.confidence, event.note, event.source, _now(),
                ),
            )


# ════════════════════════════════════════════════
# LLM 提供商配置（取代此前写 .env 的方式——.env 是纯文本KV，用字符串拼接读写，
# 遇到含特殊字符的key容易出问题；数据库更规范，且和历史事件用同一套持久化风格）
# ════════════════════════════════════════════════

def save_llm_provider_config(provider: str, api_key: str, base_url: str, model: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO llm_provider_config (provider, api_key, base_url, model, updated_at)
                   VALUES (%s, %s, %s, %s, %s)
                   ON DUPLICATE KEY UPDATE
                     api_key=VALUES(api_key), base_url=VALUES(base_url),
                     model=VALUES(model), updated_at=VALUES(updated_at)""",
                (provider, api_key, base_url, model, _now()),
            )


def get_llm_provider_config(provider: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT provider, api_key, base_url, model FROM llm_provider_config WHERE provider = %s",
                (provider,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_all_llm_provider_configs() -> dict[str, dict]:
    """返回 {provider: {provider, api_key, base_url, model}}，供前端表单回填用（明文，非脱敏——
    这个函数只在受登录保护的 /api/settings/llm/all 内部调用，不对外裸露）。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT provider, api_key, base_url, model FROM llm_provider_config")
            rows = cur.fetchall()
    return {r["provider"]: dict(r) for r in rows}


def set_app_setting(key: str, value: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)
                   ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)""",
                (key, value),
            )


def get_app_setting(key: str, default: str = "") -> str:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT `value` FROM app_settings WHERE `key` = %s", (key,))
            row = cur.fetchone()
    return row["value"] if row else default


def get_all_events(line: str | None = None) -> list[HistoryEvent]:
    """按时间正序返回事件（可选按线路过滤）。"""
    sql = "SELECT * FROM fault_events"
    args: tuple = ()
    if line:
        sql += " WHERE line = %s"
        args = (line,)
    sql += " ORDER BY time ASC"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
    return [
        HistoryEvent(
            event_id=r["event_id"], line=r["line"], time=r["time"],
            fault_types=r["fault_types"] or "", alarmed_points=r["alarmed_points"] or "",
            frontier=r["frontier"] or "", candidate_sections=r["candidate_sections"] or "",
            confidence=r["confidence"], note=r["note"] or "", source=r["source"],
        )
        for r in rows
    ]


# ════════════════════════════════════════════════
# 自定义拓扑（用户上传节点/边表——系统里唯一的拓扑来源）
# ════════════════════════════════════════════════

def create_custom_topology(
    topo_id: str, name: str,
    nodes: list[dict],   # [{"node_id":..., "label":..., "is_monitor_point": 可选}, ...]
    edges: list[dict],   # [{"from_id":..., "to_id":..., "length_km": 可选, "resistance_ohm": 可选, "reactance_ohm": 可选}, ...]
) -> None:
    """新建一个自定义拓扑并写入全部节点/边（一次性写入，upload接口用）。
    边表如果自带length_km、阻抗参数，节点表如果自带is_monitor_point，
    直接落库，不用上传完拓扑再回头单独补一遍。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO custom_topologies (id, name, created_at) VALUES (%s, %s, %s)",
                (topo_id, name, _now()),
            )
            cur.executemany(
                "INSERT INTO custom_nodes (topology_id, node_id, label, is_monitor_point) VALUES (%s, %s, %s, %s)",
                [(topo_id, n["node_id"], n.get("label") or n["node_id"], 1 if n.get("is_monitor_point") else 0) for n in nodes],
            )
            cur.executemany(
                """INSERT INTO custom_edges (topology_id, from_id, to_id, length_km, resistance_ohm, reactance_ohm)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [
                    (
                        topo_id,
                        e["from_id"],
                        e["to_id"],
                        e.get("length_km") or 0.0,
                        e.get("resistance_ohm") or 0.0,
                        e.get("reactance_ohm") or 0.0,
                    )
                    for e in edges
                ],
            )


def list_custom_topologies() -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT t.id, t.name, t.created_at,
                          (SELECT COUNT(*) FROM custom_nodes n WHERE n.topology_id = t.id) AS node_count,
                          (SELECT COUNT(*) FROM custom_edges e WHERE e.topology_id = t.id) AS edge_count,
                          (SELECT COUNT(*) FROM custom_nodes n WHERE n.topology_id = t.id AND n.is_monitor_point = 1) AS monitor_point_count
                   FROM custom_topologies t ORDER BY t.created_at DESC"""
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_custom_topology_meta(topo_id: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, created_at FROM custom_topologies WHERE id = %s", (topo_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def get_custom_nodes(topo_id: str) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT node_id, label, is_monitor_point FROM custom_nodes WHERE topology_id = %s",
                (topo_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_custom_edges(topo_id: str) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT from_id, to_id, length_km, resistance_ohm, reactance_ohm
                   FROM custom_edges WHERE topology_id = %s""",
                (topo_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def update_custom_monitor_points(topo_id: str, node_ids: list[str], is_monitor_point: bool) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE custom_nodes SET is_monitor_point = %s WHERE topology_id = %s AND node_id = %s",
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
        sets.append("length_km = %s"); args_tail.append(length_km)
    if resistance_ohm is not None:
        sets.append("resistance_ohm = %s"); args_tail.append(resistance_ohm)
    if reactance_ohm is not None:
        sets.append("reactance_ohm = %s"); args_tail.append(reactance_ohm)
    if not sets:
        return
    sql = f"UPDATE custom_edges SET {', '.join(sets)} WHERE topology_id = %s AND from_id = %s AND to_id = %s"
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, [(*args_tail, topo_id, f, t) for f, t in edges])


def delete_custom_topology(topo_id: str) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM custom_nodes WHERE topology_id = %s", (topo_id,))
            cur.execute("DELETE FROM custom_edges WHERE topology_id = %s", (topo_id,))
            cur.execute("SELECT event_id FROM custom_events WHERE topology_id = %s", (topo_id,))
            event_ids = [r["event_id"] for r in cur.fetchall()]
            for eid in event_ids:
                cur.execute("DELETE FROM custom_event_readings WHERE event_id = %s", (eid,))
            cur.execute("DELETE FROM custom_events WHERE topology_id = %s", (topo_id,))
            cur.execute("DELETE FROM custom_baseline_readings WHERE topology_id = %s", (topo_id,))
            cur.execute("DELETE FROM custom_topologies WHERE id = %s", (topo_id,))
            cur.execute("DELETE FROM fault_events WHERE line = %s", (topo_id,))


# ════════════════════════════════════════════════
# 历史电气量数据（用户为每个自定义拓扑各自上传：基线读数 + 事件快照）
# 供 core.electrical_inference 使用——自动从原始电压/电流推断报警点，
# 不需要人工先给出报警监测点列表。
# ════════════════════════════════════════════════

def clear_topology_historical_data(topo_id: str) -> None:
    """重新上传时先清空该拓扑之前的历史电气量数据，避免新旧数据混在一起。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM custom_baseline_readings WHERE topology_id = %s", (topo_id,))
            cur.execute("SELECT event_id FROM custom_events WHERE topology_id = %s", (topo_id,))
            event_ids = [r["event_id"] for r in cur.fetchall()]
            for eid in event_ids:
                cur.execute("DELETE FROM custom_event_readings WHERE event_id = %s", (eid,))
            cur.execute("DELETE FROM custom_events WHERE topology_id = %s", (topo_id,))


def insert_baseline_readings(topo_id: str, rows: list[dict]) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO custom_baseline_readings (topology_id, node_id, phase, voltage_kv, current_a)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(topo_id, r["node_id"], r["phase"], r.get("voltage_kv"), r.get("current_a")) for r in rows],
            )


def get_baseline_readings(topo_id: str) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT node_id, phase, voltage_kv, current_a FROM custom_baseline_readings WHERE topology_id = %s",
                (topo_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def insert_event_with_readings(topo_id: str, event_id: str, timestamp: str, readings: list[dict]) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "REPLACE INTO custom_events (event_id, topology_id, timestamp) VALUES (%s, %s, %s)",
                (event_id, topo_id, timestamp),
            )
            cur.execute("DELETE FROM custom_event_readings WHERE event_id = %s", (event_id,))
            cur.executemany(
                """INSERT INTO custom_event_readings (event_id, node_id, phase, voltage_kv, current_a)
                   VALUES (%s, %s, %s, %s, %s)""",
                [(event_id, r["node_id"], r["phase"], r.get("voltage_kv"), r.get("current_a")) for r in readings],
            )


def list_topology_events(topo_id: str) -> list[dict]:
    """返回该拓扑下所有历史事件快照的概要（event_id/timestamp/涉及的监测点）。"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, timestamp FROM custom_events WHERE topology_id = %s ORDER BY timestamp",
                (topo_id,),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                cur.execute(
                    "SELECT DISTINCT node_id FROM custom_event_readings WHERE event_id = %s", (r["event_id"],)
                )
                node_ids = [x["node_id"] for x in cur.fetchall()]
                result.append({"event_id": r["event_id"], "timestamp": r["timestamp"], "node_ids": node_ids})
    return result


def get_event_meta(event_id: str) -> dict | None:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, topology_id, timestamp FROM custom_events WHERE event_id = %s", (event_id,)
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_event_readings(event_id: str) -> list[dict]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT node_id, phase, voltage_kv, current_a FROM custom_event_readings WHERE event_id = %s",
                (event_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════
# 生产级监测数据存储与查询（10列标准数据模型）
# ════════════════════════════════════════════════

def save_monitoring_event_and_records(event_meta: dict, records: list[dict]) -> None:
    """保存一次监测事件以及下属的所有10列原始记录"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """REPLACE INTO monitoring_events
                   (event_id, topology_id, topology_name, timestamp, record_count, abnormal_count, fault_summary, inferred_poles, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    event_meta["event_id"],
                    event_meta["topology_id"],
                    event_meta.get("topology_name", ""),
                    event_meta["timestamp"],
                    event_meta.get("record_count", len(records)),
                    event_meta.get("abnormal_count", 0),
                    event_meta.get("fault_summary", ""),
                    event_meta.get("inferred_poles", ""),
                    _now(),
                ),
            )
            cur.execute("DELETE FROM monitoring_records WHERE event_id = %s", (event_meta["event_id"],))
            cur.executemany(
                """INSERT INTO monitoring_records
                   (event_id, topology_id, record_no, node_id, node_name, device_type, terminal_status,
                    line_status, warning_status, ua, ub, uc, ia, ib, ic, phase_a, phase_b, phase_c,
                    measure_time, is_abnormal, abnormal_reason, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        event_meta["event_id"],
                        event_meta["topology_id"],
                        r.get("record_no", idx + 1),
                        r.get("node_id", ""),
                        r.get("node_name", ""),
                        r.get("device_type", "配电线路"),
                        r.get("terminal_status", "正常"),
                        r.get("line_status", "正常"),
                        r.get("warning_status", "正常"),
                        r.get("ua"),
                        r.get("ub"),
                        r.get("uc"),
                        r.get("ia"),
                        r.get("ib"),
                        r.get("ic"),
                        r.get("phase_a"),
                        r.get("phase_b"),
                        r.get("phase_c"),
                        r.get("measure_time", ""),
                        1 if r.get("is_abnormal") else 0,
                        r.get("abnormal_reason", ""),
                        _now(),
                    )
                    for idx, r in enumerate(records)
                ],
            )


def list_monitoring_events(topology_id: str | None = None) -> list[dict]:
    """获取所有监测事件列表（按时间倒序）"""
    with _conn() as conn:
        with conn.cursor() as cur:
            if topology_id:
                cur.execute(
                    """SELECT event_id, topology_id, topology_name, timestamp, record_count,
                              abnormal_count, fault_summary, inferred_poles, created_at
                       FROM monitoring_events
                       WHERE topology_id = %s
                       ORDER BY timestamp DESC""",
                    (topology_id,),
                )
            else:
                cur.execute(
                    """SELECT event_id, topology_id, topology_name, timestamp, record_count,
                              abnormal_count, fault_summary, inferred_poles, created_at
                       FROM monitoring_events
                       ORDER BY timestamp DESC"""
                )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_monitoring_event(event_id: str) -> dict | None:
    """获取单次事件概要信息"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT event_id, topology_id, topology_name, timestamp, record_count,
                          abnormal_count, fault_summary, inferred_poles, created_at
                   FROM monitoring_events
                   WHERE event_id = %s""",
                (event_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def get_monitoring_records(event_id: str) -> list[dict]:
    """获取某事件下属的所有10列标准监测数据记录"""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, event_id, topology_id, record_no, node_id, node_name,
                          device_type, terminal_status, line_status, warning_status,
                          ua, ub, uc, ia, ib, ic, phase_a, phase_b, phase_c,
                          measure_time, is_abnormal, abnormal_reason
                   FROM monitoring_records
                   WHERE event_id = %s
                   ORDER BY record_no ASC, id ASC""",
                (event_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def query_monitoring_records(
    topology_id: str | None = None,
    device_type: str | None = None,
    line_status: str | None = None,
    terminal_status: str | None = None,
    warning_status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[dict], int]:
    """
    历史数据页用：不分批次，把所有记录打平按量测时间倒序（最新在前）分页查询，
    支持按10列表格里的枚举型字段做精确筛选、按监测点名称做模糊搜索。
    返回 (当前页记录, 符合条件的总数)。
    """
    where = []
    params: list = []
    if topology_id:
        where.append("topology_id = %s")
        params.append(topology_id)
    if device_type:
        where.append("device_type = %s")
        params.append(device_type)
    if line_status:
        where.append("line_status = %s")
        params.append(line_status)
    if terminal_status:
        where.append("terminal_status = %s")
        params.append(terminal_status)
    if warning_status:
        where.append("warning_status = %s")
        params.append(warning_status)
    if search:
        where.append("node_name LIKE %s")
        params.append(f"%{search}%")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM monitoring_records {where_sql}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""SELECT id, event_id, topology_id, record_no, node_id, node_name,
                           device_type, terminal_status, line_status, warning_status,
                           ua, ub, uc, ia, ib, ic, phase_a, phase_b, phase_c,
                           measure_time, is_abnormal, abnormal_reason
                    FROM monitoring_records
                    {where_sql}
                    ORDER BY measure_time DESC, id DESC
                    LIMIT %s OFFSET %s""",
                [*params, page_size, (page - 1) * page_size],
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows], total


def list_monitoring_filter_options(topology_id: str | None = None) -> dict:
    """历史数据页筛选下拉框用：当前实际出现过的设备类型/线路状态/终端状态/预警状态取值，
    不用写死枚举——不同拓扑、不同生产系统导出的状态文案可能不一样。"""
    where_sql = "WHERE topology_id = %s" if topology_id else ""
    params = [topology_id] if topology_id else []
    with _conn() as conn:
        with conn.cursor() as cur:
            def _distinct(col: str) -> list[str]:
                cur.execute(
                    f"SELECT DISTINCT {col} AS v FROM monitoring_records {where_sql} ORDER BY {col}", params
                )
                return [r["v"] for r in cur.fetchall() if r["v"]]
            return {
                "device_types": _distinct("device_type"),
                "line_statuses": _distinct("line_status"),
                "terminal_statuses": _distinct("terminal_status"),
                "warning_statuses": _distinct("warning_status"),
            }


def clear_monitoring_records(topology_id: str | None = None) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            if topology_id:
                cur.execute("SELECT event_id FROM monitoring_events WHERE topology_id = %s", (topology_id,))
                event_ids = [r["event_id"] for r in cur.fetchall()]
                for eid in event_ids:
                    cur.execute("DELETE FROM monitoring_records WHERE event_id = %s", (eid,))
                cur.execute("DELETE FROM monitoring_events WHERE topology_id = %s", (topology_id,))
            else:
                cur.execute("DELETE FROM monitoring_records")
                cur.execute("DELETE FROM monitoring_events")
