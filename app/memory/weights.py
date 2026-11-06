"""记忆权重：初始、强化、反证与推断类衰减（纯函数）。"""

import datetime as dt

INITIAL_WEIGHTS: dict[str, float] = {"stated": 0.8, "inferred": 0.2, "confirmed": 1.0}
WEIGHT_CAPS: dict[str, float] = {"stated": 0.9, "inferred": 0.6, "confirmed": 1.0}
INFERRED_HALF_LIFE_DAYS = 30.0
REINFORCE_STEP = 0.1
CONTRADICT_STEP = 0.2


def initial_weight(source_class: str) -> float:
    return INITIAL_WEIGHTS.get(source_class, 0.2)


def max_weight(source_class: str) -> float:
    return WEIGHT_CAPS.get(source_class, 0.6)


def effective_weight(
    source_class: str,
    weight: float,
    anchor: dt.datetime | None,
    now: dt.datetime,
) -> float:
    """推断类按 30 天半衰期衰减；stated / confirmed 不衰减。"""
    if source_class != "inferred" or anchor is None:
        return float(weight)
    age_days = max(0.0, (now - anchor).total_seconds() / 86400.0)
    decayed = weight * (0.5 ** (age_days / INFERRED_HALF_LIFE_DAYS))
    return float(decayed)


def reinforced_weight(source_class: str, weight: float, new_dates: int) -> float:
    """每个新的本地日期 +0.1，直到该类上限。"""
    return round(min(max_weight(source_class), weight + REINFORCE_STEP * new_dates), 4)


def contradicted_weight(weight: float) -> float:
    return round(max(0.0, weight - CONTRADICT_STEP), 4)


def support_days(dates: set[dt.date]) -> int:
    return len(dates)
