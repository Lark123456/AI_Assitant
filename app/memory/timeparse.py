"""槽位与 episode 时间的确定性解析。

- 槽位：7点 / 七点 / 早上7点 / 7:30 / 7点半 → HH:MM，并按槽位窗口纠正 12 小时制
- episode：先由活动词确定时间角色，再按同一窗口判断能否确定上下午；无法确定返回 None
"""

import re

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_PERIODS_EVENING = ("下午", "晚上", "傍晚", "夜里", "昨晚", "昨夜", "今晚")

# 明确时段词：出现时直接采用解析结果，不再按角色窗口猜测
PERIOD_HINTS = (
    "凌晨", "早上", "早晨", "上午", "中午", "下午", "傍晚", "晚上", "夜里",
    "昨晚", "昨夜", "今早", "今晚",
)

# 活动词 → 时间角色；多字模式先于单词匹配
_MULTI_WAKE = re.compile(r"睡到[^，。；、]*?(?:才)?(?:起|醒)")
_MULTI_SLEEP = re.compile(r"(?:\d{1,2}|[零〇一二两三四五六七八九十]+)点(?:半|[0-5]?\d分?)?才?睡|睡觉")

_SINGLE_ROLE_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wake", ("起床", "起", "醒")),
    ("sleep", ("睡",)),
    ("work_end", ("加班", "下班")),
    ("work_start", ("到公司", "上班")),
    ("lunch", ("吃午饭", "吃中午饭")),
)

# 槽位允许只给时段词、无需钟点
PERIOD_SLOT_KEYS = frozenset({"energy_peak"})

# 通勤值为方式时降级为 preference
COMMUTE_MODE_WORDS = (
    "开车", "驾车", "坐地铁", "地铁", "公交", "骑车", "步行", "打车", "班车", "通勤",
)

# 解析不出钟点即降级为 preference 的槽位
TIME_REQUIRED_SLOT_KEYS = frozenset({"wake", "sleep", "work_start", "work_end", "lunch"})


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


def _period_hint(text: str) -> str | None:
    """返回文本中第一个明确时段词。"""
    for hint in PERIOD_HINTS:
        if hint in text:
            return hint
    return None


def has_period_hint(text: str | None) -> bool:
    """文本中是否出现明确时段词（用于 episode 直接采用与 energy_peak 放宽）。"""
    if not text:
        return False
    return _period_hint(text) is not None


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
    elif any(word in value for word in ("晚上", "夜里", "昨晚", "昨夜", "今晚")) and hour == 12:
        hour = 0
    elif "凌晨" in value and hour == 12:
        hour = 0
    elif "中午" in value and hour <= 2:
        hour += 12
    return _format(hour, minute)


def episode_roles(text: str) -> set[str]:
    """从句子中提取时间角色；多字模式优先，返回命中的角色集合。"""
    remaining = text
    roles: set[str] = set()

    match = _MULTI_WAKE.search(remaining)
    if match:
        roles.add("wake")
        remaining = f"{remaining[:match.start()]} {remaining[match.end():]}"
    match = _MULTI_SLEEP.search(remaining)
    if match:
        roles.add("sleep")
        remaining = f"{remaining[:match.start()]} {remaining[match.end():]}"

    for role, words in _SINGLE_ROLE_WORDS:
        if any(word in remaining for word in words):
            roles.add(role)
    return roles


def resolve_episode_time(text: str, time_text: str | None) -> str | None:
    """按活动词角色与槽位时间窗确定 episode 的 HH:MM；无法确定返回 None。

    规则：
    - 有时段词（早上、下午、昨晚、今早等）或 24 小时制（含冒号、小时 >= 13）时直接采用
    - 否则按活动词确定唯一角色，再判断 12 小时制哪种读法落在该角色的合理窗口
    - 角色不唯一、映射不到角色、或两种读法都无法唯一确定时不写 time
    """
    raw = (time_text or "").strip()
    if not raw:
        return None

    # 时段词可能只出现在原句里（如「昨晚十一点才睡」只给了「十一点」）：
    # 把线索拼回时间表达，确保「昨晚 → PM、今早 → AM」生效
    hint = _period_hint(f"{text}{raw}")
    parsed = parse_time_text(f"{hint}{raw}" if hint else raw)
    if parsed is None:
        return None

    hour = int(parsed[:2])
    minute = parsed[3:]
    if ":" in raw.replace("：", ":") or hour >= 13:
        return parsed
    if hint is not None:
        return parsed

    roles = episode_roles(text)
    if len(roles) != 1:
        return None
    role = next(iter(roles))
    if role not in SLOT_TIME_WINDOWS:
        return None

    alt = f"00:{minute}" if hour == 12 else f"{hour + 12:02d}:{minute}"
    start, end = SLOT_TIME_WINDOWS[role]
    current_ok = _in_window(parsed, start, end)
    alt_ok = _in_window(alt, start, end)
    if current_ok and not alt_ok:
        return parsed
    if alt_ok and not current_ok:
        return alt
    return None
