"""Friday v0：手写 tool-use 循环，最多 4 步。"""

import json
import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.friday.history import build_history
from app.agents.friday.prompts import build_system_prompt
from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import User
from app.embeddings.service import EmbeddingService
from app.engine.events import append_event
from app.llm.gateway import BudgetExceededError, LLMGateway
from app.llm.schemas import LLMResult
from app.memory.retrieve import MemoryContext, render_memory_block, retrieve_memory_context
from app.tools.base import ToolContext
from app.tools.registry import execute_tool, tool_schemas

MAX_STEPS = 4
FRIDAY_ALIAS = "friday_fast"
BUDGET_EXCEEDED_REPLY = "今天的额度用完了，我们明天再聊吧。"

logger = get_logger(__name__)


class FridayAgent:
    """快通道：意图理解 + 工具调用 + 简短回复。"""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway

    async def handle(
        self,
        *,
        session: AsyncSession,
        clock: Clock,
        settings: Settings,
        user: User,
        trace_id: str,
        channel: str,
        source_event_id: uuid.UUID | None,
        text: str,
        embedder: EmbeddingService | None = None,
    ) -> str:
        """处理一条用户消息，返回回复文本。"""
        ctx = ToolContext(
            session=session,
            clock=clock,
            settings=settings,
            user=user,
            trace_id=trace_id,
            channel=channel,
            source_event_id=source_event_id,
            embedder=embedder,
        )
        memory_block = ""
        if settings.memory_inject_enabled:
            context = await retrieve_memory_context(
                session,
                user=user,
                query=text,
                embedder=embedder,
                settings=settings,
                clock=clock,
            )
            memory_block = render_memory_block(
                context,
                max_chars=settings.memory_inject_max_chars,
                item_max_chars=settings.memory_inject_item_max_chars,
            )
            await _audit_memory_context(
                session,
                user=user,
                channel=channel,
                trace_id=trace_id,
                source_event_id=source_event_id,
                context=context,
                block_chars=len(memory_block),
                clock=clock,
                query=text,
            )
        messages: list[dict] = [
            {
                "role": "system",
                "content": build_system_prompt(clock, user.timezone, memory_block),
            },
        ]
        history = await build_history(
            session,
            user_id=user.id,
            exclude_event_id=source_event_id,
            clock=clock,
        )
        messages.extend(history)
        messages.append({"role": "user", "content": text})
        last_content = ""
        call_seq = 0  # 工具调用序号：跨步骤递增，用于派生幂等键
        for _step in range(MAX_STEPS):
            try:
                result = await self._gateway.chat(
                    alias=FRIDAY_ALIAS,
                    messages=messages,
                    tools=tool_schemas(),
                    trace_id=trace_id,
                    user_id=user.id,
                )
            except BudgetExceededError:
                logger.warning("llm daily limit reached: user_id=%s trace_id=%s", user.id, trace_id)
                return BUDGET_EXCEEDED_REPLY
            if not result.tool_calls:
                return result.content or ""
            messages.append(_assistant_message(result))
            for tc in result.tool_calls:
                call_seq += 1
                tool_result: BaseModel = await execute_tool(
                    ctx, tc.name, tc.arguments, call_index=call_seq
                )
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": tool_result.model_dump_json()}
                )
            last_content = result.content or ""
        return last_content or "抱歉，这轮操作步骤太多了，请换个说法再试一次。"


async def _audit_memory_context(
    session: AsyncSession,
    *,
    user: User,
    channel: str,
    trace_id: str,
    source_event_id: uuid.UUID | None,
    context: MemoryContext,
    block_chars: int,
    clock: Clock,
    query: str,
) -> None:
    """把本轮注入的记忆写入 event_log；空注入且未降级时不写，避免噪音。"""
    if context.is_empty and not context.degraded:
        return
    items = (*context.slots, *context.preferences, *context.episodes)
    await append_event(
        session,
        user_id=user.id,
        channel=channel,
        direction="system",
        type="memory_context",
        payload={
            "query": query[:200],
            "memory_ids": context.memory_ids(),
            "items": [
                {
                    "id": str(item.id),
                    "type": item.type,
                    "slot_key": item.slot_key,
                    "source_class": item.source_class,
                    "similarity": None
                    if item.similarity is None
                    else round(item.similarity, 4),
                }
                for item in items
            ],
            "degraded": context.degraded,
            "degraded_reason": context.degraded_reason,
            "block_chars": block_chars,
        },
        trace_id=trace_id,
        clock=clock,
        idempotency_key=f"memory-context:{source_event_id}" if source_event_id else None,
    )


def _assistant_message(result: LLMResult) -> dict:
    return {
        "role": "assistant",
        "content": result.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
            }
            for tc in result.tool_calls
        ],
    }
