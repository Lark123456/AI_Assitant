"""候选的确定性校验：证据、来源、槽位、时间、scope 与敏感类别。"""

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import local_date_of
from app.db.models import EventLog, User
from app.memory.schemas import (
    SENSITIVE_CATEGORIES,
    SLOT_KEYS,
    TIME_SLOT_KEYS,
    EvidenceItem,
    MemoryCandidate,
)
from app.memory.scope import normalize_scope
from app.memory.text import (
    parse_tool_name_from_result_key,
    quote_matches,
    render_tool_fact,
    result_key_to_call_key,
)
from app.memory.timeparse import parse_time_text

REMEMBER_INTENT_KEYWORDS = ("记住", "记一下", "记下", "帮我记", "别忘了", "牢记")


@dataclass(frozen=True)
class EventRecord:
    """批次内可用于证据的事件：用户消息或已验证工具事实。"""

    event_id: uuid.UUID
    source: str  # user | tool
    text: str
    occurred_at: dt.datetime


@dataclass(frozen=True)
class ValidatedCandidate:
    candidate: MemoryCandidate
    type: str
    slot_key: str | None
    subject: str
    value: dict
    scope: dict
    source_class: str
    explicit: bool
    confidence: float
    sensitive_category: str | None
    evidence: tuple[EvidenceItem, ...]
    evidence_dates: tuple[dt.date, ...]
    fingerprint: str
    notes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RejectedCandidate:
    candidate: MemoryCandidate
    reason: str


async def build_event_index(
    session: AsyncSession, events: list[EventLog]
) -> dict[uuid.UUID, EventRecord]:
    """把批次事件转成可引用的文本；tool_result 只认成功调用的结构化参数。"""
    result_keys = [
        event.idempotency_key
        for event in events
        if event.type == "tool_result" and event.idempotency_key
    ]
    call_keys = [result_key_to_call_key(key) for key in result_keys]
    call_rows = (
        (
            await session.execute(
                select(EventLog).where(EventLog.idempotency_key.in_(call_keys))
            )
        )
        .scalars()
        .all()
    ) if call_keys else []
    calls = {row.idempotency_key: row for row in call_rows}

    index: dict[uuid.UUID, EventRecord] = {}
    for event in events:
        if event.direction == "inbound" and event.type == "message":
            text = str(event.payload.get("text", ""))
            if text:
                index[event.id] = EventRecord(event.id, "user", text, event.occurred_at)
            continue
        if event.direction == "tool" and event.type == "tool_result":
            if event.payload.get("status") != "ok":
                continue
            tool = parse_tool_name_from_result_key(event.idempotency_key)
            if tool is None:
                continue
            call = calls.get(result_key_to_call_key(event.idempotency_key or ""))
            if call is None:
                continue
            rendered = render_tool_fact(
                tool,
                dict(call.payload.get("arguments") or {}),
                dict(event.payload.get("data") or {}),
            )
            if rendered:
                index[event.id] = EventRecord(event.id, "tool", rendered, event.occurred_at)
    return index


def _remember_intent(texts: list[str]) -> bool:
    return any(keyword in text for text in texts for keyword in REMEMBER_INTENT_KEYWORDS)


def compute_fingerprint(payload: dict) -> str:
    """候选的确定性指纹（重试去重用）。"""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_fingerprint = compute_fingerprint


def validate_candidate(
    *,
    user: User,
    candidate: MemoryCandidate,
    event_index: dict[uuid.UUID, EventRecord],
    explicit_remember: bool = False,
) -> ValidatedCandidate | RejectedCandidate:
    """校验单个候选；拒绝原因稳定可审计。"""
    evidences = list(candidate.evidence)
    texts: list[str] = []
    dates: list[dt.date] = []
    for item in evidences:
        record = event_index.get(item.event_id)
        if record is None:
            return RejectedCandidate(candidate, "rejected:evidence_not_in_batch")
        if not quote_matches(item.quote, record.text):
            return RejectedCandidate(candidate, "rejected:evidence_not_found")
        texts.append(record.text)
        dates.append(local_date_of(record.occurred_at, user.timezone, user.day_start))

    if not any(event_index[item.event_id].source == "user" for item in evidences):
        return RejectedCandidate(candidate, "rejected:no_user_evidence")

    notes: list[str] = []
    if candidate.sensitive_category is not None:
        if candidate.sensitive_category not in SENSITIVE_CATEGORIES:
            return RejectedCandidate(candidate, "rejected:sensitive_unknown")
        if not explicit_remember and not _remember_intent(texts):
            return RejectedCandidate(candidate, "rejected:sensitive")

    type_ = candidate.type
    slot_key = candidate.slot_key
    if type_ == "slot":
        if slot_key not in SLOT_KEYS:
            if not candidate.subject.strip():
                return RejectedCandidate(candidate, "rejected:slot_key_invalid")
            type_ = "preference"
            slot_key = None
            notes.append("slot_key_invalid_downgraded")

    value: dict = {"text": candidate.value_text.strip()}
    if type_ == "slot" and slot_key in TIME_SLOT_KEYS:
        parsed_time = parse_time_text(candidate.time_text or candidate.value_text)
        if parsed_time is None:
            return RejectedCandidate(candidate, "rejected:slot_time_unparsed")
        value["time"] = parsed_time
    elif candidate.time_text:
        parsed_time = parse_time_text(candidate.time_text)
        if parsed_time is not None:
            value["time"] = parsed_time

    first_event_time = event_index[evidences[0].event_id].occurred_at
    scope = normalize_scope(candidate.scope, first_event_time, user.timezone, user.day_start)
    if scope is None:
        return RejectedCandidate(candidate, "rejected:scope_unparsed")

    source_class = "stated" if candidate.explicit else "inferred"
    normalized = ValidatedCandidate(
        candidate=candidate,
        type=type_,
        slot_key=slot_key,
        subject=candidate.subject.strip(),
        value=value,
        scope=scope,
        source_class=source_class,
        explicit=candidate.explicit,
        confidence=candidate.confidence,
        sensitive_category=candidate.sensitive_category,
        evidence=tuple(evidences),
        evidence_dates=tuple(dates),
        fingerprint=_fingerprint(
            {
                "type": type_,
                "slot_key": slot_key,
                "subject": candidate.subject.strip(),
                "value": value,
                "scope": scope,
                "polarity": candidate.polarity,
                "evidence": [
                    {"event_id": str(item.event_id), "quote": item.quote} for item in evidences
                ],
            }
        ),
        notes=tuple(notes),
    )
    return normalized
