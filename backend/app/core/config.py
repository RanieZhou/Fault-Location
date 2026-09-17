from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory, independent of the process's actual working directory.
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'fault_location.db').as_posix()}"
    project_name: str = "Fault Location Network Initialization API"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
