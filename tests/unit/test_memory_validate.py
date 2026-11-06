"""候选校验：证据、来源、槽位、时间、scope 与敏感类别。"""

import datetime as dt
import uuid

from app.core.clock import UTC
from app.db.models import User
from app.memory.schemas import EvidenceItem, MemoryCandidate, ScopeSpec
from app.memory.validate import (
    EventRecord,
    RejectedCandidate,
    validate_candidate,
)

USER = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
EVENT_ID = uuid.UUID("0197a000-0000-7000-8000-000000000001")
AT = dt.datetime(2026, 11, 6, 0, 0, tzinfo=UTC)


def _index(text: str, source: str = "user") -> dict[uuid.UUID, EventRecord]:
    return {EVENT_ID: EventRecord(EVENT_ID, source, text, AT)}


def _candidate(**overrides) -> MemoryCandidate:
    data = {
        "type": "slot",
        "slot_key": "wake",
        "subject": "起床时间",
        "value_text": "7点",
        "time_text": "7点",
        "explicit": True,
        "confidence": 0.9,
        "evidence": [EvidenceItem(event_id=EVENT_ID, quote="我平时7点起床")],
    }
    data.update(overrides)
    return MemoryCandidate(**data)


def test_valid_slot_normalizes_time_and_scope() -> None:
    validated = validate_candidate(
        user=USER, candidate=_candidate(), event_index=_index("我平时7点起床，周末会晚一点")
    )
    assert not isinstance(validated, RejectedCandidate)
    assert validated.type == "slot"
    assert validated.slot_key == "wake"
    assert validated.value == {"text": "7点", "time": "07:00"}
    assert validated.scope == {"kind": "persistent"}
    assert validated.source_class == "stated"


def test_quote_with_whitespace_difference_passes() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我平时 7 点 起床")]
        ),
        event_index=_index("我平时7点起床"),
    )
    assert not isinstance(validated, RejectedCandidate)


def test_tampered_quote_is_rejected() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我每天8点起床")]
        ),
        event_index=_index("我平时7点起床"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:evidence_not_found"


def test_tool_only_evidence_is_rejected() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="工具事实")]
        ),
        event_index=_index("工具事实", source="tool"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:no_user_evidence"


def test_invalid_slot_key_downgrades_to_preference() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="slot",
            slot_key="favorite_color",
            time_text=None,
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我最喜欢蓝色")],
        ),
        event_index=_index("我最喜欢蓝色"),
    )
    assert not isinstance(validated, RejectedCandidate)
    assert validated.type == "preference"
    assert validated.slot_key is None
    assert "slot_key_invalid_downgraded" in validated.notes


def test_slot_time_unparsed_is_rejected() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            value_text="随缘",
            time_text="随缘",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我一般随缘起床")],
        ),
        event_index=_index("我一般随缘起床"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:slot_time_unparsed"


def test_sensitive_requires_remember_intent() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="preference",
            slot_key=None,
            time_text=None,
            subject="身体状况",
            value_text="有糖尿病",
            sensitive_category="health",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我有糖尿病")],
        ),
        event_index=_index("我有糖尿病"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:sensitive"

    allowed = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="preference",
            slot_key=None,
            time_text=None,
            subject="身体状况",
            value_text="有糖尿病",
            sensitive_category="health",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="记住我有糖尿病")],
        ),
        event_index=_index("记住我有糖尿病"),
    )
    assert not isinstance(allowed, RejectedCandidate)


def test_unparsed_scope_is_rejected() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(scope=ScopeSpec(kind="on", date_text="某个时候")),
        event_index=_index("我平时7点起床"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:scope_unparsed"
