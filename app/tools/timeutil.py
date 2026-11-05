"""时间参数校验：必须是带时区偏移的 ISO 8601，且不得为过去时间。"""

import datetime as dt

from app.core.clock import Clock


def parse_iso_with_offset(value: str) -> dt.datetime:
    """解析 ISO 8601；拒绝无时区偏移的输入。"""
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"时间必须带时区偏移（ISO 8601），收到：{value}")
    return parsed


def parse_future_time(value: str, clock: Clock) -> dt.datetime:
    """解析并校验为未来时间。"""
    parsed = parse_iso_with_offset(value)
    if parsed <= clock.now():
        raise ValueError(f"时间不能是过去：{value}")
    return parsed
