"""移动端 Today API：只读视图与写操作。

鉴权为开发期固定用户头：X-Butler-User 支持用户 UUID 或飞书 open_id
（可带 feishu: 前缀）。这是开发期方案，正式鉴权后续替换。

写操作用 Idempotency-Key 头去重：动作与结果写入 event_log，
重放同一键时直接返回上次结果。
"""

import datetime as dt
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings, get_settings
from app.core.ids import new_trace_id
from app.core.timeutil import day_window_for_date, local_date_of
from app.db.models import ChannelIdentity, PlannedBlock, TriggerInstance, User, WorkItem
from app.engine.events import append_event, find_event_by_idempotency_key
from app.engine.materializer import ensure_block_triggers
from app.tools.timeutil import parse_iso_with_offset

router = APIRouter(prefix="/api/mobile")

VISIBLE_REMINDER_STATUSES = ("pending", "claimed", "fired", "missed")
ActionName = Literal["complete", "skip", "restore"]


class RescheduleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    starts_at: str = Field(alias="startsAt", description="新的开始时刻，ISO 8601 带时区偏移")


class ScheduleTaskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    starts_at: str = Field(alias="startsAt", description="开始时刻，ISO 8601 带时区偏移")
    duration_min: int = Field(default=60, alias="durationMin", ge=5, le=720)


class ReviewItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    item_id: str = Field(alias="itemId")
    done: bool


class ReviewRequest(BaseModel):
    results: list[ReviewItem]


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


async def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """写接口必须带幂等键；长度限制避免异常大的日志键。"""
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(status_code=400, detail="缺少 Idempotency-Key")
    value = idempotency_key.strip()
    if len(value) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key 过长")
    return value


def _settings(request: Request) -> Settings:
    return getattr(request.app.state, "settings", None) or get_settings()


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


def _task_status(task: WorkItem) -> str:
    return {"done": "done", "dropped": "skipped"}.get(task.status, "planned")


def _reminder_status(trigger: TriggerInstance) -> str:
    if trigger.status == "dropped":
        return "done" if (trigger.payload or {}).get("ack") == "done" else "skipped"
    return {
        "pending": "planned",
        "claimed": "planned",
        "fired": "done",
        "missed": "skipped",
    }.get(trigger.status, "planned")


def _block_item(block: PlannedBlock, title: str, tz: str) -> dict:
    return {
        "id": str(block.id),
        "kind": "block",
        "title": title,
        "status": _block_status(block),
        "compressible": block.compressible,
        "syncState": "synced",
        "start": _iso(block.starts_at, tz),
        "end": _iso(block.ends_at, tz),
        "durationMin": max(
            1, int((block.ends_at - block.starts_at).total_seconds() // 60)
        ),
        "sourceTag": "日程",
        "reason": None,
    }


def _reminder_item(trigger: TriggerInstance, tz: str) -> dict:
    return {
        "id": str(trigger.id),
        "kind": "reminder",
        "title": str((trigger.payload or {}).get("note") or "提醒"),
        "status": _reminder_status(trigger),
        "compressible": False,
        "syncState": "synced",
        "start": _iso(trigger.fire_at, tz),
        "end": None,
        "durationMin": None,
        "sourceTag": "提醒",
        "reason": None,
    }


def _task_item(task: WorkItem) -> dict:
    return {
        "id": str(task.id),
        "kind": "task",
        "title": task.title,
        "status": _task_status(task),
        "compressible": True,
        "syncState": "synced",
        "start": None,
        "end": None,
        "durationMin": None,
        "sourceTag": "任务",
        "reason": task.description,
    }


def _aware_time(value: str) -> dt.datetime:
    try:
        return parse_iso_with_offset(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


async def _block_title(session: AsyncSession, block: PlannedBlock) -> str:
    title = (
        await session.execute(select(WorkItem.title).where(WorkItem.id == block.work_item_id))
    ).scalar_one_or_none()
    return title or ""


async def _load_item_for_update(
    session: AsyncSession, user: User, item_id: str
) -> tuple[str, PlannedBlock | WorkItem | TriggerInstance]:
    """按 id 查找 Today 条目并加行锁；block 优先，其次 task、reminder。"""
    try:
        item_uuid = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="条目不存在") from exc

    block = (
        await session.execute(
            select(PlannedBlock)
            .where(PlannedBlock.id == item_uuid, PlannedBlock.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if block is not None:
        return "block", block

    task = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.id == item_uuid,
                WorkItem.user_id == user.id,
                WorkItem.type == "item",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is not None:
        return "task", task

    trigger = (
        await session.execute(
            select(TriggerInstance)
            .where(
                TriggerInstance.id == item_uuid,
                TriggerInstance.user_id == user.id,
                TriggerInstance.kind == "reminder",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if trigger is not None:
        return "reminder", trigger

    raise HTTPException(status_code=404, detail="条目不存在")


async def _mutate_item(
    session: AsyncSession,
    *,
    user: User,
    item_id: str,
    action: ActionName,
    settings: Settings,
    clock: Clock,
) -> dict:
    """对 block / task / reminder 应用一次状态变更，返回最新条目。"""
    kind, item = await _load_item_for_update(session, user, item_id)
    now = clock.now()

    if kind == "block":
        block = item
        assert isinstance(block, PlannedBlock)
        if action == "complete" and block.status != "done":
            block.status = "done"
            block.rev += 1
            block.updated_at = now
            block.actual_ended_at = now
        elif action == "skip" and block.status != "skipped":
            block.status = "skipped"
            block.rev += 1
            block.updated_at = now
        elif action == "restore":
            block.status = "planned"
            block.rev += 1
            block.updated_at = now
            block.actual_ended_at = None
        await ensure_block_triggers(
            session,
            block=block,
            user=user,
            title=await _block_title(session, block),
            settings=settings,
            clock=clock,
        )
        return _block_item(block, await _block_title(session, block), user.timezone)

    if kind == "task":
        task = item
        assert isinstance(task, WorkItem)
        if action == "complete" and task.status != "done":
            task.status = "done"
            task.rev += 1
            task.updated_at = now
        elif action == "skip" and task.status not in ("done", "dropped"):
            task.status = "dropped"
            task.rev += 1
            task.updated_at = now
        elif action == "restore" and task.status in ("done", "dropped"):
            task.status = "active"
            task.rev += 1
            task.updated_at = now
        return _task_item(task)

    trigger = item
    assert isinstance(trigger, TriggerInstance)
    ack = (trigger.payload or {}).get("ack")
    if action == "complete" and trigger.status in ("pending", "claimed"):
        trigger.status = "dropped"
        trigger.payload = {**(trigger.payload or {}), "ack": "done"}
    elif action == "skip" and trigger.status in ("pending", "claimed"):
        trigger.status = "dropped"
        trigger.payload = {**(trigger.payload or {}), "ack": "skipped"}
    elif action == "restore" and trigger.status == "dropped" and ack in ("done", "skipped"):
        trigger.status = "pending"
        trigger.payload = {
            key: value for key, value in (trigger.payload or {}).items() if key != "ack"
        }
    return _reminder_item(trigger, user.timezone)


async def _replay(
    session: AsyncSession, *, user: User, action: str, idempotency_key: str
) -> dict | None:
    event = await find_event_by_idempotency_key(
        session, f"mobile:{user.id}:{action}:{idempotency_key}"
    )
    if event is None:
        return None
    result = (event.payload or {}).get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=409, detail="同一幂等键的请求正在处理")
    return result


async def _record(
    session: AsyncSession,
    *,
    user: User,
    action: str,
    idempotency_key: str,
    result: dict,
    clock: Clock,
) -> None:
    await append_event(
        session,
        user_id=user.id,
        channel="mobile",
        direction="system",
        type="mobile_action",
        payload={"action": action, "result": result},
        trace_id=new_trace_id(),
        clock=clock,
        idempotency_key=f"mobile:{user.id}:{action}:{idempotency_key}",
    )
    await session.commit()


@router.get("/today")
async def get_today(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    date: str | None = Query(default=None, description="本地日期 YYYY-MM-DD；缺省为今天"),
) -> dict:
    """返回指定本地日的 Today 视图；简报暂不在此接口生成。"""
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
                or_(
                    TriggerInstance.status.in_(VISIBLE_REMINDER_STATUSES),
                    and_(
                        TriggerInstance.status == "dropped",
                        TriggerInstance.payload["ack"].astext.in_(("done", "skipped")),
                    ),
                ),
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

    items = [_block_item(block, title, user.timezone) for block, title in block_rows]
    items.extend(_reminder_item(trigger, user.timezone) for trigger in reminder_rows)
    items.sort(key=lambda item: item["start"])

    unscheduled = [_task_item(task) for task in unscheduled_rows]
    return {
        "date": day.isoformat(),
        "items": items,
        "unscheduled": unscheduled,
        "morningBrief": None,
        "eveningBrief": None,
    }


@router.post("/today/items/{item_id}/complete")
async def complete_today_item(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    item_id: str,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    replay = await _replay(
        session, user=user, action="complete", idempotency_key=idempotency_key
    )
    if replay is not None:
        return replay
    result = await _mutate_item(
        session,
        user=user,
        item_id=item_id,
        action="complete",
        settings=_settings(request),
        clock=request.app.state.clock,
    )
    await _record(
        session,
        user=user,
        action="complete",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result


@router.post("/today/items/{item_id}/skip")
async def skip_today_item(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    item_id: str,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    replay = await _replay(session, user=user, action="skip", idempotency_key=idempotency_key)
    if replay is not None:
        return replay
    result = await _mutate_item(
        session,
        user=user,
        item_id=item_id,
        action="skip",
        settings=_settings(request),
        clock=request.app.state.clock,
    )
    await _record(
        session,
        user=user,
        action="skip",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result


@router.post("/today/items/{item_id}/restore")
async def restore_today_item(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    item_id: str,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    replay = await _replay(
        session, user=user, action="restore", idempotency_key=idempotency_key
    )
    if replay is not None:
        return replay
    result = await _mutate_item(
        session,
        user=user,
        item_id=item_id,
        action="restore",
        settings=_settings(request),
        clock=request.app.state.clock,
    )
    await _record(
        session,
        user=user,
        action="restore",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result


@router.post("/today/items/{item_id}/reschedule")
async def reschedule_today_item(
    request: Request,
    body: RescheduleRequest,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    item_id: str,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    replay = await _replay(
        session, user=user, action="reschedule", idempotency_key=idempotency_key
    )
    if replay is not None:
        return replay

    starts_at = _aware_time(body.starts_at)
    kind, item = await _load_item_for_update(session, user, item_id)
    if kind != "block":
        raise HTTPException(status_code=400, detail="只有日程块支持改期")
    block = item
    assert isinstance(block, PlannedBlock)
    if starts_at >= block.ends_at:
        raise HTTPException(status_code=400, detail="新的开始时间必须早于结束时间")

    block.starts_at = starts_at
    block.status = "planned"
    block.rev += 1
    block.updated_at = request.app.state.clock.now()
    await ensure_block_triggers(
        session,
        block=block,
        user=user,
        title=await _block_title(session, block),
        settings=_settings(request),
        clock=request.app.state.clock,
    )
    result = _block_item(block, await _block_title(session, block), user.timezone)
    await _record(
        session,
        user=user,
        action="reschedule",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result


@router.post("/today/tasks/{task_id}/schedule")
async def schedule_today_task(
    request: Request,
    body: ScheduleTaskRequest,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    task_id: str,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    replay = await _replay(
        session, user=user, action="schedule", idempotency_key=idempotency_key
    )
    if replay is not None:
        return replay

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    task = (
        await session.execute(
            select(WorkItem)
            .where(
                WorkItem.id == task_uuid,
                WorkItem.user_id == user.id,
                WorkItem.type == "item",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "active":
        raise HTTPException(status_code=400, detail="只有未完成任务可以排期")

    starts_at = _aware_time(body.starts_at)
    ends_at = starts_at + dt.timedelta(minutes=body.duration_min)
    now = request.app.state.clock.now()
    block = PlannedBlock(
        user_id=user.id,
        work_item_id=task.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="planned",
        assigned_by="user",
        compressible=True,
        rev=1,
        created_at=now,
        updated_at=now,
    )
    session.add(block)
    await session.flush()
    await ensure_block_triggers(
        session,
        block=block,
        user=user,
        title=task.title,
        settings=_settings(request),
        clock=request.app.state.clock,
    )
    result = _block_item(block, task.title, user.timezone)
    await _record(
        session,
        user=user,
        action="schedule",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result


@router.post("/today/review")
async def submit_today_review(
    request: Request,
    body: ReviewRequest,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict:
    """晚间复盘：勾选完成的条目置为 done，未勾选的保持原状态。"""
    replay = await _replay(session, user=user, action="review", idempotency_key=idempotency_key)
    if replay is not None:
        return replay

    updated = 0
    for entry in body.results:
        if not entry.done:
            continue
        await _mutate_item(
            session,
            user=user,
            item_id=entry.item_id,
            action="complete",
            settings=_settings(request),
            clock=request.app.state.clock,
        )
        updated += 1
    result = {"updated": updated}
    await _record(
        session,
        user=user,
        action="review",
        idempotency_key=idempotency_key,
        result=result,
        clock=request.app.state.clock,
    )
    return result
