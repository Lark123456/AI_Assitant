"""U2 B4：手机聊天 SSE 真流式（broker、晚订阅、工具前导覆盖、回退）。"""

import asyncio
import json
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.api.routes.mobile_chat import router as chat_router
from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.models import ChannelIdentity, EventLog, User
from app.engine.pipeline import InboundPipeline
from app.engine.streaming import ChatStreamBroker
from app.llm.gateway import LLMGateway
from app.llm.providers.base import BaseProvider
from app.llm.schemas import LLMResult, ToolCall
from tests.conftest import TEST_ALIASES


class _StreamingProvider(BaseProvider):
    """按脚本输出累计文本；可在首块后暂停，便于测试实时 SSE。"""

    name = "fake"

    def __init__(
        self,
        chunks: list[str],
        *,
        first_delta: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        tool_call: ToolCall | None = None,
    ) -> None:
        self._chunks = chunks
        self._first_delta = first_delta
        self._release = release
        self._tool_call = tool_call

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        params: dict,
        on_delta=None,
    ) -> LLMResult:
        has_tool_result = any(message.get("role") == "tool" for message in messages)
        if self._tool_call is not None and not has_tool_result:
            if on_delta is not None:
                on_delta("我先看看")
            return LLMResult(content="我先看看", tool_calls=[self._tool_call])
        for index, text in enumerate(self._chunks):
            if on_delta is not None:
                on_delta(text)
            if index == 0 and self._first_delta is not None:
                self._first_delta.set()
            if index == 0 and self._release is not None:
                await asyncio.wait_for(self._release.wait(), timeout=3)
        return LLMResult(content=self._chunks[-1] if self._chunks else "")


async def _seed_user(db, clock: FakeClock) -> User:
    async with db() as session:
        user = User(display_name="流式用户", timezone="Asia/Shanghai")
        session.add(user)
        await session.flush()
        session.add(
            ChannelIdentity(user_id=user.id, channel="feishu", external_id="ou_stream")
        )
        await session.commit()
        return user


def _mobile_event(user: User, key: str, text: str = "你好") -> InboundEvent:
    return InboundEvent(
        channel="mobile",
        external_user_id=str(user.id),
        kind="message",
        text=text,
        idempotency_key=f"mobile-chat:{user.id}:{key}",
    )


def _make_pipeline(
    db,
    clock: FakeClock,
    settings: Settings,
    provider: BaseProvider,
    broker: ChatStreamBroker,
) -> InboundPipeline:
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
        stream_broker=broker,
    )


def _app(db, clock: FakeClock, settings: Settings, pipeline, broker) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    app.state.pipeline = pipeline
    app.state.chat_stream_broker = broker
    return app


def _headers(user: User) -> dict[str, str]:
    return {"X-Butler-User": str(user.id)}


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    name = "message"
    data: list[str] = []
    for line in body.splitlines():
        if not line:
            if data:
                events.append((name, json.loads("\n".join(data))))
            name = "message"
            data = []
        elif line.startswith("event:"):
            name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data.append(line.removeprefix("data:").lstrip())
    if data:
        events.append((name, json.loads("\n".join(data))))
    return events


async def _wait_status(
    client: httpx.AsyncClient,
    user: User,
    message_id: str,
    *,
    expected: tuple[str, ...] = ("done", "failed"),
) -> str:
    for _ in range(200):
        response = await client.get(
            f"/api/mobile/chat/messages/{message_id}", headers=_headers(user)
        )
        assert response.status_code == 200
        status = response.json()["status"]
        if status in expected:
            return str(status)
        await asyncio.sleep(0.02)
    raise AssertionError(f"message {message_id} did not reach terminal state")


def test_broker_cumulative_delta_and_late_done_snapshot() -> None:
    broker = ChatStreamBroker()
    event_id = uuid.uuid4()
    broker.open(event_id)
    broker.publish(event_id, "你")

    attachment = broker.attach(event_id)
    assert attachment is not None
    queue, initial = attachment
    assert initial == [("delta", {"text": "你"})]

    broker.publish(event_id, "你好")
    kind, payload = queue.get_nowait()
    assert kind == "delta"
    assert payload["text"] == "你好"

    broker.finish(event_id, text="你好", reply_id="r1", occurred_at=None)
    kind, payload = queue.get_nowait()
    assert kind == "done"
    assert payload["messageId"] == "r1"
    broker.detach(event_id, queue)

    late = broker.attach(event_id)
    assert late is not None
    _, late_initial = late
    assert late_initial[0][0] == "done"
    assert late_initial[0][1]["text"] == "你好"


async def test_sse_returns_done_after_processing_finished(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    provider = _StreamingProvider(["你", "你好"])
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    app = _app(db, fake_clock, settings, pipeline, broker)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        posted = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers={**_headers(user), "Idempotency-Key": "c1"},
        )
        message_id = posted.json()["id"]
        assert await _wait_status(client, user, message_id) == "done"

        stream = await client.get(
            f"/api/mobile/chat/messages/{message_id}/stream",
            headers=_headers(user),
        )

    assert stream.status_code == 200
    events = _parse_sse(stream.text)
    assert events[0][0] == "done"
    assert events[0][1]["text"] == "你好"
    assert events[0][1]["replyToId"] == message_id
    assert events[0][1]["messageId"] is not None


async def test_sse_delivers_live_delta_at_least_once(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    first_delta = asyncio.Event()
    release = asyncio.Event()
    provider = _StreamingProvider(
        ["你", "你好"], first_delta=first_delta, release=release
    )
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    app = _app(db, fake_clock, settings, pipeline, broker)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        posted = await client.post(
            "/api/mobile/chat/messages",
            json={"clientMessageId": "c1", "text": "你好"},
            headers={**_headers(user), "Idempotency-Key": "c1"},
        )
        message_id = posted.json()["id"]
        await asyncio.wait_for(first_delta.wait(), timeout=2)

        async def release_soon() -> None:
            await asyncio.sleep(0.05)
            release.set()

        releaser = asyncio.create_task(release_soon())
        stream = await client.get(
            f"/api/mobile/chat/messages/{message_id}/stream",
            headers=_headers(user),
        )
        await releaser
        await _wait_status(client, user, message_id)

    events = _parse_sse(stream.text)
    kinds = [kind for kind, _ in events]
    assert "delta" in kinds
    done = next(payload for kind, payload in events if kind == "done")
    assert done["text"] == "你好"


async def test_sse_tool_preamble_is_replaced_by_final_reply(
    db, fake_clock, settings
):
    from app.db.models import WorkItem

    user = await _seed_user(db, fake_clock)
    provider = _StreamingProvider(
        ["已创建"],
        tool_call=ToolCall(
            id="c1", name="create_task", arguments={"title": "写周报"}
        ),
    )
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user, "c1"), user, client_message_id="c1"
    )
    await pipeline.process(ingested)

    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
    assert len(items) == 1

    attachment = broker.attach(ingested.event_id)
    assert attachment is not None
    _, initial = attachment
    assert initial[0][0] == "done"
    assert initial[0][1]["text"] == "已创建"
    assert "我先看看" not in str(initial[0][1]["text"])


async def test_sse_stream_unavailable_when_processing_without_broker_state(
    db, fake_clock, settings
):
    user = await _seed_user(db, fake_clock)
    provider = _StreamingProvider(["不应被调用"])
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    app = _app(db, fake_clock, settings, pipeline, ChatStreamBroker())

    ingested = await pipeline.ingest_for_user(
        _mobile_event(user, "c1"), user, client_message_id="c1"
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stream = await client.get(
            f"/api/mobile/chat/messages/{ingested.event_id}/stream",
            headers=_headers(user),
        )

    events = _parse_sse(stream.text)
    assert events[0][0] == "error"
    assert events[0][1]["code"] == "stream_unavailable"


async def test_sse_falls_back_to_db_reply_after_broker_lost(
    db, fake_clock, settings
):
    user = await _seed_user(db, fake_clock)
    provider = _StreamingProvider(["你好"])
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user, "c1"), user, client_message_id="c1"
    )
    await pipeline.process(ingested)
    app = _app(db, fake_clock, settings, pipeline, ChatStreamBroker())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        stream = await client.get(
            f"/api/mobile/chat/messages/{ingested.event_id}/stream",
            headers=_headers(user),
        )

    events = _parse_sse(stream.text)
    assert events[0][0] == "done"
    assert events[0][1]["text"] == "你好"
    assert events[0][1]["replyToId"] == str(ingested.event_id)


async def test_sse_rejects_other_users_or_outbound_events(db, fake_clock, settings):
    user = await _seed_user(db, fake_clock)
    other = User(display_name="别人", timezone="Asia/Shanghai")
    async with db() as session:
        session.add(other)
        await session.flush()
        session.add(
            ChannelIdentity(
                user_id=other.id, channel="feishu", external_id="ou_stream_other"
            )
        )
        await session.commit()

    provider = _StreamingProvider(["你好"])
    broker = ChatStreamBroker()
    pipeline = _make_pipeline(db, fake_clock, settings, provider, broker)
    ingested = await pipeline.ingest_for_user(
        _mobile_event(user, "c1"), user, client_message_id="c1"
    )
    await pipeline.process(ingested)
    async with db() as session:
        outbound = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().first()
    assert outbound is not None
    app = _app(db, fake_clock, settings, pipeline, broker)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        foreign = await client.get(
            f"/api/mobile/chat/messages/{ingested.event_id}/stream",
            headers=_headers(other),
        )
        outbound_stream = await client.get(
            f"/api/mobile/chat/messages/{outbound.id}/stream",
            headers=_headers(user),
        )

    assert foreign.status_code == 404
    assert outbound_stream.status_code == 404
