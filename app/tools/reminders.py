"""set_reminder / list_reminders / cancel_reminder 工具。"""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import TriggerInstance
from app.engine.events import append_event
from app.engine.triggers import create_trigger
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id
from app.tools.timeutil import parse_future_time


class SetReminderArgs(BaseModel):
    fire_at: str = Field(description="触发时刻，ISO 8601 带时区偏移，如 2026-11-04T09:00:00+08:00")
    note: str = Field(min_length=1, description="提醒内容")
    task_id: str | None = Field(default=None, description="可选：关联任务，任务完成/放弃后提醒取消")


class ListRemindersArgs(BaseModel):
    include_past: bool = Field(default=False, description="是否包含已触发的提醒")


class CancelReminderArgs(BaseModel):
    trigger_id: str = Field(min_length=1, description="提醒的 trigger_id")


async def _run_set_reminder(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = SetReminderArgs.model_validate(args)
    fire_at = parse_future_time(parsed.fire_at, ctx.clock)
    # 阶段 2：迟到补偿窗口（late_send 时窗口内补发并标注迟到，超过则 missed）
    expires_at = fire_at + dt.timedelta(hours=ctx.settings.reminder_late_window_hours)
    key = f"reminder:{ctx.user.id}:{require_source_event_id(ctx)}:{ctx.call_index}"
    trigger, created = await create_trigger(
        ctx.session,
        user_id=ctx.user.id,
        kind="reminder",
        key=key,
        fire_at=fire_at,
        tz=ctx.user.timezone,
        payload={
            "note": parsed.note,
            "trace_id": ctx.trace_id,
            "source_event_id": str(ctx.source_event_id) if ctx.source_event_id else None,
        },
        precondition={"task_id": parsed.task_id} if parsed.task_id else None,
        expires_at=expires_at,
        clock=ctx.clock,
    )
    return ToolResult(
        status="ok",
        data={
            "trigger_id": str(trigger.id),
            "fire_at": fire_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "deduplicated": not created,
        },
        message=f"提醒已设置：{fire_at.isoformat()}",
    )


SET_REMINDER = ToolDef(
    name="set_reminder",
    description="设置一次性提醒，到点会主动发送。写操作，幂等键由系统按入站事件派生。时间参数必须是带时区偏移的 ISO 8601。",
    args_model=SetReminderArgs,
    run=_run_set_reminder,
    write=True,
)


async def _run_list_reminders(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = ListRemindersArgs.model_validate(args)
    query = select(TriggerInstance).where(
        TriggerInstance.user_id == ctx.user.id,
        TriggerInstance.kind == "reminder",
    )
    if not parsed.include_past:
        query = query.where(
            TriggerInstance.status == "pending",
            TriggerInstance.fire_at >= ctx.clock.now(),
        )
    rows = (await ctx.session.execute(query.order_by(TriggerInstance.fire_at))).scalars().all()
    reminders = [
        {
            "trigger_id": str(row.id),
            "note": row.payload.get("note", ""),
            "fire_at": row.fire_at.astimezone(ZoneInfo(ctx.user.timezone)).isoformat(),
            "status": row.status,
        }
        for row in rows
    ]
    return ToolResult(status="ok", data={"reminders": reminders}, message=f"共 {len(reminders)} 条提醒")


async def _run_cancel_reminder(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = CancelReminderArgs.model_validate(args)
    try:
        trigger_uuid = uuid.UUID(parsed.trigger_id)
    except ValueError:
        return ToolResult(status="error", message="trigger_id 不是合法 UUID")
    trigger = (
        await ctx.session.execute(
            select(TriggerInstance).where(
                TriggerInstance.id == trigger_uuid,
                TriggerInstance.user_id == ctx.user.id,
                TriggerInstance.kind == "reminder",
            )
        )
    ).scalar_one_or_none()
    if trigger is None:
        return ToolResult(status="error", message=f"提醒不存在：{parsed.trigger_id}")
    if trigger.status in ("fired", "missed", "failed"):
        return ToolResult(
            status="ok",
            data={"trigger_id": str(trigger.id), "status": trigger.status},
            message="该提醒已结束",
        )
    if trigger.status == "dropped":
        return ToolResult(
            status="ok", data={"trigger_id": str(trigger.id), "status": "dropped"}, message="提醒已取消"
        )
    trigger.status = "dropped"
    await append_event(
        ctx.session,
        user_id=ctx.user.id,
        channel=ctx.channel,
        direction="system",
        type="trigger",
        payload={"trigger_id": str(trigger.id), "status": "dropped", "reason": "user_cancelled"},
        trace_id=ctx.trace_id,
        clock=ctx.clock,
        idempotency_key=f"reminder-cancelled:{trigger.id}",
    )
    return ToolResult(
        status="ok", data={"trigger_id": str(trigger.id), "status": "dropped"}, message="提醒已取消"
    )


LIST_REMINDERS = ToolDef(
    name="list_reminders",
    description="列出尚未触发的提醒。",
    args_model=ListRemindersArgs,
    run=_run_list_reminders,
)

CANCEL_REMINDER = ToolDef(
    name="cancel_reminder",
    description="取消一条提醒。写操作，幂等键由系统按入站事件派生。",
    args_model=CancelReminderArgs,
    run=_run_cancel_reminder,
    write=True,
)
