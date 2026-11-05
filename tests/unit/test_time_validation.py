"""时间参数校验：带时区偏移的 ISO 8601，拒绝过去时间。"""

import datetime as dt

import pytest

from app.core.clock import UTC, FakeClock
from app.tools.timeutil import parse_future_time, parse_iso_with_offset


def test_accepts_offset_iso8601():
    parsed = parse_iso_with_offset("2026-11-04T09:00:00+08:00")
    assert parsed.utcoffset() == dt.timedelta(hours=8)


def test_accepts_z_suffix():
    parsed = parse_iso_with_offset("2026-11-04T01:00:00Z")
    assert parsed.utcoffset() == dt.timedelta(0)


def test_rejects_naive_datetime():
    with pytest.raises(ValueError, match="时区"):
        parse_iso_with_offset("2026-11-04T09:00:00")


def test_future_time_accepted():
    clock = FakeClock(dt.datetime(2026, 1, 1, tzinfo=UTC))
    parsed = parse_future_time("2026-01-02T09:00:00+08:00", clock)
    assert parsed == dt.datetime(2026, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def test_past_time_rejected():
    clock = FakeClock(dt.datetime(2026, 1, 2, tzinfo=UTC))
    with pytest.raises(ValueError, match="过去"):
        parse_future_time("2026-01-02T08:00:00+08:00", clock)  # = 00:00Z，已过去


def test_now_itself_is_past():
    clock = FakeClock(dt.datetime(2026, 1, 2, 1, 0, tzinfo=UTC))  # == 09:00+08:00
    with pytest.raises(ValueError):
        parse_future_time("2026-01-02T09:00:00+08:00", clock)
