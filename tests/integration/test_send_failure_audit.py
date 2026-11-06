"""发送失败审计：失败尝试的 decision 与 delivery(error) 先落库，重试后只留一条成功投递。"""

import datetime as dt

from sqlalchemy import select

from app.adapters.base import DeliveryResult, OutboundIntent
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.db.models import ChannelIdentity, Delivery, NudgeDecision, TriggerInstance, User
from app.engine.materializer import get_or_create_prefs
from app.engine.triggers import claim_due_triggers, create_trigger
from app.worker.runner import process_claimed_trigger


class FlakyAdapter(ConsoleAdapter):
    """第一次发送失败，之后恢复。"""

    def __init__(self, resolver) -> None:
        super().__init__(resolver)
        self.attempts = 0

    async def send(self, intent: OutboundIntent) -> DeliveryResult:
        self.attempts += 1
        if self.attempts == 1:
            return DeliveryResult(ok=False, error="boom")
        return await super().send(intent)


async def test_failed_send_audit_survives_retry(db, fake_clock, settings) -> None:
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        session.add(ChannelIdentity(user_id=user.id, channel="console", external_id="u1", rev=1))
        await get_or_create_prefs(session, user.id, fake_clock)
        trigger, _ = await create_trigger(
            session,
            user_id=user.id,
            kind="reminder",
            key="audit-t1",
            fire_at=fake_clock.now(),
            tz="Asia/Shanghai",
            payload={"note": "交报告"},
            expires_at=fake_clock.now() + dt.timedelta(hours=24),
            clock=fake_clock,
        )
        await session.commit()

    adapter = FlakyAdapter(make_identity_resolver(db, "console"))
    async with db() as session:
        claimed = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert len(claimed) == 1
    trigger_id = claimed[0].id

    # 第一次：发送失败。审计（decision + delivery(error)）必须已提交，trigger 回 pending
    processed = await process_claimed_trigger(
        db,
        trigger_id=trigger_id,
        adapters={"console": adapter},
        clock=fake_clock,
        settings=settings,
        gateway=None,
    )
    assert processed is False
    async with db() as session:
        trigger = await session.get(TriggerInstance, trigger_id)
        assert trigger is not None
        assert trigger.status == "pending"
        assert trigger.attempts == 1
        assert trigger.next_attempt_at == fake_clock.now() + dt.timedelta(seconds=30)
        decisions = (await session.execute(select(NudgeDecision))).scalars().all()
        deliveries = (await session.execute(select(Delivery))).scalars().all()
    assert len(decisions) == 1
    assert decisions[0].decision == "send"
    assert len(deliveries) == 1
    assert deliveries[0].sent_at is None
    assert deliveries[0].error == "boom"

    # 第二次：退避后重试成功
    fake_clock.advance(31)
    async with db() as session:
        claimed_again = await claim_due_triggers(session, now=fake_clock.now(), limit=10)
        await session.commit()
    assert len(claimed_again) == 1
    processed_again = await process_claimed_trigger(
        db,
        trigger_id=trigger_id,
        adapters={"console": adapter},
        clock=fake_clock,
        settings=settings,
        gateway=None,
    )
    assert processed_again is True

    async with db() as session:
        trigger = await session.get(TriggerInstance, trigger_id)
        assert trigger is not None and trigger.status == "fired"
        decisions = (await session.execute(select(NudgeDecision))).scalars().all()
        deliveries = (await session.execute(select(Delivery))).scalars().all()
    # 两次尝试各有一条决策；失败投递保留，成功投递恰好一条
    assert len(decisions) == 2
    successes = [d for d in deliveries if d.sent_at is not None]
    failures = [d for d in deliveries if d.sent_at is None]
    assert len(successes) == 1
    assert len(failures) == 1 and failures[0].error == "boom"
    messages = adapter.messages_for("u1")
    assert len(messages) == 1
    assert messages[0]["provider_msg_id"] == successes[0].provider_msg_id
