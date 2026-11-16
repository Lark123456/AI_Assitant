"""记忆不变量（需要 Postgres）：

- inferred 来源的候选不得 supersede stated / confirmed 记忆
- 槽位 scope 归一化标记写入决策日志的 candidate JSON
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import UTC, FakeClock
from app.core.config import Settings
from app.db.models import EventLog, Memory, MemoryDecisionLog, User
from app.memory.pipeline import process_candidate
from app.memory.schemas import EvidenceItem, MemoryCandidate, ScopeSpec
from app.memory.validate import EventRecord, ValidatedCandidate, validate_candidate

NOW = dt.datetime(2026, 11, 6, 2, 0, tzinfo=UTC)


async def _user_with_event(db: async_sessionmaker[AsyncSession]) -> tuple[User, uuid.UUID]:
    """用户 + 一条可引用的入站事件（memory_source 有外键约束）。"""
    async with db() as session:
        user = User(
            display_name=f"inv-{uuid.uuid4().hex[:6]}",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
            rev=1,
        )
        session.add(user)
        await session.flush()
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": "我平时7点起床"},
            trace_id=f"inv-{uuid.uuid4().hex[:6]}",
            occurred_at=NOW,
            recorded_at=NOW,
        )
        session.add(event)
        await session.commit()
        return user, event.id


def _candidate(
    *,
    event_id: uuid.UUID,
    type_: str,
    slot_key: str | None,
    subject: str,
    value_text: str,
    source_class: str,
    confidence: float = 0.9,
) -> ValidatedCandidate:
    candidate = MemoryCandidate(
        type=type_,  # type: ignore[arg-type]
        slot_key=slot_key,
        subject=subject,
        value_text=value_text,
        explicit=source_class == "stated",
        confidence=confidence,
        scope=ScopeSpec(kind="persistent"),
        evidence=[EvidenceItem(event_id=event_id, quote="我平时7点起床")],
    )
    return ValidatedCandidate(
        candidate=candidate,
        type=type_,
        slot_key=slot_key,
        subject=subject,
        value={"text": value_text},
        scope={"kind": "persistent"},
        source_class=source_class,
        explicit=source_class == "stated",
        confidence=confidence,
        sensitive_category=None,
        evidence=tuple(candidate.evidence),
        evidence_dates=(dt.date(2026, 11, 6),),
        fingerprint=f"fp-{uuid.uuid4().hex}",
    )


async def test_inferred_candidate_cannot_supersede_stated_memory(
    db, fake_clock: FakeClock, settings: Settings
) -> None:
    user, event_id = await _user_with_event(db)
    async with db() as session:
        old = Memory(
            user_id=user.id,
            type="preference",
            slot_key=None,
            subject="咖啡",
            value={"text": "喜欢美式"},
            scope={"kind": "persistent"},
            source_class="stated",
            weight=0.8,
            confidence=0.9,
            status="active",
            recorded_at=NOW,
            valid_from=NOW,
            support_days=1,
            contradict_count=0,
            last_reinforced_at=NOW,
        )
        session.add(old)
        await session.commit()
        old_id = old.id

    relaxed = settings.model_copy(update={"memory_neighbor_threshold": 0.0})
    candidate = _candidate(
        event_id=event_id,
        type_="preference",
        slot_key=None,
        subject="咖啡",
        value_text="喜欢拿铁",
        source_class="inferred",
    )
    async with db() as session:
        outcome = await process_candidate(
            session,
            user=user,
            candidate=candidate,
            run_id=None,
            extractor_version="memory-extract-v2.1",
            gateway=None,
            embedder=None,
            clock=fake_clock,
            settings=relaxed,
            trace_id="inv-1",
        )
        await session.commit()

    assert outcome.decision == "ASK"
    assert outcome.reason == "inferred_cannot_override"

    async with db() as session:
        stored = await session.get(Memory, old_id)
        assert stored is not None
        assert stored.status == "active"
        pending = (
            await session.execute(
                select(Memory).where(
                    Memory.user_id == user.id,
                    Memory.status == "pending",
                    Memory.type == "preference",
                )
            )
        ).scalars().all()
        assert len(pending) == 1
        assert pending[0].supersedes_id == old_id


async def test_slot_scope_normalized_note_is_logged(
    db, fake_clock: FakeClock, settings: Settings
) -> None:
    user, event_id = await _user_with_event(db)
    raw = MemoryCandidate(
        type="slot",
        slot_key="wake",
        subject="起床时间",
        value_text="7点",
        time_text="7点",
        explicit=True,
        confidence=0.9,
        scope=ScopeSpec(kind="recurring", rule=None),
        evidence=[EvidenceItem(event_id=event_id, quote="我平时7点起床")],
    )
    index = {event_id: EventRecord(event_id, "user", "我平时7点起床", NOW)}
    validated = validate_candidate(user=user, candidate=raw, event_index=index)
    assert isinstance(validated, ValidatedCandidate)

    async with db() as session:
        await process_candidate(
            session,
            user=user,
            candidate=validated,
            run_id=None,
            extractor_version="memory-extract-v2.1",
            gateway=None,
            embedder=None,
            clock=fake_clock,
            settings=settings,
            trace_id="inv-2",
        )
        await session.commit()

    async with db() as session:
        logs = (
            await session.execute(
                select(MemoryDecisionLog).where(MemoryDecisionLog.user_id == user.id)
            )
        ).scalars().all()
    assert len(logs) == 1
    payload = logs[0].candidate or {}
    assert "slot_scope_normalized" in (payload.get("notes") or [])
