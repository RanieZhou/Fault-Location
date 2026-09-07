# -*- coding: utf-8 -*-
"""
一次性脚本：把原SQLite数据库（data/app.db）里的实际业务数据迁移到MySQL。

用法：先确保 core/db.py 已经指向MySQL、且 init_db() 已经在MySQL里建好了空表
（应用启动时会自动调用），再运行这个脚本把旧数据搬过去。可重复运行——每张表
迁移前会先清空，不会重复插入。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import db as mysql_db
from core.config import DB_PATH, settings

SQLITE_PATH = DB_PATH


def read_sqlite_table(conn, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(r) for r in rows]


def main():
    if not SQLITE_PATH.exists():
        print(f"[!] 找不到旧的SQLite数据库文件: {SQLITE_PATH}，没有数据需要迁移")
        return

    sconn = sqlite3.connect(str(SQLITE_PATH))
    sconn.row_factory = sqlite3.Row

    tables = [
        "custom_topologies", "custom_nodes", "custom_edges",
        "custom_baseline_readings", "custom_events", "custom_event_readings",
        "monitoring_events", "monitoring_records", "fault_events",
        "llm_provider_config", "app_settings",
    ]

    data = {}
    for t in tables:
        try:
            data[t] = read_sqlite_table(sconn, t)
        except sqlite3.OperationalError:
            data[t] = []  # 旧库里可能没有这张表（比如从更早版本升级过来的）
        print(f"[读取] {t}: {len(data[t])} 行")
    sconn.close()

    with mysql_db._conn() as conn:
        with conn.cursor() as cur:
            # 按依赖顺序清空后重新导入，可重复运行不产生重复数据
            for t in reversed(tables):
                cur.execute(f"DELETE FROM {t}")

            for row in data["custom_topologies"]:
                cur.execute(
                    "INSERT INTO custom_topologies (id, name, created_at) VALUES (%s, %s, %s)",
                    (row["id"], row["name"], row.get("created_at")),
                )
            for row in data["custom_nodes"]:
                cur.execute(
                    "INSERT INTO custom_nodes (topology_id, node_id, label, is_monitor_point) VALUES (%s, %s, %s, %s)",
                    (row["topology_id"], row["node_id"], row["label"], row["is_monitor_point"]),
                )
            for row in data["custom_edges"]:
                cur.execute(
                    """INSERT INTO custom_edges (topology_id, from_id, to_id, length_km, resistance_ohm, reactance_ohm)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (row["topology_id"], row["from_id"], row["to_id"],
                     row["length_km"], row["resistance_ohm"], row["reactance_ohm"]),
                )
            for row in data["custom_baseline_readings"]:
                cur.execute(
                    """INSERT INTO custom_baseline_readings (topology_id, node_id, phase, voltage_kv, current_a)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (row["topology_id"], row["node_id"], row["phase"], row["voltage_kv"], row["current_a"]),
                )
            for row in data["custom_events"]:
                cur.execute(
                    "INSERT INTO custom_events (event_id, topology_id, timestamp) VALUES (%s, %s, %s)",
                    (row["event_id"], row["topology_id"], row["timestamp"]),
                )
            for row in data["custom_event_readings"]:
                cur.execute(
                    """INSERT INTO custom_event_readings (event_id, node_id, phase, voltage_kv, current_a)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (row["event_id"], row["node_id"], row["phase"], row["voltage_kv"], row["current_a"]),
                )
            for row in data["monitoring_events"]:
                cur.execute(
                    """INSERT INTO monitoring_events
                       (event_id, topology_id, topology_name, timestamp, record_count, abnormal_count,
                        fault_summary, inferred_poles, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (row["event_id"], row["topology_id"], row["topology_name"], row["timestamp"],
                     row["record_count"], row["abnormal_count"], row["fault_summary"],
                     row["inferred_poles"], row.get("created_at")),
                )
            for row in data["monitoring_records"]:
                cur.execute(
                    """INSERT INTO monitoring_records
                       (event_id, topology_id, record_no, node_id, node_name, device_type, terminal_status,
                        line_status, warning_status, ua, ub, uc, ia, ib, ic, phase_a, phase_b, phase_c,
                        measure_time, is_abnormal, abnormal_reason, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (row["event_id"], row["topology_id"], row["record_no"], row["node_id"], row["node_name"],
                     row["device_type"], row["terminal_status"], row["line_status"], row["warning_status"],
                     row["ua"], row["ub"], row["uc"], row["ia"], row["ib"], row["ic"],
                     row["phase_a"], row["phase_b"], row["phase_c"], row["measure_time"],
                     row["is_abnormal"], row["abnormal_reason"], row.get("created_at")),
                )
            for row in data["fault_events"]:
                cur.execute(
                    """INSERT INTO fault_events
                       (event_id, line, time, fault_types, alarmed_points, frontier,
                        candidate_sections, confidence, note, source, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (row["event_id"], row["line"], row["time"], row["fault_types"], row["alarmed_points"],
                     row["frontier"], row["candidate_sections"], row["confidence"], row["note"],
                     row["source"], row.get("created_at")),
                )
            # llm_provider_config / app_settings 以SQLite里的实际值为准——这两张表
            # init_db() 已经从 .env 兜底迁移过一次，但用户可能后来在设置页更新过，
            # SQLite里的才是最新的，这里覆盖掉刚才.env迁移出来的初始值。
            for row in data["llm_provider_config"]:
                cur.execute(
                    """INSERT INTO llm_provider_config (provider, api_key, base_url, model, updated_at)
                       VALUES (%s, %s, %s, %s, %s)
                       ON DUPLICATE KEY UPDATE
                         api_key=VALUES(api_key), base_url=VALUES(base_url),
                         model=VALUES(model), updated_at=VALUES(updated_at)""",
                    (row["provider"], row["api_key"], row["base_url"], row["model"], row.get("updated_at")),
                )
            for row in data["app_settings"]:
                cur.execute(
                    """INSERT INTO app_settings (`key`, `value`) VALUES (%s, %s)
                       ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)""",
                    (row["key"], row["value"]),
                )

    print("\n[完成] 已将SQLite数据迁移到MySQL")
    for t in tables:
        print(f"  {t}: {len(data[t])} 行")


if __name__ == "__main__":
    main()
