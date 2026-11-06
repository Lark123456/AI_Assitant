"""物化器：保证未来窗口内的 trigger 实例存在；设置变更后重算（旧实例 superseded）。

幂等约定：
- 简报 key = brief_morning|brief_evening:{user_id}:{local_date}
- 块 key = block_start|overdue_check:{block_id}:{rev}
- 时间/时区/开关变化时，未触发的旧实例写 dropped（reason=superseded）并删除，
  使同 key 可被重建；event_log 保留完整的变更证据。
"""

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.timeutil import local_date_of
from app.db.models import NotifPrefs, PlannedBlock, TriggerInstance, User
from app.engine.events import append_event
from app.engine.nudge_rules import create_suggestion_candidates
from app.engine.triggers import create_trigger

logger = get_logger(__name__)

BRIEF_HORIZON_DAYS = 2  # 今天 + 明天 + 后天（覆盖 48 小时以上）
BRIEF_KINDS = ("brief_morning", "brief_evening")
DEFAULT_QUIET_HOURS = {"start": "23:00", "end": "07:00"}


@dataclass
class MaterializeStats:
    brief_created: int = 0
    brief_superseded: int = 0
    block_created: int = 0
    block_superseded: int = 0
    suggestions_created: int = 0


async def get_or_create_prefs(
    session: AsyncSession, user_id: object, clock: Clock
) -> NotifPrefs:
    """首次需要时按契约默认值创建偏好。"""
    prefs = await session.get(NotifPrefs, user_id)
    if prefs is None:
        prefs = NotifPrefs(
            user_id=user_id,
            daily_budget=4,
            quiet_hours=DEFAULT_QUIET_HOURS,
            class_enabled={},
            morning_brief_time=dt.time(8, 30),
            evening_brief_time=dt.time(21, 0),
            briefs_enabled=True,
        )
        session.add(prefs)
        await session.flush()
    return prefs


async def _supersede(session: AsyncSession, trigger: TriggerInstance, *, clock: Clock) -> None:
    """旧实例写 dropped 事件后删除，释放 key 以便按新设置重建。"""
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
            "reason": "superseded",
        },
        trace_id=trigger.payload.get("trace_id", ""),
        clock=clock,
        idempotency_key=f"trigger-superseded:{trigger.id}",
    )
    await session.delete(trigger)
    await session.flush()


def _fire_at(day: dt.date, at: dt.time, tz: str) -> dt.datetime:
    return dt.datetime.combine(day, at).replace(tzinfo=ZoneInfo(tz)).astimezone(dt.UTC)


async def ensure_brief_triggers(
    session: AsyncSession,
    *,
    user: User,
    prefs: NotifPrefs,
    clock: Clock,
) -> tuple[int, int]:
    """保证未来窗口内的简报实例存在；返回 (新建数, 被替换数)。"""
    now = clock.now()
    pending = (
        (
            await session.execute(
                select(TriggerInstance).where(
                    TriggerInstance.user_id == user.id,
                    TriggerInstance.status == "pending",
                    TriggerInstance.kind.in_(BRIEF_KINDS),
                )
            )
        )
        .scalars()
        .all()
    )

    expected: dict[str, tuple[str, dt.datetime]] = {}
    if prefs.briefs_enabled:
        first_day = local_date_of(now, user.timezone, user.day_start)
        for offset in range(BRIEF_HORIZON_DAYS + 1):
            day = first_day + dt.timedelta(days=offset)
            for kind, at in (
                ("brief_morning", prefs.morning_brief_time),
                ("brief_evening", prefs.evening_brief_time),
            ):
                key = f"{kind}:{user.id}:{day.isoformat()}"
                expected[key] = (kind, _fire_at(day, at, user.timezone))

    superseded = 0
    live: set[str] = set()
    for row in pending:
        want = expected.get(row.key)
        if want is None or want[1] != row.fire_at:
            await _supersede(session, row, clock=clock)
            superseded += 1
        else:
            live.add(row.key)

    created = 0
    for key, (kind, fire_at) in expected.items():
        if key in live:
            continue
        exists = (
            await session.execute(select(TriggerInstance.id).where(TriggerInstance.key == key))
        ).first()
        if exists is not None:
            # 历史行（已触发/已丢弃）不重建
            continue
        await create_trigger(
            session,
            user_id=user.id,
            kind=kind,
            key=key,
            fire_at=fire_at,
            tz=user.timezone,
            payload={"kind": kind, "local_date": key.rsplit(":", 1)[-1]},
            expires_at=fire_at + dt.timedelta(hours=2),
            clock=clock,
        )
        created += 1
    return created, superseded


async def ensure_block_triggers(
    session: AsyncSession,
    *,
    block: PlannedBlock,
    user: User,
    title: str,
    settings: Settings,
    clock: Clock,
) -> tuple[int, int]:
    """为计划块物化 block_start 与 overdue_check；旧 rev 的 pending 实例置 dropped。"""
    now = clock.now()
    stale = (
        (
            await session.execute(
                select(TriggerInstance).where(
                    TriggerInstance.user_id == block.user_id,
                    TriggerInstance.status == "pending",
                    TriggerInstance.kind.in_(("block_start", "overdue_check")),
                    or_(
                        TriggerInstance.key.like(f"block_start:{block.id}:%"),
                        TriggerInstance.key.like(f"overdue_check:{block.id}:%"),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    superseded = 0
    for row in stale:
        await _supersede(session, row, clock=clock)
        superseded += 1

    if block.status != "planned":
        return 0, superseded

    lead_minutes = settings.block_lead_minutes
    grace_minutes = settings.block_grace_minutes
    planned_triggers = (
        (
            "block_start",
            f"block_start:{block.id}:{block.rev}",
            block.starts_at - dt.timedelta(minutes=lead_minutes),
            {"block_id": str(block.id), "expected_starts_at": block.starts_at.isoformat()},
            dt.timedelta(hours=settings.reminder_late_window_hours),
        ),
        (
            "overdue_check",
            f"overdue_check:{block.id}:{block.rev}",
            block.ends_at + dt.timedelta(minutes=grace_minutes),
            {"block_id": str(block.id), "expected_status": "planned"},
            dt.timedelta(hours=24),
        ),
    )
    created = 0
    for kind, key, fire_at, precondition, ttl in planned_triggers:
        exists = (
            await session.execute(select(TriggerInstance.id).where(TriggerInstance.key == key))
        ).first()
        if exists is not None:
            continue
        if fire_at <= now:
            # 只向前物化：已经错过的触发点不再补建
            continue
        await create_trigger(
            session,
            user_id=block.user_id,
            kind=kind,
            key=key,
            fire_at=fire_at,
            tz=user.timezone,
            payload={
                "block_id": str(block.id),
                "work_item_id": str(block.work_item_id),
                "title": title,
                "trace_id": "",
            },
            precondition=precondition,
            expires_at=fire_at + ttl,
            clock=clock,
        )
        created += 1
    return created, superseded


async def run_materializer(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    clock: Clock,
    settings: Settings,
) -> MaterializeStats:
    """worker 启动时与每 5 分钟调用：为全部用户物化简报并评估规则。"""
    stats = MaterializeStats()
    async with sessionmaker() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            prefs = await get_or_create_prefs(session, user.id, clock)
            created, superseded = await ensure_brief_triggers(
                session, user=user, prefs=prefs, clock=clock
            )
            stats.brief_created += created
            stats.brief_superseded += superseded
            stats.suggestions_created += await create_suggestion_candidates(
                session, user=user, clock=clock
            )
        await session.commit()
    if stats.brief_created or stats.brief_superseded or stats.suggestions_created:
        logger.info(
            "materializer: brief_created=%d brief_superseded=%d suggestions=%d",
            stats.brief_created,
            stats.brief_superseded,
            stats.suggestions_created,
        )
    return stats
