"""规则引擎：声明式 SQL 产出 suggestion 候选，不调用 LLM。

每条规则的候选按 dedupe_key 含「规则名 + 本地日期」做同日幂等。
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.timeutil import day_window_utc, local_date_of
from app.db.models import EventLog, NudgeCandidate, User, WorkItem

STALE_TASK_DAYS = 7
STALE_TASK_LIMIT = 3
OVERDUE_SIGNAL_WINDOW_HOURS = 24
OVERDUE_SIGNAL_MIN_BLOCKS = 2


async def _candidate_exists(session: AsyncSession, user_id: object, dedupe_key: str) -> bool:
    row = (
        await session.execute(
            select(NudgeCandidate.id)
            .where(
                NudgeCandidate.user_id == user_id,
                NudgeCandidate.dedupe_key == dedupe_key,
            )
            .limit(1)
        )
    ).first()
    return row is not None


async def create_suggestion_candidates(
    session: AsyncSession, *, user: User, clock: Clock
) -> int:
    """评估全部规则并创建当日候选；同日重复运行不产生重复候选。"""
    now = clock.now()
    local_day = local_date_of(now, user.timezone, user.day_start)
    _, day_end = day_window_utc(now, user.timezone, user.day_start)
    created = 0

    # 规则 1：过去 24 小时至少 2 条 overdue 信号（不同计划块）
    signals = (
        (
            await session.execute(
                select(EventLog.payload).where(
                    EventLog.user_id == user.id,
                    EventLog.type == "signal",
                    EventLog.occurred_at >= now - dt.timedelta(hours=OVERDUE_SIGNAL_WINDOW_HOURS),
                )
            )
        )
        .scalars()
        .all()
    )
    block_ids = {str(p.get("block_id")) for p in signals if p.get("block_id")}
    if len(block_ids) >= OVERDUE_SIGNAL_MIN_BLOCKS:
        key = f"suggestion.overdue_blocks:{local_day.isoformat()}"
        if not await _candidate_exists(session, user.id, key):
            session.add(
                NudgeCandidate(
                    user_id=user.id,
                    class_="suggestion",
                    reason_code="suggestion.overdue_blocks",
                    reason_text=f"过去 24 小时有 {len(block_ids)} 个计划块逾期未完成",
                    value_score=0.6,
                    expires_at=day_end,
                    dedupe_key=key,
                    explicit=False,
                )
            )
            created += 1

    # 规则 2：active 任务 7 天无变化，最多列 3 个
    stale_titles = (
        (
            await session.execute(
                select(WorkItem.title)
                .where(
                    WorkItem.user_id == user.id,
                    WorkItem.status == "active",
                    WorkItem.updated_at < now - dt.timedelta(days=STALE_TASK_DAYS),
                )
                .order_by(WorkItem.updated_at)
                .limit(STALE_TASK_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if stale_titles:
        key = f"suggestion.stale_tasks:{local_day.isoformat()}"
        if not await _candidate_exists(session, user.id, key):
            session.add(
                NudgeCandidate(
                    user_id=user.id,
                    class_="suggestion",
                    reason_code="suggestion.stale_tasks",
                    reason_text="这些任务很久没动了：" + "、".join(stale_titles),
                    value_score=0.5,
                    expires_at=day_end,
                    dedupe_key=key,
                    explicit=False,
                )
            )
            created += 1

    await session.flush()
    return created
