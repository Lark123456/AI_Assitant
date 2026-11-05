"""停机补偿与租约回收（需要 Postgres）：
- missed 只用于停机错过：到期处理时已过 expires_at → missed，未过 → 补发。
- claimed_at 超过租约的记录被回收：有余量回 pending，次数耗尽置 failed。
"""

import datetime as dt
import uuid

from sqlalchemy import select

from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.db.models import ChannelIdentity, EventLog, TriggerInstance, User
from app.engine.gate import PassthroughGate
from app.engine.triggers import claim_due_triggers, create_trigger, reclaim_expired_leases
from app.worker.runner import process_claimed_trigger


async def _make_user(db, clock) -> uuid.UUID:
    async with db() as session:
        user = User(
            display_name="u", timezone="Asia/Shanghai",
            created_at=clock.now(), updated_at=clock.now(),
        )
        session.add(user)
        await session.flush()
        session.add(ChannelIdentity(
            user_id=user.id, channel="console", external_id="u1",
            created_at=clock.now(), updated_at=clock.now(),
        ))
        await session.commit()
        return user.id


async def _run_due(db, fake_clock, adapters):
    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    for trigger in claimed:
        await process_claimed_trigger(
            db, trigger_id=trigger.id, adapters=adapters, clock=fake_clock, gate=PassthroughGate()
        )
    return claimed


async def test_downtime_fires_unexpired_and_misses_expired(db, fake_clock):
    """停机期间错过的 trigger：未过 expires_at 的补发，已过的标记 missed。"""
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()

    async with db() as session:
        fresh = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-fresh",
            fire_at=now - dt.timedelta(minutes=5),
            tz="Asia/Shanghai", payload={"note": "补发我", "trace_id": "tr-recover"},
            expires_at=now + dt.timedelta(minutes=30),
            clock=fake_clock,
        )
        stale = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-stale",
            fire_at=now - dt.timedelta(hours=3),
            tz="Asia/Shanghai", payload={"note": "错过我", "trace_id": "tr-recover"},
            expires_at=now - dt.timedelta(minutes=1),
            clock=fake_clock,
        )
        await session.commit()
        fresh_id, stale_id = fresh.id, stale.id

    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    claimed = await _run_due(db, fake_clock, {"console": console})
    assert len(claimed) == 2

    async with db() as session:
        rows = {
            r.id: r.status
            for r in (await session.execute(select(TriggerInstance))).scalars().all()
        }
    assert rows[fresh_id] == "fired"    # 未过 expires_at：补发
    assert rows[stale_id] == "missed"   # 已过 expires_at：标记 missed

    # 补发的内容真的送到了 Console
    nudges = [m for m in console.messages_for("u1") if m["type"] == "nudge"]
    assert len(nudges) == 1
    assert nudges[0]["body"]["text"] == "补发我"

    # missed 与补发都写入了 event_log
    async with db() as session:
        trigger_events = (
            await session.execute(select(EventLog).where(EventLog.type == "trigger"))
        ).scalars().all()
        statuses = sorted(e.payload["status"] for e in trigger_events)
        assert statuses == ["missed"]
        delivery_events = (
            await session.execute(select(EventLog).where(EventLog.type == "delivery"))
        ).scalars().all()
    assert len(delivery_events) == 1


async def test_lease_reclaim_repends_stale_claimed(db, fake_clock):
    """租约超时回收：claimed_at 过期 → 回 pending（可再次领取，attempts 递增）。"""
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()

    async with db() as session:
        trigger = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-lease",
            fire_at=now, tz="Asia/Shanghai", payload={"note": "租约"},
            clock=fake_clock,
        )
        await session.commit()
        trigger_id = trigger.id

    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert len(claimed) == 1

    # 未超租约：不会被回收
    async with db() as session:
        reclaimed = await reclaim_expired_leases(session, now=fake_clock.now(), lease_seconds=300)
        await session.commit()
    assert reclaimed == []

    # 超过租约：回收回 pending，可再次领取
    fake_clock.advance(301)
    async with db() as session:
        reclaimed = await reclaim_expired_leases(
            session, now=fake_clock.now(), lease_seconds=300
        )
        await session.commit()
    assert len(reclaimed) == 1
    assert reclaimed[0].status == "pending"
    assert reclaimed[0].last_error == "lease expired"

    async with db() as session:
        claimed_again = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert len(claimed_again) == 1
    async with db() as session:
        row = await session.get(TriggerInstance, trigger_id)
        assert row.attempts == 2
        assert row.status == "claimed"


async def test_lease_reclaim_marks_failed_when_attempts_exhausted(db, fake_clock):
    """回收时重试次数已耗尽：直接置 failed，不再被领取。"""
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()

    async with db() as session:
        trigger = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-exhaust",
            fire_at=now, tz="Asia/Shanghai", payload={"note": "耗尽"},
            clock=fake_clock,
        )
        trigger.attempts = 5
        trigger.status = "claimed"
        trigger.claimed_at = now
        await session.commit()
        trigger_id = trigger.id

    fake_clock.advance(301)
    async with db() as session:
        reclaimed = await reclaim_expired_leases(
            session, now=fake_clock.now(), lease_seconds=300
        )
        await session.commit()
    assert len(reclaimed) == 1
    assert reclaimed[0].status == "failed"

    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert claimed == []
    async with db() as session:
        row = await session.get(TriggerInstance, trigger_id)
        assert row.status == "failed"
