"""capture_note 工具：阶段 1 只把笔记写入 event_log（type=note）。"""

from pydantic import BaseModel, Field

from app.engine.events import append_event
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id


class CaptureNoteArgs(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


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


CAPTURE_NOTE = ToolDef(
    name="capture_note",
    description="记录一条用户口述的笔记或事实。写操作，幂等键由系统按入站事件派生。",
    args_model=CaptureNoteArgs,
    run=_run_capture_note,
    write=True,
)
