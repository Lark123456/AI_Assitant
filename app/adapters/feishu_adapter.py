"""FeishuAdapter：飞书官方 SDK（lark-oapi）长连接收消息 + 发文本。

说明：
- 长连接模式由 SDK 维持鉴权，无需 HTTP 回调验签；入站幂等键优先用飞书 event_id，缺失时退回 message_id。
- confirm_card 阶段 1 降级为纯文本发送。
- 渠道细节只允许存在于本文件（adapters 目录）。
"""

import asyncio
import hashlib
import json
import uuid
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

from app.adapters.base import (
    Capabilities,
    ChannelAdapter,
    DeliveryResult,
    InboundEvent,
    OutboundIntent,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# 飞书消息体 uuid 字段上限 64 字符
_FEISHU_UUID_MAX = 64


def feishu_send_uuid(collapse_key: str | None) -> str | None:
    """发送幂等 uuid：取 collapse_key，超长取其 sha256；无 collapse_key 则不传。"""
    if not collapse_key:
        return None
    if len(collapse_key) <= _FEISHU_UUID_MAX:
        return collapse_key
    return hashlib.sha256(collapse_key.encode()).hexdigest()


class FeishuAdapter(ChannelAdapter):
    """飞书渠道适配：收消息（长连接）、发文本（im.v1.message.create）。"""

    channel = "feishu"
    capabilities = Capabilities(can_push_unsolicited=True, can_update_message=False, supports_buttons=False)

    def __init__(self, resolve_external_id: Any, *, app_id: str, app_secret: str) -> None:
        super().__init__(resolve_external_id)
        self._app_id = app_id
        self._app_secret = app_secret
        self._client: Any = None
        self._ws_client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_clients(self) -> None:
        if self._client is not None:
            return
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        self._lark = lark
        self._CreateMessageRequest = CreateMessageRequest
        self._CreateMessageRequestBody = CreateMessageRequestBody
        self._client = lark.Client.builder().app_id(self._app_id).app_secret(self._app_secret).build()

    async def start(self, on_event: Any) -> None:
        """启动长连接监听；SDK 的 start() 是阻塞调用，放入后台线程。

        回调只同步等待落库（上限 3 秒）：ingest 超时则转入后台继续，
        SDK 线程不被阻塞。
        """
        self._ensure_clients()
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

        lark_api = self._lark
        loop = asyncio.get_running_loop()
        self._loop = loop

        def _on_message(data: P2ImMessageReceiveV1) -> None:
            try:
                event = self._to_inbound_event(data)
            except Exception:
                logger.exception("failed to parse feishu event")
                return
            if event is None:
                return
            future = asyncio.run_coroutine_threadsafe(on_event(event), loop)
            try:
                future.result(timeout=3.0)
            except FuturesTimeoutError:
                logger.warning("feishu ingest exceeded 3s, continuing in background")
            except Exception:
                logger.exception("feishu ingest failed")

        handler = (
            lark_api.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message)
            .build()
        )
        self._ws_client = lark_api.ws.Client(
            self._app_id, self._app_secret, event_handler=handler, log_level=lark.LogLevel.INFO
        )
        await asyncio.to_thread(self._ws_client.start)

    def _to_inbound_event(self, data: Any) -> InboundEvent | None:
        """把 SDK 事件转成规范 InboundEvent；仅处理文本消息。

        SDK 回调只传一个参数（P2ImMessageReceiveV1，继承 EventContext），
        event_id 与 tenant_key 位于其 header 上，而非独立的 ctx 参数。
        """
        event = data.event
        if event is None or event.message is None:
            return None
        message = event.message
        if message.message_type != "text":
            logger.info("skip non-text feishu message: type=%s", message.message_type)
            return None
        content = json.loads(message.content or "{}")
        sender = event.sender
        external_id = sender.sender_id.open_id if sender and sender.sender_id else ""
        if not external_id:
            return None
        occurred_ms = int(message.create_time) if message.create_time else None
        import datetime as dt

        occurred_at = (
            dt.datetime.fromtimestamp(occurred_ms / 1000, tz=dt.UTC) if occurred_ms else None
        )
        # 入站幂等键：优先飞书 event_id，缺失时退回 message_id
        header = getattr(data, "header", None)
        event_id = header.event_id if header else ""
        tenant_key = header.tenant_key if header else None
        idem = event_id or message.message_id or str(uuid.uuid4())
        return InboundEvent(
            channel="feishu",
            external_user_id=external_id,
            tenant_id=tenant_key,
            kind="message",
            text=content.get("text", ""),
            occurred_at=occurred_at,
            idempotency_key=idem,
            raw={"message_id": message.message_id, "chat_id": message.chat_id},
        )

    async def send(self, intent: OutboundIntent) -> DeliveryResult:
        """发送文本消息（confirm_card 等类型阶段 1 一律降级为文本）。

        传 uuid（collapse_key 或其哈希）作为发送幂等键：trigger 重试投递时
        飞书服务端按 uuid 去重，不会重复下发同一条提醒。
        """
        self._ensure_clients()
        open_id = await self.external_id_of(intent.user_id)
        if open_id is None:
            return DeliveryResult(ok=False, error="feishu: no open_id for user")
        text = intent.body.get("text", "")
        send_uuid = feishu_send_uuid(intent.collapse_key)
        request = (
            self._CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                self._CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .uuid(send_uuid)
                .build()
            )
            .build()
        )
        response = await asyncio.to_thread(self._client.im.v1.message.create, request)
        if not response.success():
            msg = f"feishu send failed: code={response.get_code()} msg={response.get_msg()}"
            logger.warning(msg)
            return DeliveryResult(ok=False, error=msg)
        data = response.data
        return DeliveryResult(ok=True, provider_msg_id=data.message_id if data else None)
