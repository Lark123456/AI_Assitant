"""移动端 Chat API：U2-A1 只接收入站消息并落库。

本批不启动 Friday Agent、不注册 MobileAdapter、不产生 outbound。
A2 完成安全处理路径后再启用 process。
"""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import InboundEvent
from app.api.routes.mobile import get_mobile_user, get_session
from app.db.models import InboundProcessing, User

router = APIRouter(prefix="/api/mobile/chat")

MAX_CLIENT_MESSAGE_ID = 200
MAX_TEXT = 4000


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    client_message_id: str = Field(alias="clientMessageId")
    text: str


@router.post("/messages")
async def send_message(
    request: Request,
    body: SendMessageRequest,
    response: Response,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """接收一条手机文字消息；A1 只落库，不启动 Agent。"""
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

    processing = await session.get(InboundProcessing, ingested.event_id)
    status = processing.status if processing is not None else "processing"
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
