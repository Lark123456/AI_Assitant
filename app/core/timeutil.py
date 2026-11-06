"""用户本地日与免打扰时段计算（全部基于 zoneinfo，夏令时安全）。

约定：instant 必须是带时区的 UTC 时刻；「用户的一天」以 user.day_start 为边界，
不假设一天固定 86400 秒（夏令时切换日可能是 23 或 25 小时）。
"""

import datetime as dt
from zoneinfo import ZoneInfo


def _local(instant: dt.datetime, tz: str) -> dt.datetime:
    if instant.tzinfo is None:
        raise ValueError("instant must be timezone-aware")
    return instant.astimezone(ZoneInfo(tz))


def local_date_of(instant: dt.datetime, tz: str, day_start: dt.time) -> dt.date:
    """instant 所属的本地日：早于 day_start 的时刻算前一天。"""
    local = _local(instant, tz)
    day = local.date()
    if local.time() < day_start:
        day -= dt.timedelta(days=1)
    return day


def day_window_for_date(
    day: dt.date, tz: str, day_start: dt.time
) -> tuple[dt.datetime, dt.datetime]:
    """指定本地日的 UTC 窗口 [start, end)。"""
    zone = ZoneInfo(tz)
    start = dt.datetime.combine(day, day_start).replace(tzinfo=zone)
    end = dt.datetime.combine(day + dt.timedelta(days=1), day_start).replace(tzinfo=zone)
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


def day_window_utc(
    instant: dt.datetime, tz: str, day_start: dt.time
) -> tuple[dt.datetime, dt.datetime]:
    """本地日的 UTC 窗口 [start, end)：按 zoneinfo 真实偏移计算，夏令时安全。"""
    return day_window_for_date(local_date_of(instant, tz, day_start), tz, day_start)


def local_time_of(instant: dt.datetime, tz: str) -> dt.time:
    """instant 在该时区的本地墙钟时间。"""
    return _local(instant, tz).time()


def in_quiet_hours(local_time: dt.time, start: dt.time, end: dt.time) -> bool:
    """判断本地时间是否在免打扰区间 [start, end)，支持跨午夜（如 23:00–07:00）。"""
    if start == end:
        return False
    if start < end:
        return start <= local_time < end
    return local_time >= start or local_time < end


def quiet_hours_end(instant: dt.datetime, tz: str, start: dt.time, end: dt.time) -> dt.datetime:
    """若当前处于免打扰时段，返回该时段结束的 UTC 时刻；不在时段内则原样返回。"""
    if not in_quiet_hours(_local(instant, tz).time(), start, end):
        return instant
    zone = ZoneInfo(tz)
    local = _local(instant, tz)
    if start < end:
        end_day = local.date()
    else:
        # 跨午夜：已过 start（如 23:30）则结束在明天；未到 end（如 02:00）则结束在今天
        end_day = local.date() + dt.timedelta(days=1 if local.time() >= start else 0)
    return dt.datetime.combine(end_day, end).replace(tzinfo=zone).astimezone(dt.UTC)
