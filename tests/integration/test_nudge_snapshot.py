"""build_snapshot 表驱动集成测试：预置真实决策数据，逐字段断言快照。"""

import datetime as dt

import pytest

from app.core.clock import UTC
from app.core.config import Settings
from app.db.models import NotifPrefs, NudgeCandidate, NudgeDecision, User
from app.engine.materializer import get_or_create_prefs
from app.engine.nudge import build_snapshot


async def _add_decision(
    session,
    user: User,
    *,
    class_: str,
    reason: str,
    decision: str,
    at: dt.datetime,
    dedupe_key: str | None = None,
) -> NudgeCandidate:
    candidate = NudgeCandidate(
        user_id=user.id,
        class_=class_,
        reason_code=reason,
        reason_text=reason,
        value_score=1.0,
        dedupe_key=dedupe_key,
        explicit=False,
    )
    session.add(candidate)
    await session.flush()
    session.add(
        NudgeDecision(
            candidate_id=candidate.id,
            decision=decision,
            gate_reasons=None,
            policy_version="test",
            budget_snapshot=None,
            decided_at=at,
        )
    )
    await session.flush()
    return candidate


async def _seed_baseline(db, clock) -> dict:
    """一天内的各类决策 + 昨日决策 + 其他用户决策 + 用于排除自身校验的候选。"""
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        other = User(display_name="u2", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add_all([user, other])
        await session.flush()
        prefs = await get_or_create_prefs(session, user.id, clock)

        d1 = await _add_decision(
            session, user, class_="commitment", reason="commitment.reminder",
            decision="send", at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC), dedupe_key="k1",
        )
        await _add_decision(
            session, user, class_="brief", reason="brief.morning",
            decision="send", at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC), dedupe_key="k2",
        )
        await _add_decision(
            session, user, class_="suggestion", reason="suggestion.stale_tasks",
            decision="merge", at=dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC), dedupe_key="k3",
        )
        await _add_decision(
            session, user, class_="suggestion", reason="suggestion.overdue_blocks",
            decision="drop", at=dt.datetime(2026, 1, 1, 4, 0, tzinfo=UTC), dedupe_key="k4",
        )
        d5 = await _add_decision(
            session, user, class_="commitment", reason="commitment.block_start",
            decision="defer", at=dt.datetime(2026, 1, 1, 5, 0, tzinfo=UTC), dedupe_key="k1",
        )
        d6 = await _add_decision(
            session, user, class_="commitment", reason="commitment.reminder",
            decision="send", at=dt.datetime(2025, 12, 31, 19, 0, tzinfo=UTC), dedupe_key="k5",
        )
        await _add_decision(
            session, other, class_="commitment", reason="commitment.reminder",
            decision="send", at=dt.datetime(2026, 1, 1, 6, 0, tzinfo=UTC), dedupe_key="k1",
        )
        await session.commit()

    return {
        "user": user,
        "prefs": prefs,
        "candidates": {"d1": d1, "d5": d5, "d6": d6},
    }


async def test_snapshot_today_counts(db, fake_clock, settings) -> None:
    data = await _seed_baseline(db, fake_clock)
    async with db() as session:
        snapshot = await build_snapshot(
            session, user=data["user"], prefs=data["prefs"], clock=fake_clock,
            settings=settings, dedupe_key=None,
        )
    # 只统计今日 send；defer/drop/merge 不算、昨日与其他用户不算
    assert snapshot.sent_today_by_class == {"commitment": 1, "brief": 1}
    assert snapshot.sent_today_by_reason == {
        "commitment.reminder": 1,
        "brief.morning": 1,
    }
    # 今日 merge 计入建议并入预算
    assert snapshot.suggestion_budget_used == 1
    assert snapshot.last_decision_at == {}


@pytest.mark.parametrize(
    ("dedupe_key", "exclude", "expected"),
    [
        ("k1", None, dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC)),   # send，defer 不算
        ("k1", "d1", None),                                        # 排除自身后无 send/merge
        ("k2", None, dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC)),   # send
        ("k3", None, dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC)),   # merge 也算
        ("k4", None, None),                                        # drop 不算
        ("k5", None, dt.datetime(2025, 12, 31, 19, 0, tzinfo=UTC)),  # 跨天仍在 24h 窗口
    ],
)
async def test_snapshot_last_decision_at_table(
    db, fake_clock, settings, dedupe_key, exclude, expected
) -> None:
    data = await _seed_baseline(db, fake_clock)
    exclude_id = data["candidates"][exclude].id if exclude else None
    async with db() as session:
        snapshot = await build_snapshot(
            session, user=data["user"], prefs=data["prefs"], clock=fake_clock,
            settings=settings, dedupe_key=dedupe_key, candidate_id=exclude_id,
        )
    assert snapshot.last_decision_at.get(dedupe_key) == expected


async def test_snapshot_prefs_and_kill_switch(db, fake_clock) -> None:
    data = await _seed_baseline(db, fake_clock)
    async with db() as session:
        prefs = await session.get(NotifPrefs, data["user"].id)
        assert prefs is not None
        prefs.daily_budget = 2
        prefs.quiet_hours = {"start": "22:00", "end": "08:00"}
        prefs.class_enabled = {"suggestion": False}
        prefs.snooze_until = dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
        prefs.briefs_enabled = False
        await session.commit()

    custom = Settings(_env_file=None, nudge_kill_switch=True)
    async with db() as session:
        fresh_prefs = await session.get(NotifPrefs, data["user"].id)
        assert fresh_prefs is not None
        snapshot = await build_snapshot(
            session, user=data["user"], prefs=fresh_prefs, clock=fake_clock,
            settings=custom, dedupe_key=None,
        )
    assert snapshot.now == fake_clock.now()
    assert snapshot.tz == "Asia/Shanghai"
    assert snapshot.day_start == dt.time(4, 0)
    assert snapshot.daily_budget == 2
    assert snapshot.quiet_start == dt.time(22, 0)
    assert snapshot.quiet_end == dt.time(8, 0)
    assert snapshot.class_enabled == {"suggestion": False}
    assert snapshot.snooze_until == dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    assert snapshot.briefs_enabled is False
    assert snapshot.kill_switch is True
