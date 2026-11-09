"""槽位时间的确定性解析：7点 / 七点 / 早上7点 / 7:30 / 7点半 → HH:MM。"""

import re

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_PERIODS_EVENING = ("下午", "晚上", "傍晚", "夜里")
_PERIODS_MORNING = ("凌晨", "早上", "早晨", "上午")


def _cn_number(text: str) -> int | None:
    """解析 0-59 的中文数字（十一、二十、二十一、两）。"""
    if not text:
        return None
    if text == "十":
        return 10
    if "十" in text:
        left, _, right = text.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _CN_DIGITS.get(text)


def _hour(text: str) -> int | None:
    return int(text) if text.isdigit() else _cn_number(text)


def _format(hour: int, minute: int) -> str | None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


# 12 小时制消歧窗口（用户本地时间，闭区间；sleep 跨午夜）
SLOT_TIME_WINDOWS: dict[str, tuple[str, str]] = {
    "wake": ("04:00", "11:00"),
    "work_start": ("06:00", "12:00"),
    "lunch": ("10:30", "14:30"),
    "work_end": ("14:00", "23:30"),
    "sleep": ("20:00", "04:00"),
}


def _in_window(hhmm: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= hhmm <= end
    return hhmm >= start or hhmm <= end


def disambiguate_slot_time(slot_key: str | None, hhmm: str) -> str:
    """按槽位合理时间窗把 12 小时制纠正为 24 小时制；无法判断时保留原值。"""
    if slot_key not in SLOT_TIME_WINDOWS:
        return hhmm
    hour = int(hhmm[:2])
    minute = int(hhmm[3:])
    if hour >= 13:
        return hhmm
    alt = f"00:{minute:02d}" if hour == 12 else f"{hour + 12:02d}:{minute:02d}"
    start, end = SLOT_TIME_WINDOWS[slot_key]
    current_ok = _in_window(hhmm, start, end)
    alt_ok = _in_window(alt, start, end)
    if current_ok and not alt_ok:
        return hhmm
    if alt_ok and not current_ok:
        return alt
    # 两种读法都合理或都不合理：不猜，保留原话
    return hhmm


def parse_time_text(text: str | None) -> str | None:
    """返回规范化 HH:MM；无法解析返回 None。"""
    if not text:
        return None
    value = str(text).strip().replace("：", ":").replace(" ", "")
    if not value:
        return None

    # 7:30 / 07:30
    match = re.search(r"(\d{1,2}):(\d{2})", value)
    if match:
        return _format(int(match.group(1)), int(match.group(2)))

    # 7点半 / 7点30 / 七点 / 十一点半
    match = re.search(r"([零〇一二两三四五六七八九十]+|\d{1,2})点(半|[0-5]?\d分?)", value)
    if not match:
        match = re.search(r"([零〇一二两三四五六七八九十]+|\d{1,2})点", value)
    if not match:
        return None
    hour = _hour(match.group(1))
    if hour is None:
        return None
    minute = 0
    tail = match.group(2) if match.lastindex and match.lastindex >= 2 else None
    if tail:
        if tail == "半":
            minute = 30
        elif tail.rstrip("分").isdigit():
            minute = int(tail.rstrip("分"))

    if any(prefix in value for prefix in _PERIODS_EVENING) and hour < 12:
        hour += 12
    elif "晚上" in value and hour == 12:
        hour = 0
    elif "凌晨" in value and hour == 12:
        hour = 0
    elif "中午" in value and hour <= 2:
        hour += 12
    return _format(hour, minute)
