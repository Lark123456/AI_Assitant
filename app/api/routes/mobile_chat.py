"""移动端 Chat API：消息接收、历史查询与单条状态查询。

处理路径（U2-A2 起）：
- POST 只负责落库并立即返回 202；Friday 处理在后台按用户串行执行。
- 手机回复由 InboundPipeline 直接写入 event_log（delivery="persisted"），
  MobileAdapter 不写第二份记录；App 轮询 GET 即可取到。
- 手机出站状态是 available（已落库可取），不是 sent；processing/done/failed
  只用于入站消息。

运行环境限制：同一用户的串行锁是进程内 asyncio.Lock，U2-A 只支持单进程 API
服务（当前 uvicorn 默认单 worker）。多 worker / 多副本时必须改为数据库队列、
租约或其他跨进程协调机制，否则同一用户的消息仍可能被并发处理。
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import InboundEvent
from app.api.routes.mobile import get_mobile_user, get_session, resolve_mobile_user
from app.core.logging import get_logger
from app.core.tasks import spawn
from app.db.models import EventLog, InboundProcessing, Memory, User
from app.engine.pipeline import InboundPipeline, IngestedEvent
from app.engine.streaming import ChatStreamBroker, StreamMessage
from app.memory.confirm import PendingMemoryNotFound, decide_pending_memory

router = APIRouter(prefix="/api/mobile/chat")
logger = get_logger(__name__)

MAX_CLIENT_MESSAGE_ID = 200
MAX_TEXT = 4000
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
STREAM_HEARTBEAT_SECONDS = 15.0
STREAM_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_message_id: str = Field(alias="clientMessageId")
    text: str


class CardActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action: Literal["confirm", "reject"]
    item_id: str | None = Field(default=None, alias="itemId")


def _chat_lock(state: Any, user_id: uuid.UUID) -> asyncio.Lock:
    """取该用户的进程内串行锁；锁只在当前 Python 进程有效。"""
    locks: dict[uuid.UUID, asyncio.Lock] | None = getattr(
        state, "mobile_chat_locks", None
    )
    if locks is None:
        locks = {}
        state.mobile_chat_locks = locks
    lock = locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        locks[user_id] = lock
    return lock


async def process_mobile_event(
    pipeline: InboundPipeline, lock: asyncio.Lock, ingested: IngestedEvent
) -> None:
    """按用户串行处理手机消息，避免同一用户的 Agent 并发读写上下文。"""
    async with lock:
        await pipeline.process(ingested)


def _missing_status(event_id: uuid.UUID) -> str:
    """处理状态行缺失（迁移前旧事件等）时按失败处理并告警。"""
    logger.warning("chat message has no inbound_processing row: event_id=%s", event_id)
    return "failed"


async def _inbound_statuses(
    session: AsyncSession, event_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not event_ids:
        return {}
    rows = (
        await session.execute(
            select(InboundProcessing.event_id, InboundProcessing.status).where(
                InboundProcessing.event_id.in_(event_ids)
            )
        )
    ).all()
    statuses = {event_id: status for event_id, status in rows}
    for event_id in event_ids:
        if event_id not in statuses:
            statuses[event_id] = _missing_status(event_id)
    return statuses


def _message_item(event: EventLog, *, status: str | None, tz: str) -> dict:
    """单条消息的 API 结构；手机出站固定为 available。"""
    payload = event.payload or {}
    inbound = event.direction == "inbound"
    return {
        "id": str(event.id),
        "kind": "text",
        "clientMessageId": payload.get("client_message_id"),
        "role": "user" if inbound else "friday",
        "text": str(payload.get("text", "")),
        "status": status if inbound else "available",
        "replyToId": None if inbound else payload.get("reply_to_event_id"),
        "createdAt": event.occurred_at.astimezone(ZoneInfo(tz)).isoformat(),
    }


def _memory_state(memory: Memory) -> str:
    if memory.status == "pending":
        return "pending"
    if memory.status == "retracted":
        return "rejected"
    if memory.source_class == "confirmed":
        return "confirmed"
    return "rejected"


async def _card_states(
    session: AsyncSession, user: User, events: list[EventLog]
) -> dict[str, str]:
    """批量查询卡片引用的 pending 记忆，返回 item_id → 展示状态。"""
    memory_ids: set[uuid.UUID] = set()
    for event in events:
        if event.type != "card":
            continue
        for item in (event.payload or {}).get("items", []):
            raw = item.get("item_id") if isinstance(item, dict) else None
            try:
                memory_ids.add(uuid.UUID(raw))
            except (TypeError, ValueError):
                continue
    if not memory_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(Memory).where(
                    Memory.user_id == user.id, Memory.id.in_(memory_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(memory.id): _memory_state(memory) for memory in rows}


def _card_item(event: EventLog, *, states: dict[str, str], tz: str) -> dict:
    payload = event.payload or {}
    items = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            continue
        items.append(
            {
                "itemId": item_id,
                "label": str(item.get("label", "")),
                "state": states.get(item_id, "rejected"),
            }
        )
    return {
        "id": str(event.id),
        "kind": "memory_confirm",
        "clientMessageId": None,
        "role": "friday",
        "text": str(payload.get("text", "")),
        "status": "available",
        "replyToId": None,
        "createdAt": event.occurred_at.astimezone(ZoneInfo(tz)).isoformat(),
        "items": items,
        "allHandled": all(item["state"] != "pending" for item in items),
        "allConfirmed": bool(items)
        and all(item["state"] == "confirmed" for item in items),
    }


async def _serialize(
    session: AsyncSession, events: list[EventLog], tz: str, user: User
) -> list[dict]:
    statuses = await _inbound_statuses(
        session, [event.id for event in events if event.direction == "inbound"]
    )
    states = await _card_states(session, user, events)
    return [
        _message_item(event, status=statuses.get(event.id), tz=tz)
        if event.type == "message"
        else _card_item(event, states=states, tz=tz)
        for event in events
    ]


def _chat_conditions(user: User) -> list[Any]:
    """聊天事实来源边界：本用户的手机 message / card 事件。"""
    return [
        EventLog.user_id == user.id,
        EventLog.channel == "mobile",
        EventLog.type.in_(("message", "card")),
        EventLog.direction.in_(("inbound", "outbound")),
    ]


async def _resolve_cursor(
    session: AsyncSession, user: User, raw: str
) -> EventLog:
    """把 after/before 游标解析为同用户的手机聊天事件。"""
    try:
        event_id = uuid.UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="游标无效") from exc
    event = await session.get(EventLog, event_id)
    if (
        event is None
        or event.user_id != user.id
        or event.channel != "mobile"
        or event.type not in ("message", "card")
        or event.direction not in ("inbound", "outbound")
    ):
        raise HTTPException(status_code=400, detail="游标无效")
    return event


@router.post("/messages")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    response: Response,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """接收一条手机文字消息：落库后立即返回，处理在后台按用户串行执行。"""
    client_message_id = body.client_message_id.strip()
    text = body.text.strip()
    if not client_message_id or len(client_message_id) > MAX_CLIENT_MESSAGE_ID:
        raise HTTPException(status_code=400, detail="clientMessageId 长度不合法")
    if not text or len(text) > MAX_TEXT:
        raise HTTPException(status_code=400, detail="text 长度不合法")
    if idempotency_key is not None and idempotency_key.strip() != client_message_id:
        raise HTTPException(
            status_code=400, detail="Idempotency-Key 必须与 clientMessageId 一致"
        )

    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline 未就绪")

    clock = request.app.state.clock
    event = InboundEvent(
        channel="mobile",
        external_user_id=str(user.id),
        kind="message",
        text=text,
        occurred_at=clock.now(),
        idempotency_key=f"mobile-chat:{user.id}:{client_message_id}",
        raw={"client_message_id": client_message_id},
    )
    ingested = await pipeline.ingest_for_user(
        event, user, client_message_id=client_message_id
    )

    if ingested.created:
        spawn(
            process_mobile_event(
                pipeline, _chat_lock(request.app.state, user.id), ingested
            )
        )
        status = "processing"
    else:
        statuses = await _inbound_statuses(session, [ingested.event_id])
        status = statuses[ingested.event_id]

    created_at = (event.occurred_at or clock.now()).astimezone(
        ZoneInfo(user.timezone)
    ).isoformat()
    response.status_code = 202 if ingested.created else 200
    return {
        "id": str(ingested.event_id),
        "clientMessageId": client_message_id,
        "status": status,
        "createdAt": created_at,
        "duplicate": not ingested.created,
    }


@router.get("/messages")
async def list_messages(
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=DEFAULT_LIMIT),
    after: str | None = Query(default=None),
    before: str | None = Query(default=None),
) -> dict:
    """查询手机聊天历史；messages 始终按 occurred_at ASC, id ASC 返回。

    - 无游标：取最新 limit 条（先倒序查再反转），hasMore 表示还有更早历史；
    - after：取该事件之后的增量，hasMore 表示还有更新的消息；
    - before：取该事件之前的 limit 条，用于向上翻更早历史。
    """
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(status_code=400, detail="limit 必须在 1-100 之间")
    if after is not None and before is not None:
        raise HTTPException(status_code=400, detail="after 与 before 不能同时使用")

    conditions = _chat_conditions(user)
    if after is not None:
        cursor = await _resolve_cursor(session, user, after)
        rows = (
            (
                await session.execute(
                    select(EventLog)
                    .where(
                        *conditions,
                        or_(
                            EventLog.occurred_at > cursor.occurred_at,
                            and_(
                                EventLog.occurred_at == cursor.occurred_at,
                                EventLog.id > cursor.id,
                            ),
                        ),
                    )
                    .order_by(EventLog.occurred_at.asc(), EventLog.id.asc())
                    .limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        has_more = len(rows) > limit
        events = list(rows[:limit])
    else:
        statement = select(EventLog).where(*conditions)
        if before is not None:
            cursor = await _resolve_cursor(session, user, before)
            statement = statement.where(
                or_(
                    EventLog.occurred_at < cursor.occurred_at,
                    and_(
                        EventLog.occurred_at == cursor.occurred_at,
                        EventLog.id < cursor.id,
                    ),
                )
            )
        rows = (
            (
                await session.execute(
                    statement.order_by(
                        EventLog.occurred_at.desc(), EventLog.id.desc()
                    ).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        has_more = len(rows) > limit
        events = list(reversed(rows[:limit]))

    messages = await _serialize(session, events, user.timezone, user)
    return {
        "messages": messages,
        "nextCursor": messages[-1]["id"] if messages else None,
        "previousCursor": messages[0]["id"] if messages else None,
        "hasMore": has_more,
    }


async def _load_mobile_message(
    session: AsyncSession,
    user: User,
    message_id: str,
    *,
    inbound_only: bool,
) -> EventLog:
    """按 id 取当前用户的手机聊天消息；不存在/越权返回 404。"""
    try:
        event_id = uuid.UUID(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="消息不存在") from exc
    event = await session.get(EventLog, event_id)
    directions = ("inbound",) if inbound_only else ("inbound", "outbound")
    if (
        event is None
        or event.user_id != user.id
        or event.channel != "mobile"
        or event.type != "message"
        or event.direction not in directions
    ):
        raise HTTPException(status_code=404, detail="消息不存在")
    return event


async def _load_card_event(
    session: AsyncSession, user: User, message_id: str
) -> EventLog:
    """取当前用户的手机 outbound 卡片事件。"""
    try:
        event_id = uuid.UUID(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="卡片不存在") from exc
    event = await session.get(EventLog, event_id)
    if (
        event is None
        or event.user_id != user.id
        or event.channel != "mobile"
        or event.type != "card"
        or event.direction != "outbound"
    ):
        raise HTTPException(status_code=404, detail="卡片不存在")
    return event


async def _find_reply(
    session: AsyncSession, user: User, inbound_id: uuid.UUID
) -> EventLog | None:
    """查询某条入站消息已落库的 Friday 回复。"""
    return (
        await session.execute(
            select(EventLog)
            .where(
                EventLog.user_id == user.id,
                EventLog.channel == "mobile",
                EventLog.direction == "outbound",
                EventLog.type == "message",
                EventLog.payload["reply_to_event_id"].astext == str(inbound_id),
            )
            .order_by(EventLog.occurred_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _reply_done_payload(
    reply: EventLog, inbound_id: uuid.UUID, tz: str
) -> dict:
    return {
        "text": str((reply.payload or {}).get("text", "")),
        "messageId": str(reply.id),
        "replyToId": str(inbound_id),
        "createdAt": reply.occurred_at.astimezone(ZoneInfo(tz)).isoformat(),
    }


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _single_sse_event(event: str, payload: dict) -> AsyncIterator[str]:
    yield _sse(event, payload)


async def _stream_sse(
    request: Request,
    broker: ChatStreamBroker,
    event_id: uuid.UUID,
    queue: asyncio.Queue[StreamMessage],
    initial: list[StreamMessage],
) -> AsyncIterator[str]:
    """转发 broker 事件；空闲时发送心跳并检测客户端断开。"""
    try:
        terminal = False
        for kind, payload in initial:
            yield _sse(kind, payload)
            terminal = kind in ("done", "error")
        if terminal:
            return
        while True:
            try:
                kind, payload = await asyncio.wait_for(
                    queue.get(), timeout=STREAM_HEARTBEAT_SECONDS
                )
            except TimeoutError:
                if await request.is_disconnected():
                    return
                yield ": ping\n\n"
                continue
            yield _sse(kind, payload)
            if kind in ("done", "error"):
                return
    finally:
        broker.detach(event_id, queue)


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """查询单条手机消息的最新状态；不存在或不属于当前用户时 404。"""
    event = await _load_mobile_message(
        session, user, message_id, inbound_only=False
    )
    statuses = await _inbound_statuses(
        session, [event.id] if event.direction == "inbound" else []
    )
    return _message_item(event, status=statuses.get(event.id), tz=user.timezone)


@router.post("/messages/{message_id}/card-actions")
async def act_on_card(
    message_id: str,
    body: CardActionRequest,
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """确认或拒绝记忆卡片中的 pending 记忆。

    只允许操作该卡片 payload 内的 item；重复操作幂等，返回卡片当前状态。
    """
    event = await _load_card_event(session, user, message_id)
    raw_items = (event.payload or {}).get("items", [])
    allowed = [
        item["item_id"]
        for item in raw_items
        if isinstance(item, dict)
        and isinstance(item.get("item_id"), str)
        and item["item_id"]
    ]
    if not allowed:
        raise HTTPException(status_code=400, detail="卡片没有可处理项")

    targets = allowed if body.item_id is None else [body.item_id]
    if body.item_id is not None and body.item_id not in allowed:
        raise HTTPException(status_code=400, detail="itemId 不属于该卡片")

    for raw in dict.fromkeys(targets):
        try:
            pending_id = uuid.UUID(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="itemId 无效") from exc
        try:
            await decide_pending_memory(
                session,
                user=user,
                pending_id=pending_id,
                confirm=body.action == "confirm",
                clock=request.app.state.clock,
            )
        except PendingMemoryNotFound:
            # 卡片引用的记忆已被清理：保留现状，不阻断其它项。
            continue
    await session.commit()

    states = await _card_states(session, user, [event])
    return _card_item(event, states=states, tz=user.timezone)


@router.get("/messages/{message_id}/stream")
async def stream_message(
    message_id: str,
    request: Request,
    x_butler_user: Annotated[str | None, Header(alias="X-Butler-User")] = None,
) -> StreamingResponse:
    """SSE 流式回复：delta 为累计文本，done 为最终持久化回复。

    若处理已完成，直接从 broker 终态或数据库回复返回；processing 但 broker
    无状态（重启/多进程）时返回 stream_unavailable，客户端回退轮询。
    """
    broker: ChatStreamBroker | None = getattr(
        request.app.state, "chat_stream_broker", None
    )
    attachment: (
        tuple[asyncio.Queue[StreamMessage], list[StreamMessage]] | None
    ) = None
    terminal: StreamMessage | None = None
    event_id: uuid.UUID
    async with request.app.state.sessionmaker() as session:
        user = await resolve_mobile_user(session, request, x_butler_user)
        event = await _load_mobile_message(
            session, user, message_id, inbound_only=True
        )
        event_id = event.id
        if broker is not None and broker.has(event.id):
            attachment = broker.attach(event.id)
        if attachment is None:
            status = (await _inbound_statuses(session, [event.id]))[event.id]
            if status == "failed":
                terminal = ("error", {"code": "processing_failed"})
            elif status == "processing":
                terminal = ("error", {"code": "stream_unavailable"})
            else:
                reply = await _find_reply(session, user, event.id)
                terminal = (
                    ("done", _reply_done_payload(reply, event.id, user.timezone))
                    if reply is not None
                    else (
                        "done",
                        {
                            "text": "",
                            "messageId": None,
                            "replyToId": str(event.id),
                            "createdAt": None,
                        },
                    )
                )

    if attachment is not None:
        assert broker is not None
        queue, initial = attachment
        return StreamingResponse(
            _stream_sse(request, broker, event_id, queue, initial),
            media_type="text/event-stream",
            headers=STREAM_HEADERS,
        )
    assert terminal is not None
    return StreamingResponse(
        _single_sse_event(*terminal),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
