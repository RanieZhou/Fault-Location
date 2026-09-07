"""
全局配置模块 — 路径、常量、可配参数
"""
from pathlib import Path
from pydantic_settings import BaseSettings


# ── 项目根目录 ──────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR   = ROOT_DIR / "data"

# 持久化数据库（拓扑/监测点/线路参数/历史电气量数据/故障事件历史 全部存这里，
# 系统不再依赖任何硬编码的固定线路或固定数据文件——见 core/custom_topology.py、
# core/electrical_inference.py）。原来用SQLite（单文件app.db），现在迁移到MySQL，
# 这个路径不再被db.py使用，只留着给旧数据迁移脚本（scripts/migrate_sqlite_to_mysql.py）
# 读取原始数据用。
DB_PATH = DATA_DIR / "app.db"


class Settings(BaseSettings):
    """可通过 .env 文件或环境变量覆盖的运行时配置"""

    # ── 登录账号 ──────────────────────────────────────────────
    admin_username: str = "admin"
    admin_password: str = "admin"

    # ── LLM 配置 ──────────────────────────────────────────────
    llm_provider: str = "deepseek"          # deepseek | qwen | openai
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-max"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    custom_api_key: str = ""
    custom_base_url: str = ""
    custom_model: str = ""

    # ── 故障定位算法参数 ──────────────────────────────────────
    fault_time_window_s: int = 15       # 事件分组滑动窗口（秒）
    alarm_current_threshold: float = 200.0  # 报警电流阈值（A）

    # ── 电网参数 ──────────────────────────────────────────────
    voltage_kv: float = 10.0           # 标称电压（kV）
    grounding: str = "direct"          # direct | isolated | small_resistance

    # ── MySQL 连接（取代此前的SQLite单文件） ─────────────────────
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "123456"
    mysql_database: str = "fault_location"

    class Config:
        env_file = str(ROOT_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


# 全局单例
settings = Settings()
