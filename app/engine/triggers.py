"""trigger_instance 的幂等创建、SKIP LOCKED 领取、租约回收与退避重试。"""

import datetime as dt
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.ids import new_uuid7
from app.db.models import TriggerInstance, WorkItem

TRIGGER_MAX_ATTEMPTS = 5
TRIGGER_BACKOFF_BASE_SECONDS = 30.0


def trigger_backoff_seconds(attempts: int) -> float:
    """第 n 次失败后的退避时长：30s × 2^(n-1)。"""
    return float(TRIGGER_BACKOFF_BASE_SECONDS * (2 ** (attempts - 1)))


async def create_trigger(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    key: str,
    fire_at: dt.datetime,
    tz: str,
    payload: dict,
    precondition: dict | None = None,
    expires_at: dt.datetime | None = None,
    clock: Clock,
) -> TriggerInstance:
    """幂等创建 trigger：key 冲突时返回既有记录。"""
    values = {
        "id": new_uuid7(),
        "user_id": user_id,
        "kind": kind,
        "key": key,
        "fire_at": fire_at,
        "tz": tz,
        "precondition": precondition,
        "payload": payload,
        "status": "pending",
        "expires_at": expires_at,
        "created_at": clock.now(),
    }
    stmt = (
        pg_insert(TriggerInstance)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["key"])
        .returning(TriggerInstance)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    existing = (
        await session.execute(select(TriggerInstance).where(TriggerInstance.key == key))
    ).scalar_one()
    return existing


async def claim_due_triggers(
    session: AsyncSession, *, now: dt.datetime, limit: int
) -> list[TriggerInstance]:
    """用 FOR UPDATE SKIP LOCKED 领取到期的 pending trigger。

    领取即持久化 attempts 与 claimed_at；崩溃后由租约回收兜底。
    只领取：到期、未在退避等待、且重试次数未耗尽的记录。
    """
    subq = (
        select(TriggerInstance.id)
        .where(
            TriggerInstance.status == "pending",
            TriggerInstance.fire_at <= now,
            TriggerInstance.attempts < TRIGGER_MAX_ATTEMPTS,
            or_(
                TriggerInstance.next_attempt_at.is_(None),
                TriggerInstance.next_attempt_at <= now,
            ),
        )
        .order_by(TriggerInstance.fire_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    stmt = (
        update(TriggerInstance)
        .where(TriggerInstance.id.in_(subq))
        .values(
            status="claimed",
            claimed_at=now,
            attempts=TriggerInstance.attempts + 1,
        )
        .returning(TriggerInstance)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def reclaim_expired_leases(
    session: AsyncSession, *, now: dt.datetime, lease_seconds: float
) -> list[TriggerInstance]:
    """回收租约超时的 claimed trigger：仍有重试余量回 pending，否则置 failed。"""
    cutoff = now - dt.timedelta(seconds=lease_seconds)
    rows = (
        (
            await session.execute(
                select(TriggerInstance)
                .where(
                    TriggerInstance.status == "claimed",
                    TriggerInstance.claimed_at.is_not(None),
                    TriggerInstance.claimed_at < cutoff,
                )
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for trigger in rows:
        if trigger.attempts >= TRIGGER_MAX_ATTEMPTS:
            trigger.status = "failed"
            trigger.last_error = "lease expired after max attempts"
        else:
            trigger.status = "pending"
            trigger.next_attempt_at = now
            trigger.last_error = "lease expired"
    return list(rows)


async def record_trigger_failure(
    session: AsyncSession, *, trigger_id: uuid.UUID, error: str, now: dt.datetime
) -> TriggerInstance | None:
    """处理异常后的退避重试：次数耗尽置 failed，否则回 pending 并按指数退避安排重试。"""
    trigger = await session.get(TriggerInstance, trigger_id)
    if trigger is None:
        return None
    trigger.last_error = error[:500]
    if trigger.attempts >= TRIGGER_MAX_ATTEMPTS:
        trigger.status = "failed"
    else:
        trigger.status = "pending"
        trigger.next_attempt_at = now + dt.timedelta(
            seconds=trigger_backoff_seconds(trigger.attempts)
        )
    return trigger


async def reset_stale_claimed(session: AsyncSession) -> int:
    """启动时把上次运行遗留的 claimed 状态复位为 pending（单实例 worker 安全）。"""
    stmt = (
        update(TriggerInstance)
        .where(TriggerInstance.status == "claimed")
        .values(status="pending")
        .returning(TriggerInstance.id)
    )
    result = await session.execute(stmt)
    return len(result.scalars().all())


async def check_precondition(
    session: AsyncSession, trigger: TriggerInstance
) -> tuple[bool, str]:
    """触发前重新校验前提；阶段 1 仅支持关联任务未完成/未放弃。"""
    precondition = trigger.precondition
    if not precondition:
        return True, ""
    task_id = precondition.get("task_id")
    if not task_id:
        return True, ""
    try:
        item_uuid = uuid.UUID(str(task_id))
    except ValueError:
        return False, f"关联任务 id 非法：{task_id}"
    item = (
        await session.execute(select(WorkItem).where(WorkItem.id == item_uuid))
    ).scalar_one_or_none()
    if item is None:
        return False, f"关联任务不存在：{task_id}"
    if item.status in ("done", "dropped"):
        return False, f"关联任务已{item.status}，取消提醒"
    return True, ""
