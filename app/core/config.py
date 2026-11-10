"""应用配置：所有配置来自环境变量（可 .env），禁止硬编码。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://butler:butler@localhost:5432/butler"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    # Agent Plan（智体套餐）凭据：provider 为 openai_compat_agent 的档位使用
    llm_agent_base_url: str = ""
    llm_agent_api_key: str = ""
    aliases_path: str = "app/llm/aliases.yaml"
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    default_timezone: str = "Asia/Shanghai"
    allowed_open_ids: str = ""  # 逗号分隔的外部 id（open_id 等）白名单；空 = 不限制；对所有渠道生效
    enable_console: bool = False  # Console HTTP 路由开关（本地测试用），默认关闭
    llm_daily_limit: int = 200  # 每用户每日 LLM 调用上限（按用户时区当日计）；<=0 不限制
    worker_poll_interval: float = 1.0
    worker_batch_size: int = 10
    # 阶段 2：提前多少分钟提醒块开始；结束后多少分钟检查是否完成
    block_lead_minutes: int = 10
    block_grace_minutes: int = 15
    # 停机补偿：late_send = 窗口内补发并标注迟到；drop = 过期即丢弃
    reminder_late_policy: str = "late_send"
    reminder_late_window_hours: float = 24.0
    # 主动消息总开关：1/true 时非 commitment 一律丢弃
    nudge_kill_switch: bool = False
    # 物化器运行间隔（秒）
    materialize_interval_seconds: float = 300.0
    trigger_lease_seconds: float = 300.0  # claimed 租约超时，超时后回收重试
    # 阶段 3a：嵌入与记忆写入
    embedding_base_url: str = "http://localhost:11434"
    embedding_model: str = "qwen3-embedding:0.6b"
    embedding_dim: int = 1024
    memory_idle_minutes: float = 10.0
    memory_batch_max_events: int = 40
    memory_neighbor_threshold: float = 0.75
    memory_neighbor_topk: int = 5
    # 阶段 3b：把长期记忆注入 Friday 上下文
    memory_inject_enabled: bool = True
    memory_inject_topk: int = 6
    memory_inject_min_similarity: float = 0.45
    memory_inject_max_chars: int = 800
    memory_inject_item_max_chars: int = 120
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """进程级单例配置。"""
    return Settings()
