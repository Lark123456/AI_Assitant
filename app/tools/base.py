"""工具基座：统一返回结构与执行上下文。"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import User
from app.embeddings.service import EmbeddingService


class ToolResult(BaseModel):
    """契约规定的统一返回结构。"""

    status: str  # ok | pending_confirmation | error
    data: dict = {}
    message: str = ""


class ToolContext:
    """工具执行上下文：一次入站消息内的共享状态。"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        clock: Clock,
        settings: Settings,
        user: User,
        trace_id: str,
        channel: str,
        source_event_id: uuid.UUID | None,
        embedder: EmbeddingService | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        self.settings = settings
        self.user = user
        self.trace_id = trace_id
        self.channel = channel
        self.source_event_id = source_event_id
        self.embedder = embedder
        # 当前工具调用在整条入站消息内的序号（跨步骤递增），用于派生幂等键
        self.call_index: int = 0


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[ToolContext, dict], Awaitable[ToolResult]]
    write: bool = False  # 写工具的幂等键由代码按入站事件派生


def tool_schema(tool: ToolDef) -> dict:
    """生成 OpenAI function-calling 的 tools 条目。"""
    schema = tool.args_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description, "parameters": schema},
    }


def require_source_event_id(ctx: ToolContext) -> uuid.UUID:
    """写工具必须携带入站事件 id，否则拒绝执行（幂等键无从派生）。"""
    if ctx.source_event_id is None:
        raise ValueError("write tool requires source_event_id (inbound event)")
    return ctx.source_event_id
