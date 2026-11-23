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
import uuid
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import InboundEvent
from app.api.routes.mobile import get_mobile_user, get_session
from app.core.logging import get_logger
from app.core.tasks import spawn
from app.db.models import EventLog, InboundProcessing, User
from app.engine.pipeline import InboundPipeline, IngestedEvent

router = APIRouter(prefix="/api/mobile/chat")
logger = get_logger(__name__)

MAX_CLIENT_MESSAGE_ID = 200
MAX_TEXT = 4000
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_message_id: str = Field(alias="clientMessageId")
    text: str


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
        "clientMessageId": payload.get("client_message_id"),
        "role": "user" if inbound else "friday",
        "text": str(payload.get("text", "")),
        "status": status if inbound else "available",
        "replyToId": None if inbound else payload.get("reply_to_event_id"),
        "createdAt": event.occurred_at.astimezone(ZoneInfo(tz)).isoformat(),
    }


async def _serialize(
    session: AsyncSession, events: list[EventLog], tz: str
) -> list[dict]:
    statuses = await _inbound_statuses(
        session, [event.id for event in events if event.direction == "inbound"]
    )
    return [
        _message_item(event, status=statuses.get(event.id), tz=tz) for event in events
    ]


def _chat_conditions(user: User) -> list[Any]:
    """聊天事实来源边界：只取本用户的手机 message 事件。"""
    return [
        EventLog.user_id == user.id,
        EventLog.channel == "mobile",
        EventLog.type == "message",
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
        or event.type != "message"
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

    messages = await _serialize(session, events, user.timezone)
    return {
        "messages": messages,
        "nextCursor": messages[-1]["id"] if messages else None,
        "previousCursor": messages[0]["id"] if messages else None,
        "hasMore": has_more,
    }


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """查询单条手机消息的最新状态；不存在或不属于当前用户时 404。"""
    try:
        event_id = uuid.UUID(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="消息不存在") from exc
    event = await session.get(EventLog, event_id)
    if (
        event is None
        or event.user_id != user.id
        or event.channel != "mobile"
        or event.type != "message"
        or event.direction not in ("inbound", "outbound")
    ):
        raise HTTPException(status_code=404, detail="消息不存在")
    statuses = await _inbound_statuses(
        session, [event.id] if event.direction == "inbound" else []
    )
    return _message_item(event, status=statuses.get(event.id), tz=user.timezone)
