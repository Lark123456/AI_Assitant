"""Worker：领取到期 trigger → 校验前提 → 仲裁 → 投递。

阶段 1 修订：
- 领取即提交（attempts / claimed_at 持久化），崩溃后由租约回收兜底。
- 每轮回收 claimed_at 超过租约的记录：有余量回 pending，耗尽置 failed。
- 处理异常按指数退避（30s × 2^(n-1)）重试，上限 5 次，耗尽置 failed 并写 event_log。
- missed 只用于停机错过（到期处理时已过 expires_at）。
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.base import ChannelAdapter
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.feishu_adapter import FeishuAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import Clock
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.base import make_engine, make_sessionmaker
from app.db.models import ChannelIdentity, TriggerInstance
from app.engine.delivery import deliver_trigger_nudge
from app.engine.events import append_event
from app.engine.gate import PassthroughGate
from app.engine.triggers import (
    check_precondition,
    claim_due_triggers,
    reclaim_expired_leases,
    record_trigger_failure,
    reset_stale_claimed,
)

logger = get_logger(__name__)

PREFERRED_CHANNELS = ("feishu", "console")  # 投递渠道优先级


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
    gate: PassthroughGate,
) -> None:
    """单条 trigger 的处理：过期→missed；前提失败→dropped；否则投递→fired。"""
    trace_id: str = trigger.payload.get("trace_id", "")
    now = clock.now()
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
        )
        logger.info(
            "trigger missed (expired): id=%s kind=%s fire_at=%s",
            trigger.id,
            trigger.kind,
            trigger.fire_at.isoformat(),
        )
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
        )
        logger.info("trigger dropped (precondition): id=%s reason=%s", trigger.id, reason)
        return

    adapter = await resolve_channel(session, trigger.user_id, adapters)
    if adapter is None:
        trigger.status = "dropped"
        logger.error("no channel to deliver trigger %s for user %s", trigger.id, trigger.user_id)
        return
    await deliver_trigger_nudge(session, trigger=trigger, adapter=adapter, clock=clock, gate=gate)
    trigger.status = "fired"
    logger.info("trigger fired: id=%s kind=%s channel=%s", trigger.id, trigger.kind, adapter.channel)


async def process_claimed_trigger(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    trigger_id: uuid.UUID,
    adapters: dict[str, ChannelAdapter],
    clock: Clock,
    gate: PassthroughGate,
) -> bool:
    """处理一条已领取的 trigger。成功返回 True；失败时记录退避或置 failed。"""
    try:
        async with sessionmaker() as session:
            trigger = await session.get(TriggerInstance, trigger_id)
            if trigger is None or trigger.status != "claimed":
                return True  # 已被回收或已终态
            await process_trigger(session, trigger=trigger, adapters=adapters, clock=clock, gate=gate)
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


async def run_worker() -> None:
    """worker 主循环。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    clock = Clock()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)

    adapters: dict[str, ChannelAdapter] = {
        "console": ConsoleAdapter(make_identity_resolver(sessionmaker, "console"))
    }
    if settings.feishu_app_id and settings.feishu_app_secret:
        # worker 只用发送客户端，不启动长连接
        adapters["feishu"] = FeishuAdapter(
            make_identity_resolver(sessionmaker, "feishu"),
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
        )
    gate = PassthroughGate()

    # 启动复位上次运行遗留的 claimed（单实例 worker 安全）
    async with sessionmaker() as session:
        reset = await reset_stale_claimed(session)
        if reset:
            logger.info("startup: reset %d stale claimed triggers to pending", reset)
        await session.commit()

    while True:
        # 1) 回收租约超时的 claimed
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

        # 2) 领取并立即提交，保证 claimed_at / attempts 落库
        async with sessionmaker() as session:
            claimed = await claim_due_triggers(
                session, now=clock.now(), limit=settings.worker_batch_size
            )
            await session.commit()
        for trigger in claimed:
            await process_claimed_trigger(
                sessionmaker, trigger_id=trigger.id, adapters=adapters, clock=clock, gate=gate
            )
        await asyncio.sleep(settings.worker_poll_interval)


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
