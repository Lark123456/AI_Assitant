"""set_timezone 工具：更新用户 IANA 时区（rev 递增）。"""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from app.tools.base import ToolContext, ToolDef, ToolResult


class SetTimezoneArgs(BaseModel):
    timezone: str = Field(
        min_length=1, max_length=64,
        description="IANA 时区名，如 Asia/Shanghai、America/New_York",
    )


async def _run_set_timezone(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = SetTimezoneArgs.model_validate(args)
    try:
        ZoneInfo(parsed.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ToolResult(status="error", message=f"未知时区：{parsed.timezone}（需要 IANA 名称，如 Asia/Shanghai）")
    if ctx.user.timezone == parsed.timezone:
        return ToolResult(
            status="ok",
            data={"timezone": parsed.timezone},
            message="时区未变化",
        )
    ctx.user.timezone = parsed.timezone
    ctx.user.rev += 1
    ctx.user.updated_at = ctx.clock.now()
    await ctx.session.flush()
    return ToolResult(
        status="ok",
        data={"timezone": parsed.timezone},
        message=f"时区已更新为 {parsed.timezone}",
    )


SET_TIMEZONE = ToolDef(
    name="set_timezone",
    description="设置用户时区（IANA 名称，如 Asia/Shanghai）。用户表达时区偏好（如「把时区改成东京时间」）时调用。",
    args_model=SetTimezoneArgs,
    run=_run_set_timezone,
    write=True,
)
