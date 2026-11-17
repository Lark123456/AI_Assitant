"""移动端只读 API：U2 第一批 Today 数据。

鉴权为开发期固定用户头：X-Butler-User 支持用户 UUID 或飞书 open_id
（可带 feishu: 前缀）。这是开发期方案，正式鉴权后续替换。
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import day_window_for_date, local_date_of
from app.db.models import ChannelIdentity, PlannedBlock, TriggerInstance, User, WorkItem

router = APIRouter(prefix="/api/mobile")


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """从应用状态取会话工厂；测试可注入最小应用状态。"""
    async with request.app.state.sessionmaker() as session:
        yield session


async def get_mobile_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    x_butler_user: Annotated[str | None, Header(alias="X-Butler-User")] = None,
) -> User:
    """开发期用户识别：UUID 优先，其次按渠道外部 id 查找。"""
    if not x_butler_user or not x_butler_user.strip():
        raise HTTPException(status_code=401, detail="缺少 X-Butler-User")
    raw = x_butler_user.strip()
    value = raw.removeprefix("feishu:")

    user: User | None = None
    try:
        user = await session.get(User, uuid.UUID(value))
    except ValueError:
        user = None
    if user is not None:
        return user

    identity = (
        await session.execute(
            select(ChannelIdentity).where(ChannelIdentity.external_id == value)
        )
    ).scalars().first()
    if identity is not None:
        user = await session.get(User, identity.user_id)
        if user is not None:
            return user
    raise HTTPException(status_code=401, detail="未知用户")


def _iso(value: dt.datetime, tz: str) -> str:
    return value.astimezone(ZoneInfo(tz)).isoformat()


def _block_status(block: PlannedBlock) -> str:
    if block.status == "done":
        return "done"
    if block.status == "skipped":
        return "skipped"
    if block.actual_started_at is not None and block.actual_ended_at is None:
        return "in_progress"
    return "planned"


def _reminder_status(status: str) -> str:
    return {
        "pending": "planned",
        "claimed": "planned",
        "fired": "done",
        "missed": "skipped",
    }.get(status, "planned")


@router.get("/today")
async def get_today(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    date: str | None = Query(default=None, description="本地日期 YYYY-MM-DD；缺省为今天"),
) -> dict:
    """返回指定本地日的只读 Today 视图；简报暂不在此接口生成。"""
    clock = request.app.state.clock
    if date:
        try:
            day = dt.date.fromisoformat(date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date 必须是 YYYY-MM-DD") from exc
    else:
        day = local_date_of(clock.now(), user.timezone, user.day_start)

    # 与移动端 DayView 的本地零点对齐；不按 user.day_start 切日。
    start_utc, end_utc = day_window_for_date(day, user.timezone, dt.time(0, 0))

    block_rows = (
        await session.execute(
            select(PlannedBlock, WorkItem.title)
            .join(WorkItem, WorkItem.id == PlannedBlock.work_item_id)
            .where(
                PlannedBlock.user_id == user.id,
                PlannedBlock.starts_at < end_utc,
                PlannedBlock.ends_at > start_utc,
            )
            .order_by(PlannedBlock.starts_at)
        )
    ).all()

    reminder_rows = (
        await session.execute(
            select(TriggerInstance)
            .where(
                TriggerInstance.user_id == user.id,
                TriggerInstance.kind == "reminder",
                TriggerInstance.fire_at >= start_utc,
                TriggerInstance.fire_at < end_utc,
                TriggerInstance.status.in_(("pending", "claimed", "fired", "missed")),
            )
            .order_by(TriggerInstance.fire_at)
        )
    ).scalars().all()

    has_block = (
        select(PlannedBlock.id)
        .where(PlannedBlock.work_item_id == WorkItem.id)
        .exists()
    )
    unscheduled_rows = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user.id,
                WorkItem.type == "item",
                WorkItem.status == "active",
                ~has_block,
            )
            .order_by(WorkItem.created_at)
        )
    ).scalars().all()

    items: list[dict] = []
    for block, title in block_rows:
        items.append(
            {
                "id": str(block.id),
                "kind": "block",
                "title": title,
                "status": _block_status(block),
                "compressible": block.compressible,
                "syncState": "synced",
                "start": _iso(block.starts_at, user.timezone),
                "end": _iso(block.ends_at, user.timezone),
                "durationMin": max(
                    1, int((block.ends_at - block.starts_at).total_seconds() // 60)
                ),
                "sourceTag": "日程",
                "reason": None,
            }
        )

    for trigger in reminder_rows:
        note = str((trigger.payload or {}).get("note") or "提醒")
        items.append(
            {
                "id": str(trigger.id),
                "kind": "reminder",
                "title": note,
                "status": _reminder_status(trigger.status),
                "compressible": False,
                "syncState": "synced",
                "start": _iso(trigger.fire_at, user.timezone),
                "end": None,
                "durationMin": None,
                "sourceTag": "提醒",
                "reason": None,
            }
        )

    items.sort(key=lambda item: item["start"])
    unscheduled = [
        {
            "id": str(task.id),
            "kind": "task",
            "title": task.title,
            "status": "planned",
            "compressible": True,
            "syncState": "synced",
            "start": None,
            "end": None,
            "durationMin": None,
            "sourceTag": "任务",
            "reason": task.description,
        }
        for task in unscheduled_rows
    ]

    return {
        "date": day.isoformat(),
        "items": items,
        "unscheduled": unscheduled,
        "morningBrief": None,
        "eveningBrief": None,
    }
