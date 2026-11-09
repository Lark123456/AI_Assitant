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
from app.memory.scope import normalize_scope, scope_valid_to
from app.memory.text import (
    parse_tool_name_from_result_key,
    quote_matches,
    render_tool_fact,
    result_key_to_call_key,
)
from app.memory.timeparse import disambiguate_slot_time, parse_time_text

# 敏感类别关键词兜底：模型漏标时仍能拦截；词表保守，避免误伤常见表达
_SENSITIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "health": (
        "糖尿病", "高血压", "低血压", "血压", "血糖", "体检", "医院", "住院",
        "手术", "吃药", "服药", "降压药", "抑郁", "焦虑症", "怀孕", "发烧",
        "感冒", "过敏", "诊断", "病历",
    ),
    "finance": (
        "工资", "薪资", "存款", "贷款", "房贷", "车贷", "信用卡", "欠款",
        "借款", "收入", "股票", "基金", "纳税", "税额", "报销",
    ),
    "exact_location": (
        "住址", "家庭住址", "家住", "门牌", "小区", "楼栋", "单元", "经纬度",
        "身份证",
    ),
    "third_party": (
        "我朋友", "我同事", "我老板", "我妈妈", "我爸爸", "我妈", "我爸",
        "室友", "手机号", "电话号码", "电话是", "微信号", "邮箱",
    ),
    "credentials": (
        "密码", "验证码", "密钥", "API key", "api key", "token", "账号密码",
    ),
}


def _keyword_sensitive(texts: list[str]) -> tuple[str, str] | None:
    """返回 (类别, 命中词)；词表保守，宁可漏拦也不误伤。"""
    for category, keywords in _SENSITIVE_KEYWORDS.items():
        for keyword in keywords:
            if any(keyword in text for text in texts):
                return category, keyword
    return None


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
    now: dt.datetime | None = None,
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
    if candidate.sensitive_category is not None and candidate.sensitive_category not in (
        SENSITIVE_CATEGORIES
    ):
        return RejectedCandidate(candidate, "rejected:sensitive_unknown")
    if not explicit_remember:
        # 异步抽取一律拒绝敏感类别；模型漏标时用关键词兜底
        if candidate.sensitive_category is not None:
            return RejectedCandidate(candidate, "rejected:sensitive")
        candidate_texts = [candidate.subject, candidate.value_text] + [
            item.quote for item in evidences
        ]
        hit = _keyword_sensitive(candidate_texts)
        if hit is not None:
            category, keyword = hit
            return RejectedCandidate(
                candidate, f"rejected:sensitive_keyword:{category}:{keyword}"
            )

    type_ = candidate.type
    slot_key = candidate.slot_key
    if type_ == "slot":
        if slot_key not in SLOT_KEYS:
            if not candidate.subject.strip():
                return RejectedCandidate(candidate, "rejected:slot_key_invalid")
            type_ = "preference"
            slot_key = None
            notes.append("slot_key_invalid_downgraded")
    elif type_ == "episode":
        if candidate.confidence < 0.6:
            return RejectedCandidate(candidate, "rejected:episode_low_confidence")

    value: dict = {"text": candidate.value_text.strip()}
    if type_ == "slot" and slot_key in TIME_SLOT_KEYS:
        parsed_time = parse_time_text(candidate.time_text or candidate.value_text)
        if parsed_time is None:
            return RejectedCandidate(candidate, "rejected:slot_time_unparsed")
        value["time"] = disambiguate_slot_time(slot_key, parsed_time)
    elif candidate.time_text:
        parsed_time = parse_time_text(candidate.time_text)
        if parsed_time is not None:
            value["time"] = parsed_time

    first_event_time = event_index[evidences[0].event_id].occurred_at
    scope = normalize_scope(candidate.scope, first_event_time, user.timezone, user.day_start)
    if scope is None:
        return RejectedCandidate(candidate, "rejected:scope_unparsed")

    # slot 只允许长期或周期；episode 必须有明确日期范围
    if type_ == "slot" and scope["kind"] not in ("persistent", "recurring"):
        return RejectedCandidate(candidate, "rejected:slot_scope")
    if type_ == "episode" and scope["kind"] not in ("on", "until"):
        return RejectedCandidate(candidate, "rejected:episode_scope")

    if type_ == "episode" and now is not None:
        valid_to = scope_valid_to(scope, user.timezone)
        if valid_to is not None and valid_to <= now:
            return RejectedCandidate(candidate, "rejected:episode_date_past")

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
