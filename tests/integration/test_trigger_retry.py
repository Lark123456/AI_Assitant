"""trigger 异常退避重试与 failed 终态（需要 Postgres）。

退避序列：30s × 2^(n-1)，上限 5 次尝试；耗尽置 failed 并写 event_log。
"""

import datetime as dt
import uuid

from sqlalchemy import select

from app.adapters.base import OutboundIntent
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.db.models import ChannelIdentity, EventLog, TriggerInstance, User
from app.engine.gate import PassthroughGate
from app.engine.triggers import (
    TRIGGER_BACKOFF_BASE_SECONDS,
    TRIGGER_MAX_ATTEMPTS,
    claim_due_triggers,
    create_trigger,
    trigger_backoff_seconds,
)
from app.worker.runner import process_claimed_trigger


class BrokenAdapter(ConsoleAdapter):
    """发送必炸，用于模拟投递故障。"""

    async def send(self, intent: OutboundIntent):  # type: ignore[override]
        raise RuntimeError("delivery backend down")


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


def _backoff(attempt: int) -> float:
    return TRIGGER_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))


async def test_backoff_schedule_and_failed_terminal_state(db, fake_clock):
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()
    assert TRIGGER_MAX_ATTEMPTS == 5
    assert [trigger_backoff_seconds(n) for n in range(1, 6)] == [30, 60, 120, 240, 480]

    async with db() as session:
        trigger = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-bo",
            fire_at=now, tz="Asia/Shanghai", payload={"note": "退避", "trace_id": "tr-bo"},
            clock=fake_clock,
        )
        await session.commit()
        trigger_id = trigger.id

    adapter = BrokenAdapter(make_identity_resolver(db, "console"))

    for attempt in range(1, TRIGGER_MAX_ATTEMPTS + 1):
        # 到期即可领取（上一轮退避到期后）
        async with db() as session:
            claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
            await session.commit()
        assert len(claimed) == 1, f"attempt {attempt} should be claimable"
        assert claimed[0].attempts == attempt

        failure_at = fake_clock.now()
        ok = await process_claimed_trigger(
            db, trigger_id=trigger_id, adapters={"console": adapter},
            clock=fake_clock, gate=PassthroughGate(),
        )
        assert ok is False  # 发送失败

        async with db() as session:
            row = await session.get(TriggerInstance, trigger_id)
            if attempt < TRIGGER_MAX_ATTEMPTS:
                assert row.status == "pending"
                assert row.next_attempt_at == failure_at + dt.timedelta(
                    seconds=trigger_backoff_seconds(attempt)
                )
                assert row.last_error is not None
            else:
                assert row.status == "failed"
                assert row.last_error is not None
        if attempt < TRIGGER_MAX_ATTEMPTS:
            # 快进到退避到期，领取下一轮
            async with db() as session:
                row = await session.get(TriggerInstance, trigger_id)
                fake_clock.advance_to(row.next_attempt_at)

    # 耗尽后不再被领取
    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert claimed == []

    # failed 写入 event_log
    async with db() as session:
        failed_events = (
            await session.execute(select(EventLog).where(EventLog.type == "trigger"))
        ).scalars().all()
    assert len(failed_events) == 1
    payload = failed_events[0].payload
    assert payload["status"] == "failed"
    assert payload["attempts"] == TRIGGER_MAX_ATTEMPTS
    assert payload["trigger_id"] == str(trigger_id)


async def test_deliver_is_idempotent_across_reprocessing(db, fake_clock):
    """发送幂等（方案 A）：同一 trigger 重复处理不重发，只复用既有 delivery。"""
    user_id = await _make_user(db, fake_clock)
    now = fake_clock.now()

    async with db() as session:
        trigger = await create_trigger(
            session, user_id=user_id, kind="reminder", key="r-idem",
            fire_at=now, tz="Asia/Shanghai", payload={"note": "只发一次", "trace_id": "tr-idem"},
            clock=fake_clock,
        )
        await session.commit()
        trigger_id = trigger.id

    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert len(claimed) == 1

    # 第一次处理成功
    assert await process_claimed_trigger(
        db, trigger_id=trigger_id, adapters={"console": console},
        clock=fake_clock, gate=PassthroughGate(),
    )
    nudges = [m for m in console.messages_for("u1") if m["type"] == "nudge"]
    assert len(nudges) == 1

    # 模拟租约回收后重复处理：不重发
    async with db() as session:
        row = await session.get(TriggerInstance, trigger_id)
        row.status = "claimed"
        row.claimed_at = fake_clock.now()
        await session.commit()
    assert await process_claimed_trigger(
        db, trigger_id=trigger_id, adapters={"console": console},
        clock=fake_clock, gate=PassthroughGate(),
    )
    assert len([m for m in console.messages_for("u1") if m["type"] == "nudge"]) == 1

    # 第二次处理不新增 delivery 行（复用既有已发送 delivery）
    from app.db.models import Delivery

    async with db() as session:
        deliveries = (
            await session.execute(select(Delivery).where(Delivery.sent_at.is_not(None)))
        ).scalars().all()
    assert len(deliveries) == 1
