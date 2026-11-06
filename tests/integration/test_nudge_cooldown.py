"""冷却语义：不同候选共享 dedupe_key 时，只有已成功/已合并的决策才触发冷却。"""

import datetime as dt

from sqlalchemy import select

from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.db.models import ChannelIdentity, NudgeCandidate, NudgeDecision, User
from app.engine.handlers import CandidateDraft
from app.engine.materializer import get_or_create_prefs
from app.engine.nudge import get_or_create_candidate, process_candidate
from app.engine.triggers import create_trigger


async def _setup(db, clock, settings):
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        session.add(ChannelIdentity(user_id=user.id, channel="console", external_id="u1", rev=1))
        prefs = await get_or_create_prefs(session, user.id, clock)
        triggers = []
        for key in ("cooldown-t1", "cooldown-t2"):
            trigger, _ = await create_trigger(
                session,
                user_id=user.id,
                kind="reminder",
                key=key,
                fire_at=clock.now(),
                tz="Asia/Shanghai",
                payload={"note": key},
                expires_at=clock.now() + dt.timedelta(hours=24),
                clock=clock,
            )
            triggers.append(trigger)
        await session.commit()
    adapter = ConsoleAdapter(make_identity_resolver(db, "console"))
    return user, prefs, triggers[0], triggers[1], adapter


async def _process(
    db, clock, settings, *, user, prefs, trigger, adapter, expires_at=None
) -> tuple[str, NudgeCandidate]:
    async with db() as session:
        draft = CandidateDraft(
            class_="commitment",
            reason_code="commitment.reminder",
            reason_text="共享键候选",
            value_score=1.0,
            explicit=True,
            dedupe_key="shared-key",
            expires_at=expires_at,
            precondition=None,
        )
        candidate = await get_or_create_candidate(session, trigger=trigger, draft=draft)
        outcome = await process_candidate(
            session,
            user=user,
            prefs=prefs,
            candidate=candidate,
            trigger=trigger,
            adapter=adapter,
            clock=clock,
            settings=settings,
            gateway=None,
            trace_id="cooldown",
        )
        await session.commit()
    return outcome.decision, candidate


async def test_second_candidate_with_shared_key_is_dropped(db, fake_clock, settings) -> None:
    user, prefs, t1, t2, adapter = await _setup(db, fake_clock, settings)

    first, _ = await _process(
        db, fake_clock, settings, user=user, prefs=prefs, trigger=t1, adapter=adapter
    )
    assert first == "send"

    second, candidate2 = await _process(
        db, fake_clock, settings, user=user, prefs=prefs, trigger=t2, adapter=adapter
    )
    assert second == "drop"

    async with db() as session:
        decision = (
            await session.execute(
                select(NudgeDecision).where(NudgeDecision.candidate_id == candidate2.id)
            )
        ).scalar_one()
    assert decision.decision == "drop"
    failed_rules = {s["rule"] for s in decision.gate_reasons["steps"] if not s["passed"]}
    assert "cooldown" in failed_rules


async def test_drop_decision_does_not_start_cooldown(db, fake_clock, settings) -> None:
    user, prefs, t1, t2, adapter = await _setup(db, fake_clock, settings)

    # 第一个候选已过期 → drop；drop 不应给同名 dedupe_key 上冷却
    first, _ = await _process(
        db, fake_clock, settings, user=user, prefs=prefs, trigger=t1, adapter=adapter,
        expires_at=fake_clock.now() - dt.timedelta(hours=1),
    )
    assert first == "drop"

    second, _ = await _process(
        db, fake_clock, settings, user=user, prefs=prefs, trigger=t2, adapter=adapter
    )
    assert second == "send"
