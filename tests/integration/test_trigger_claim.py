"""trigger 并发领取不重复（SKIP LOCKED，需要 Postgres）。"""

import asyncio

from app.db.models import User
from app.engine.triggers import claim_due_triggers, create_trigger


async def _make_user(db, clock) -> object:
    async with db() as session:
        user = User(
            display_name="u", timezone="Asia/Shanghai",
            created_at=clock.now(), updated_at=clock.now(),
        )
        session.add(user)
        await session.commit()
        return user.id


async def test_concurrent_claims_are_disjoint(db, fake_clock):
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()
    async with db() as session:
        for i in range(5):
            _, created = await create_trigger(
                session,
                user_id=user_id,
                kind="reminder",
                key=f"r-{i}",
                fire_at=now,
                tz="Asia/Shanghai",
                payload={"note": f"n{i}"},
                clock=fake_clock,
            )
            assert created
        await session.commit()

    async def claim_all(limit: int) -> list:
        async with db() as session:
            rows = await claim_due_triggers(session, now=now, limit=limit)
            await session.commit()
            return [r.id for r in rows]

    # 两个并发领取方：总领取数等于 5，且互不重叠
    ids_a, ids_b = await asyncio.gather(claim_all(5), claim_all(5))
    assert len(ids_a) + len(ids_b) == 5
    assert set(ids_a).isdisjoint(ids_b)


async def test_claim_only_takes_due_and_pending(db, fake_clock):
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()
    async with db() as session:
        due, _ = await create_trigger(
            session, user_id=user_id, kind="reminder", key="due-1", fire_at=now,
            tz="Asia/Shanghai", payload={}, clock=fake_clock,
        )
        future, _ = await create_trigger(
            session, user_id=user_id, kind="reminder", key="future-1",
            fire_at=now.replace(hour=23), tz="Asia/Shanghai", payload={}, clock=fake_clock,
        )
        fired, _ = await create_trigger(
            session, user_id=user_id, kind="reminder", key="fired-1", fire_at=now,
            tz="Asia/Shanghai", payload={}, clock=fake_clock,
        )
        fired.status = "fired"
        await session.commit()
        due_id, future_id, fired_id = due.id, future.id, fired.id

    async with db() as session:
        claimed = await claim_due_triggers(session, now=now, limit=10)
        await session.commit()
    claimed_ids = {t.id for t in claimed}
    assert due_id in claimed_ids
    assert future_id not in claimed_ids
    assert fired_id not in claimed_ids


async def test_claim_skips_backoff_wait_and_exhausted(db, fake_clock):
    """退避等待中的、以及次数耗尽的 pending，都不会被领取。"""
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()
    async with db() as session:
        waiting, _ = await create_trigger(
            session, user_id=user_id, kind="reminder", key="wait-1", fire_at=now,
            tz="Asia/Shanghai", payload={}, clock=fake_clock,
        )
        waiting.next_attempt_at = now.replace(hour=23)
        exhausted, _ = await create_trigger(
            session, user_id=user_id, kind="reminder", key="ex-1", fire_at=now,
            tz="Asia/Shanghai", payload={}, clock=fake_clock,
        )
        exhausted.attempts = 5
        await session.commit()
        waiting_id, exhausted_id = waiting.id, exhausted.id

    async with db() as session:
        claimed = await claim_due_triggers(session, now=now, limit=10)
        await session.commit()
    claimed_ids = {t.id for t in claimed}
    assert waiting_id not in claimed_ids
    assert exhausted_id not in claimed_ids
