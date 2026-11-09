"""单候选写入管线：嵌入 → 近邻 → 裁决 → 落库 → 决策日志。

事务约定：调用方持有会话；本模块不 commit。异步抽取按候选逐个短事务提交，
remember 工具在工具的 savepoint 内执行。
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.core.timeutil import local_date_of
from app.db.models import (
    EventLog,
    LLMCall,
    Memory,
    MemoryDecisionLog,
    MemorySource,
    User,
)
from app.embeddings.service import EmbeddingService
from app.llm.gateway import LLMGateway
from app.memory.resolve import (
    RESOLVE_ALIAS,
    Neighbor,
    RuleDecision,
    resolve_rules,
    resolve_with_llm,
)
from app.memory.scope import scope_valid_to
from app.memory.validate import ValidatedCandidate
from app.memory.weights import (
    contradicted_weight,
    initial_weight,
    max_weight,
    reinforced_weight,
    support_days,
)


@dataclass
class CandidateOutcome:
    decision: str
    memory_id: uuid.UUID | None
    reason: str
    degraded: bool = False


def _candidate_text(candidate: ValidatedCandidate) -> str:
    parts = [candidate.type, candidate.slot_key or "", candidate.subject, candidate.value.get("text", "")]
    return " ".join(part for part in parts if part)


def _neighbor_rows_to_view(rows: list[tuple[Memory, float | None]]) -> list[Neighbor]:
    return [
        Neighbor(
            id=memory.id,
            type=memory.type,
            slot_key=memory.slot_key,
            subject=memory.subject,
            value=dict(memory.value or {}),
            scope=dict(memory.scope) if memory.scope else None,
            source_class=memory.source_class,
            status=memory.status,
            weight=float(memory.weight or 0.0),
            suppress_until=memory.suppress_until,
            similarity=None if distance is None else 1.0 - float(distance),
        )
        for memory, distance in rows
    ]


async def load_neighbors(
    session: AsyncSession,
    user: User,
    candidate: ValidatedCandidate,
    embedding: list[float] | None,
    settings: Settings,
) -> list[Neighbor]:
    """按 type 取 active 近邻；pending 不参与（防止未确证数据扩散）。"""
    if candidate.type == "slot":
        rows = (
            await session.execute(
                select(Memory)
                .where(
                    Memory.user_id == user.id,
                    Memory.type == "slot",
                    Memory.slot_key == candidate.slot_key,
                    Memory.status == "active",
                )
                .order_by(Memory.recorded_at.desc())
                .limit(20)
            )
        ).scalars().all()
        return _neighbor_rows_to_view([(row, None) for row in rows])

    results: list[tuple[Memory, float | None]] = []
    if embedding is not None:
        distance = Memory.embedding.cosine_distance(embedding)
        vector_rows = (
            await session.execute(
                select(Memory, distance.label("distance"))
                .where(
                    Memory.user_id == user.id,
                    Memory.type == candidate.type,
                    Memory.status == "active",
                    Memory.embedding.isnot(None),
                )
                .order_by(distance)
                .limit(settings.memory_neighbor_topk)
            )
        ).all()
        results.extend((memory, float(distance_value)) for memory, distance_value in vector_rows)

    exact_rows = (
        await session.execute(
            select(Memory)
            .where(
                Memory.user_id == user.id,
                Memory.type == candidate.type,
                Memory.status == "active",
                func.lower(Memory.subject) == candidate.subject.casefold(),
            )
            .limit(5)
        )
    ).scalars().all()
    known = {memory.id for memory, _ in results}
    results.extend((row, None) for row in exact_rows if row.id not in known)
    return _neighbor_rows_to_view(results)


async def _find_llm_call_id(session: AsyncSession, trace_id: str) -> uuid.UUID | None:
    return (
        await session.execute(
            select(LLMCall.id)
            .where(LLMCall.trace_id == trace_id, LLMCall.alias == RESOLVE_ALIAS)
            .order_by(LLMCall.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _existing_evidence_dates(
    session: AsyncSession, memory_id: uuid.UUID, tz: str, day_start: dt.time
) -> set[dt.date]:
    rows = (
        await session.execute(
            select(EventLog.occurred_at)
            .join(MemorySource, MemorySource.event_id == EventLog.id)
            .where(MemorySource.memory_id == memory_id)
        )
    ).scalars().all()
    return {local_date_of(at, tz, day_start) for at in rows}


async def _attach_sources(
    session: AsyncSession, memory_id: uuid.UUID, candidate: ValidatedCandidate
) -> None:
    values = [
        {"memory_id": memory_id, "event_id": item.event_id} for item in candidate.evidence
    ]
    if values:
        await session.execute(
            pg_insert(MemorySource)
            .values(values)
            .on_conflict_do_nothing(index_elements=["memory_id", "event_id"])
        )


async def _reinforce(
    session: AsyncSession,
    memory: Memory,
    candidate: ValidatedCandidate,
    *,
    user: User,
    clock: Clock,
) -> None:
    existing_dates = await _existing_evidence_dates(
        session, memory.id, user.timezone, user.day_start
    )
    new_dates = set(candidate.evidence_dates) - existing_dates
    if new_dates:
        memory.weight = reinforced_weight(
            memory.source_class, float(memory.weight or 0.0), len(new_dates)
        )
        memory.support_days = (memory.support_days or 0) + len(new_dates)
        memory.last_reinforced_at = clock.now()
    await _attach_sources(session, memory.id, candidate)


def _new_memory(
    user: User,
    candidate: ValidatedCandidate,
    *,
    status: str,
    supersedes_id: uuid.UUID | None,
    embedding: list[float] | None,
    embedding_model: str | None,
    clock: Clock,
    extractor_version: str | None,
) -> Memory:
    distinct = support_days(set(candidate.evidence_dates)) or 1
    weight = min(
        initial_weight(candidate.source_class) + 0.1 * max(0, distinct - 1),
        max_weight(candidate.source_class),
    )
    valid_to = (
        scope_valid_to(candidate.scope, user.timezone) if candidate.type == "episode" else None
    )
    return Memory(
        user_id=user.id,
        type=candidate.type,
        slot_key=candidate.slot_key,
        subject=candidate.subject,
        value=candidate.value,
        polarity=candidate.candidate.polarity,
        scope=candidate.scope,
        source_class=candidate.source_class,
        weight=weight,
        confidence=candidate.confidence,
        status=status,
        supersedes_id=supersedes_id,
        valid_from=clock.now(),
        valid_to=valid_to,
        recorded_at=clock.now(),
        support_days=distinct,
        contradict_count=0,
        last_reinforced_at=clock.now(),
        extractor_version=extractor_version,
        embedding=embedding,
        embedding_model=embedding_model if embedding is not None else None,
    )


def _log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    run_id: uuid.UUID | None,
    memory_id: uuid.UUID | None,
    candidate: ValidatedCandidate,
    neighbors: list[Neighbor],
    action: str,
    reason: str,
    alias: str | None,
    llm_call_id: uuid.UUID | None,
    clock: Clock,
    embedding_error: str | None,
    raw_fingerprint: str | None,
) -> None:
    candidate_payload = {
        "type": candidate.type,
        "slot_key": candidate.slot_key,
        "subject": candidate.subject,
        "value": candidate.value,
        "scope": candidate.scope,
        "source_class": candidate.source_class,
        "explicit": candidate.explicit,
        "confidence": candidate.confidence,
        "evidence": [
            {"event_id": str(item.event_id), "quote": item.quote} for item in candidate.evidence
        ],
        "fingerprint": candidate.fingerprint,
        "raw_fingerprint": raw_fingerprint,
        "notes": list(candidate.notes),
        "embedding_error": embedding_error,
    }
    session.add(
        MemoryDecisionLog(
            user_id=user_id,
            run_id=run_id,
            memory_id=memory_id,
            candidate=candidate_payload,
            neighbors={
                "items": [
                    {
                        "id": str(neighbor.id),
                        "type": neighbor.type,
                        "slot_key": neighbor.slot_key,
                        "subject": neighbor.subject,
                        "value": neighbor.value,
                        "scope": neighbor.scope,
                        "source_class": neighbor.source_class,
                        "status": neighbor.status,
                        "similarity": neighbor.similarity,
                    }
                    for neighbor in neighbors
                ]
            },
            action=action,
            reason=reason[:500],
            alias=alias,
            llm_call_id=llm_call_id,
            created_at=clock.now(),
        )
    )


async def _apply_decision(
    session: AsyncSession,
    *,
    user: User,
    candidate: ValidatedCandidate,
    neighbors: list[Neighbor],
    decision: RuleDecision,
    run_id: uuid.UUID | None,
    extractor_version: str | None,
    embedding: list[float] | None,
    embedding_model: str | None,
    alias: str | None,
    llm_call_id: uuid.UUID | None,
    clock: Clock,
    embedding_error: str | None,
    degraded: bool,
    raw_fingerprint: str | None,
) -> CandidateOutcome:
    action = "NOOP" if decision.action in ("MERGE", "NEEDS_LLM") else decision.action
    target = next((n for n in neighbors if n.id == decision.target_id), None)
    memory_id: uuid.UUID | None = None

    if action in ("NOOP", "ASK") and target is not None:
        memory = await session.get(Memory, target.id)
        if memory is not None:
            if action == "NOOP" and decision.reason in (
                "duplicate_slot",
                "duplicate_open_fact",
                "merge_as_noop",
            ):
                await _reinforce(session, memory, candidate, user=user, clock=clock)
            if action == "ASK":
                memory.contradict_count = (memory.contradict_count or 0) + 1
                memory.weight = contradicted_weight(float(memory.weight or 0.0))
            memory_id = memory.id

    if action == "ADD":
        memory = _new_memory(
            user,
            candidate,
            status="active",
            supersedes_id=None,
            embedding=embedding,
            embedding_model=embedding_model,
            clock=clock,
            extractor_version=extractor_version,
        )
        session.add(memory)
        await session.flush()
        memory_id = memory.id
    elif action == "ASK":
        memory = _new_memory(
            user,
            candidate,
            status="pending",
            supersedes_id=target.id if target else None,
            embedding=embedding,
            embedding_model=embedding_model,
            clock=clock,
            extractor_version=extractor_version,
        )
        session.add(memory)
        await session.flush()
        memory_id = memory.id
    elif action == "SUPERSEDE" and target is not None:
        old = await session.get(Memory, target.id)
        if old is not None:
            old.status = "superseded"
            old.superseded_at = clock.now()
        memory = _new_memory(
            user,
            candidate,
            status="active",
            supersedes_id=target.id,
            embedding=embedding,
            embedding_model=embedding_model,
            clock=clock,
            extractor_version=extractor_version,
        )
        session.add(memory)
        await session.flush()
        memory_id = memory.id

    if memory_id is not None and action in ("ADD", "ASK", "SUPERSEDE"):
        await _attach_sources(session, memory_id, candidate)

    _log(
        session,
        user_id=user.id,
        run_id=run_id,
        memory_id=memory_id,
        candidate=candidate,
        neighbors=neighbors,
        action=action,
        reason=decision.reason,
        alias=alias,
        llm_call_id=llm_call_id,
        clock=clock,
        embedding_error=embedding_error,
        raw_fingerprint=raw_fingerprint,
    )
    return CandidateOutcome(action, memory_id, decision.reason, degraded)


async def _embed_candidate(
    embedder: EmbeddingService | None, candidate: ValidatedCandidate
) -> tuple[list[float] | None, str | None]:
    if embedder is None:
        return None, "embedder_unavailable"
    try:
        return await embedder.embed_one(_candidate_text(candidate), kind="document"), None
    except Exception as exc:  # 嵌入失败不阻塞写入，保留空向量
        return None, f"{type(exc).__name__}: {exc}"


async def process_candidate(
    session: AsyncSession,
    *,
    user: User,
    candidate: ValidatedCandidate,
    run_id: uuid.UUID | None,
    extractor_version: str | None,
    gateway: LLMGateway | None,
    embedder: EmbeddingService | None,
    clock: Clock,
    settings: Settings,
    trace_id: str,
    explicit_remember: bool = False,
    raw_fingerprint: str | None = None,
) -> CandidateOutcome:
    """异步抽取 / 同步 remember 共用的单候选处理；调用方负责 commit。"""
    if run_id is not None:
        dedupe_fingerprint = raw_fingerprint or candidate.fingerprint
        dedupe_column = (
            MemoryDecisionLog.candidate["raw_fingerprint"].astext
            if raw_fingerprint is not None
            else MemoryDecisionLog.candidate["fingerprint"].astext
        )
        skipped = await session.execute(
            select(MemoryDecisionLog.id)
            .where(
                MemoryDecisionLog.run_id == run_id,
                dedupe_column == dedupe_fingerprint,
            )
            .limit(1)
        )
        if skipped.first() is not None:
            return CandidateOutcome("NOOP", None, "skipped_duplicate_run")

    embedding, embedding_error = await _embed_candidate(embedder, candidate)
    neighbors = await load_neighbors(session, user, candidate, embedding, settings)
    rules = resolve_rules(
        candidate,
        neighbors,
        now=clock.now(),
        threshold=settings.memory_neighbor_threshold,
    )
    used_llm = rules.needs_llm and not explicit_remember
    degraded = False
    if rules.needs_llm and explicit_remember:
        # 同步路径拿不到网关：用户明确陈述的开放事实按 ADD 写入
        decision = RuleDecision("ADD", "sync_explicit")
        alias = None
    else:
        decision, degraded = await resolve_with_llm(
            gateway,
            candidate,
            neighbors,
            now=clock.now(),
            threshold=settings.memory_neighbor_threshold,
            trace_id=trace_id,
            user_id=user.id,
        )
        alias = RESOLVE_ALIAS if used_llm else None
    llm_call_id = await _find_llm_call_id(session, trace_id) if used_llm else None

    return await _apply_decision(
        session,
        user=user,
        candidate=candidate,
        neighbors=neighbors,
        decision=decision,
        run_id=run_id,
        extractor_version=extractor_version,
        embedding=embedding,
        embedding_model=embedder.model_name if embedding is not None and embedder else None,
        alias=alias,
        llm_call_id=llm_call_id,
        clock=clock,
        embedding_error=embedding_error,
        degraded=degraded,
        raw_fingerprint=raw_fingerprint,
    )
