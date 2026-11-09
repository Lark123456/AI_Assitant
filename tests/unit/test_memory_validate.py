"""候选校验：证据、来源、槽位、时间、scope 与敏感类别。"""

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

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


def test_sensitive_rejected_in_async_even_with_remember_words() -> None:
    validated = validate_candidate(
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
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:sensitive"


def test_sensitive_allowed_with_explicit_remember_flag() -> None:
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
        explicit_remember=True,
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


def test_slot_scope_must_be_persistent_or_recurring() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(scope=ScopeSpec(kind="on", date_text="今天")),
        event_index=_index("我平时7点起床"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:slot_scope"


def _episode(**overrides) -> MemoryCandidate:
    data = {
        "type": "episode",
        "slot_key": None,
        "subject": "加班",
        "value_text": "加班到九点",
        "time_text": None,
        "explicit": True,
        "confidence": 0.9,
        "scope": ScopeSpec(kind="on", date_text="今天"),
        "evidence": [EvidenceItem(event_id=EVENT_ID, quote="今天加班到九点")],
    }
    data.update(overrides)
    return MemoryCandidate(**data)


def test_episode_requires_on_or_until_scope() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_episode(scope=ScopeSpec(kind="persistent")),
        event_index=_index("今天加班到九点"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:episode_scope"


def test_episode_requires_min_confidence() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_episode(confidence=0.5),
        event_index=_index("今天加班到九点"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:episode_low_confidence"


def test_episode_past_date_rejected() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_episode(
            scope=ScopeSpec(kind="on", date_text="上周三"),
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="上周三加班到九点")],
        ),
        event_index=_index("上周三加班到九点"),
        now=dt.datetime(2026, 11, 6, 2, 0, tzinfo=UTC),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:episode_date_past"


def test_yesterday_episode_still_in_window_is_accepted() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_episode(
            scope=ScopeSpec(kind="on", date_text="昨天"),
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="昨天加班到九点")],
        ),
        event_index=_index("昨天加班到九点"),
        now=dt.datetime(2026, 11, 6, 2, 0, tzinfo=UTC),
    )
    assert not isinstance(validated, RejectedCandidate)
    assert validated.scope == {"kind": "on", "date": "2026-11-05"}


def test_keyword_sensitive_fallback_rejects_and_records_word() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="preference",
            slot_key=None,
            time_text=None,
            subject="收入",
            value_text="2万",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="记住我的工资是2万")],
        ),
        event_index=_index("记住我的工资是2万"),
    )
    assert isinstance(validated, RejectedCandidate)
    assert validated.reason == "rejected:sensitive_keyword:finance:工资"


def test_keyword_sensitive_does_not_hit_benign_bank_employment() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="preference",
            slot_key=None,
            time_text=None,
            subject="工作",
            value_text="在银行上班",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我在银行上班")],
        ),
        event_index=_index("我在银行上班"),
    )
    assert not isinstance(validated, RejectedCandidate)


def test_remember_path_bypasses_keyword_sensitive_fallback() -> None:
    validated = validate_candidate(
        user=USER,
        candidate=_candidate(
            type="preference",
            slot_key=None,
            time_text=None,
            subject="收入",
            value_text="2万",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="记住我的工资是2万")],
        ),
        event_index=_index("记住我的工资是2万"),
        explicit_remember=True,
    )
    assert not isinstance(validated, RejectedCandidate)


def test_state_signal_is_not_in_extractor_schema() -> None:
    with pytest.raises(ValidationError):
        MemoryCandidate(
            type="state_signal",  # type: ignore[arg-type]
            subject="精力",
            value_text="充沛",
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我精力充沛")],
        )
