"""应用配置：所有配置来自环境变量（可 .env），禁止硬编码。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://butler:butler@localhost:5432/butler"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    aliases_path: str = "app/llm/aliases.yaml"
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    default_timezone: str = "Asia/Shanghai"
    allowed_open_ids: str = ""  # 逗号分隔的飞书 open_id 白名单；空 = 不限制
    llm_daily_limit: int = 200  # 每用户每日 LLM 调用上限（按用户时区当日计）；<=0 不限制
    worker_poll_interval: float = 1.0
    worker_batch_size: int = 10
    reminder_ttl_minutes: float = 60.0
    trigger_lease_seconds: float = 300.0  # claimed 租约超时，超时后回收重试
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """进程级单例配置。"""
    return Settings()
