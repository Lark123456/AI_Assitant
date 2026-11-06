"""入站管道：白名单 → onboard → 去重落库（ingest，3 秒内）→ 异步处理（process）。

阶段 1 修订 2：
- ingest 同时写入 inbound_processing（status=processing），process 结束置 done/failed；
  服务启动时补处理仍为 processing 的事件（工具幂等键保证重放不重复写）。
- process 事务拆分：agent+工具先 commit，再发送回复，outbound 事件另开事务记录；
  LLM 调用前先释放读事务，避免长时间占用连接。
- 白名单 ALLOWED_OPEN_IDS 对所有渠道生效（配置了名单即只放名单内的外部 id）。
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
from app.db.models import EventLog, InboundProcessing, User
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
        if self._allowed_open_ids and event.external_user_id not in self._allowed_open_ids:
            logger.warning(
                "message from external id outside ALLOWED_OPEN_IDS dropped: channel=%s",
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
            if created:
                # 处理状态与入站事件同一事务写入；崩溃后由启动补处理兜底
                session.add(
                    InboundProcessing(
                        event_id=row.id,
                        user_id=user.id,
                        status="processing",
                        updated_at=self._clock.now(),
                    )
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
        """Friday 处理并回复；由调用方放入后台任务执行。意外崩溃时置 failed。"""
        if not ingested.created:
            return
        try:
            await self._process_one(ingested)
        except Exception:
            logger.exception("inbound processing crashed: event_id=%s", ingested.event_id)
            await self._mark_status(ingested.event_id, "failed")

    async def _process_one(self, ingested: IngestedEvent) -> None:
        with log_context(trace_id=ingested.trace_id, user_id=str(ingested.user_id)):
            adapter = self._adapters[ingested.event.channel]
            # 事务 A：agent + 工具写入。先短读用户并 commit 释放连接，再进 LLM 循环，
            # 避免第一次模型调用期间持有事务。
            async with self._sessionmaker() as session:
                user = await session.get(User, ingested.user_id)
                assert user is not None  # ingest 已确保用户存在
                await session.commit()
                # 提前取时区：异常路径 rollback 会使 ORM 对象过期，不能再访问属性
                user_tz = user.timezone
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
                    reply = FALLBACK_REPLY.format(trace=ingested.trace_id[:8])
                await session.commit()

            if ingested.is_new_user and reply:
                # 首答确定性告知所用时区（不走 LLM）
                reply = (
                    f"{reply}\n\n（当前使用时区 {user_tz}，"
                    f'如需修改请说「把时区设置为 …」）'
                )
            if not reply:
                await self._mark_status(ingested.event_id, "done")
                return

            # 发送回复：此刻不持有任何数据库事务
            try:
                result = await adapter.send(
                    OutboundIntent(
                        type="text",
                        user_id=ingested.user_id,
                        body={"text": reply},
                        reply_to_event_id=ingested.event_id,
                    )
                )
            except Exception:
                # 发送失败也要把 outbound 事件落库（send_ok=False），不能炸掉整个任务
                logger.exception("adapter send failed")
                result = DeliveryResult(ok=False, error="send raised")

            # 事务 B：outbound 事件与处理状态另开事务记录
            async with self._sessionmaker() as session:
                await append_event(
                    session,
                    user_id=ingested.user_id,
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
                await self._apply_status(session, ingested.event_id, "done")
                await session.commit()

    async def recover_unfinished(self) -> int:
        """启动补处理：重放状态仍为 processing 的入站事件（工具幂等键保证不重复写）。

        只处理本服务持有 adapter 的渠道；其余渠道由对应服务补处理。
        """
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(InboundProcessing, EventLog)
                        .join(EventLog, InboundProcessing.event_id == EventLog.id)
                        .where(InboundProcessing.status == "processing")
                    )
                )
                .all()
            )
        count = 0
        for proc, event in rows:
            if event.channel not in self._adapters:
                logger.info(
                    "skip recovery (no adapter in this service): channel=%s event_id=%s",
                    event.channel, event.id,
                )
                continue
            logger.info("recovering unfinished inbound event: id=%s", event.id)
            count += 1
            await self.process(
                IngestedEvent(
                    event=InboundEvent(
                        channel=event.channel,
                        external_user_id="",  # 发送走 user_id → 渠道身份解析，无需外部 id
                        kind=event.payload.get("kind", "message"),
                        text=event.payload.get("text", ""),
                    ),
                    event_id=event.id,
                    user_id=proc.user_id,
                    trace_id=event.trace_id,
                    is_new_user=False,
                    created=True,
                )
            )
        if count:
            logger.info("startup: recovered %d unfinished inbound events", count)
        return count

    async def _mark_status(self, event_id: uuid.UUID, status: str) -> None:
        try:
            async with self._sessionmaker() as session:
                await self._apply_status(session, event_id, status)
                await session.commit()
        except Exception:
            logger.exception("failed to mark inbound_processing status: event_id=%s", event_id)

    async def _apply_status(
        self, session: AsyncSession, event_id: uuid.UUID, status: str
    ) -> None:
        """更新处理状态；迁移前的旧事件没有状态行，跳过即可。"""
        row = await session.get(InboundProcessing, event_id)
        if row is None:
            return
        row.status = status
        row.updated_at = self._clock.now()

    async def handle(self, event: InboundEvent) -> None:
        """便捷入口：ingest + process（测试与简单场景用）。"""
        ingested = await self.ingest(event)
        if ingested is None:
            return
        await self.process(ingested)
