"""笔记工具：capture_note 写入 event_log（type=note），list_notes 查询历史笔记。"""

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import EventLog
from app.engine.events import append_event
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id


class CaptureNoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class ListNotesArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100, description="返回最近多少条笔记（最多 100）")


async def _run_capture_note(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = CaptureNoteArgs.model_validate(args)
    event, created = await append_event(
        ctx.session,
        user_id=ctx.user.id,
        channel=ctx.channel,
        direction="tool",
        type="note",
        payload={"text": parsed.text, "source_event_id": str(require_source_event_id(ctx))},
        trace_id=ctx.trace_id,
        clock=ctx.clock,
        idempotency_key=f"note:{ctx.user.id}:{ctx.source_event_id}:{ctx.call_index}",
    )
    return ToolResult(
        status="ok",
        data={"note_event_id": str(event.id), "created": created},
        message="笔记已记录",
    )


async def _run_list_notes(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = ListNotesArgs.model_validate(args)
    rows = (
        (
            await ctx.session.execute(
                select(EventLog)
                .where(
                    EventLog.user_id == ctx.user.id,
                    EventLog.direction == "tool",
                    EventLog.type == "note",
                )
                .order_by(EventLog.occurred_at.desc(), EventLog.id.desc())
                .limit(parsed.limit)
            )
        )
        .scalars()
        .all()
    )
    tz = ZoneInfo(ctx.user.timezone)
    notes = [
        {
            "note_event_id": str(row.id),
            "text": str((row.payload or {}).get("text", "")),
            "created_at": row.occurred_at.astimezone(tz).isoformat(),
        }
        for row in rows
    ]
    return ToolResult(
        status="ok",
        data={"notes": notes, "count": len(notes)},
        message=f"共 {len(notes)} 条笔记",
    )


CAPTURE_NOTE = ToolDef(
    name="capture_note",
    description="记录一条用户口述的笔记或事实。写操作，幂等键由系统按入站事件派生。",
    args_model=CaptureNoteArgs,
    run=_run_capture_note,
    write=True,
)

LIST_NOTES = ToolDef(
    name="list_notes",
    description="按时间倒序查询当前用户最近的笔记。",
    args_model=ListNotesArgs,
    run=_run_list_notes,
)
