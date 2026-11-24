"""阶段 3b：pending 记忆的确认/拒绝状态机。"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select

from app.db.models import Memory, MemoryDecisionLog, User
from app.memory.confirm import PendingMemoryNotFound, decide_pending_memory


async def _seed_user(db, clock) -> uuid.UUID:
    async with db() as session:
        user = User(
            display_name="记忆用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        session.add(user)
        await session.commit()
        return user.id


async def _seed_pair(
    db,
    clock,
    user_id: uuid.UUID,
    *,
    old_status: str = "active",
    old_weight: float = 0.8,
    old_source: str = "stated",
) -> tuple[uuid.UUID, uuid.UUID]:
    async with db() as session:
        old = Memory(
            user_id=user_id,
            type="slot",
            slot_key="wake",
            subject="起床时间",
            value={"text": "7点", "time": "07:00"},
            scope={"kind": "persistent"},
            source_class=old_source,
            weight=old_weight,
            confidence=0.9,
            status=old_status,
            recorded_at=clock.now(),
            support_days=1,
            contradict_count=0,
        )
        session.add(old)
        await session.flush()
        pending = Memory(
            user_id=user_id,
            type="slot",
            slot_key="wake",
            subject="起床时间",
            value={"text": "8点", "time": "08:00"},
            scope={"kind": "persistent"},
            source_class=old_source,
            weight=old_weight,
            confidence=0.9,
            status="pending",
            supersedes_id=old.id,
            recorded_at=clock.now(),
            support_days=1,
            contradict_count=0,
        )
        session.add(pending)
        await session.commit()
        return old.id, pending.id


async def _decide(db, clock, user_id, pending_id, *, confirm: bool) -> str:
    async with db() as session:
        user = await session.get(User, user_id)
        assert user is not None
        result = await decide_pending_memory(
            session,
            user=user,
            pending_id=pending_id,
            confirm=confirm,
            clock=clock,
        )
        await session.commit()
        return result


async def test_confirm_upgrades_pending_and_supersedes_old(
    db, fake_clock
) -> None:
    user_id = await _seed_user(db, fake_clock)
    old_id, pending_id = await _seed_pair(db, fake_clock, user_id)

    assert await _decide(db, fake_clock, user_id, pending_id, confirm=True) == "confirmed"

    async with db() as session:
        old = await session.get(Memory, old_id)
        pending = await session.get(Memory, pending_id)
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert old is not None and old.status == "superseded"
    assert old.superseded_at is not None
    assert pending is not None
    assert pending.status == "active"
    assert pending.source_class == "confirmed"
    assert pending.weight == 1.0
    assert [(log.action, log.reason) for log in logs] == [
        ("SUPERSEDE", "user_confirmed")
    ]
    assert logs[0].memory_id == pending_id


async def test_reject_retracts_pending_and_keeps_old(db, fake_clock) -> None:
    user_id = await _seed_user(db, fake_clock)
    old_id, pending_id = await _seed_pair(db, fake_clock, user_id)

    assert await _decide(db, fake_clock, user_id, pending_id, confirm=False) == "rejected"

    async with db() as session:
        old = await session.get(Memory, old_id)
        pending = await session.get(Memory, pending_id)
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert old is not None
    assert old.status == "active"
    assert old.weight == 0.8
    assert pending is not None
    assert pending.status == "retracted"
    assert pending.rejected_at is not None
    assert [(log.action, log.reason) for log in logs] == [("NOOP", "user_rejected")]


async def test_repeat_actions_are_idempotent(db, fake_clock) -> None:
    user_id = await _seed_user(db, fake_clock)
    old_id, pending_id = await _seed_pair(db, fake_clock, user_id)

    assert await _decide(db, fake_clock, user_id, pending_id, confirm=True) == "confirmed"
    assert await _decide(db, fake_clock, user_id, pending_id, confirm=True) == "confirmed"
    assert await _decide(db, fake_clock, user_id, pending_id, confirm=False) == "confirmed"

    async with db() as session:
        old = await session.get(Memory, old_id)
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert old is not None and old.status == "superseded"
    assert len(logs) == 1


async def test_confirm_with_stale_target_retracts_pending(db, fake_clock) -> None:
    user_id = await _seed_user(db, fake_clock)
    old_id, pending_id = await _seed_pair(
        db, fake_clock, user_id, old_status="superseded"
    )

    assert await _decide(db, fake_clock, user_id, pending_id, confirm=True) == "rejected"

    async with db() as session:
        old = await session.get(Memory, old_id)
        pending = await session.get(Memory, pending_id)
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert old is not None and old.status == "superseded"
    assert pending is not None
    assert pending.status == "retracted"
    assert [(log.action, log.reason) for log in logs] == [("NOOP", "stale_target")]


async def test_confirm_retracts_sibling_pending(db, fake_clock) -> None:
    user_id = await _seed_user(db, fake_clock)
    old_id, pending_id = await _seed_pair(db, fake_clock, user_id)
    async with db() as session:
        sibling = Memory(
            user_id=user_id,
            type="slot",
            slot_key="wake",
            subject="起床时间",
            value={"text": "9点", "time": "09:00"},
            scope={"kind": "persistent"},
            source_class="stated",
            weight=0.8,
            confidence=0.9,
            status="pending",
            supersedes_id=old_id,
            recorded_at=fake_clock.now(),
            support_days=1,
            contradict_count=0,
        )
        session.add(sibling)
        await session.commit()
        sibling_id = sibling.id

    assert await _decide(db, fake_clock, user_id, pending_id, confirm=True) == "confirmed"

    async with db() as session:
        sibling = await session.get(Memory, sibling_id)
        active = (
            await session.execute(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.status == "active",
                )
            )
        ).scalars().all()
    assert sibling is not None and sibling.status == "retracted"
    assert len(active) == 1
    assert active[0].id == pending_id


async def test_unknown_or_foreign_pending_is_not_found(db, fake_clock) -> None:
    user_id = await _seed_user(db, fake_clock)
    _, pending_id = await _seed_pair(db, fake_clock, user_id)
    async with db() as session:
        stranger = User(display_name="别人", timezone="Asia/Shanghai")
        session.add(stranger)
        await session.commit()
        stranger_id = stranger.id

    with pytest.raises(PendingMemoryNotFound):
        await _decide(db, fake_clock, stranger_id, pending_id, confirm=True)
