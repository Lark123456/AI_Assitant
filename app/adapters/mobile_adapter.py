"""MobileAdapter：手机渠道适配器。

手机没有服务端主动推送：回复由 InboundPipeline 直接写入 event_log，
App 通过 chat API 轮询获取。因此正常手机路径不会调用 send()；
保留它只为 adapter 注册、recovery 渠道过滤与能力声明。

MobileAdapter 不写 event_log，避免与 Pipeline 各存一份 outbound。
"""

from collections.abc import Callable
from typing import Any

from app.adapters.base import (
    Capabilities,
    ChannelAdapter,
    DeliveryResult,
    InboundEvent,
    OutboundIntent,
)


class MobileAdapter(ChannelAdapter):
    """手机渠道：入站由 HTTP 路由驱动，出站由 App 主动拉取。"""

    channel = "mobile"
    capabilities = Capabilities(
        can_push_unsolicited=False,
        can_update_message=False,
        supports_buttons=False,
        streaming=False,
    )

    async def start(self, on_event: Callable[[InboundEvent], Any]) -> None:
        """手机渠道由 API 路由驱动，无需后台监听。"""

    async def send(self, intent: OutboundIntent) -> DeliveryResult:
        """防御性 no-op：不发送、不落库，仅声明成功。"""
        return DeliveryResult(ok=True)
