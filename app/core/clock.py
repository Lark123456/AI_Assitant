"""可注入时钟。所有业务时间读取必须经由 Clock，禁止 datetime.now() / time.time()。"""

import datetime as dt
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


class Clock:
    """系统时钟，读取真实当前时间。"""

    def now(self) -> dt.datetime:
        """当前 UTC 时间（aware）。"""
        return dt.datetime.now(tz=UTC)

    def now_tz(self, tz: str) -> dt.datetime:
        """当前时间，按给定 IANA 时区返回。"""
        return dt.datetime.now(tz=ZoneInfo(tz))


class FakeClock(Clock):
    """测试用假时钟：固定时间起点，可任意快进。"""

    def __init__(self, start: dt.datetime | None = None) -> None:
        self._now = start.astimezone(UTC) if start else dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def now(self) -> dt.datetime:
        return self._now

    def now_tz(self, tz: str) -> dt.datetime:
        return self._now.astimezone(ZoneInfo(tz))

    def advance(self, seconds: float) -> None:
        """快进 seconds 秒。"""
        self._now = self._now + dt.timedelta(seconds=seconds)

    def advance_to(self, target: dt.datetime) -> None:
        """快进到指定时刻（必须带时区）。"""
        if target.tzinfo is None:
            raise ValueError("advance_to target must be timezone-aware")
        target_utc = target.astimezone(UTC)
        if target_utc < self._now:
            raise ValueError("advance_to target must not be in the past")
        self._now = target_utc
