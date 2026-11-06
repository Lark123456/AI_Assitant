"""时间与 scope 的确定性归一化。"""

import datetime as dt

from app.core.clock import UTC
from app.memory.schemas import ScopeSpec
from app.memory.scope import normalize_scope
from app.memory.timeparse import parse_time_text


def test_parse_time_text() -> None:
    assert parse_time_text("7点") == "07:00"
    assert parse_time_text("七点") == "07:00"
    assert parse_time_text("早上7点") == "07:00"
    assert parse_time_text("晚上9点") == "21:00"
    assert parse_time_text("下午3点半") == "15:30"
    assert parse_time_text("7:30") == "07:30"
    assert parse_time_text("中午12点") == "12:00"
    assert parse_time_text("晚上12点") == "00:00"
    assert parse_time_text("十一点") == "11:00"
    assert parse_time_text("随便") is None


def test_normalize_scope_relative_dates() -> None:
    event_time = dt.datetime(2026, 11, 6, 0, 0, tzinfo=UTC)  # 本地 11-06 08:00（周五）
    tz = "Asia/Shanghai"
    day_start = dt.time(4, 0)

    assert normalize_scope(ScopeSpec(kind="persistent"), event_time, tz, day_start) == {
        "kind": "persistent"
    }
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="今天"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-06"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="明天"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-07"}
    assert normalize_scope(
        ScopeSpec(kind="until", date_text="月底"), event_time, tz, day_start
    ) == {"kind": "until", "date": "2026-11-30"}
    # 周五的“下周三” = 11-11
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="下周三"), event_time, tz, day_start
    ) == {"kind": "on", "date": "2026-11-11"}
    assert normalize_scope(
        ScopeSpec(kind="recurring", rule="每周一"), event_time, tz, day_start
    ) == {"kind": "recurring", "rule": "每周一"}
    assert normalize_scope(
        ScopeSpec(kind="on", date_text="不知道"), event_time, tz, day_start
    ) is None
