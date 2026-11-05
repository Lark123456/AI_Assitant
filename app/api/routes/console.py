"""Console 渠道路由：本地测试入口。"""

import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.adapters.base import InboundEvent
from app.core.ids import new_idempotency_key

router = APIRouter(prefix="/console")


class ConsoleMessageIn(BaseModel):
    external_user_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    idempotency_key: str | None = None


@router.post("/messages", status_code=202)
async def post_message(body: ConsoleMessageIn, request: Request) -> dict:
    """接收 Console 消息：同步 ingest（幂等落库）后立即应答，处理异步进行。"""
    pipeline = request.app.state.pipeline
    event = InboundEvent(
        channel="console",
        external_user_id=body.external_user_id,
        kind="message",
        text=body.text,
        idempotency_key=body.idempotency_key or new_idempotency_key(),
    )
    ingested = await pipeline.ingest(event)
    if ingested is None:
        return {"status": "dropped"}
    if ingested.created:
        asyncio.create_task(pipeline.process(ingested))
    return {
        "status": "accepted",
        "idempotency_key": event.idempotency_key,
        "duplicate": not ingested.created,
    }


@router.get("/messages")
async def list_messages(external_user_id: str, request: Request) -> dict:
    """查看 Console 渠道的出站消息（测试与人工验证用）。"""
    console = request.app.state.adapters["console"]
    return {"messages": console.messages_for(external_user_id)}
