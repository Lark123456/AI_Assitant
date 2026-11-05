"""入站管道：白名单 → onboard → 去重落库（ingest，3 秒内）→ 异步处理（process）。

渠道回调只同步等待 ingest；process 由调用方放入后台执行。
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.base import ChannelAdapter, DeliveryResult, InboundEvent, OutboundIntent
from app.agents.friday.agent import FridayAgent
from app.core.clock import Clock
from app.core.config import Settings
from app.core.ids import new_trace_id
from app.core.logging import get_logger, log_context
from app.db.models import User
from app.engine.events import append_event
from app.engine.users import get_or_create_user
from app.llm.gateway import LLMGateway

logger = get_logger(__name__)

# 处理链路故障时的兜底回复；带 trace 片段便于用户报障后定位日志
FALLBACK_REPLY = "抱歉，我这边出了点故障，这条消息没能处理，请稍后再试。（trace: {trace}）"


@dataclass(frozen=True)
class IngestedEvent:
    """ingest 的结果：process 所需的全部上下文。"""

    event: InboundEvent
    event_id: uuid.UUID
    user_id: uuid.UUID
    trace_id: str
    is_new_user: bool
    created: bool  # 入站事件是否新写入（False = 重复事件）


class InboundPipeline:
    """一次入站事件的完整处理流程。"""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        settings: Settings,
        gateway: LLMGateway,
        adapters: dict[str, ChannelAdapter],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._settings = settings
        self._adapters = adapters
        self._friday = FridayAgent(gateway)
        self._allowed_open_ids = {
            x.strip() for x in settings.allowed_open_ids.split(",") if x.strip()
        }

    async def ingest(self, event: InboundEvent) -> IngestedEvent | None:
        """验证白名单并幂等落库；必须在渠道回调时限（3 秒）内返回。"""
        if (
            event.channel == "feishu"
            and self._allowed_open_ids
            and event.external_user_id not in self._allowed_open_ids
        ):
            logger.warning(
                "feishu message from open_id outside ALLOWED_OPEN_IDS dropped: channel=%s",
                event.channel,
            )
            return None
        trace_id = new_trace_id()
        async with self._sessionmaker() as session:
            user, is_new = await get_or_create_user(
                session,
                channel=event.channel,
                external_id=event.external_user_id,
                tenant_id=event.tenant_id,
                display_name=event.external_user_id,
                default_timezone=self._settings.default_timezone,
                clock=self._clock,
            )
            row, created = await append_event(
                session,
                user_id=user.id,
                channel=event.channel,
                direction="inbound",
                type=event.kind,
                payload={
                    "kind": event.kind,
                    "text": event.text,
                    "callback_payload": event.callback_payload,
                    "raw": event.raw,
                },
                trace_id=trace_id,
                clock=self._clock,
                idempotency_key=event.idempotency_key,
                occurred_at=event.occurred_at,
            )
            await session.commit()
        if not created:
            logger.info(
                "duplicate inbound event skipped: channel=%s key=%s",
                event.channel, event.idempotency_key,
            )
        return IngestedEvent(
            event=event,
            event_id=row.id,
            user_id=user.id,
            trace_id=trace_id,
            is_new_user=is_new,
            created=created,
        )

    async def process(self, ingested: IngestedEvent) -> None:
        """Friday 处理并回复；由调用方放入后台任务执行。"""
        if not ingested.created:
            return
        with log_context(trace_id=ingested.trace_id, user_id=str(ingested.user_id)):
            adapter = self._adapters[ingested.event.channel]
            async with self._sessionmaker() as session:
                user = (
                    await session.execute(select(User).where(User.id == ingested.user_id))
                ).scalar_one()
                try:
                    reply = await self._friday.handle(
                        session=session,
                        clock=self._clock,
                        settings=self._settings,
                        user=user,
                        trace_id=ingested.trace_id,
                        channel=ingested.event.channel,
                        source_event_id=ingested.event_id,
                        text=ingested.event.text,
                    )
                except Exception:
                    # 故障兜底：回滚事务（丢弃半途写入），回复兜底文案而非沉默
                    logger.exception("friday handle failed, replying fallback")
                    await session.rollback()
                    # rollback 使 user 过期，后续读取前显式刷新
                    await session.refresh(user)
                    reply = FALLBACK_REPLY.format(trace=ingested.trace_id[:8])
                if ingested.is_new_user and reply:
                    # 首答确定性告知所用时区（不走 LLM）
                    reply = (
                        f"{reply}\n\n（当前使用时区 {user.timezone}，"
                        f'如需修改请说「把时区设置为 …」）'
                    )
                if reply:
                    try:
                        result = await adapter.send(
                            OutboundIntent(
                                type="text",
                                user_id=user.id,
                                body={"text": reply},
                                reply_to_event_id=ingested.event_id,
                            )
                        )
                    except Exception:
                        # 发送失败也要把 outbound 事件落库（send_ok=False），不能炸掉整个任务
                        logger.exception("adapter send failed")
                        result = DeliveryResult(ok=False, error="send raised")
                    await append_event(
                        session,
                        user_id=user.id,
                        channel=ingested.event.channel,
                        direction="outbound",
                        type="message",
                        payload={
                            "text": reply,
                            "send_ok": result.ok,
                            "provider_msg_id": result.provider_msg_id,
                        },
                        trace_id=ingested.trace_id,
                        clock=self._clock,
                    )
                await session.commit()

    async def handle(self, event: InboundEvent) -> None:
        """便捷入口：ingest + process（测试与简单场景用）。"""
        ingested = await self.ingest(event)
        if ingested is None:
            return
        await self.process(ingested)
