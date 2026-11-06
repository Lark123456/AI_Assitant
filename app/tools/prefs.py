"""通知偏好工具：set_notif_prefs。修改后立即重算尚未触发的简报实例。"""

import datetime as dt

from pydantic import BaseModel, Field

from app.engine.materializer import ensure_brief_triggers, get_or_create_prefs
from app.tools.base import ToolContext, ToolDef, ToolResult


class SetNotifPrefsArgs(BaseModel):
    daily_budget: int | None = Field(default=None, ge=0, le=20, description="每天可并入简报的建议条数")
    quiet_hours: str | None = Field(
        default=None,
        description='免打扰时段，格式 "HH:MM-HH:MM"（如 23:00-07:00）；传空字符串表示关闭免打扰',
    )
    morning_brief_time: str | None = Field(default=None, description="晨间简报本地时间 HH:MM")
    evening_brief_time: str | None = Field(default=None, description="晚间复盘本地时间 HH:MM")
    briefs_enabled: bool | None = Field(default=None, description="是否启用简报")
    snooze_hours: float | None = Field(
        default=None, ge=0, le=168, description="暂停非承诺类消息的小时数；0 表示取消暂停"
    )


def _parse_clock(value: str) -> dt.time:
    hour, minute = value.split(":")
    parsed = dt.time(int(hour), int(minute))
    return parsed


def _parse_range(value: str) -> dict | None:
    if not value.strip():
        return None
    start, end = value.split("-")
    return {"start": _parse_clock(start).strftime("%H:%M"), "end": _parse_clock(end).strftime("%H:%M")}


async def _run_set_notif_prefs(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = SetNotifPrefsArgs.model_validate(args)
    prefs = await get_or_create_prefs(ctx.session, ctx.user.id, ctx.clock)
    if parsed.daily_budget is not None:
        prefs.daily_budget = parsed.daily_budget
    if parsed.quiet_hours is not None:
        prefs.quiet_hours = _parse_range(parsed.quiet_hours)
    if parsed.morning_brief_time is not None:
        prefs.morning_brief_time = _parse_clock(parsed.morning_brief_time)
    if parsed.evening_brief_time is not None:
        prefs.evening_brief_time = _parse_clock(parsed.evening_brief_time)
    if parsed.briefs_enabled is not None:
        prefs.briefs_enabled = parsed.briefs_enabled
    if parsed.snooze_hours is not None:
        prefs.snooze_until = (
            ctx.clock.now() + dt.timedelta(hours=parsed.snooze_hours) if parsed.snooze_hours else None
        )
    await ctx.session.flush()
    created, superseded = await ensure_brief_triggers(
        ctx.session, user=ctx.user, prefs=prefs, clock=ctx.clock
    )
    return ToolResult(
        status="ok",
        data={
            "daily_budget": prefs.daily_budget,
            "quiet_hours": prefs.quiet_hours,
            "morning_brief_time": prefs.morning_brief_time.strftime("%H:%M"),
            "evening_brief_time": prefs.evening_brief_time.strftime("%H:%M"),
            "briefs_enabled": prefs.briefs_enabled,
            "snooze_until": prefs.snooze_until.isoformat() if prefs.snooze_until else None,
            "brief_triggers_created": created,
            "brief_triggers_superseded": superseded,
        },
        message="通知偏好已更新",
    )


SET_NOTIF_PREFS = ToolDef(
    name="set_notif_prefs",
    description=(
        "修改通知偏好：简报时间、免打扰时段、每日建议预算、简报开关与暂停。"
        "写操作，幂等键由系统按入站事件派生。"
    ),
    args_model=SetNotifPrefsArgs,
    run=_run_set_notif_prefs,
    write=True,
)
