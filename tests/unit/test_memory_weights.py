"""权重：初始、强化、反证与推断类衰减。"""

import datetime as dt

from app.core.clock import UTC
from app.memory.weights import (
    contradicted_weight,
    effective_weight,
    initial_weight,
    max_weight,
    reinforced_weight,
)


def test_initial_and_caps() -> None:
    assert initial_weight("stated") == 0.8
    assert initial_weight("inferred") == 0.2
    assert initial_weight("confirmed") == 1.0
    assert max_weight("inferred") == 0.6
    assert max_weight("stated") == 0.9


def test_reinforce_adds_per_new_date_and_caps() -> None:
    assert reinforced_weight("stated", 0.8, 1) == 0.9
    assert reinforced_weight("stated", 0.9, 3) == 0.9
    assert reinforced_weight("inferred", 0.2, 2) == 0.4
    assert reinforced_weight("inferred", 0.5, 5) == 0.6


def test_contradiction_floors_at_zero() -> None:
    assert contradicted_weight(0.8) == 0.6
    assert contradicted_weight(0.1) == 0.0


def test_inferred_decays_with_30_day_half_life() -> None:
    anchor = dt.datetime(2026, 1, 1, tzinfo=UTC)
    now = anchor + dt.timedelta(days=30)
    assert effective_weight("inferred", 0.4, anchor, now) == 0.2
    assert effective_weight("inferred", 0.4, anchor, anchor) == 0.4
    # stated / confirmed 不衰减
    assert effective_weight("stated", 0.8, anchor, now) == 0.8
    assert effective_weight("confirmed", 1.0, anchor, now) == 1.0
