"""计划块工具：schedule_block / list_schedule / update_block_status / reschedule_block。

写操作在写库后立即物化/重物化 block_start 与 overdue_check 触发。
"""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.timeutil import day_window_for_date, local_date_of
from app.db.models import PlannedBlock, WorkItem
from app.engine.materializer import ensure_block_triggers
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id
from app.tools.timeutil import parse_future_time, parse_iso_with_offset


class ScheduleBlockArgs(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500, description="任务标题；与 work_item_id 二选一")
    work_item_id: str | None = Field(default=None, description="已有任务 id；与 title 二选一")
    starts_at: str = Field(description="开始时刻，ISO 8601 带时区偏移")
    ends_at: str | None = Field(default=None, description="结束时刻，ISO 8601 带时区偏移")
    duration_min: int | None = Field(default=None, ge=5, le=720, description="时长（分钟），与 ends_at 二选一")
    difficulty: int | None = Field(default=None, ge=1, le=5)
    energy: str | None = Field(default=None, description="low | mid | high")
    compressible: bool = True

    @model_validator(mode="after")
    def _check_inputs(self) -> "ScheduleBlockArgs":
        if not self.title and not self.work_item_id:
            raise ValueError("title 与 work_item_id 至少提供一个")
        if not self.ends_at and not self.duration_min:
            raise ValueError("ends_at 与 duration_min 至少提供一个")
        return self


class ListScheduleArgs(BaseModel):
    date: str | None = Field(default=None, description="本地日期 YYYY-MM-DD；缺省为今天")
    start_date: str | None = Field(default=None, description="起始本地日期 YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="结束本地日期（含）")


class UpdateBlockStatusArgs(BaseModel):
    block_id: str = Field(min_length=1)
    status: str = Field(description="done | skipped")
    actual_started_at: str | None = None
    actual_ended_at: str | None = None


class RescheduleBlockArgs(BaseModel):
    block_id: str = Field(min_length=1)
    starts_at: str = Field(description="新的开始时刻，ISO 8601 带时区偏移")
    ends_at: str = Field(description="新的结束时刻，ISO 8601 带时区偏移")


def _uuid_or_error(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def _run_schedule_block(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = ScheduleBlockArgs.model_validate(args)
    starts = parse_future_time(parsed.starts_at, ctx.clock)
    if parsed.ends_at:
        ends = parse_iso_with_offset(parsed.ends_at)
    else:
        assert parsed.duration_min is not None
        ends = starts + dt.timedelta(minutes=parsed.duration_min)
    if ends <= starts:
        return ToolResult(status="error", message="结束时间必须晚于开始时间")

    item: WorkItem | None = None
    if parsed.work_item_id:
        item_uuid = _uuid_or_error(parsed.work_item_id)
        if item_uuid is None:
            return ToolResult(status="error", message="work_item_id 不是合法 UUID")
        item = (
            await ctx.session.execute(
                select(WorkItem).where(WorkItem.id == item_uuid, WorkItem.user_id == ctx.user.id)
            )
        ).scalar_one_or_none()
        if item is None:
            return ToolResult(status="error", message=f"任务不存在：{parsed.work_item_id}")
    else:
        assert parsed.title is not None
        item = WorkItem(
            user_id=ctx.user.id,
            type="item",
            status="active",
            title=parsed.title,
            source_event_id=require_source_event_id(ctx),
            created_at=ctx.clock.now(),
            updated_at=ctx.clock.now(),
        )
        ctx.session.add(item)
        await ctx.session.flush()

    block = PlannedBlock(
        user_id=ctx.user.id,
        work_item_id=item.id,
        starts_at=starts,
        ends_at=ends,
        status="planned",
        assigned_by="friday",
        difficulty=parsed.difficulty,
        energy=parsed.energy,
        compressible=parsed.compressible,
        rev=1,
        created_at=ctx.clock.now(),
        updated_at=ctx.clock.now(),
    )
    ctx.session.add(block)
    await ctx.session.flush()
    created, _ = await ensure_block_triggers(
        ctx.session, block=block, user=ctx.user, title=item.title, settings=ctx.settings, clock=ctx.clock
    )
    return ToolResult(
        status="ok",
        data={
            "block_id": str(block.id),
            "work_item_id": str(item.id),
            "title": item.title,
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "triggers_created": created,
        },
        message=f"已安排：{item.title}",
    )


async def _run_list_schedule(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = ListScheduleArgs.model_validate(args)
    tz = ctx.user.timezone
    if parsed.start_date:
        first = dt.date.fromisoformat(parsed.start_date)
        last = dt.date.fromisoformat(parsed.end_date) if parsed.end_date else first
    else:
        today = local_date_of(ctx.clock.now(), tz, ctx.user.day_start)
        first = dt.date.fromisoformat(parsed.date) if parsed.date else today
        last = first
    start, _ = day_window_for_date(first, tz, ctx.user.day_start)
    _, end = day_window_for_date(last, tz, ctx.user.day_start)
    rows = (
        await ctx.session.execute(
            select(PlannedBlock, WorkItem.title)
            .join(WorkItem, PlannedBlock.work_item_id == WorkItem.id)
            .where(
                PlannedBlock.user_id == ctx.user.id,
                PlannedBlock.starts_at >= start,
                PlannedBlock.starts_at < end,
            )
            .order_by(PlannedBlock.starts_at)
        )
    ).all()
    blocks = [
        {
            "block_id": str(block.id),
            "title": title,
            "starts_at": block.starts_at.astimezone(ZoneInfo(tz)).isoformat(),
            "ends_at": block.ends_at.astimezone(ZoneInfo(tz)).isoformat(),
            "status": block.status,
        }
        for block, title in rows
    ]
    return ToolResult(status="ok", data={"blocks": blocks}, message=f"共 {len(blocks)} 个时间块")


async def _run_update_block_status(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = UpdateBlockStatusArgs.model_validate(args)
    if parsed.status not in ("done", "skipped"):
        return ToolResult(status="error", message="status 只能是 done 或 skipped")
    block_uuid = _uuid_or_error(parsed.block_id)
    if block_uuid is None:
        return ToolResult(status="error", message="block_id 不是合法 UUID")
    block = (
        await ctx.session.execute(
            select(PlannedBlock).where(
                PlannedBlock.id == block_uuid, PlannedBlock.user_id == ctx.user.id
            )
        )
    ).scalar_one_or_none()
    if block is None:
        return ToolResult(status="error", message=f"时间块不存在：{parsed.block_id}")
    if block.status == parsed.status:
        return ToolResult(
            status="ok", data={"block_id": str(block.id), "status": block.status}, message="状态未变"
        )
    block.status = parsed.status
    block.rev += 1
    block.updated_at = ctx.clock.now()
    if parsed.actual_started_at:
        block.actual_started_at = parse_iso_with_offset(parsed.actual_started_at)
    if parsed.actual_ended_at:
        block.actual_ended_at = parse_iso_with_offset(parsed.actual_ended_at)
    elif parsed.status == "done":
        block.actual_ended_at = ctx.clock.now()
    await ensure_block_triggers(
        ctx.session, block=block, user=ctx.user, title="", settings=ctx.settings, clock=ctx.clock
    )
    return ToolResult(
        status="ok",
        data={"block_id": str(block.id), "status": block.status},
        message=f"时间块已标记为 {block.status}",
    )


async def _run_reschedule_block(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = RescheduleBlockArgs.model_validate(args)
    starts = parse_future_time(parsed.starts_at, ctx.clock)
    ends = parse_iso_with_offset(parsed.ends_at)
    if ends <= starts:
        return ToolResult(status="error", message="结束时间必须晚于开始时间")
    block_uuid = _uuid_or_error(parsed.block_id)
    if block_uuid is None:
        return ToolResult(status="error", message="block_id 不是合法 UUID")
    block = (
        await ctx.session.execute(
            select(PlannedBlock).where(
                PlannedBlock.id == block_uuid, PlannedBlock.user_id == ctx.user.id
            )
        )
    ).scalar_one_or_none()
    if block is None:
        return ToolResult(status="error", message=f"时间块不存在：{parsed.block_id}")
    block.starts_at = starts
    block.ends_at = ends
    block.status = "planned"
    block.rev += 1
    block.updated_at = ctx.clock.now()
    title = (
        await ctx.session.execute(select(WorkItem.title).where(WorkItem.id == block.work_item_id))
    ).scalar_one_or_none() or ""
    created, superseded = await ensure_block_triggers(
        ctx.session, block=block, user=ctx.user, title=title, settings=ctx.settings, clock=ctx.clock
    )
    return ToolResult(
        status="ok",
        data={
            "block_id": str(block.id),
            "starts_at": starts.isoformat(),
            "ends_at": ends.isoformat(),
            "triggers_created": created,
            "triggers_superseded": superseded,
        },
        message="已改期",
    )


SCHEDULE_BLOCK = ToolDef(
    name="schedule_block",
    description="把一个任务安排到具体时间段。写操作，幂等键由系统按入站事件派生。",
    args_model=ScheduleBlockArgs,
    run=_run_schedule_block,
    write=True,
)

LIST_SCHEDULE = ToolDef(
    name="list_schedule",
    description="查看某天或某段时间的日程安排。",
    args_model=ListScheduleArgs,
    run=_run_list_schedule,
)

UPDATE_BLOCK_STATUS = ToolDef(
    name="update_block_status",
    description="标记时间块已完成或跳过。写操作，幂等键由系统按入站事件派生。",
    args_model=UpdateBlockStatusArgs,
    run=_run_update_block_status,
    write=True,
)

RESCHEDULE_BLOCK = ToolDef(
    name="reschedule_block",
    description="修改时间块的时间并重排提醒。写操作，幂等键由系统按入站事件派生。",
    args_model=RescheduleBlockArgs,
    run=_run_reschedule_block,
    write=True,
)
