"""set_reminder 工具：创建 kind=reminder 的 trigger_instance。"""

import datetime as dt

from pydantic import BaseModel, Field

from app.engine.triggers import create_trigger
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id
from app.tools.timeutil import parse_future_time


class SetReminderArgs(BaseModel):
    fire_at: str = Field(description="触发时刻，ISO 8601 带时区偏移，如 2026-11-04T09:00:00+08:00")
    note: str = Field(min_length=1, description="提醒内容")
    task_id: str | None = Field(default=None, description="可选：关联任务，任务完成/放弃后提醒取消")


async def _run_set_reminder(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = SetReminderArgs.model_validate(args)
    fire_at = parse_future_time(parsed.fire_at, ctx.clock)
    expires_at = fire_at + dt.timedelta(minutes=ctx.settings.reminder_ttl_minutes)
    key = f"reminder:{ctx.user.id}:{require_source_event_id(ctx)}:{ctx.call_index}"
    trigger = await create_trigger(
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
            "deduplicated": trigger.status == "pending" and trigger.key == key,
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
