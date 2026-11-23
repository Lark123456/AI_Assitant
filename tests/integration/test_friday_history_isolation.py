"""U2-A2：Friday 短期上下文按渠道隔离（手机/飞书/Console 互不可见）。"""

import datetime as dt

from app.adapters.base import InboundEvent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.agents.friday.history import build_history
from app.db.models import ChannelIdentity, User
from app.engine.events import append_event
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, Usage
from tests.conftest import TEST_ALIASES, FakeProvider


async def _seed_user(db, clock) -> User:
    async with db() as session:
        user = User(
            display_name="隔离测试用户",
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
                external_id="ou_isolation",
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        await session.commit()
        return user


async def _seed_message(
    db,
    clock,
    *,
    user_id,
    channel: str,
    direction: str,
    text: str,
    minutes_ago: int,
    type: str = "message",
) -> None:
    async with db() as session:
        await append_event(
            session,
            user_id=user_id,
            channel=channel,
            direction=direction,
            type=type,
            payload={"text": text},
            trace_id="t-isolation",
            clock=clock,
            occurred_at=clock.now() - dt.timedelta(minutes=minutes_ago),
        )
        await session.commit()


async def test_build_history_is_isolated_by_channel(db, fake_clock):
    user = await _seed_user(db, fake_clock)
    for channel, direction, text, minutes in (
        ("mobile", "inbound", "手机说的话", 4),
        ("mobile", "outbound", "手机回复", 3),
        ("feishu", "inbound", "飞书说的话", 2),
        ("feishu", "outbound", "飞书回复", 1),
        ("console", "inbound", "控制台说的话", 0),
    ):
        await _seed_message(
            db,
            fake_clock,
            user_id=user.id,
            channel=channel,
            direction=direction,
            text=text,
            minutes_ago=minutes,
        )

    async with db() as session:
        mobile = await build_history(
            session,
            user_id=user.id,
            channel="mobile",
            exclude_event_id=None,
            clock=fake_clock,
        )
        feishu = await build_history(
            session,
            user_id=user.id,
            channel="feishu",
            exclude_event_id=None,
            clock=fake_clock,
        )
        console = await build_history(
            session,
            user_id=user.id,
            channel="console",
            exclude_event_id=None,
            clock=fake_clock,
        )

    assert [message["content"] for message in mobile] == ["手机说的话", "手机回复"]
    assert [message["content"] for message in feishu] == ["飞书说的话", "飞书回复"]
    assert [message["content"] for message in console] == ["控制台说的话"]
    assert [message["role"] for message in mobile] == ["user", "assistant"]


async def test_mobile_agent_does_not_see_feishu_history(db, fake_clock, settings):
    """端到端：手机消息触发 Friday 时，发给模型的上下文不含飞书对话。"""
    user = await _seed_user(db, fake_clock)
    await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        channel="feishu",
        direction="inbound",
        text="飞书说的话",
        minutes_ago=5,
    )
    await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        channel="feishu",
        direction="outbound",
        text="飞书回复",
        minutes_ago=4,
    )
    await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        channel="mobile",
        direction="inbound",
        text="手机历史消息",
        minutes_ago=3,
    )
    await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        channel="mobile",
        direction="outbound",
        text="手机历史回复",
        minutes_ago=2,
    )

    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content="好的", usage=Usage(input=1, cached=0, output=1, reasoning=0))

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
        InboundEvent(
            channel="mobile",
            external_user_id=str(user.id),
            kind="message",
            text="现在几点",
            idempotency_key=f"mobile-chat:{user.id}:c1",
        ),
        user,
        client_message_id="c1",
    )
    await pipeline.process(ingested)

    assert provider.calls, "Friday 应当调用模型"
    contents = "\n".join(
        str(message.get("content", "")) for message in provider.calls[0]
    )
    assert "现在几点" in contents
    assert "手机历史消息" in contents
    assert "手机历史回复" in contents
    assert "飞书说的话" not in contents
    assert "飞书回复" not in contents
