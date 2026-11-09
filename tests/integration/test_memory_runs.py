"""run 重试/指针前移、pending 隔离、抑制与 LLM 降级。"""

import datetime as dt
import json
import uuid

from sqlalchemy import select

from app.db.models import EventLog, Memory, MemoryDecisionLog, MemoryExtractionRun, User
from app.llm.schemas import LLMResult
from app.memory.pipeline import load_neighbors, process_candidate
from app.memory.runs import claim_due_run, process_run, schedule_runs
from app.memory.schemas import EvidenceItem, MemoryCandidate
from app.memory.validate import ValidatedCandidate

EVENT_ID = uuid.UUID("0197a000-0000-7000-8000-000000000010")


def _validated(**overrides) -> ValidatedCandidate:
    data = {
        "type_": "preference",
        "slot_key": None,
        "subject": "咖啡",
        "value": {"text": "喜欢拿铁"},
        "scope": {"kind": "persistent"},
        "source_class": "stated",
        "evidence_event_id": EVENT_ID,
    }
    data.update(overrides)
    event_id = data["evidence_event_id"]
    return ValidatedCandidate(
        candidate=MemoryCandidate(
            type=data["type_"],  # type: ignore[arg-type]
            slot_key=data["slot_key"],
            subject=data["subject"],
            value_text=str(data["value"].get("text", "")),
            evidence=[EvidenceItem(event_id=event_id, quote="我喜欢拿铁")],
            explicit=data["source_class"] == "stated",
        ),
        type=data["type_"],
        slot_key=data["slot_key"],
        subject=data["subject"],
        value=data["value"],
        scope=data["scope"],
        source_class=data["source_class"],
        explicit=data["source_class"] == "stated",
        confidence=0.9,
        sensitive_category=None,
        evidence=(EvidenceItem(event_id=event_id, quote="我喜欢拿铁"),),
        evidence_dates=(dt.date(2026, 1, 1),),
        fingerprint="fp",
    )


async def _seed_event(db, clock, text: str, *, minutes_ago: int) -> tuple[User, EventLog]:
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        event = EventLog(
            user_id=user.id, channel="console", direction="inbound", type="message",
            payload={"text": text}, trace_id="trace-retry",
            occurred_at=clock.now() - dt.timedelta(minutes=minutes_ago),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        return user, event


def _always_fail(messages: list[dict]) -> LLMResult:
    raise RuntimeError("llm down")


async def test_run_retries_then_fails_and_pointer_moves_forward(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, first_event = await _seed_event(db, fake_clock, "我平时7点起床", minutes_ago=30)
    gateway = make_gateway(_always_fail)

    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 1
    for attempt in range(4):
        run = await claim_due_run(db, now=fake_clock.now())
        if run is None:
            fake_clock.advance(70)
            run = await claim_due_run(db, now=fake_clock.now())
        assert run is not None, f"attempt {attempt} 没有可领取的 run"
        processed = await process_run(
            db, run.id,
            gateway=gateway, embedder=fake_embedder, clock=fake_clock, settings=settings,
        )
        assert processed is False
        async with db() as session:
            stored = await session.get(MemoryExtractionRun, run.id)
            assert stored is not None
            if attempt < 3:
                assert stored.status == "pending"
                assert stored.stats["attempts"] == attempt + 1
                assert "next_attempt_at" in stored.stats
            else:
                assert stored.status == "failed"
                assert stored.stats["attempts"] == 4
        if attempt < 3:
            fake_clock.advance(70)

    async with db() as session:
        failed_events = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_run_failed")
            )
        ).scalars().all()
    assert len(failed_events) == 1

    # 新事件到来：指针越过失败 run，创建新 run，不阻塞后续抽取
    async with db() as session:
        new_event = EventLog(
            user_id=user.id, channel="console", direction="inbound", type="message",
            payload={"text": "我平时8点起床"}, trace_id="trace-next",
            occurred_at=fake_clock.now() - dt.timedelta(minutes=15),
            recorded_at=fake_clock.now(),
        )
        session.add(new_event)
        await session.commit()
        new_event_id = new_event.id
    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 1
    async with db() as session:
        runs = (await session.execute(select(MemoryExtractionRun))).scalars().all()
    assert {run.to_event_id for run in runs} == {first_event.id, new_event_id}


async def test_pending_memory_not_used_as_neighbor(
    db, fake_clock, settings, fake_embedder
) -> None:
    user, _ = await _seed_event(db, fake_clock, "我喜欢拿铁", minutes_ago=10)
    embedding = await fake_embedder.embed_one("咖啡 喜欢拿铁")
    async with db() as session:
        active = Memory(
            user_id=user.id, type="preference", subject="咖啡", value={"text": "喜欢美式"},
            source_class="stated", weight=0.8, confidence=0.9, status="active",
            recorded_at=fake_clock.now(), support_days=1, contradict_count=0,
            embedding=embedding, embedding_model="fake-hash-1024",
        )
        pending = Memory(
            user_id=user.id, type="preference", subject="咖啡", value={"text": "可能喜欢摩卡"},
            source_class="inferred", weight=0.2, confidence=0.5, status="pending",
            recorded_at=fake_clock.now(), support_days=1, contradict_count=0,
            embedding=embedding, embedding_model="fake-hash-1024",
        )
        session.add_all([active, pending])
        await session.commit()
        active_id, pending_id = active.id, pending.id

    candidate = _validated()
    async with db() as session:
        neighbors = await load_neighbors(
            session, user, candidate, embedding, settings
        )
    ids = {neighbor.id for neighbor in neighbors}
    assert active_id in ids
    assert pending_id not in ids


async def test_suppressed_topic_writes_nothing(
    db, fake_clock, settings, fake_embedder
) -> None:
    user, _ = await _seed_event(db, fake_clock, "我喜欢拿铁", minutes_ago=10)
    embedding = await fake_embedder.embed_one("咖啡 喜欢美式")
    async with db() as session:
        memory = Memory(
            user_id=user.id, type="preference", subject="咖啡", value={"text": "喜欢美式"},
            source_class="stated", weight=0.8, confidence=0.9, status="active",
            recorded_at=fake_clock.now(), support_days=1, contradict_count=0,
            suppress_until=fake_clock.now() + dt.timedelta(days=7),
            embedding=embedding, embedding_model="fake-hash-1024",
        )
        session.add(memory)
        await session.commit()

    async with db() as session:
        outcome = await process_candidate(
            session, user=user, candidate=_validated(), run_id=None,
            extractor_version="memory-extract-v1", gateway=None, embedder=fake_embedder,
            clock=fake_clock, settings=settings, trace_id="suppress",
        )
        await session.commit()
    assert outcome.decision == "NOOP"
    assert outcome.reason == "suppressed"
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert len(memories) == 1
    assert len(logs) == 1 and logs[0].reason == "suppressed"


def _add_responder(messages: list[dict]) -> LLMResult:
    return LLMResult(
        content=json.dumps({"action": "ADD", "target_id": None, "reason": "episode"})
    )


async def test_episode_writes_valid_to_two_days_after_scope_date(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_event(db, fake_clock, "今天加班到九点", minutes_ago=5)
    gateway = make_gateway(_add_responder)
    candidate = _validated(
        type_="episode",
        subject="加班",
        value={"text": "加班到九点"},
        scope={"kind": "on", "date": "2026-11-06"},
        evidence_event_id=event.id,
    )
    async with db() as session:
        outcome = await process_candidate(
            session, user=user, candidate=candidate, run_id=None,
            extractor_version="memory-extract-v2", gateway=gateway, embedder=fake_embedder,
            clock=fake_clock, settings=settings, trace_id="episode-valid-to",
        )
        await session.commit()
        assert outcome.decision == "ADD"
        memory = await session.get(Memory, outcome.memory_id)

    assert memory is not None
    assert memory.valid_to == dt.datetime(2026, 11, 7, 16, 0, tzinfo=dt.UTC)


async def test_episode_does_not_create_slot_pending(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_event(db, fake_clock, "今天加班到九点", minutes_ago=5)
    gateway = make_gateway(_add_responder)
    async with db() as session:
        session.add(
            Memory(
                user_id=user.id, type="slot", slot_key="work_end", subject="下班时间",
                value={"text": "6点", "time": "18:00"}, scope={"kind": "persistent"},
                source_class="stated", weight=0.8, confidence=0.9, status="active",
                recorded_at=fake_clock.now(), support_days=1, contradict_count=0,
            )
        )
        await session.commit()

    candidate = _validated(
        type_="episode",
        subject="加班",
        value={"text": "加班到九点"},
        scope={"kind": "on", "date": "2026-11-06"},
        evidence_event_id=event.id,
    )
    async with db() as session:
        outcome = await process_candidate(
            session, user=user, candidate=candidate, run_id=None,
            extractor_version="memory-extract-v2", gateway=gateway, embedder=fake_embedder,
            clock=fake_clock, settings=settings, trace_id="episode-no-slot",
        )
        await session.commit()

    assert outcome.decision == "ADD"
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
    assert not any(memory.status == "pending" for memory in memories)
    assert all(memory.type != "slot" or memory.slot_key != "work_end" or memory.status == "active"
               for memory in memories)


async def test_episode_cap_rejects_sixth_episode(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_event(db, fake_clock, "今天加班到十点", minutes_ago=15)
    candidates = [
        {
            "type": "episode",
            "slot_key": None,
            "subject": f"加班{i}",
            "value_text": f"加班到十点{i}",
            "time_text": None,
            "scope": {"kind": "on", "date_text": "今天", "rule": None},
            "explicit": True,
            "confidence": 0.9,
            "sensitive_category": None,
            "evidence": [
                {"event_id": str(event.id), "quote": "今天加班到十点"}
            ],
        }
        for i in range(6)
    ]

    def responder(messages: list[dict]) -> LLMResult:
        if "记忆裁决器" in str(messages[0].get("content", "")):
            return LLMResult(content=json.dumps({"action": "ADD", "target_id": None, "reason": "add"}))
        return LLMResult(content=json.dumps({"candidates": candidates}, ensure_ascii=False))

    gateway = make_gateway(responder)
    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 1
    run = await claim_due_run(db, now=fake_clock.now())
    assert run is not None
    assert await process_run(
        db, run.id, gateway=gateway, embedder=fake_embedder, clock=fake_clock, settings=settings
    )
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
        stored_run = await session.get(MemoryExtractionRun, run.id)
    assert len([memory for memory in memories if memory.type == "episode"]) == 5
    assert not any(memory.subject == "加班5" for memory in memories)
    assert any(log.reason == "rejected:episode_cap" for log in logs)
    assert stored_run is not None
    assert stored_run.stats["rejected"]["rejected:episode_cap"] == 1


async def test_llm_resolve_failure_degrades_to_noop(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, _ = await _seed_event(db, fake_clock, "我喜欢拿铁", minutes_ago=10)
    embedding = await fake_embedder.embed_one("preference  咖啡口味 喜欢美式")
    async with db() as session:
        session.add(
            Memory(
                user_id=user.id, type="preference", subject="咖啡口味",
                value={"text": "喜欢美式"}, source_class="stated", weight=0.8,
                confidence=0.9, status="active", recorded_at=fake_clock.now(),
                support_days=1, contradict_count=0, embedding=embedding,
                embedding_model="fake-hash-1024",
            )
        )
        await session.commit()

    gateway = make_gateway(_always_fail)
    async with db() as session:
        outcome = await process_candidate(
            session, user=user, candidate=_validated(subject="咖啡", value={"text": "喜欢拿铁"}),
            run_id=None, extractor_version="memory-extract-v1", gateway=gateway,
            embedder=fake_embedder, clock=fake_clock, settings=settings,
            trace_id="degrade",
        )
        await session.commit()
    assert outcome.decision == "NOOP"
    assert outcome.reason == "llm_failed_conservative"
    assert outcome.degraded is True
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
    assert len(memories) == 1
