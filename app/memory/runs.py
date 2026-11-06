"""抽取 run 的调度、领取、处理与有限重试。"""

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.core.ids import new_uuid7
from app.core.logging import get_logger
from app.db.models import (
    EventLog,
    MemoryDecisionLog,
    MemoryExtractionRun,
    User,
)
from app.embeddings.service import EmbeddingService
from app.engine.events import append_event
from app.llm.gateway import LLMGateway
from app.memory.extract import (
    EXTRACTOR_VERSION,
    embed_query,
    extract_candidates,
    load_related_memories,
    query_text,
)
from app.memory.pipeline import process_candidate
from app.memory.validate import (
    RejectedCandidate,
    build_event_index,
    compute_fingerprint,
    validate_candidate,
)

logger = get_logger(__name__)

MAX_RETRIES = 3  # 首次 + 3 次重试 = 最多 4 次尝试
RETRY_BASE_SECONDS = 30.0
RETRY_MAX_SECONDS = 120.0


@dataclass
class RunStats:
    events: int = 0
    candidates: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    actions: dict[str, int] = field(default_factory=dict)
    skipped_duplicates: int = 0
    embedding_failures: int = 0
    degraded: int = 0

    def as_dict(self) -> dict:
        return {
            "events": self.events,
            "candidates": self.candidates,
            "rejected": self.rejected,
            "actions": self.actions,
            "skipped_duplicates": self.skipped_duplicates,
            "embedding_failures": self.embedding_failures,
            "degraded": self.degraded,
        }


def _retry_delay(attempts: int) -> float:
    delay = RETRY_BASE_SECONDS * (2 ** max(0, attempts - 1))
    return float(min(RETRY_MAX_SECONDS, delay))


async def _latest_run(session: AsyncSession, user_id: uuid.UUID) -> MemoryExtractionRun | None:
    return (
        await session.execute(
            select(MemoryExtractionRun)
            .where(MemoryExtractionRun.user_id == user_id)
            .order_by(MemoryExtractionRun.created_at.desc(), MemoryExtractionRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _run_exists_pending(session: AsyncSession, user_id: uuid.UUID) -> bool:
    return (
        await session.execute(
            select(MemoryExtractionRun.id)
            .where(
                MemoryExtractionRun.user_id == user_id,
                MemoryExtractionRun.status == "pending",
            )
            .limit(1)
        )
    ).first() is not None


async def _ready_event(
    session: AsyncSession, target_id: uuid.UUID
) -> EventLog:
    event = await session.get(EventLog, target_id)
    if event is None:
        raise RuntimeError(f"run target event missing: {target_id}")
    return event


async def schedule_runs(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    clock: Clock,
    settings: Settings,
) -> int:
    """为满足空闲/批量条件的用户创建 run；唯一约束保证重复调度不重复处理。"""
    now = clock.now()
    created = 0
    async with sessionmaker() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            if await _run_exists_pending(session, user.id):
                continue
            latest = await _latest_run(session, user.id)
            covered = await _ready_event(session, latest.to_event_id) if latest else None

            filters = [
                EventLog.user_id == user.id,
                EventLog.direction == "inbound",
                EventLog.type == "message",
            ]
            if covered is not None:
                filters.append(
                    or_(
                        EventLog.occurred_at > covered.occurred_at,
                        and_(
                            EventLog.occurred_at == covered.occurred_at,
                            EventLog.id > covered.id,
                        ),
                    )
                )
            messages = (
                (
                    await session.execute(
                        select(EventLog)
                        .where(*filters)
                        .order_by(EventLog.occurred_at, EventLog.id)
                    )
                )
                .scalars()
                .all()
            )
            if not messages:
                continue
            latest_message = messages[-1]
            idle = now - latest_message.occurred_at >= dt.timedelta(
                minutes=settings.memory_idle_minutes
            )
            if not idle and len(messages) < settings.memory_batch_max_events:
                continue

            row = (
                await session.execute(
                    pg_insert(MemoryExtractionRun)
                    .values(
                        id=new_uuid7(),
                        user_id=user.id,
                        to_event_id=latest_message.id,
                        extractor_version=EXTRACTOR_VERSION,
                        event_count=len(messages),
                        status="pending",
                        stats={},
                        created_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["user_id", "to_event_id", "extractor_version"]
                    )
                    .returning(MemoryExtractionRun.id)
                )
            ).scalar_one_or_none()
            if row is not None:
                created += 1
        await session.commit()
    if created:
        logger.info("memory: scheduled %d extraction runs", created)
    return created


async def claim_due_run(
    sessionmaker: async_sessionmaker[AsyncSession], *, now: dt.datetime
) -> MemoryExtractionRun | None:
    """领取一个到期的 pending run（单 worker 串行处理）。"""
    async with sessionmaker() as session:
        rows = (
            (
                await session.execute(
                    select(MemoryExtractionRun)
                    .where(MemoryExtractionRun.status == "pending")
                    .order_by(MemoryExtractionRun.created_at)
                    .limit(10)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for run in rows:
            raw_next = (run.stats or {}).get("next_attempt_at")
            if raw_next:
                try:
                    if dt.datetime.fromisoformat(str(raw_next)) > now:
                        continue
                except ValueError:
                    pass
            await session.commit()
            return run
        await session.commit()
    return None


async def _previous_run(
    session: AsyncSession, run: MemoryExtractionRun
) -> MemoryExtractionRun | None:
    return (
        await session.execute(
            select(MemoryExtractionRun)
            .where(
                MemoryExtractionRun.user_id == run.user_id,
                or_(
                    MemoryExtractionRun.created_at < run.created_at,
                    and_(
                        MemoryExtractionRun.created_at == run.created_at,
                        MemoryExtractionRun.id < run.id,
                    ),
                ),
            )
            .order_by(MemoryExtractionRun.created_at.desc(), MemoryExtractionRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _load_batch(
    session: AsyncSession, run: MemoryExtractionRun
) -> list[EventLog]:
    target = await _ready_event(session, run.to_event_id)
    previous = await _previous_run(session, run)
    previous_event = (
        await _ready_event(session, previous.to_event_id) if previous is not None else None
    )
    filters = [
        EventLog.user_id == run.user_id,
        EventLog.direction == "inbound",
        EventLog.type == "message",
        or_(
            EventLog.occurred_at < target.occurred_at,
            and_(EventLog.occurred_at == target.occurred_at, EventLog.id <= target.id),
        ),
    ]
    if previous_event is not None:
        filters.append(
            or_(
                EventLog.occurred_at > previous_event.occurred_at,
                and_(
                    EventLog.occurred_at == previous_event.occurred_at,
                    EventLog.id > previous_event.id,
                ),
            )
        )
    messages = (
        (
            await session.execute(
                select(EventLog).where(*filters).order_by(EventLog.occurred_at, EventLog.id)
            )
        )
        .scalars()
        .all()
    )
    trace_ids = {message.trace_id for message in messages}
    tool_results = (
        (
            await session.execute(
                select(EventLog)
                .where(
                    EventLog.user_id == run.user_id,
                    EventLog.direction == "tool",
                    EventLog.type == "tool_result",
                    EventLog.trace_id.in_(trace_ids),
                )
                .order_by(EventLog.occurred_at, EventLog.id)
            )
        )
        .scalars()
        .all()
    ) if trace_ids else []
    return list(messages) + list(tool_results)


async def _mark_done(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    stats: RunStats,
    *,
    clock: Clock,
) -> None:
    async with sessionmaker() as session:
        run = await session.get(MemoryExtractionRun, run_id)
        if run is None:
            return
        merged = dict(run.stats or {})
        merged.update(stats.as_dict())
        run.stats = merged
        run.status = "done"
        run.error = None
        run.finished_at = clock.now()
        await session.commit()


async def _mark_failed(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    exc: Exception,
    *,
    clock: Clock,
) -> None:
    async with sessionmaker() as session:
        run = await session.get(MemoryExtractionRun, run_id)
        if run is None:
            return
        stats = dict(run.stats or {})
        attempts = int(stats.get("attempts", 0)) + 1
        stats["attempts"] = attempts
        run.error = f"{type(exc).__name__}: {exc}"[:500]
        if attempts > MAX_RETRIES:
            run.status = "failed"
            run.finished_at = clock.now()
            await append_event(
                session,
                user_id=run.user_id,
                channel="system",
                direction="system",
                type="memory_run_failed",
                payload={
                    "run_id": str(run.id),
                    "attempts": attempts,
                    "error": run.error,
                    "to_event_id": str(run.to_event_id),
                },
                trace_id=f"memory-run:{run.id}",
                clock=clock,
                idempotency_key=f"memory-run-failed:{run.id}:{attempts}",
            )
            logger.error(
                "memory extraction run failed after %d attempts: run=%s error=%s",
                attempts, run.id, run.error,
            )
        else:
            run.status = "pending"
            stats["next_attempt_at"] = (
                clock.now() + dt.timedelta(seconds=_retry_delay(attempts))
            ).isoformat()
            logger.warning(
                "memory extraction run failed, retry %d/%d: run=%s error=%s",
                attempts, MAX_RETRIES, run.id, run.error,
            )
        run.stats = stats
        await session.commit()


async def process_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    gateway: LLMGateway,
    embedder: EmbeddingService | None,
    clock: Clock,
    settings: Settings,
) -> bool:
    """处理一个 run；成功返回 True，失败已记录重试状态返回 False。"""
    trace_id = f"memory-run:{run_id}"
    try:
        async with sessionmaker() as session:
            run = await session.get(MemoryExtractionRun, run_id)
            if run is None or run.status != "pending":
                return True
            user = await session.get(User, run.user_id)
            if user is None:
                raise RuntimeError(f"user missing for run: {run_id}")
            events = await _load_batch(session, run)
            index = await build_event_index(session, events)
            await session.commit()

        if not index:
            await _mark_done(sessionmaker, run_id, RunStats(), clock=clock)
            return True

        query_vector = await embed_query(embedder, query_text(index))
        async with sessionmaker() as session:
            related = await load_related_memories(session, user, query_vector, settings)
            await session.commit()

        extracted = await extract_candidates(
            gateway,
            user=user,
            tz=user.timezone,
            events=index,
            related=related,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.exception("memory extraction failed: run=%s", run_id)
        await _mark_failed(sessionmaker, run_id, exc, clock=clock)
        return False

    stats = RunStats(events=len(index), candidates=len(extracted.candidates))
    for candidate in extracted.candidates:
        raw_fp = compute_fingerprint(candidate.model_dump(mode="json"))
        async with sessionmaker() as session:
            existing = await session.execute(
                select(MemoryDecisionLog.id)
                .where(
                    MemoryDecisionLog.run_id == run_id,
                    MemoryDecisionLog.candidate["raw_fingerprint"].astext == raw_fp,
                )
                .limit(1)
            )
            if existing.first() is not None:
                stats.skipped_duplicates += 1
                await session.commit()
                continue

            validated = validate_candidate(
                user=user, candidate=candidate, event_index=index
            )
            if isinstance(validated, RejectedCandidate):
                session.add(
                    MemoryDecisionLog(
                        user_id=user.id,
                        run_id=run_id,
                        memory_id=None,
                        candidate={
                            "raw": candidate.model_dump(mode="json"),
                            "raw_fingerprint": raw_fp,
                        },
                        neighbors=None,
                        action="NOOP",
                        reason=validated.reason,
                        alias=None,
                        llm_call_id=None,
                        created_at=clock.now(),
                    )
                )
                stats.rejected[validated.reason] = (
                    stats.rejected.get(validated.reason, 0) + 1
                )
                await session.commit()
                continue

            outcome = await process_candidate(
                session,
                user=user,
                candidate=validated,
                run_id=run_id,
                extractor_version=EXTRACTOR_VERSION,
                gateway=gateway,
                embedder=embedder,
                clock=clock,
                settings=settings,
                trace_id=trace_id,
                raw_fingerprint=raw_fp,
            )
            await session.commit()
            stats.actions[outcome.decision] = stats.actions.get(outcome.decision, 0) + 1
            if outcome.degraded:
                stats.degraded += 1

    await _mark_done(sessionmaker, run_id, stats, clock=clock)
    logger.info(
        "memory run done: run=%s events=%d candidates=%d actions=%s rejected=%s",
        run_id, stats.events, stats.candidates, stats.actions, stats.rejected,
    )
    return True


async def memory_worker_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    gateway: LLMGateway,
    embedder: EmbeddingService | None,
    clock: Clock,
    settings: Settings,
) -> None:
    """worker 内的独立循环：定期调度并串行处理 run，不阻塞 trigger。"""
    interval = max(30.0, settings.materialize_interval_seconds)
    while True:
        try:
            await schedule_runs(sessionmaker, clock=clock, settings=settings)
            for _ in range(3):
                run = await claim_due_run(sessionmaker, now=clock.now())
                if run is None:
                    break
                await process_run(
                    sessionmaker,
                    run.id,
                    gateway=gateway,
                    embedder=embedder,
                    clock=clock,
                    settings=settings,
                )
        except Exception:
            logger.exception("memory worker iteration failed")
        await asyncio.sleep(interval)
