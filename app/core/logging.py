"""结构化 JSON 日志，trace_id 与 user_id 通过 contextvar 自动附带。"""

import contextvars
import datetime as dt
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="")


class JsonFormatter(logging.Formatter):
    """把日志记录序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": dt.datetime.fromtimestamp(
                record.created, tz=dt.UTC
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": trace_id_var.get(),
            "user_id": user_id_var.get(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str) -> None:
    """配置根 logger 为 JSON 输出，幂等。"""
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_context(trace_id: str = "", user_id: str = "") -> Iterator[None]:
    """在上下文内绑定 trace_id / user_id，退出后恢复。"""
    t_token = trace_id_var.set(trace_id) if trace_id else None
    u_token = user_id_var.set(user_id) if user_id else None
    try:
        yield
    finally:
        if u_token is not None:
            user_id_var.reset(u_token)
        if t_token is not None:
            trace_id_var.reset(t_token)
