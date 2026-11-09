"""resolve_rules 表驱动：槽位、例外、开放事实、抑制与保守降级。"""

import datetime as dt
import uuid

import pytest

from app.core.clock import UTC
from app.memory.resolve import Neighbor, resolve_rules
from app.memory.schemas import EvidenceItem, MemoryCandidate
from app.memory.validate import ValidatedCandidate

NOW = dt.datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
EVENT_ID = uuid.UUID("0197a000-0000-7000-8000-000000000002")
THRESHOLD = 0.75


def _candidate(
    *,
    type_: str = "slot",
    slot_key: str | None = "wake",
    subject: str = "起床时间",
    value: dict | None = None,
    scope: dict | None = None,
    source_class: str = "stated",
) -> ValidatedCandidate:
    value = value or {"text": "7点", "time": "07:00"}
    scope = scope or {"kind": "persistent"}
    return ValidatedCandidate(
        candidate=MemoryCandidate(
            type=type_,  # type: ignore[arg-type]
            slot_key=slot_key,
            subject=subject,
            value_text=str(value.get("text", "")),
            evidence=[EvidenceItem(event_id=EVENT_ID, quote="我平时7点起床")],
            explicit=source_class == "stated",
        ),
        type=type_,
        slot_key=slot_key,
        subject=subject,
        value=value,
        scope=scope,
        source_class=source_class,
        explicit=source_class == "stated",
        confidence=0.9,
        sensitive_category=None,
        evidence=(EvidenceItem(event_id=EVENT_ID, quote="我平时7点起床"),),
        evidence_dates=(dt.date(2026, 11, 6),),
        fingerprint="fp",
    )


def _neighbor(**overrides) -> Neighbor:
    data = {
        "id": uuid.UUID("0197a000-0000-7000-8000-000000000003"),
        "type": "slot",
        "slot_key": "wake",
        "subject": "起床时间",
        "value": {"text": "8点", "time": "08:00"},
        "scope": {"kind": "persistent"},
        "source_class": "stated",
        "status": "active",
        "weight": 0.8,
        "suppress_until": None,
        "similarity": None,
    }
    data.update(overrides)
    return Neighbor(**data)


def test_slot_without_neighbors_adds() -> None:
    decision = resolve_rules(_candidate(), [], now=NOW, threshold=THRESHOLD)
    assert decision.action == "ADD"


def test_slot_same_value_noops() -> None:
    decision = resolve_rules(
        _candidate(),
        [_neighbor(value={"text": "7点", "time": "07:00"})],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NOOP"
    assert decision.reason == "duplicate_slot"


def test_slot_conflict_goes_pending() -> None:
    decision = resolve_rules(_candidate(), [_neighbor()], now=NOW, threshold=THRESHOLD)
    assert decision.action == "ASK"
    assert decision.target_id == uuid.UUID("0197a000-0000-7000-8000-000000000003")


def test_episode_scope_never_compares_against_persistent_slot() -> None:
    decision = resolve_rules(
        _candidate(scope={"kind": "on", "date": "2026-11-06"}),
        [_neighbor()],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "ADD"


def test_same_episode_same_day_is_duplicate() -> None:
    decision = resolve_rules(
        _candidate(
            type_="episode",
            slot_key=None,
            subject="加班",
            value={"text": "加班到九点"},
            scope={"kind": "on", "date": "2026-11-06"},
        ),
        [
            _neighbor(
                type="episode",
                slot_key=None,
                subject="加班",
                value={"text": "加班到九点"},
                scope={"kind": "on", "date": "2026-11-06"},
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NOOP"
    assert decision.reason == "duplicate_open_fact"


def test_same_episode_different_day_is_not_duplicate() -> None:
    decision = resolve_rules(
        _candidate(
            type_="episode",
            slot_key=None,
            subject="加班",
            value={"text": "加班到九点"},
            scope={"kind": "on", "date": "2026-11-06"},
        ),
        [
            _neighbor(
                type="episode",
                slot_key=None,
                subject="加班",
                value={"text": "加班到九点"},
                scope={"kind": "on", "date": "2026-11-05"},
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NEEDS_LLM"


def test_suppressed_topic_noops() -> None:
    decision = resolve_rules(
        _candidate(),
        [_neighbor(suppress_until=NOW + dt.timedelta(days=3))],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NOOP"
    assert decision.reason == "suppressed"


def test_open_fact_exact_duplicate_noops_without_vector() -> None:
    decision = resolve_rules(
        _candidate(
            type_="preference",
            slot_key=None,
            subject="咖啡",
            value={"text": "喜欢拿铁"},
        ),
        [
            _neighbor(
                type="preference",
                slot_key=None,
                subject="咖啡",
                value={"text": "喜欢拿铁"},
                similarity=None,
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NOOP"
    assert decision.reason == "duplicate_open_fact"


def test_inferred_vs_stated_goes_pending() -> None:
    decision = resolve_rules(
        _candidate(
            type_="preference",
            slot_key=None,
            subject="咖啡",
            value={"text": "可能喜欢拿铁"},
            source_class="inferred",
        ),
        [
            _neighbor(
                type="preference",
                slot_key=None,
                subject="咖啡口味",
                value={"text": "喜欢美式"},
                similarity=0.9,
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "ASK"
    assert decision.reason == "inferred_cannot_override"


def test_ambiguous_open_fact_needs_llm() -> None:
    decision = resolve_rules(
        _candidate(
            type_="preference",
            slot_key=None,
            subject="咖啡",
            value={"text": "喜欢拿铁"},
        ),
        [
            _neighbor(
                type="preference",
                slot_key=None,
                subject="饮品偏好",
                value={"text": "常喝美式"},
                similarity=0.8,
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == "NEEDS_LLM"


@pytest.mark.parametrize(
    ("status", "expected"),
    [("pending", "NEEDS_LLM"), ("superseded", "NEEDS_LLM")],
)
def test_non_active_neighbors_are_not_used(status: str, expected: str) -> None:
    decision = resolve_rules(
        _candidate(
            type_="preference",
            slot_key=None,
            subject="咖啡",
            value={"text": "喜欢拿铁"},
        ),
        [
            _neighbor(
                type="preference",
                slot_key=None,
                subject="咖啡",
                value={"text": "喜欢拿铁"},
                status=status,
            )
        ],
        now=NOW,
        threshold=THRESHOLD,
    )
    assert decision.action == expected
