"""本地日窗口与免打扰时段：边界、跨午夜、夏令时。"""

import datetime as dt

from app.core.timeutil import (
    day_window_utc,
    in_quiet_hours,
    local_date_of,
    local_time_of,
)


def test_local_date_respects_day_start() -> None:
    tz = "Asia/Shanghai"
    start = dt.time(4, 0)
    # 2026-01-01 02:00 UTC = 本地 10:00 → 当天
    assert local_date_of(dt.datetime(2026, 1, 1, 2, 0, tzinfo=dt.UTC), tz, start) == dt.date(2026, 1, 1)
    # 2025-12-31 19:00 UTC = 本地 2026-01-01 03:00 → 早于 04:00，算前一天
    assert local_date_of(dt.datetime(2025, 12, 31, 19, 0, tzinfo=dt.UTC), tz, start) == dt.date(
        2025, 12, 31
    )


def test_day_window_utc_shanghai() -> None:
    tz = "Asia/Shanghai"
    start = dt.time(4, 0)
    begin, end = day_window_utc(dt.datetime(2026, 1, 1, 2, 0, tzinfo=dt.UTC), tz, start)
    # 2026-01-01 04:00+08 == 2025-12-31 20:00Z
    assert begin == dt.datetime(2025, 12, 31, 20, 0, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 1, 1, 20, 0, tzinfo=dt.UTC)
    assert end - begin == dt.timedelta(hours=24)


def test_day_window_utc_spring_dst_is_23_hours() -> None:
    # America/Los_Angeles 2026-03-08 02:00 拨快：03-07 的窗口只有 23 小时
    tz = "America/Los_Angeles"
    start = dt.time(4, 0)
    begin, end = day_window_utc(dt.datetime(2026, 3, 7, 12, 0, tzinfo=dt.UTC), tz, start)
    assert end - begin == dt.timedelta(hours=23)


def test_day_window_utc_autumn_dst_is_25_hours() -> None:
    # 2026-11-01 02:00 拨慢：10-31 的窗口有 25 小时
    tz = "America/Los_Angeles"
    start = dt.time(4, 0)
    begin, end = day_window_utc(dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC), tz, start)
    assert end - begin == dt.timedelta(hours=25)


def test_local_time_of() -> None:
    assert local_time_of(dt.datetime(2026, 1, 1, 0, 30, tzinfo=dt.UTC), "Asia/Shanghai") == dt.time(
        8, 30
    )


def test_quiet_hours_cross_midnight() -> None:
    start, end = dt.time(23, 0), dt.time(7, 0)
    assert in_quiet_hours(dt.time(23, 30), start, end)
    assert in_quiet_hours(dt.time(0, 1), start, end)
    assert in_quiet_hours(dt.time(6, 59), start, end)
    assert not in_quiet_hours(dt.time(7, 0), start, end)
    assert not in_quiet_hours(dt.time(12, 0), start, end)
    assert in_quiet_hours(dt.time(23, 0), start, end)


def test_quiet_hours_same_day_range() -> None:
    start, end = dt.time(9, 0), dt.time(18, 0)
    assert in_quiet_hours(dt.time(12, 0), start, end)
    assert not in_quiet_hours(dt.time(8, 59), start, end)
    assert not in_quiet_hours(dt.time(18, 0), start, end)


def test_quiet_hours_empty_range() -> None:
    assert not in_quiet_hours(dt.time(12, 0), dt.time(10, 0), dt.time(10, 0))
