"""U2-A5：手机聊天可靠性与整体验收（崩溃、并发、多用户、开关与记忆写入）。"""

import asyncio
import datetime as dt
import uuid

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.api.routes.mobile_chat import process_mobile_event
from app.api.routes.mobile_chat import router as chat_router
from app.core.clock import FakeClock
from app.core.config import Settings, get_settings
from app.db.models import (
    ChannelIdentity,
    EventLog,
    InboundProcessing,
    MemoryExtractionRun,
    User,
    WorkItem,
)
from app.engine.events import append_event
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, ToolCall
from app.memory.runs import schedule_runs
from tests.conftest import TEST_ALIASES, FakeProvider


async def _seed_user(
    db,
    clock: FakeClock,
    external_id: str = "ou_a5",
    *,
    event_channel: str = "console",
) -> tuple[User, uuid.UUID]:
    """用户 + 一条较早的入站消息（默认 Console，避免污染手机聊天历史）。"""
    async with db() as session:
        user = User(
            display_name="A5 用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        session.add(user)
        await session.flush()
        session.add(
            ChannelIdentity(user_id=user.id, channel="feishu", external_id=external_id)
        )
        event = EventLog(
            user_id=user.id,
            channel=event_channel,
            direction="inbound",
            type="message",
            payload={"text": "test"},
            trace_id="a5-test",
            occurred_at=clock.now() - dt.timedelta(minutes=30),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        return user, event.id


def _mobile_event(user: User, key: str, text: str = "你好") -> InboundEvent:
    return InboundEvent(
        channel="mobile",
        external_user_id=str(user.id),
        kind="message",
        text=text,
        idempotency_key=f"mobile-chat:{user.id}:{key}",
    )


def _plain_responder(text: str):
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text)

    return responder


def _make_pipeline(db, clock: FakeClock, settings: Settings, responder):
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


def _app(db, clock: FakeClock, settings: Settings, pipeline) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    app.state.pipeline = pipeline
    return app


def _headers(user: User, key: str) -> dict[str, str]:
    return {"X-Butler-User": str(user.id), "Idempotency-Key": key}


async def _wait_status(
    client: httpx.AsyncClient,
    user: User,
    message_id: str,
    *,
    expected: tuple[str, ...] = ("done", "failed"),
    timeout: float = 10.0,
) -> dict:
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


async def test_crash_before_outbound_rolls_back_tools_and_recovery(
    db, fake_clock, settings, monkeypatch
):
    """Agent 工具写入随 outbound 一起回滚；恢复重跑不产生重复任务或第二条回复。"""
    user, _ = await _seed_user(db, fake_clock)

    def responder(messages: list[dict]) -> LLMResult:
        if any(message.get("role") == "tool" for message in messages):
            return LLMResult(content="记好了")
        return LLMResult(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="create_task", arguments={"title": "写周报"})
            ],
        )

    pipeline, _ = _make_pipeline(db, fake_clock, settings, responder)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user, "c1"), user, client_message_id="c1"
    )

    async def crash_before_outbound(session, ingested_event, reply):
        raise RuntimeError("crash before outbound commit")

    monkeypatch.setattr(pipeline, "_append_mobile_reply", crash_before_outbound)
    await pipeline.process(ingested)

    async with db() as session:
        processing = await session.get(InboundProcessing, ingested.event_id)
        items = (await session.execute(select(WorkItem))).scalars().all()
        outbound = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
    assert processing is not None and processing.status == "failed"
    assert items == []  # 工具写入未提交
    assert outbound == []

    # 恢复条件：状态回到 processing 后由 API 进程补处理
    monkeypatch.undo()
    async with db() as session:
        row = await session.get(InboundProcessing, ingested.event_id)
        assert row is not None
        row.status = "processing"
        await session.commit()

    assert await pipeline.recover_unfinished() == 1

    async with db() as session:
        processing = await session.get(InboundProcessing, ingested.event_id)
        items = (await session.execute(select(WorkItem))).scalars().all()
        outbound = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()
        contexts = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_context")
            )
        ).scalars().all()
    assert processing is not None and processing.status == "done"
    assert len(items) == 1
    assert items[0].title == "写周报"
    assert len(outbound) == 1
    assert outbound[0].channel == "mobile"
    assert outbound[0].user_id == user.id
    assert await pipeline.recover_unfinished() == 0
    # MEMORY_INJECT_ENABLED 默认关闭：手机 Agent 不注入长期记忆
    assert contexts
    assert all(context.payload["enabled"] is False for context in contexts)


async def test_concurrent_same_client_message_id_single_execution(
    db, fake_clock, settings
):
    user, _ = await _seed_user(db, fake_clock)
    pipeline, provider = _make_pipeline(
        db, fake_clock, settings, _plain_responder("收到")
    )
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first, second = await asyncio.gather(
            client.post(
                "/api/mobile/chat/messages",
                json={"clientMessageId": "same", "text": "你好"},
                headers=_headers(user, "same"),
            ),
            client.post(
                "/api/mobile/chat/messages",
                json={"clientMessageId": "same", "text": "你好"},
                headers=_headers(user, "same"),
            ),
        )
        ids = {first.json()["id"], second.json()["id"]}
        assert len(ids) == 1
        final = await _wait_status(client, user, next(iter(ids)))

    assert sorted([first.status_code, second.status_code]) == [200, 202]
    assert final["status"] == "done"
    assert len(provider.calls) == 1

    async with db() as session:
        inbound = (
            await session.execute(
                select(EventLog).where(
                    EventLog.channel == "mobile",
                    EventLog.type == "message",
                    EventLog.direction == "inbound",
                )
            )
        ).scalars().all()
        outbound = (
            await session.execute(
                select(EventLog).where(
                    EventLog.channel == "mobile",
                    EventLog.type == "message",
                    EventLog.direction == "outbound",
                )
            )
        ).scalars().all()
    assert len(inbound) == 1
    assert len(outbound) == 1


async def test_two_users_chat_concurrently_and_stay_isolated(db, fake_clock, settings):
    user_a, _ = await _seed_user(db, fake_clock, external_id="ou_a")
    user_b, _ = await _seed_user(db, fake_clock, external_id="ou_b")

    def responder(messages: list[dict]) -> LLMResult:
        text = [m["content"] for m in messages if m.get("role") == "user"][-1]
        return LLMResult(content=f"回复:{text}")

    pipeline, _ = _make_pipeline(db, fake_clock, settings, responder)
    app = _app(db, fake_clock, settings, pipeline)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response_a, response_b = await asyncio.gather(
            client.post(
                "/api/mobile/chat/messages",
                json={"clientMessageId": "c-a", "text": "A 的消息"},
                headers=_headers(user_a, "c-a"),
            ),
            client.post(
                "/api/mobile/chat/messages",
                json={"clientMessageId": "c-b", "text": "B 的消息"},
                headers=_headers(user_b, "c-b"),
            ),
        )
        await _wait_status(client, user_a, response_a.json()["id"])
        await _wait_status(client, user_b, response_b.json()["id"])
        history_a = await client.get(
            "/api/mobile/chat/messages",
            headers={"X-Butler-User": str(user_a.id)},
        )
        history_b = await client.get(
            "/api/mobile/chat/messages",
            headers={"X-Butler-User": str(user_b.id)},
        )

    texts_a = {message["text"] for message in history_a.json()["messages"]}
    texts_b = {message["text"] for message in history_b.json()["messages"]}
    assert texts_a == {"A 的消息", "回复:A 的消息"}
    assert texts_b == {"B 的消息", "回复:B 的消息"}


async def test_same_user_messages_process_in_send_order(db, fake_clock, settings):
    user, _ = await _seed_user(db, fake_clock)
    seen: list[str] = []

    def responder(messages: list[dict]) -> LLMResult:
        text = [m["content"] for m in messages if m.get("role") == "user"][-1]
        seen.append(text)
        return LLMResult(content=f"回复:{text}")

    pipeline, _ = _make_pipeline(db, fake_clock, settings, responder)
    first = await pipeline.ingest_for_user(
        _mobile_event(user, "c1", "第一句"), user, client_message_id="c1"
    )
    second = await pipeline.ingest_for_user(
        _mobile_event(user, "c2", "第二句"), user, client_message_id="c2"
    )

    lock = asyncio.Lock()
    await asyncio.gather(
        process_mobile_event(pipeline, lock, first),
        process_mobile_event(pipeline, lock, second),
    )

    assert seen == ["第一句", "第二句"]
    async with db() as session:
        outbound = (
            await session.execute(
                select(EventLog)
                .where(EventLog.direction == "outbound")
                .order_by(EventLog.recorded_at, EventLog.id)
            )
        ).scalars().all()
    assert {event.payload["text"] for event in outbound} == {
        "回复:第一句",
        "回复:第二句",
    }


async def test_first_page_returns_latest_50_of_long_history(db, fake_clock, settings):
    user, _ = await _seed_user(db, fake_clock)
    app = _app(db, fake_clock, settings, None)

    async with db() as session:
        for index in range(120):
            row, _ = await append_event(
                session,
                user_id=user.id,
                channel="mobile",
                direction="inbound",
                type="message",
                payload={"text": f"m{index:03d}"},
                trace_id="a5-history",
                clock=fake_clock,
                occurred_at=fake_clock.now() + dt.timedelta(seconds=index),
            )
            session.add(
                InboundProcessing(
                    event_id=row.id,
                    user_id=user.id,
                    status="done",
                    updated_at=fake_clock.now(),
                )
            )
        await session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/mobile/chat/messages",
            headers={"X-Butler-User": str(user.id)},
        )

    body = response.json()
    texts = [message["text"] for message in body["messages"]]
    assert len(texts) == 50
    assert texts[0] == "m070"
    assert texts[-1] == "m119"
    assert body["hasMore"] is True


async def test_failed_message_requires_new_client_message_id(
    db, fake_clock, settings, monkeypatch
):
    user, _ = await _seed_user(db, fake_clock)
    pipeline, provider = _make_pipeline(
        db, fake_clock, settings, _plain_responder("收到")
    )
    app = _app(db, fake_clock, settings, pipeline)

    async def boom(ingested):
        raise RuntimeError("boom")

    monkeypatch.setattr(pipeline, "_process_one", boom)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user, "c1"),
        )
        failed = await _wait_status(
            client, user, first.json()["id"], expected=("failed",)
        )
        same_id = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers=_headers(user, "c1"),
        )
        assert same_id.status_code == 200
        assert same_id.json()["status"] == "failed"
        assert len(provider.calls) == 0

        monkeypatch.undo()
        retried = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c2", "text": "你好"},
            headers=_headers(user, "c2"),
        )
        final = await _wait_status(client, user, retried.json()["id"])

    assert failed["status"] == "failed"
    assert retried.status_code == 202
    assert final["status"] == "done"
    assert len(provider.calls) == 1


async def test_chat_auth_requires_header_and_whitelist(db, fake_clock):
    user, _ = await _seed_user(db, fake_clock, external_id="ou_a5")
    settings = Settings(_env_file=None, allowed_open_ids="ou_other")
    app = _app(db, fake_clock, settings, None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/mobile/chat/messages")
        blocked = await client.get(
            "/api/mobile/chat/messages",
            headers={"X-Butler-User": str(user.id)},
        )

    assert missing.status_code == 401
    assert blocked.status_code == 403


def test_chat_route_follows_mobile_api_switch(monkeypatch):
    """ENABLE_MOBILE_API=0 时 chat 路由 404；开启后路由存在（缺用户头 401）。"""
    from app.main import create_app

    monkeypatch.delenv("ENABLE_MOBILE_API", raising=False)
    get_settings.cache_clear()
    try:
        disabled = TestClient(create_app())
        assert disabled.get("/api/mobile/chat/messages").status_code == 404

        monkeypatch.setenv("ENABLE_MOBILE_API", "1")
        get_settings.cache_clear()
        enabled = TestClient(create_app())
        assert enabled.get("/api/mobile/chat/messages").status_code == 401
    finally:
        get_settings.cache_clear()


async def test_mobile_message_enters_memory_extraction_queue(
    db, fake_clock, settings
):
    user, event_id = await _seed_user(db, fake_clock, event_channel="mobile")

    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 1

    async with db() as session:
        runs = (await session.execute(select(MemoryExtractionRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].user_id == user.id
    assert runs[0].to_event_id == event_id
    assert runs[0].status == "pending"
