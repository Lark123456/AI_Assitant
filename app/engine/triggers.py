"""trigger_instance 的幂等创建、SKIP LOCKED 领取、租约回收与退避重试。"""

import datetime as dt
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.ids import new_uuid7
from app.db.models import PlannedBlock, TriggerInstance, WorkItem

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
) -> tuple[TriggerInstance, bool]:
    """幂等创建 trigger：返回 (记录, 是否新建)；key 冲突时返回既有记录与 False。"""
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
        return row, True
    existing = (
        await session.execute(select(TriggerInstance).where(TriggerInstance.key == key))
    ).scalar_one()
    return existing, False


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
    """触发前重新校验前提；支持关联任务与计划块。"""
    precondition = trigger.precondition
    if not precondition:
        return True, ""
    if "block_id" in precondition:
        return await _check_block_precondition(session, precondition)
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


async def _check_block_precondition(
    session: AsyncSession, precondition: dict
) -> tuple[bool, str]:
    """计划块前提：仍为 planned 且（block_start）开始时间未变。"""
    raw_id = precondition.get("block_id")
    try:
        block_uuid = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        return False, f"计划块 id 非法：{raw_id}"
    block = await session.get(PlannedBlock, block_uuid)
    if block is None:
        return False, "计划块不存在"
    if block.status != "planned":
        return False, f"计划块已{block.status}"
    expected_starts = precondition.get("expected_starts_at")
    if expected_starts:
        try:
            expected = dt.datetime.fromisoformat(str(expected_starts))
        except ValueError:
            return False, f"计划块时间格式非法：{expected_starts}"
        # 数据库取回的是 UTC aware，payload 里是原始时区字符串；必须按时刻比较而非字符串
        if block.starts_at != expected:
            return False, "计划块时间已变更"
    return True, ""
