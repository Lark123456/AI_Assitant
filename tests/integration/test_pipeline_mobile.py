"""手机渠道处理：U2-A1 落库 + U2-A2 安全完成路径与恢复隔离。"""

import datetime as dt
import uuid
from collections.abc import Callable

from sqlalchemy import select

from app.adapters.base import InboundEvent, OutboundIntent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.db.models import ChannelIdentity, EventLog, InboundProcessing, User
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, Usage
from tests.conftest import TEST_ALIASES, FakeProvider


def _plain_responder(text: str) -> Callable[[list[dict]], LLMResult]:
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text, usage=Usage(input=1, cached=0, output=1, reasoning=0))

    return responder


def _make_mobile_pipeline(db, fake_clock, settings, responder) -> InboundPipeline:
    """只注册 mobile adapter 的管道：recovery 只接手手机事件。"""
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": FakeProvider(responder)},
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
    return pipeline


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


async def test_mobile_adapter_send_is_noop(db, fake_clock):
    """MobileAdapter 只声明成功：不发送、不写 event_log（outbound 只由 Pipeline 写）。"""
    adapter = MobileAdapter(make_identity_resolver(db, "mobile"))
    assert adapter.channel == "mobile"
    assert adapter.capabilities.can_push_unsolicited is False
    assert adapter.capabilities.streaming is False

    result = await adapter.send(
        OutboundIntent(type="text", user_id=uuid.uuid4(), body={"text": "hi"})
    )

    assert result.ok is True
    async with db() as session:
        events = (await session.execute(select(EventLog))).scalars().all()
    assert events == []


async def test_process_mobile_persists_single_reply_and_done(db, fake_clock, settings):
    """手机回复与 done 同事务；payload 为 persisted，无 send_ok；重放不重复回复。"""
    user = await _seed_user(db, fake_clock)
    pipeline = _make_mobile_pipeline(db, fake_clock, settings, _plain_responder("收到"))

    ingested = await pipeline.ingest_for_user(
        _event(user, "c1"), user, client_message_id="c1"
    )
    await pipeline.process(ingested)

    async with db() as session:
        outbound_rows = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
        assert len(outbound_rows) == 1
        outbound = outbound_rows[0]
        assert outbound.channel == "mobile"
        assert outbound.type == "message"
        assert outbound.payload == {
            "text": "收到",
            "delivery": "persisted",
            "reply_to_event_id": str(ingested.event_id),
            "client_message_id": "c1",
        }
        processing = await session.get(InboundProcessing, ingested.event_id)
        assert processing is not None and processing.status == "done"

    # 模拟“提交后崩溃、状态被拨回 processing”的 recovery 重放：回复仍只有一条
    async with db() as session:
        row = await session.get(InboundProcessing, ingested.event_id)
        assert row is not None
        row.status = "processing"
        await session.commit()
    await pipeline.process(ingested)

    async with db() as session:
        outbound_rows = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
        processing = await session.get(InboundProcessing, ingested.event_id)
    assert len(outbound_rows) == 1
    assert processing is not None and processing.status == "done"


async def test_process_mobile_agent_failure_writes_single_fallback(
    db, fake_clock, settings
):
    """Agent 异常：回滚半途写入后仍落库一条兜底回复并置 done。"""

    def boom(messages: list[dict]) -> LLMResult:
        raise RuntimeError("llm down")

    user = await _seed_user(db, fake_clock)
    pipeline = _make_mobile_pipeline(db, fake_clock, settings, boom)
    ingested = await pipeline.ingest_for_user(
        _event(user, "c1"), user, client_message_id="c1"
    )

    await pipeline.process(ingested)

    async with db() as session:
        outbound_rows = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
        assert len(outbound_rows) == 1
        payload = outbound_rows[0].payload
        assert "抱歉" in payload["text"]
        assert payload["delivery"] == "persisted"
        assert payload["client_message_id"] == "c1"
        assert "send_ok" not in payload
        processing = await session.get(InboundProcessing, ingested.event_id)
        assert processing is not None and processing.status == "done"


async def test_mobile_recovery_only_in_service_with_mobile_adapter(
    db, fake_clock, settings, make_pipeline
):
    """未注册 mobile adapter 的服务跳过手机事件；注册后才补处理。"""
    user = await _seed_user(db, fake_clock)
    console_pipeline, _ = make_pipeline(_plain_responder("不应被调用"))
    ingested = await console_pipeline.ingest_for_user(
        _event(user, "c1"), user, client_message_id="c1"
    )

    # 模拟崩溃：只落库未处理。Feishu/Console 服务没有 mobile adapter，不能接手
    assert await console_pipeline.recover_unfinished() == 0
    async with db() as session:
        processing = await session.get(InboundProcessing, ingested.event_id)
        outbound_rows = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
    assert processing is not None and processing.status == "processing"
    assert outbound_rows == []

    # API 服务注册了 mobile adapter，启动补处理应接手
    mobile_pipeline = _make_mobile_pipeline(
        db, fake_clock, settings, _plain_responder("补处理回复")
    )
    assert await mobile_pipeline.recover_unfinished() == 1

    async with db() as session:
        processing = await session.get(InboundProcessing, ingested.event_id)
        outbound_rows = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
    assert processing is not None and processing.status == "done"
    assert len(outbound_rows) == 1
    # recovery 从入站 payload 还原 client_message_id
    assert outbound_rows[0].payload["client_message_id"] == "c1"
    assert await mobile_pipeline.recover_unfinished() == 0
