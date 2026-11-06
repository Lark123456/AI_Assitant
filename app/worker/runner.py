"""Worker：物化 → 领取到期 trigger → 前提校验 → 候选 → 仲裁 → 投递。

阶段 2：
- 每轮按 interval 运行物化器（brief 触发、规则候选）。
- trigger 处理走 handlers（kind → 候选）与 nudge（仲裁 → 发送/延后/合并/丢弃）。
- 唯一发送出口在 nudge.send；defer 不消耗 attempts。
"""

import asyncio
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.base import ChannelAdapter
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.feishu_adapter import FeishuAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.ids import new_trace_id
from app.core.logging import get_logger, setup_logging
from app.core.tasks import spawn
from app.db.base import make_engine, make_sessionmaker
from app.db.models import ChannelIdentity, TriggerInstance, User
from app.embeddings.service import build_embedding_service
from app.engine.events import append_event
from app.engine.handlers import build_candidates
from app.engine.materializer import get_or_create_prefs, run_materializer
from app.engine.nudge import (
    arbitrate_pending_suggestions,
    get_or_create_candidate,
    process_candidate,
)
from app.engine.triggers import (
    check_precondition,
    claim_due_triggers,
    reclaim_expired_leases,
    record_trigger_failure,
    reset_stale_claimed,
)
from app.llm.gateway import LLMGateway
from app.llm.providers.base import BaseProvider
from app.llm.providers.openai_compat import OpenAICompatProvider
from app.memory.runs import memory_worker_loop

logger = get_logger(__name__)

PREFERRED_CHANNELS = ("feishu", "console")  # 投递渠道优先级
LATE_DROP_GRACE_MINUTES = 5


async def resolve_channel(
    session: AsyncSession, user_id: uuid.UUID, adapters: dict[str, ChannelAdapter]
) -> ChannelAdapter | None:
    """按用户已有的渠道身份选择投递渠道（优先飞书）。"""
    for channel in PREFERRED_CHANNELS:
        if channel not in adapters:
            continue
        row = (
            await session.execute(
                select(ChannelIdentity).where(
                    ChannelIdentity.user_id == user_id, ChannelIdentity.channel == channel
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            return adapters[channel]
    return None


async def process_trigger(
    session: AsyncSession,
    *,
    trigger: TriggerInstance,
    adapters: dict[str, ChannelAdapter],
    clock: Clock,
    settings: Settings,
    gateway: LLMGateway | None,
) -> None:
    """单条 trigger：过期/前提/渠道校验后产出候选并交给仲裁器。"""
    trace_id: str = trigger.payload.get("trace_id", "") or new_trace_id()
    now = clock.now()

    # 停机补偿：超过 expires_at 即 missed；policy=drop 时提醒超过宽限即 dropped
    if trigger.expires_at is not None and trigger.expires_at < now:
        trigger.status = "missed"
        await append_event(
            session,
            user_id=trigger.user_id,
            channel="system",
            direction="system",
            type="trigger",
            payload={"trigger_id": str(trigger.id), "status": "missed", "kind": trigger.kind},
            trace_id=trace_id,
            clock=clock,
            idempotency_key=f"trigger-missed:{trigger.id}",
        )
        logger.info("trigger missed (expired): id=%s kind=%s", trigger.id, trigger.kind)
        return
    if (
        settings.reminder_late_policy == "drop"
        and trigger.kind == "reminder"
        and now > trigger.fire_at + dt.timedelta(minutes=LATE_DROP_GRACE_MINUTES)
    ):
        trigger.status = "dropped"
        await append_event(
            session,
            user_id=trigger.user_id,
            channel="system",
            direction="system",
            type="trigger",
            payload={
                "trigger_id": str(trigger.id),
                "status": "dropped",
                "kind": trigger.kind,
                "reason": "late_policy_drop",
            },
            trace_id=trace_id,
            clock=clock,
            idempotency_key=f"trigger-late-dropped:{trigger.id}",
        )
        logger.info("trigger dropped (late policy): id=%s kind=%s", trigger.id, trigger.kind)
        return

    ok, reason = await check_precondition(session, trigger)
    if not ok:
        trigger.status = "dropped"
        await append_event(
            session,
            user_id=trigger.user_id,
            channel="system",
            direction="system",
            type="trigger",
            payload={
                "trigger_id": str(trigger.id),
                "status": "dropped",
                "kind": trigger.kind,
                "reason": reason,
            },
            trace_id=trace_id,
            clock=clock,
            idempotency_key=f"trigger-dropped:{trigger.id}",
        )
        logger.info("trigger dropped (precondition): id=%s reason=%s", trigger.id, reason)
        return

    adapter = await resolve_channel(session, trigger.user_id, adapters)
    if adapter is None:
        trigger.status = "dropped"
        logger.error("no channel to deliver trigger %s for user %s", trigger.id, trigger.user_id)
        return

    user = await session.get(User, trigger.user_id)
    if user is None:
        trigger.status = "failed"
        trigger.last_error = "user not found"
        return
    prefs = await get_or_create_prefs(session, user.id, clock)

    result = build_candidates(trigger)
    if result.signal is not None:
        await append_event(
            session,
            user_id=user.id,
            channel="system",
            direction="system",
            type="signal",
            payload=result.signal,
            trace_id=trace_id,
            clock=clock,
            idempotency_key=f"signal:{trigger.id}",
        )
        trigger.status = "fired"
        return

    outcomes = []
    for draft in result.candidates:
        candidate = await get_or_create_candidate(session, trigger=trigger, draft=draft)
        outcomes.append(
            await process_candidate(
                session,
                user=user,
                prefs=prefs,
                candidate=candidate,
                trigger=trigger,
                adapter=adapter,
                clock=clock,
                settings=settings,
                gateway=gateway,
                trace_id=trace_id,
            )
        )

    if any(outcome.decision == "defer" for outcome in outcomes):
        # process_candidate 已把 trigger 退回 pending 并设置 next_attempt_at
        return
    failed = next(
        (o for o in outcomes if o.decision == "send" and not o.delivered), None
    )
    if failed is not None:
        # 审计先行：失败尝试的 decision 与 delivery(error) 必须先提交，
        # 之后的重试/回滚不能把它们抹掉；重试调度由 _record_failure 另开会话完成
        await session.commit()
        logger.warning("trigger delivery failed, audit committed: id=%s error=%s", trigger.id, failed.error)
        raise RuntimeError(f"trigger delivery failed: {failed.error}")
    if all(outcome.decision == "drop" for outcome in outcomes):
        trigger.status = "dropped"
        return
    trigger.status = "fired"
    logger.info("trigger fired: id=%s kind=%s channel=%s", trigger.id, trigger.kind, adapter.channel)


async def process_claimed_trigger(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    trigger_id: uuid.UUID,
    adapters: dict[str, ChannelAdapter],
    clock: Clock,
    settings: Settings,
    gateway: LLMGateway | None = None,
) -> bool:
    """处理一条已领取的 trigger。成功返回 True；失败时记录退避或置 failed。"""
    try:
        async with sessionmaker() as session:
            trigger = await session.get(TriggerInstance, trigger_id)
            if trigger is None or trigger.status != "claimed":
                return True  # 已被回收或已终态
            await process_trigger(
                session,
                trigger=trigger,
                adapters=adapters,
                clock=clock,
                settings=settings,
                gateway=gateway,
            )
            await session.commit()
        return True
    except Exception as exc:
        logger.exception("trigger processing failed: id=%s", trigger_id)
        await _record_failure(sessionmaker, trigger_id=trigger_id, exc=exc, clock=clock)
        return False


async def _record_failure(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    trigger_id: uuid.UUID,
    exc: Exception,
    clock: Clock,
) -> None:
    """失败处理走独立事务：退避回 pending，次数耗尽置 failed 并写 event_log。"""
    async with sessionmaker() as session:
        trigger = await record_trigger_failure(
            session, trigger_id=trigger_id, error=f"{type(exc).__name__}: {exc}", now=clock.now()
        )
        if trigger is not None and trigger.status == "failed":
            await append_event(
                session,
                user_id=trigger.user_id,
                channel="system",
                direction="system",
                type="trigger",
                payload={
                    "trigger_id": str(trigger.id),
                    "status": "failed",
                    "kind": trigger.kind,
                    "last_error": trigger.last_error,
                    "attempts": trigger.attempts,
                },
                trace_id=trigger.payload.get("trace_id", ""),
                clock=clock,
            )
        await session.commit()


def build_gateway(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> LLMGateway:
    """构造与 api/feishu 服务一致的网关（brief_compose 需要）。"""
    providers: dict[str, BaseProvider] = {
        "openai_compat": OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key),
        "openai_compat_agent": OpenAICompatProvider(
            settings.llm_agent_base_url, settings.llm_agent_api_key
        ),
    }
    return LLMGateway(
        aliases_path=settings.aliases_path,
        providers=providers,
        sessionmaker=sessionmaker,
        clock=clock,
        daily_limit=settings.llm_daily_limit,
    )


async def run_worker() -> None:
    """worker 主循环：物化 → 回收租约 → 领取 → 处理。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    clock = Clock()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    gateway = build_gateway(settings, sessionmaker, clock)

    adapters: dict[str, ChannelAdapter] = {
        "console": ConsoleAdapter(make_identity_resolver(sessionmaker, "console"))
    }
    if settings.feishu_app_id and settings.feishu_app_secret:
        adapters["feishu"] = FeishuAdapter(
            make_identity_resolver(sessionmaker, "feishu"),
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
        )

    async with sessionmaker() as session:
        reset = await reset_stale_claimed(session)
        if reset:
            logger.info("startup: reset %d stale claimed triggers to pending", reset)
        await session.commit()

    spawn(
        memory_worker_loop(
            sessionmaker,
            gateway=gateway,
            embedder=build_embedding_service(settings),
            clock=clock,
            settings=settings,
        )
    )

    last_materialized: dt.datetime | None = None
    while True:
        now = clock.now()
        if (
            last_materialized is None
            or (now - last_materialized).total_seconds() >= settings.materialize_interval_seconds
        ):
            await run_materializer(sessionmaker, clock=clock, settings=settings)
            await arbitrate_pending_suggestions(sessionmaker, clock=clock, settings=settings)
            last_materialized = now

        async with sessionmaker() as session:
            reclaimed = await reclaim_expired_leases(
                session, now=clock.now(), lease_seconds=settings.trigger_lease_seconds
            )
            for trigger in reclaimed:
                if trigger.status == "failed":
                    await append_event(
                        session,
                        user_id=trigger.user_id,
                        channel="system",
                        direction="system",
                        type="trigger",
                        payload={
                            "trigger_id": str(trigger.id),
                            "status": "failed",
                            "kind": trigger.kind,
                            "last_error": trigger.last_error,
                            "attempts": trigger.attempts,
                        },
                        trace_id=trigger.payload.get("trace_id", ""),
                        clock=clock,
                    )
            if reclaimed:
                await session.commit()

        async with sessionmaker() as session:
            claimed = await claim_due_triggers(
                session, now=clock.now(), limit=settings.worker_batch_size
            )
            await session.commit()
        for trigger in claimed:
            await process_claimed_trigger(
                sessionmaker,
                trigger_id=trigger.id,
                adapters=adapters,
                clock=clock,
                settings=settings,
                gateway=gateway,
            )
        await asyncio.sleep(settings.worker_poll_interval)


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
