"""scope 相对日期归一化：LLM 只给 date_text，代码按事件时间与用户时区计算。"""

import calendar
import datetime as dt
import re
from zoneinfo import ZoneInfo

from app.core.timeutil import local_date_of
from app.memory.schemas import ScopeSpec

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _month_end(day: dt.date, months_offset: int = 0) -> dt.date:
    year = day.year + (day.month - 1 + months_offset) // 12
    month = (day.month - 1 + months_offset) % 12 + 1
    return dt.date(year, month, calendar.monthrange(year, month)[1])


def _parse_date_text(text: str, base: dt.date) -> dt.date | None:
    value = text.strip()
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        pass
    if value in ("今天", "今日"):
        return base
    if value in ("明天", "明日"):
        return base + dt.timedelta(days=1)
    if value == "后天":
        return base + dt.timedelta(days=2)
    if value in ("昨天", "昨日"):
        return base - dt.timedelta(days=1)

    if value in ("月底", "本月底", "这个月底", "月末"):
        return _month_end(base)
    if value in ("下月底", "下个月底"):
        return _month_end(base, 1)

    match = re.search(r"(\d{1,2})月(\d{1,2})日", value)
    if match:
        try:
            return dt.date(base.year, int(match.group(1)), int(match.group(2)))
        except ValueError:
            return None

    match = re.search(r"(本|这|下)?(?:周|星期|礼拜)([一二三四五六日天])", value)
    if match:
        weekday = _WEEKDAYS[match.group(2)]
        monday = base - dt.timedelta(days=base.weekday())
        offset = weekday
        if match.group(1) == "下":
            offset += 7
        return monday + dt.timedelta(days=offset)
    return None


def normalize_scope(
    spec: ScopeSpec,
    event_time: dt.datetime,
    tz: str,
    day_start: dt.time,
) -> dict | None:
    """返回契约规定的 scope JSON；无法归一化返回 None。"""
    if spec.kind == "persistent":
        return {"kind": "persistent"}
    if spec.kind == "recurring":
        rule = (spec.rule or "").strip()
        return {"kind": "recurring", "rule": rule} if rule else None
    if spec.kind in ("on", "until"):
        if not spec.date_text:
            return None
        base = local_date_of(event_time, tz, day_start)
        parsed = _parse_date_text(spec.date_text, base)
        if parsed is None:
            return None
        return {"kind": spec.kind, "date": parsed.isoformat()}
    return None


def local_date_at(instant: dt.datetime, tz: str) -> dt.date:
    return instant.astimezone(ZoneInfo(tz)).date()
