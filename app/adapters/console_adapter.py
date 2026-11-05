"""ConsoleAdapter：本地 HTTP 渠道，用于开发与端到端测试。"""

from collections import defaultdict
from typing import Any

from app.adapters.base import Capabilities, ChannelAdapter, DeliveryResult, OutboundIntent
from app.core.ids import new_id


class ConsoleAdapter(ChannelAdapter):
    """把出站消息存进内存队列，通过 GET /console/messages 读取。"""

    channel = "console"
    capabilities = Capabilities(can_push_unsolicited=True, can_update_message=False)

    def __init__(self, resolve_external_id: Any) -> None:
        super().__init__(resolve_external_id)
        self.outbox: dict[str, list[dict]] = defaultdict(list)

    async def start(self, on_event: Any) -> None:
        """Console 渠道由 HTTP 路由驱动，无需后台监听。"""

    async def send(self, intent: OutboundIntent) -> DeliveryResult:
        external_id = await self.external_id_of(intent.user_id)
        if external_id is None:
            return DeliveryResult(ok=False, error="console: no external id for user")
        msg_id = new_id()
        self.outbox[external_id].append(
            {
                "provider_msg_id": msg_id,
                "type": intent.type,
                "body": intent.body,
                "reply_to_event_id": str(intent.reply_to_event_id) if intent.reply_to_event_id else None,
            }
        )
        return DeliveryResult(ok=True, provider_msg_id=msg_id)

    def messages_for(self, external_user_id: str) -> list[dict]:
        """读取某外部用户的出站消息（测试与人工查看）。"""
        return list(self.outbox[external_user_id])
