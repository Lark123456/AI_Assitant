"""阶段 3b：手机 remember 冲突时在同一事务写确认卡片，且恢复不重复。"""

import datetime as dt

from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.models import EventLog, InboundProcessing, Memory, User
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, ToolCall
from tests.conftest import TEST_ALIASES, FakeProvider


async def _seed_user(db, clock: FakeClock) -> User:
    async with db() as session:
        user = User(
            display_name="记忆卡用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        session.add(user)
        await session.flush()
        session.add(
            Memory(
                user_id=user.id,
                type="slot",
                slot_key="wake",
                subject="起床时间",
                value={"text": "7点", "time": "07:00"},
                scope={"kind": "persistent"},
                source_class="stated",
                weight=0.8,
                confidence=0.9,
                status="active",
                recorded_at=clock.now(),
                support_days=1,
                contradict_count=0,
            )
        )
        await session.commit()
        return user


def _mobile_event(user: User) -> InboundEvent:
    return InboundEvent(
        channel="mobile",
        external_user_id=str(user.id),
        kind="message",
        text="我现在8点起床",
        idempotency_key=f"mobile-chat:{user.id}:c1",
    )


def _responder(messages: list[dict]) -> LLMResult:
    if any(message.get("role") == "tool" for message in messages):
        return LLMResult(content="已有记录，要替换吗？")
    return LLMResult(
        content="",
        tool_calls=[
            ToolCall(
                id="call-1",
                name="remember",
                arguments={
                    "type": "slot",
                    "slot_key": "wake",
                    "subject": "起床时间",
                    "value": "8点",
                    "evidence_quote": "我现在8点起床",
                },
            )
        ],
    )


def _pipeline(db, clock: FakeClock, settings: Settings) -> InboundPipeline:
    provider = FakeProvider(_responder)
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": provider},
        sessionmaker=db,
        clock=clock,
        daily_limit=0,
    )
    return InboundPipeline(
        sessionmaker=db,
        clock=clock,
        settings=settings,
        gateway=gateway,
        adapters={"mobile": MobileAdapter(make_identity_resolver(db, "mobile"))},
    )


async def test_remember_conflict_writes_card_in_same_transaction(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline = _pipeline(db, fake_clock, settings)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user), user, client_message_id="c1"
    )

    await pipeline.process(ingested)

    async with db() as session:
        reply = (
            await session.execute(
                select(EventLog).where(
                    EventLog.direction == "outbound",
                    EventLog.type == "message",
                )
            )
        ).scalar_one()
        card = (
            await session.execute(
                select(EventLog).where(
                    EventLog.direction == "outbound",
                    EventLog.type == "card",
                )
            )
        ).scalar_one()
        pending = (
            await session.execute(
                select(Memory).where(Memory.status == "pending")
            )
        ).scalar_one()

    assert reply.payload["text"] == "已有记录，要替换吗？"
    assert card.payload["card_type"] == "memory_confirm"
    assert card.payload["items"] == [
        {
            "item_id": str(pending.id),
            "label": "起床时间：8点（原 7点）",
        }
    ]
    assert card.occurred_at > reply.occurred_at
    assert card.idempotency_key == f"mobile-card:{ingested.event_id}:{pending.id}"


async def test_recovery_does_not_duplicate_card(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline = _pipeline(db, fake_clock, settings)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user), user, client_message_id="c1"
    )
    await pipeline.process(ingested)

    async with db() as session:
        row = await session.get(InboundProcessing, ingested.event_id)
        assert row is not None
        row.status = "processing"
        await session.commit()

    assert await pipeline.recover_unfinished() == 1

    async with db() as session:
        cards = (
            await session.execute(
                select(EventLog).where(EventLog.type == "card")
            )
        ).scalars().all()
        replies = (
            await session.execute(
                select(EventLog).where(
                    EventLog.direction == "outbound",
                    EventLog.type == "message",
                )
            )
        ).scalars().all()
        pending = (
            await session.execute(
                select(Memory).where(Memory.status == "pending")
            )
        ).scalars().all()
    assert len(cards) == 1
    assert len(replies) == 1
    assert len(pending) == 1
    assert await pipeline.recover_unfinished() == 0


async def test_empty_reply_still_persists_card(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)

    def responder(messages: list[dict]) -> LLMResult:
        if any(message.get("role") == "tool" for message in messages):
            return LLMResult(content="")
        return _responder(messages)

    provider = FakeProvider(responder)
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": provider},
        sessionmaker=db,
        clock=fake_clock,
        daily_limit=0,
    )
    pipeline = InboundPipeline(
        sessionmaker=db,
        clock=fake_clock,
        settings=settings,
        gateway=gateway,
        adapters={"mobile": MobileAdapter(make_identity_resolver(db, "mobile"))},
    )
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user), user, client_message_id="c1"
    )
    await pipeline.process(ingested)

    async with db() as session:
        replies = (
            await session.execute(
                select(EventLog).where(
                    EventLog.direction == "outbound",
                    EventLog.type == "message",
                )
            )
        ).scalars().all()
        cards = (
            await session.execute(
                select(EventLog).where(EventLog.type == "card")
            )
        ).scalars().all()
        processing = await session.get(InboundProcessing, ingested.event_id)
    assert replies == []
    assert len(cards) == 1
    assert processing is not None and processing.status == "done"
