"""手机 Chat API：U2-A1 接收入口 + U2-A2 处理、历史与状态查询。"""

import asyncio
import datetime as dt
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.api.routes.mobile_chat import process_mobile_event
from app.api.routes.mobile_chat import router as chat_router
from app.db.models import ChannelIdentity, EventLog, InboundProcessing, User
from app.engine.events import append_event
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, Usage
from tests.conftest import TEST_ALIASES, FakeProvider


def _app(db, clock, settings, pipeline) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    app.state.pipeline = pipeline
    return app


async def _seed_user(db, clock, external_id: str = "ou_chat") -> User:
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
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
        await session.commit()
        return user


def _mobile_pipeline(
    db, clock, settings, responder
) -> tuple[InboundPipeline, FakeProvider]:
    provider = FakeProvider(responder)
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": provider},
        sessionmaker=db,
        clock=clock,
        daily_limit=0,
    )
    pipeline = InboundPipeline(
        sessionmaker=db,
        clock=clock,
        settings=settings,
        gateway=gateway,
        adapters={"mobile": MobileAdapter(make_identity_resolver(db, "mobile"))},
    )
    return pipeline, provider


def _plain_responder(text: str):
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text, usage=Usage(input=1, cached=0, output=1, reasoning=0))

    return responder


def _headers(user: User, key: str | None = "c1") -> dict[str, str]:
    headers = {"X-Butler-User": str(user.id)}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def _wait_status(
    client: httpx.AsyncClient,
    user: User,
    message_id: str,
    *,
    expected: tuple[str, ...] = ("done", "failed"),
    timeout: float = 10.0,
) -> dict:
    """轮询单条状态接口直到进入终态（后台 process 是独立任务）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        response = await client.get(
            f"/api/mobile/chat/messages/{message_id}",
            headers={"X-Butler-User": str(user.id)},
        )
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        if loop.time() > deadline:
            raise AssertionError(f"message {message_id} stuck at {body['status']}")
        await asyncio.sleep(0.02)


async def _seed_message(
    db,
    clock,
    *,
    user_id,
    text: str,
    offset_min: int,
    direction: str = "inbound",
    channel: str = "mobile",
    type: str = "message",
    client_message_id: str | None = None,
    reply_to_event_id: str | None = None,
    status: str | None = "done",
) -> str:
    """直接写入聊天事件；手机入站同时写处理状态（status=None 表示缺状态行）。"""
    payload: dict = {"text": text}
    if client_message_id is not None:
        payload["client_message_id"] = client_message_id
    if reply_to_event_id is not None:
        payload["delivery"] = "persisted"
        payload["reply_to_event_id"] = reply_to_event_id
    async with db() as session:
        row, _ = await append_event(
            session,
            user_id=user_id,
            channel=channel,
            direction=direction,
            type=type,
            payload=payload,
            trace_id="t-chat",
            clock=clock,
            occurred_at=clock.now() + dt.timedelta(minutes=offset_min),
        )
        if (
            status is not None
            and channel == "mobile"
            and direction == "inbound"
            and type == "message"
        ):
            session.add(
                InboundProcessing(
                    event_id=row.id,
                    user_id=user_id,
                    status=status,
                    updated_at=clock.now(),
                )
            )
        await session.commit()
        return str(row.id)


async def test_send_message_processes_and_is_idempotent(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline, provider = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("收到")
    )
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user),
        )
        message_id = first.json()["id"]
        final = await _wait_status(client, user, message_id)
        duplicate = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user),
        )

    assert first.status_code == 202
    assert first.json()["status"] == "processing"
    assert first.json()["duplicate"] is False
    assert final["status"] == "done"
    assert final["role"] == "user"
    assert final["clientMessageId"] == "c1"

    # 重复请求返回既有事件与当前状态，不再跑 Agent
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == message_id
    assert duplicate.json()["status"] == "done"
    assert len(provider.calls) == 1

    async with db() as session:
        events = (
            await session.execute(
                select(EventLog).where(
                    EventLog.channel == "mobile", EventLog.type == "message"
                )
            )
        ).scalars().all()
    assert len(events) == 2
    inbound = next(event for event in events if event.direction == "inbound")
    outbound = next(event for event in events if event.direction == "outbound")
    assert inbound.payload["client_message_id"] == "c1"
    assert outbound.payload == {
        "text": "收到",
        "delivery": "persisted",
        "reply_to_event_id": str(inbound.id),
        "client_message_id": "c1",
    }


async def test_send_message_validates_header_and_text(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("不应被调用")
    )
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


async def test_send_message_does_not_create_mobile_identity(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("好的")
    )
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c4", "text": "今天做什么"},
            headers=_headers(user, key="c4"),
        )
        await _wait_status(client, user, response.json()["id"])

    assert response.status_code == 202
    async with db() as session:
        identities = (
            await session.execute(select(ChannelIdentity))
        ).scalars().all()
        assert [(row.channel, row.external_id) for row in identities] == [
            ("feishu", "ou_chat")
        ]
        events = (
            await session.execute(
                select(EventLog).where(
                    EventLog.channel == "mobile", EventLog.type == "message"
                )
            )
        ).scalars().all()
        assert {event.direction for event in events} == {"inbound", "outbound"}


async def test_list_messages_returns_latest_page_ascending(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    other = await _seed_user(db, fake_clock, external_id="ou_other")
    pipeline, _ = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("不应被调用")
    )
    app = _app(db, fake_clock, settings, pipeline)

    m1 = await _seed_message(
        db, fake_clock, user_id=user.id, text="m1", offset_min=1, client_message_id="c1"
    )
    r1 = await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="r1",
        offset_min=2,
        direction="outbound",
        reply_to_event_id=m1,
    )
    assert r1 and m1 != r1
    m2 = await _seed_message(
        db, fake_clock, user_id=user.id, text="m2", offset_min=3, client_message_id="c2"
    )
    await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="r2",
        offset_min=4,
        direction="outbound",
        reply_to_event_id=m2,
    )
    m3 = await _seed_message(
        db, fake_clock, user_id=user.id, text="m3", offset_min=5, client_message_id="c3"
    )
    r3 = await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="r3",
        offset_min=6,
        direction="outbound",
        reply_to_event_id=m3,
    )
    # 干扰项：其他渠道、其他类型、其他用户都不得进入聊天历史
    await _seed_message(
        db, fake_clock, user_id=user.id, text="飞书消息", offset_min=6, channel="feishu"
    )
    await _seed_message(
        db, fake_clock, user_id=user.id, text="笔记", offset_min=6, type="note"
    )
    await _seed_message(
        db, fake_clock, user_id=user.id, text="工具", offset_min=6, direction="tool"
    )
    other_message = await _seed_message(
        db, fake_clock, user_id=other.id, text="别人的消息", offset_min=7
    )

    headers = {"X-Butler-User": str(user.id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first_page = await client.get(
            "/api/mobile/chat/messages", params={"limit": 4}, headers=headers
        )
        body = first_page.json()
        after = await client.get(
            "/api/mobile/chat/messages",
            params={"after": body["nextCursor"]},
            headers=headers,
        )
        before = await client.get(
            "/api/mobile/chat/messages",
            params={"before": body["previousCursor"], "limit": 2},
            headers=headers,
        )
        single = await client.get(
            f"/api/mobile/chat/messages/{m3}", headers=headers
        )
        other_user_message = await client.get(
            f"/api/mobile/chat/messages/{other_message}", headers=headers
        )

    assert first_page.status_code == 200
    messages = body["messages"]
    assert [message["text"] for message in messages] == ["m2", "r2", "m3", "r3"]
    assert [message["role"] for message in messages] == [
        "user",
        "friday",
        "user",
        "friday",
    ]
    assert [message["status"] for message in messages] == [
        "done",
        "available",
        "done",
        "available",
    ]
    assert messages[0]["clientMessageId"] == "c2"
    assert messages[1]["replyToId"] == m2
    assert messages[1]["clientMessageId"] is None
    assert body["hasMore"] is True
    assert body["previousCursor"] == m2
    assert body["nextCursor"] == r3

    assert after.json()["messages"] == []
    assert after.json()["hasMore"] is False

    older = before.json()
    assert [message["text"] for message in older["messages"]] == ["m1", "r1"]
    assert older["hasMore"] is False

    assert single.status_code == 200
    assert single.json()["text"] == "m3"
    assert single.json()["status"] == "done"
    assert other_user_message.status_code == 404


async def test_get_message_status_reflects_processing_and_failure(
    db, fake_clock, settings
):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("不应被调用")
    )
    app = _app(db, fake_clock, settings, pipeline)

    processing_id = await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="处理中",
        offset_min=1,
        status="processing",
    )
    missing_row_id = await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="没有状态行",
        offset_min=2,
        status=None,
    )
    # 模拟处理失败
    async with db() as session:
        row = await session.get(InboundProcessing, uuid.UUID(processing_id))
        assert row is not None
        row.status = "failed"
        await session.commit()

    headers = {"X-Butler-User": str(user.id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        failed = await client.get(
            f"/api/mobile/chat/messages/{processing_id}", headers=headers
        )
        missing = await client.get(
            f"/api/mobile/chat/messages/{missing_row_id}", headers=headers
        )
        bad_id = await client.get(
            "/api/mobile/chat/messages/not-a-uuid", headers=headers
        )

    assert failed.json()["status"] == "failed"
    assert missing.json()["status"] == "failed"
    assert bad_id.status_code == 404


async def test_list_messages_validates_limit_and_cursor(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    pipeline, _ = _mobile_pipeline(
        db, fake_clock, settings, _plain_responder("不应被调用")
    )
    app = _app(db, fake_clock, settings, pipeline)
    feishu_id = await _seed_message(
        db,
        fake_clock,
        user_id=user.id,
        text="飞书消息",
        offset_min=1,
        channel="feishu",
    )
    mobile_id = await _seed_message(
        db, fake_clock, user_id=user.id, text="手机消息", offset_min=2
    )

    headers = {"X-Butler-User": str(user.id)}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        zero = await client.get(
            "/api/mobile/chat/messages", params={"limit": 0}, headers=headers
        )
        overflow = await client.get(
            "/api/mobile/chat/messages", params={"limit": 101}, headers=headers
        )
        both = await client.get(
            "/api/mobile/chat/messages",
            params={"after": mobile_id, "before": mobile_id},
            headers=headers,
        )
        invalid = await client.get(
            "/api/mobile/chat/messages", params={"after": "nope"}, headers=headers
        )
        cross_channel = await client.get(
            "/api/mobile/chat/messages", params={"after": feishu_id}, headers=headers
        )

    assert zero.status_code == 400
    assert overflow.status_code == 400
    assert both.status_code == 400
    assert invalid.status_code == 400
    assert cross_channel.status_code == 400


async def test_process_mobile_event_serializes_same_user():
    """同一用户的处理串行执行（进程内锁）；不同用户互不阻塞由各自锁保证。"""
    active = 0
    max_active = 0

    class _Pipeline:
        async def process(self, ingested) -> None:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1

    lock = asyncio.Lock()
    pipeline = _Pipeline()
    await asyncio.gather(
        process_mobile_event(pipeline, lock, None),
        process_mobile_event(pipeline, lock, None),
        process_mobile_event(pipeline, lock, None),
    )

    assert max_active == 1
