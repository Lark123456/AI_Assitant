"""remember 工具：用户明确要求记住时的同步写入（slot / preference / episode）。"""

from typing import Literal

from pydantic import BaseModel, Field

from app.db.models import EventLog, Memory
from app.memory.pipeline import process_candidate
from app.memory.schemas import EvidenceItem, MemoryCandidate, ScopeSpec
from app.memory.validate import (
    RejectedCandidate,
    build_event_index,
    validate_candidate,
)
from app.tools.base import ToolContext, ToolDef, ToolResult, require_source_event_id


class RememberArgs(BaseModel):
    type: Literal["slot", "preference", "episode"] = Field(
        description="记忆类型；state_signal 只能由异步抽取写入"
    )
    slot_key: str | None = Field(
        default=None,
        description="type=slot 时必填：work_start | work_end | lunch | sleep | wake | commute | energy_peak | fixed_event",
    )
    subject: str = Field(min_length=1, max_length=200, description="短标题，如「起床时间」")
    value: str = Field(min_length=1, max_length=500, description="事实内容，如「7点」或「今天加班到九点」")
    scope: str | None = Field(
        default=None,
        description="persistent（默认）| on:今天 | until:月底；可写相对日期文本，由代码归一化",
    )
    evidence_quote: str = Field(min_length=1, max_length=300, description="用户原话片段，必须逐字出现")


def _parse_scope(raw: str | None) -> ScopeSpec:
    if raw is None or not raw.strip() or raw.strip() in ("persistent", "长期", "永久"):
        return ScopeSpec(kind="persistent")
    value = raw.strip()
    if value.startswith("on:"):
        return ScopeSpec(kind="on", date_text=value[3:].strip() or None)
    if value.startswith("until:"):
        return ScopeSpec(kind="until", date_text=value[5:].strip() or None)
    return ScopeSpec(kind="on", date_text=value)


async def _run_remember(ctx: ToolContext, args: dict) -> ToolResult:
    parsed = RememberArgs.model_validate(args)
    source_event_id = require_source_event_id(ctx)
    event = await ctx.session.get(EventLog, source_event_id)
    if event is None:
        return ToolResult(status="error", message="找不到当前入站事件，无法写入记忆")
    index = await build_event_index(ctx.session, [event])

    candidate = MemoryCandidate(
        type=parsed.type,
        slot_key=parsed.slot_key,
        subject=parsed.subject,
        value_text=parsed.value,
        time_text=parsed.value if parsed.type == "slot" else None,
        scope=_parse_scope(parsed.scope),
        explicit=True,
        confidence=0.9,
        evidence=[EvidenceItem(event_id=source_event_id, quote=parsed.evidence_quote)],
    )
    validated = validate_candidate(
        user=ctx.user,
        candidate=candidate,
        event_index=index,
        explicit_remember=True,
    )
    if isinstance(validated, RejectedCandidate):
        return ToolResult(status="error", message=f"记忆候选被拒绝：{validated.reason}")

    outcome = await process_candidate(
        ctx.session,
        user=ctx.user,
        candidate=validated,
        run_id=None,
        extractor_version=None,
        gateway=None,
        embedder=ctx.embedder,
        clock=ctx.clock,
        settings=ctx.settings,
        trace_id=ctx.trace_id,
        explicit_remember=True,
    )

    if outcome.decision == "ASK" and outcome.memory_id is not None:
        pending = await ctx.session.get(Memory, outcome.memory_id)
        existing: Memory | None = None
        if pending is not None and pending.supersedes_id is not None:
            existing = await ctx.session.get(Memory, pending.supersedes_id)
        return ToolResult(
            status="pending_confirmation",
            data={
                "pending_memory_id": str(outcome.memory_id),
                "existing_memory_id": str(existing.id) if existing else None,
                "existing_subject": existing.subject if existing else None,
                "existing_value": existing.value if existing else None,
            },
            message="已有不同的记录，是否用新值替换？",
        )

    if outcome.decision in ("ADD", "SUPERSEDE", "NOOP"):
        return ToolResult(
            status="ok",
            data={
                "memory_id": str(outcome.memory_id) if outcome.memory_id else None,
                "action": outcome.decision,
                "reason": outcome.reason,
            },
            message="记忆已写入" if outcome.decision != "NOOP" else "已有相同记忆，无需重复写入",
        )
    return ToolResult(
        status="error",
        message=f"记忆未写入：{outcome.reason}",
    )


REMEMBER = ToolDef(
    name="remember",
    description=(
        "用户明确要求记住或明确陈述长期事实时，同步写入记忆。"
        "type 支持 slot / preference / episode；state_signal 不允许同步写入。"
        "evidence_quote 必须是用户原话片段。写操作，幂等键由系统按入站事件派生。"
    ),
    args_model=RememberArgs,
    run=_run_remember,
    write=True,
)
