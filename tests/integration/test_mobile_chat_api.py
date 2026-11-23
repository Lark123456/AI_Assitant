"""U2-A1：手机 Chat POST 接收入口。

本批只验证落库、幂等、权限和 header 规则；不启动 Agent、不产生 outbound。
"""

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.api.routes.mobile_chat import router as chat_router
from app.db.models import ChannelIdentity, EventLog, InboundProcessing, User
from app.llm.schemas import LLMResult


def _app(db, clock, settings, pipeline) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    app.state.pipeline = pipeline
    return app


async def _seed_user(db, clock) -> User:
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
                external_id="ou_chat",
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        await session.commit()
        return user


def _headers(user: User, key: str | None = "c1") -> dict[str, str]:
    headers = {"X-Butler-User": str(user.id)}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def test_send_message_persists_and_is_idempotent(db, fake_clock, settings, make_pipeline):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = make_pipeline(lambda messages: LLMResult(content="不应被调用"))
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user),
        )
        duplicate = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user),
        )

    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert first.json()["duplicate"] is False
    assert duplicate.json()["duplicate"] is True
    assert first.json()["id"] == duplicate.json()["id"]
    assert first.json()["status"] == "processing"
    assert duplicate.json()["status"] == "processing"

    async with db() as session:
        events = (
            await session.execute(select(EventLog).where(EventLog.channel == "mobile"))
        ).scalars().all()
        assert len(events) == 1
        assert events[0].payload["client_message_id"] == "c1"
        assert events[0].payload["text"] == "你好"
        processing = await session.get(InboundProcessing, events[0].id)
        assert processing is not None and processing.status == "processing"
        outbound_or_tool = (
            await session.execute(
                select(EventLog).where(EventLog.direction.in_(("outbound", "tool")))
            )
        ).scalars().all()
        assert outbound_or_tool == []


async def test_send_message_validates_header_and_text(db, fake_clock, settings, make_pipeline):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = make_pipeline(lambda messages: LLMResult(content="不应被调用"))
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        mismatch = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers={**_headers(user, key="other")},
        )
        empty = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c2", "text": "   "},
            headers=_headers(user, key="c2"),
        )
        missing_user = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c3", "text": "你好"},
        )

    assert mismatch.status_code == 400
    assert empty.status_code == 400
    assert missing_user.status_code == 401


async def test_send_message_does_not_create_mobile_identity(db, fake_clock, settings, make_pipeline):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = make_pipeline(lambda messages: LLMResult(content="不应被调用"))
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c4", "text": "今天做什么"},
            headers=_headers(user, key="c4"),
        )

    assert response.status_code == 202
    async with db() as session:
        identities = (
            await session.execute(select(ChannelIdentity))
        ).scalars().all()
        assert [(row.channel, row.external_id) for row in identities] == [
            ("feishu", "ou_chat")
        ]
        events = (
            await session.execute(select(EventLog).where(EventLog.channel == "mobile"))
        ).scalars().all()
        assert len(events) == 1
        assert events[0].occurred_at is not None
