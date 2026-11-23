"""U2-A1：手机消息使用已认证 User 落库，不 onboarding、不启动 Agent。"""

import datetime as dt

from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.db.models import ChannelIdentity, EventLog, InboundProcessing, User
from app.llm.schemas import LLMResult


def _event(user: User, key: str, text: str = "你好") -> InboundEvent:
    return InboundEvent(
        channel="mobile",
        external_user_id=str(user.id),
        kind="message",
        text=text,
        occurred_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=dt.UTC),
        idempotency_key=f"mobile-chat:{user.id}:{key}",
    )


async def _seed_user(db, clock, external_id: str = "ou_mobile") -> User:
    async with db() as session:
        user = User(
            display_name="手机用户",
            timezone="Asia/Shanghai",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add(user)
        await session.flush()
        session.add(
            ChannelIdentity(
                user_id=user.id,
                channel="feishu",
                external_id=external_id,
                tenant_id="tenant-1",
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        await session.commit()
        return user


async def test_ingest_for_user_reuses_user_and_only_persists(
    db, fake_clock, make_pipeline
):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = make_pipeline(
        lambda messages: LLMResult(content="不应被调用")
    )

    ingested = await pipeline.ingest_for_user(
        _event(user, "c1"), user, client_message_id="c1"
    )

    assert ingested.created is True
    assert ingested.user_id == user.id
    async with db() as session:
        events = (
            await session.execute(select(EventLog).where(EventLog.channel == "mobile"))
        ).scalars().all()
        assert len(events) == 1
        event = events[0]
        assert event.direction == "inbound"
        assert event.type == "message"
        assert event.payload["text"] == "你好"
        assert event.payload["client_message_id"] == "c1"
        processing = await session.get(InboundProcessing, event.id)
        assert processing is not None
        assert processing.status == "processing"
        assert processing.user_id == user.id
        mobile_identity = (
            await session.execute(
                select(ChannelIdentity).where(ChannelIdentity.channel == "mobile")
            )
        ).scalars().all()
        assert mobile_identity == []
        outbound = (
            await session.execute(
                select(EventLog).where(
                    EventLog.direction.in_(("outbound", "tool"))
                )
            )
        ).scalars().all()
        assert outbound == []
        users = (await session.execute(select(User))).scalars().all()
        assert [row.id for row in users] == [user.id]


async def test_ingest_for_user_is_idempotent_and_user_scoped(
    db, fake_clock, make_pipeline
):
    user_a = await _seed_user(db, fake_clock, external_id="ou_a")
    user_b = await _seed_user(db, fake_clock, external_id="ou_b")
    pipeline, _ = make_pipeline(
        lambda messages: LLMResult(content="不应被调用")
    )

    first = await pipeline.ingest_for_user(
        _event(user_a, "same"), user_a, client_message_id="same"
    )
    duplicate = await pipeline.ingest_for_user(
        _event(user_a, "same"), user_a, client_message_id="same"
    )
    other_user = await pipeline.ingest_for_user(
        _event(user_b, "same"), user_b, client_message_id="same"
    )

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.event_id == first.event_id
    assert other_user.created is True
    assert other_user.event_id != first.event_id

    async with db() as session:
        events = (
            await session.execute(select(EventLog).where(EventLog.channel == "mobile"))
        ).scalars().all()
        assert len(events) == 2
        processing_rows = (
            await session.execute(select(InboundProcessing))
        ).scalars().all()
        assert len(processing_rows) == 2
        assert {row.user_id for row in processing_rows} == {user_a.id, user_b.id}
