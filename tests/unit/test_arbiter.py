"""仲裁器纯函数：每条规则的通过与拒绝、豁免、延后与上限。"""

import datetime as dt
from dataclasses import replace

import pytest

from app.engine.arbiter import (
    DEFER_LIMIT,
    NON_COMMITMENT_DAILY_CAP,
    CandidateView,
    UserStateSnapshot,
    evaluate,
)


def snap(**overrides: object) -> UserStateSnapshot:
    base = UserStateSnapshot(
        # 2026-11-06 12:00Z = 上海 20:00（不在默认免打扰时段）
        now=dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.UTC),
        tz="Asia/Shanghai",
        day_start=dt.time(4, 0),
    )
    return replace(base, **overrides)


def cand(**overrides: object) -> CandidateView:
    base = CandidateView(class_="commitment", reason_code="commitment.reminder")
    return replace(base, **overrides)


def test_plain_commitment_sends() -> None:
    decision = evaluate(cand(), snap())
    assert decision.decision == "send"
    assert decision.policy_version == "stage2-v0"


def test_kill_switch_drops_non_commitment_but_exempts_commitment() -> None:
    killed = snap(kill_switch=True)
    assert evaluate(cand(class_="brief", reason_code="brief.morning"), killed).decision == "drop"
    assert evaluate(cand(class_="suggestion", reason_code="suggestion.stale_tasks"), killed).decision == "drop"
    assert evaluate(cand(), killed).decision == "send"


def test_class_disabled_and_briefs_disabled() -> None:
    off = snap(class_enabled={"suggestion": False})
    assert evaluate(cand(class_="suggestion", reason_code="suggestion.stale_tasks"), off).decision == "drop"
    # commitment 不受类别开关影响
    assert evaluate(cand(), off).decision == "send"
    no_briefs = snap(briefs_enabled=False)
    assert evaluate(cand(class_="brief", reason_code="brief.morning"), no_briefs).decision == "drop"


def test_snooze_drops_non_commitment_only() -> None:
    snoozed = snap(snooze_until=dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    assert evaluate(cand(class_="brief", reason_code="brief.morning"), snoozed).decision == "drop"
    assert evaluate(cand(), snoozed).decision == "send"


def test_expired_and_precondition_failed() -> None:
    s = snap()
    expired = cand(expires_at=dt.datetime(2026, 11, 6, 11, 0, tzinfo=dt.UTC))
    assert evaluate(expired, s).decision == "drop"
    assert evaluate(cand(precondition_ok=False), s).decision == "drop"


def test_cooldown_within_24h() -> None:
    s = snap(
        last_decision_at={"reminder:42": dt.datetime(2026, 11, 6, 11, 0, tzinfo=dt.UTC)}
    )
    assert evaluate(cand(dedupe_key="reminder:42"), s).decision == "drop"
    old = snap(
        last_decision_at={"reminder:42": dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.UTC)}
    )
    assert evaluate(cand(dedupe_key="reminder:42"), old).decision == "send"


def test_quiet_hours_defers_non_explicit_to_period_end() -> None:
    # 上海 23:30 → 免打扰结束是次日 07:00（UTC 23:00）
    s = snap(now=dt.datetime(2026, 11, 6, 15, 30, tzinfo=dt.UTC))
    deferred = evaluate(cand(explicit=False), s)
    assert deferred.decision == "defer"
    assert deferred.defer_until == dt.datetime(2026, 11, 6, 23, 0, tzinfo=dt.UTC)


def test_quiet_hours_exempts_explicit_commitment() -> None:
    s = snap(now=dt.datetime(2026, 11, 6, 15, 30, tzinfo=dt.UTC))
    assert evaluate(cand(explicit=True), s).decision == "send"
    # 非 explicit 的 block_start 仍要延后
    assert evaluate(cand(reason_code="commitment.block_start", explicit=False), s).decision == "defer"


def test_quiet_hours_drops_when_expires_before_period_end() -> None:
    s = snap(now=dt.datetime(2026, 11, 6, 15, 30, tzinfo=dt.UTC))
    expires = dt.datetime(2026, 11, 6, 16, 0, tzinfo=dt.UTC)
    decision = evaluate(cand(explicit=False, expires_at=expires), s)
    assert decision.decision == "drop"
    assert decision.gate_reasons["steps"][-1]["rule"] == "quiet_hours"


def test_quiet_hours_drops_after_defer_limit() -> None:
    s = snap(now=dt.datetime(2026, 11, 6, 15, 30, tzinfo=dt.UTC))
    decision = evaluate(cand(explicit=False, defer_count=DEFER_LIMIT), s)
    assert decision.decision == "drop"


def test_brief_budget_one_per_kind_per_day() -> None:
    s = snap(sent_today_by_reason={"brief.morning": 1})
    assert evaluate(cand(class_="brief", reason_code="brief.morning"), s).decision == "drop"
    assert evaluate(cand(class_="brief", reason_code="brief.evening"), s).decision == "send"


def test_suggestion_budget_and_merge() -> None:
    s = snap(daily_budget=4, suggestion_budget_used=0)
    assert evaluate(cand(class_="suggestion", reason_code="suggestion.stale_tasks"), s).decision == "merge"
    full = snap(daily_budget=4, suggestion_budget_used=4)
    assert (
        evaluate(cand(class_="suggestion", reason_code="suggestion.stale_tasks"), full).decision
        == "drop"
    )


def test_hard_caps() -> None:
    s = snap(sent_today_by_class={"brief": NON_COMMITMENT_DAILY_CAP})
    assert evaluate(cand(class_="brief", reason_code="brief.evening"), s).decision == "drop"
    s2 = snap(sent_today_by_class={"commitment": 50})
    assert evaluate(cand(), s2).decision == "drop"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, "send"),
        ({"kill_switch": True}, "send"),
        ({"snooze_until": dt.datetime(2027, 1, 1, tzinfo=dt.UTC)}, "send"),
    ],
)
def test_commitment_is_exempt_from_soft_controls(
    overrides: dict[str, object], expected: str
) -> None:
    """表驱动：commitment 对 kill switch / snooze 均豁免。"""
    assert evaluate(cand(), snap(**overrides)).decision == expected
