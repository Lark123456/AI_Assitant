"""ChannelAdapter 契约接口（见 docs/contracts.md）：渠道无关的核心只依赖这些类型。"""

import datetime as dt
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel


class InboundEvent(BaseModel):
    """渠道入站事件的规范化表示。"""

    channel: str
    external_user_id: str
    tenant_id: str | None = None
    kind: str  # message | callback
    text: str = ""
    attachments: list[dict] = []
    callback_payload: dict | None = None
    occurred_at: dt.datetime | None = None  # 缺省由管道按 Clock 补
    idempotency_key: str | None = None
    raw: dict = {}


class OutboundIntent(BaseModel):
    """出站消息意图，由 adapter 渲染为渠道具体格式。"""

    type: str  # text | confirm_card | choice | nudge
    user_id: uuid.UUID
    body: dict
    reply_to_event_id: uuid.UUID | None = None
    collapse_key: str | None = None


class Capabilities(BaseModel):
    """渠道能力声明。"""

    can_push_unsolicited: bool = False
    push_credits: int | None = None
    can_update_message: bool = False
    supports_buttons: bool = False
    streaming: bool = False


class DeliveryResult(BaseModel):
    """send/update 的返回。"""

    ok: bool
    provider_msg_id: str | None = None
    error: str | None = None


IdentityResolver = Callable[[uuid.UUID], Awaitable[str | None]]


class ChannelAdapter(ABC):
    """渠道适配器基类。核心代码只面向本接口，不 import 任何渠道 SDK。"""

    channel: str
    capabilities: Capabilities

    def __init__(self, resolve_external_id: IdentityResolver) -> None:
        self._resolve_external_id = resolve_external_id

    @abstractmethod
    async def start(
        self, on_event: Callable[[InboundEvent], Any]
    ) -> None:
        """启动渠道监听，把入站事件交给回调。"""

    @abstractmethod
    async def send(self, intent: OutboundIntent) -> DeliveryResult:
        """发送出站意图。"""

    async def update(self, provider_msg_id: str, intent: OutboundIntent) -> DeliveryResult:
        """更新已发送消息（仅当 can_update_message）。"""
        raise NotImplementedError(f"channel {self.channel} cannot update messages")

    async def external_id_of(self, user_id: uuid.UUID) -> str | None:
        """内部 user_id -> 渠道外部 id。"""
        return await self._resolve_external_id(user_id)
