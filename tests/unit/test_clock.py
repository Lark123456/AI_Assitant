"""Clock 与 FakeClock 的行为。"""

import datetime as dt

import pytest

from app.core.clock import UTC, Clock, FakeClock


def test_clock_now_is_utc_aware():
    now = Clock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == dt.timedelta(0)


def test_fake_clock_starts_at_fixed_point():
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert clock.now() == dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def test_fake_clock_advance():
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    clock.advance(90)
    assert clock.now() == dt.datetime(2026, 1, 1, 0, 1, 30, tzinfo=UTC)


def test_fake_clock_advance_to_converts_timezone():
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    clock.advance_to(dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))
    assert clock.now() == dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC)


def test_fake_clock_rejects_naive_and_past_targets():
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    with pytest.raises(ValueError):
        clock.advance_to(dt.datetime(2026, 1, 2, tzinfo=None))
    with pytest.raises(ValueError):
        clock.advance_to(dt.datetime(2025, 12, 31, tzinfo=UTC))


def test_now_tz_converts():
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    local = clock.now_tz("Asia/Shanghai")
    assert local.hour == 8
