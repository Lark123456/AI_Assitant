"""抽取集成：run 幂等、证据回查拒绝、敏感拦截、向量与决策日志落库。"""

import datetime as dt
import json

from sqlalchemy import select

from app.core.clock import FakeClock
from app.db.models import (
    EventLog,
    Memory,
    MemoryDecisionLog,
    MemoryExtractionRun,
    MemorySource,
    User,
)
from app.llm.schemas import LLMResult
from app.memory.runs import claim_due_run, process_run, schedule_runs
from app.memory.validate import compute_fingerprint


async def _seed(db, clock: FakeClock) -> tuple[User, EventLog, EventLog]:
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        inbound = EventLog(
            user_id=user.id, channel="console", direction="inbound", type="message",
            payload={"text": "我平时7点起床，最近在吃降压药"}, trace_id="trace-1",
            occurred_at=clock.now() - dt.timedelta(minutes=15), recorded_at=clock.now(),
        )
        assistant = EventLog(
            user_id=user.id, channel="console", direction="outbound", type="message",
            payload={"text": "好的，我记住了"}, trace_id="trace-2",
            occurred_at=clock.now() - dt.timedelta(minutes=14), recorded_at=clock.now(),
        )
        session.add_all([inbound, assistant])
        await session.commit()
        return user, inbound, assistant


def _responder(inbound: EventLog, assistant: EventLog):
    def responder(messages: list[dict]) -> LLMResult:
        system = str(messages[0]["content"])
        if "记忆裁决器" in system:
            return LLMResult(
                content=json.dumps(
                    {"action": "ADD", "target_id": None, "reason": "open fact"}
                )
            )
        common = {
            "scope": {"kind": "persistent", "date_text": None, "rule": None},
            "explicit": True,
            "confidence": 0.9,
            "sensitive_category": None,
        }
        candidates = [
            {
                **common,
                "type": "slot",
                "slot_key": "wake",
                "subject": "起床时间",
                "value_text": "7点",
                "time_text": "7点",
                "evidence": [
                    {"event_id": str(inbound.id), "quote": "我平时7点起床"}
                ],
            },
            {
                **common,
                "type": "preference",
                "slot_key": "favorite_color",
                "subject": "喜欢的颜色",
                "value_text": "蓝色",
                "time_text": None,
                "evidence": [
                    {"event_id": str(inbound.id), "quote": "我平时7点起床"}
                ],
            },
            {
                **common,
                "type": "preference",
                "slot_key": None,
                "subject": "起床时间",
                "value_text": "6点",
                "time_text": None,
                "evidence": [
                    {"event_id": str(inbound.id), "quote": "我每天6点起床"}
                ],
            },
            {
                **common,
                "type": "preference",
                "slot_key": None,
                "subject": "助手说的话",
                "value_text": "记住了",
                "time_text": None,
                "evidence": [
                    {"event_id": str(assistant.id), "quote": "好的，我记住了"}
                ],
            },
            {
                **common,
                "type": "preference",
                "slot_key": None,
                "subject": "身体状况",
                "value_text": "吃降压药",
                "time_text": None,
                "sensitive_category": "health",
                "evidence": [
                    {"event_id": str(inbound.id), "quote": "最近在吃降压药"}
                ],
            },
        ]
        return LLMResult(content=json.dumps({"candidates": candidates}, ensure_ascii=False))

    return responder


async def test_extraction_writes_memory_and_rejections(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, inbound, assistant = await _seed(db, fake_clock)
    gateway = make_gateway(_responder(inbound, assistant))

    created = await schedule_runs(db, clock=fake_clock, settings=settings)
    assert created == 1
    # 同一批重复调度不会创建第二个 run
    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 0

    run = await claim_due_run(db, now=fake_clock.now())
    assert run is not None
    assert await process_run(
        db,
        run.id,
        gateway=gateway,
        embedder=fake_embedder,
        clock=fake_clock,
        settings=settings,
    )

    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
        run_row = await session.get(MemoryExtractionRun, run.id)
        sources = (await session.execute(select(MemorySource))).scalars().all()

    assert run_row is not None and run_row.status == "done"
    # 有效槽位 + 越界槽位降级为 preference（两条都写入）
    assert len(memories) == 2
    slot = next(memory for memory in memories if memory.type == "slot")
    assert slot.slot_key == "wake"
    assert slot.value == {"text": "7点", "time": "07:00"}
    assert slot.source_class == "stated"
    assert slot.embedding is not None and slot.embedding_model == "fake-hash-1024"
    assert slot.extractor_version == "memory-extract-v2"
    assert len(sources) == 2  # 每条记忆一个证据事件

    reasons = {log.reason for log in logs if log.action == "NOOP"}
    assert "rejected:evidence_not_found" in reasons
    assert "rejected:evidence_not_in_batch" in reasons
    assert "rejected:sensitive" in reasons
    assert {log.action for log in logs} == {"ADD", "NOOP"}

    # 重试同一 run 不重复产生记忆或日志
    async with db() as session:
        stored = await session.get(MemoryExtractionRun, run.id)
        assert stored is not None
        stored.status = "pending"
        await session.commit()
    assert await process_run(
        db,
        run.id,
        gateway=gateway,
        embedder=fake_embedder,
        clock=fake_clock,
        settings=settings,
    )
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
        stored = await session.get(MemoryExtractionRun, run.id)
    assert len(memories) == 2
    assert len(logs) == 5
    assert stored is not None and stored.stats["skipped_duplicates"] == 5


def test_raw_fingerprint_is_stable() -> None:
    payload = {"type": "slot", "subject": "起床时间", "value": {"text": "7点"}}
    assert compute_fingerprint(payload) == compute_fingerprint(payload)
    assert compute_fingerprint(payload) != compute_fingerprint({"type": "preference"})
