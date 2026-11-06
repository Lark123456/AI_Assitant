"""同步 remember：slot 写入、冲突 pending、episode 支持、异步去重。"""

import datetime as dt
import json

from sqlalchemy import select

from app.db.models import EventLog, Memory, MemoryDecisionLog, MemorySource, User
from app.llm.schemas import LLMResult
from app.memory.runs import claim_due_run, process_run, schedule_runs
from app.tools.base import ToolContext
from app.tools.registry import execute_tool


async def _seed_event(db, clock, text: str, *, minutes_ago: int = 0) -> tuple[User, EventLog]:
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        event = EventLog(
            user_id=user.id, channel="console", direction="inbound", type="message",
            payload={"text": text}, trace_id="trace-sync",
            occurred_at=clock.now() - dt.timedelta(minutes=minutes_ago),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        return user, event


async def _remember(db, clock, settings, user, event, args, embedder, call_index=1):
    async with db() as session:
        user = await session.get(User, user.id)
        assert user is not None
        ctx = ToolContext(
            session=session, clock=clock, settings=settings, user=user,
            trace_id="sync", channel="console", source_event_id=event.id,
            embedder=embedder,
        )
        result = await execute_tool(ctx, "remember", args, call_index=call_index)
        await session.commit()
        return result


async def test_remember_slot_writes_memory_with_source(db, fake_clock, settings, fake_embedder) -> None:
    user, event = await _seed_event(db, fake_clock, "我平时7点起床")
    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        ctx = ToolContext(
            session=session, clock=fake_clock, settings=settings, user=fresh_user,
            trace_id="sync", channel="console", source_event_id=event.id,
            embedder=fake_embedder,
        )
        result = await execute_tool(
            ctx,
            "remember",
            {
                "type": "slot",
                "slot_key": "wake",
                "subject": "起床时间",
                "value": "7点",
                "evidence_quote": "我平时7点起床",
            },
            call_index=1,
        )
        await session.commit()
    assert result.status == "ok"
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        sources = (await session.execute(select(MemorySource))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert len(memories) == 1
    assert memories[0].status == "active"
    assert memories[0].value == {"text": "7点", "time": "07:00"}
    assert memories[0].embedding is not None
    assert len(sources) == 1
    assert logs[0].action == "ADD" and logs[0].run_id is None


async def test_remember_slot_conflict_returns_pending_confirmation(
    db, fake_clock, settings, fake_embedder
) -> None:
    user, first_event = await _seed_event(db, fake_clock, "我平时7点起床")
    first = await _remember(
        db, fake_clock, settings, user, first_event,
        {
            "type": "slot", "slot_key": "wake", "subject": "起床时间",
            "value": "7点", "evidence_quote": "我平时7点起床",
        },
        fake_embedder,
    )
    assert first.status == "ok"

    async with db() as session:
        second_event = EventLog(
            user_id=user.id, channel="console", direction="inbound", type="message",
            payload={"text": "我现在8点起床"}, trace_id="trace-sync-2",
            occurred_at=fake_clock.now(), recorded_at=fake_clock.now(),
        )
        session.add(second_event)
        await session.commit()
    result = await _remember(
        db, fake_clock, settings, user, second_event,
        {
            "type": "slot", "slot_key": "wake", "subject": "起床时间",
            "value": "8点", "evidence_quote": "我现在8点起床",
        },
        fake_embedder,
        call_index=2,
    )
    assert result.status == "pending_confirmation"
    assert result.data["existing_value"] == {"text": "7点", "time": "07:00"}
    async with db() as session:
        memories = (
            await session.execute(select(Memory).order_by(Memory.recorded_at))
        ).scalars().all()
    assert len(memories) == 2
    assert memories[0].status == "active"
    assert memories[1].status == "pending"
    assert memories[1].supersedes_id == memories[0].id


async def test_remember_episode_is_allowed(db, fake_clock, settings, fake_embedder) -> None:
    user, event = await _seed_event(db, fake_clock, "今天加班到九点")
    result = await _remember(
        db, fake_clock, settings, user, event,
        {
            "type": "episode", "subject": "加班", "value": "加班到九点",
            "scope": "on:今天", "evidence_quote": "今天加班到九点",
        },
        fake_embedder,
    )
    assert result.status == "ok"
    async with db() as session:
        memory = (await session.execute(select(Memory))).scalar_one()
    assert memory.type == "episode"
    assert memory.scope == {"kind": "on", "date": "2026-01-01"}


async def test_state_signal_is_rejected_by_tool_schema(
    db, fake_clock, settings, fake_embedder
) -> None:
    user, event = await _seed_event(db, fake_clock, "我精力很充沛")
    result = await _remember(
        db, fake_clock, settings, user, event,
        {
            "type": "state_signal", "subject": "精力", "value": "充沛",
            "evidence_quote": "我精力很充沛",
        },
        fake_embedder,
    )
    assert result.status == "error"


async def test_async_extraction_dedupes_sync_memory(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_event(db, fake_clock, "我平时7点起床", minutes_ago=15)
    result = await _remember(
        db, fake_clock, settings, user, event,
        {
            "type": "slot", "slot_key": "wake", "subject": "起床时间",
            "value": "7点", "evidence_quote": "我平时7点起床",
        },
        fake_embedder,
    )
    assert result.status == "ok"

    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(
            content=json.dumps(
                {
                    "candidates": [
                        {
                            "type": "slot",
                            "slot_key": "wake",
                            "subject": "起床时间",
                            "value_text": "7点",
                            "time_text": "7点",
                            "scope": {"kind": "persistent", "date_text": None, "rule": None},
                            "explicit": True,
                            "confidence": 0.9,
                            "sensitive_category": None,
                            "evidence": [
                                {"event_id": str(event.id), "quote": "我平时7点起床"}
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )

    gateway = make_gateway(responder)
    assert await schedule_runs(db, clock=fake_clock, settings=settings) == 1
    run = await claim_due_run(db, now=fake_clock.now())
    assert run is not None
    assert await process_run(
        db, run.id, gateway=gateway, embedder=fake_embedder,
        clock=fake_clock, settings=settings,
    )
    async with db() as session:
        memories = (await session.execute(select(Memory))).scalars().all()
        logs = (await session.execute(select(MemoryDecisionLog))).scalars().all()
    assert len(memories) == 1
    actions = {log.action for log in logs}
    assert actions == {"ADD", "NOOP"}
    assert any(log.reason == "duplicate_slot" for log in logs)
