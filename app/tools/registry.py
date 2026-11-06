"""工具注册表与幂等执行。

幂等实现（阶段 1 修订）：写工具的幂等键由代码从入站事件派生
（inbound_event_id + 工具名 + 调用序号），不接受 LLM 提供；
每次执行在 event_log 写 tool_call / tool_result 两条记录，以派生键去重，
重放同一键时返回上次结果。幂等键写入与业务写入在同一事务。
"""


import uuid

from pydantic import BaseModel, ValidationError

from app.engine.events import append_event, find_event_by_idempotency_key
from app.tools.base import ToolContext, ToolDef, ToolResult, tool_schema
from app.tools.blocks import (
    LIST_SCHEDULE,
    RESCHEDULE_BLOCK,
    SCHEDULE_BLOCK,
    UPDATE_BLOCK_STATUS,
)
from app.tools.notes import CAPTURE_NOTE
from app.tools.prefs import SET_NOTIF_PREFS
from app.tools.reminders import CANCEL_REMINDER, LIST_REMINDERS, SET_REMINDER
from app.tools.tasks import COMPLETE_TASK, CREATE_TASK, LIST_TASKS
from app.tools.timezone import SET_TIMEZONE

TOOLS: dict[str, ToolDef] = {
    t.name: t
    for t in (
        CREATE_TASK,
        LIST_TASKS,
        COMPLETE_TASK,
        SET_REMINDER,
        LIST_REMINDERS,
        CANCEL_REMINDER,
        CAPTURE_NOTE,
        SET_TIMEZONE,
        SCHEDULE_BLOCK,
        LIST_SCHEDULE,
        UPDATE_BLOCK_STATUS,
        RESCHEDULE_BLOCK,
        SET_NOTIF_PREFS,
    )
}


def derived_idempotency_key(
    inbound_event_id: uuid.UUID, tool_name: str, call_index: int
) -> str:
    """代码派生的工具幂等键：入站事件 + 工具名 + 调用序号（跨步骤递增）。"""
    return f"{inbound_event_id}:{tool_name}:{call_index}"


def tool_schemas() -> list[dict]:
    """全部工具的 OpenAI schema。"""
    return [tool_schema(t) for t in TOOLS.values()]


async def execute_tool(ctx: ToolContext, name: str, args: dict, *, call_index: int) -> ToolResult:
    """校验参数并幂等执行工具；写工具按入站事件派生幂等键。"""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(status="error", message=f"unknown tool: {name}")
    try:
        parsed: BaseModel = tool.args_model.model_validate(args)
    except ValidationError as exc:
        return ToolResult(status="error", message=f"参数校验失败：{exc}")

    if not tool.write:
        # 读工具无需幂等，直接执行
        return await _run_and_log(ctx, tool, args, result_key=None, parsed=parsed)

    if ctx.source_event_id is None:
        return ToolResult(status="error", message="缺少入站事件，无法执行写工具")
    ctx.call_index = call_index
    idem = derived_idempotency_key(ctx.source_event_id, name, call_index)
    call_key = f"tool-call:{idem}"
    result_key = f"tool-result:{idem}"

    existing_call = await find_event_by_idempotency_key(ctx.session, call_key)
    if existing_call is not None:
        existing_result = await find_event_by_idempotency_key(ctx.session, result_key)
        if existing_result is None:
            return ToolResult(status="error", message="previous execution unfinished")
        return _result_from_payload(existing_result.payload)

    await _append_tool_event(
        ctx, type="tool_call", idempotency_key=call_key, payload={"tool": name, "arguments": args}
    )
    return await _run_and_log(ctx, tool, args, result_key=result_key, parsed=parsed)


async def _run_and_log(
    ctx: ToolContext, tool: ToolDef, args: dict, result_key: str | None, parsed: BaseModel
) -> ToolResult:
    """在 savepoint 中执行并写结果事件；工具异常回滚 savepoint，不污染外层事务。"""
    try:
        async with ctx.session.begin_nested():
            result = await tool.run(ctx, parsed.model_dump())
            if result_key is not None:
                await _append_tool_event(
                    ctx, type="tool_result", idempotency_key=result_key, payload=result.model_dump()
                )
            return result
    except Exception as exc:
        # savepoint 已回滚（业务写入与结果事件一并撤销）；错误结果另写，仍留痕
        result = ToolResult(status="error", message=f"{type(exc).__name__}: {exc}")
        if result_key is not None:
            await _append_tool_event(
                ctx, type="tool_result", idempotency_key=result_key, payload=result.model_dump()
            )
        return result


def _result_from_payload(payload: dict) -> ToolResult:
    return ToolResult(
        status=payload.get("status", "error"),
        data=payload.get("data", {}),
        message=payload.get("message", ""),
    )


async def _append_tool_event(
    ctx: ToolContext, *, type: str, idempotency_key: str | None, payload: dict
) -> None:
    await append_event(
        ctx.session,
        user_id=ctx.user.id,
        channel=ctx.channel,
        direction="tool",
        type=type,
        payload=payload,
        trace_id=ctx.trace_id,
        clock=ctx.clock,
        idempotency_key=idempotency_key,
    )
