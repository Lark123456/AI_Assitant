"""Friday 记忆注入：注入内容、检索查询构造、审计与降级。"""

import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from app.agents.friday.agent import FridayAgent
from app.db.models import EventLog, Memory, User
from app.llm.schemas import LLMResult
from app.memory.retrieve import BLOCK_HEADER, RETRIEVAL_VERSION

MODEL = "fake-hash-1024"


async def _seed_user_and_event(db, clock, text: str = "我今天几点起床来着？"):
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": text},
            trace_id="trace-friday",
            occurred_at=clock.now(),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        return user, event


async def _add_slot(db, clock, fake_embedder, user: User) -> None:
    embedding = await fake_embedder.embed_one("slot wake 起床时间 7点")
    async with db() as session:
        session.add(
            Memory(
                user_id=user.id,
                type="slot",
                slot_key="wake",
                subject="起床时间",
                value={"text": "7点", "time": "07:00"},
                scope={"kind": "persistent"},
                source_class="stated",
                weight=0.8,
                confidence=0.9,
                status="active",
                recorded_at=clock.now(),
                support_days=1,
                contradict_count=0,
                last_reinforced_at=clock.now(),
                embedding=embedding,
                embedding_model=MODEL,
            )
        )
        await session.commit()


async def _add_preference(db, clock, fake_embedder, user: User) -> None:
    embedding = await fake_embedder.embed_one("preference 咖啡 喜欢美式")
    async with db() as session:
        session.add(
            Memory(
                user_id=user.id,
                type="preference",
                subject="咖啡",
                value={"text": "喜欢美式"},
                scope={"kind": "persistent"},
                source_class="stated",
                weight=0.8,
                confidence=0.9,
                status="active",
                recorded_at=clock.now(),
                support_days=1,
                contradict_count=0,
                last_reinforced_at=clock.now(),
                embedding=embedding,
                embedding_model=MODEL,
            )
        )
        await session.commit()


def _reply(text: str):
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text)

    return responder


def _enabled(settings, **overrides):
    return settings.model_copy(update={"memory_inject_enabled": True, **overrides})


class _RecordingEmbedder:
    """记录检索查询文本，用于验证查询构造。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.queries: list[str] = []

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def embed_one(self, text: str, *, kind: str = "document"):
        self.queries.append(text)
        return await self._inner.embed_one(text, kind=kind)


class _SlowEmbedder:
    model_name = "slow-model"

    async def embed_one(self, text: str, *, kind: str = "document"):
        await asyncio.sleep(1.0)
        return [0.0] * 1024


async def _handle(db, clock, settings, gateway, user, event, *, text, embedder):
    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        reply = await FridayAgent(gateway).handle(
            session=session,
            clock=clock,
            settings=settings,
            user=fresh_user,
            trace_id="trace-friday",
            channel="console",
            source_event_id=event.id,
            text=text,
            embedder=embedder,
        )
        await session.commit()
        return reply


async def _audits(db) -> list[EventLog]:
    async with db() as session:
        return (
            await session.execute(select(EventLog).where(EventLog.type == "memory_context"))
        ).scalars().all()


async def test_friday_injects_slot_and_writes_audit(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    gateway = make_gateway(_reply("你平时 7:00 起床。"))

    reply = await _handle(
        db, fake_clock, _enabled(settings), gateway, user, event,
        text="我今天几点起床来着？", embedder=fake_embedder,
    )

    assert reply == "你平时 7:00 起床。"
    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    system_prompt = str(provider.calls[0][0]["content"])
    assert "【已知长期信息】" in system_prompt
    assert "长期作息：" in system_prompt
    assert "起床时间：07:00" in system_prompt

    rows = await _audits(db)
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["retrieval_version"] == RETRIEVAL_VERSION
    assert payload["source_event_id"] == str(event.id)
    assert payload["enabled"] is True
    assert payload["result_count"] == 1
    assert payload["retrieved_count"] == 1
    assert payload["degraded"] is False
    assert payload["embedding_model"] == MODEL
    assert payload["duration_ms"] >= 0
    assert payload["memory_ids"]
    assert set(payload["similarities"]) == set(payload["memory_ids"])


async def test_no_hit_still_writes_audit(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock, "今天天气不错")
    gateway = make_gateway(_reply("是挺好的。"))

    await _handle(
        db, fake_clock, _enabled(settings), gateway, user, event,
        text="今天天气不错", embedder=fake_embedder,
    )

    rows = await _audits(db)
    assert len(rows) == 1
    assert rows[0].payload["result_count"] == 0
    assert rows[0].payload["retrieved_count"] == 0
    assert rows[0].payload["memory_ids"] == []


async def test_disabled_still_writes_audit_and_skips_embedding(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    recording = _RecordingEmbedder(fake_embedder)
    gateway = make_gateway(_reply("你平时 7:00 起床。"))
    disabled = settings.model_copy(update={"memory_inject_enabled": False})

    await _handle(
        db, fake_clock, disabled, gateway, user, event,
        text="我今天几点起床来着？", embedder=recording,
    )

    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    assert "【已知长期信息】" not in str(provider.calls[0][0]["content"])
    assert recording.queries == []
    rows = await _audits(db)
    assert len(rows) == 1
    assert rows[0].payload["enabled"] is False
    assert rows[0].payload["result_count"] == 0


async def test_embedding_timeout_degrades_to_slots(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    gateway = make_gateway(_reply("你平时 7:00 起床。"))
    timed = _enabled(settings, memory_inject_timeout_seconds=0.01)

    reply = await _handle(
        db, fake_clock, timed, gateway, user, event,
        text="我今天几点起床来着？", embedder=_SlowEmbedder(),
    )

    assert reply == "你平时 7:00 起床。"
    rows = await _audits(db)
    assert len(rows) == 1
    assert rows[0].payload["degraded"] is True
    assert rows[0].payload["degraded_reason"] == "embedding_timeout"
    assert rows[0].payload["result_count"] == 1


async def test_retrieval_query_uses_recent_user_messages_only(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock, "那个几点来着？")
    async with db() as session:
        session.add_all(
            [
                EventLog(
                    user_id=user.id, channel="console", direction="inbound", type="message",
                    payload={"text": "我一般七点起床"}, trace_id="t1",
                    occurred_at=fake_clock.now() - dt.timedelta(minutes=10),
                    recorded_at=fake_clock.now(),
                ),
                EventLog(
                    user_id=user.id, channel="console", direction="outbound", type="message",
                    payload={"text": "好的，我记住了"}, trace_id="t2",
                    occurred_at=fake_clock.now() - dt.timedelta(minutes=9),
                    recorded_at=fake_clock.now(),
                ),
            ]
        )
        await session.commit()
    recording = _RecordingEmbedder(fake_embedder)
    gateway = make_gateway(_reply("你七点起床。"))

    await _handle(
        db, fake_clock, _enabled(settings), gateway, user, event,
        text="那个几点来着？", embedder=recording,
    )

    assert len(recording.queries) == 1
    query = recording.queries[0]
    assert "我一般七点起床" in query
    assert "那个几点来着？" in query
    assert "好的，我记住了" not in query


async def test_budget_truncation_audits_only_injected_ids(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    await _add_preference(db, fake_clock, fake_embedder, user)
    gateway = make_gateway(_reply("好。"))
    tight = _enabled(
        settings,
        memory_inject_max_chars=len(BLOCK_HEADER) + 30,
        memory_inject_min_similarity=0.0,
    )

    await _handle(
        db, fake_clock, tight, gateway, user, event,
        text="我喜欢喝什么", embedder=fake_embedder,
    )

    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    system_prompt = str(provider.calls[0][0]["content"])
    assert "起床时间：07:00" in system_prompt
    assert "喜欢美式" not in system_prompt

    rows = await _audits(db)
    payload = rows[0].payload
    assert payload["retrieved_count"] == 2
    assert payload["result_count"] == 1
    assert len(payload["memory_ids"]) == 1
    assert payload["block_chars"] > 0


async def test_audit_survives_llm_failure(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed_user_and_event(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)

    def failing(messages: list[dict]) -> LLMResult:
        raise RuntimeError("llm down")

    gateway = make_gateway(failing)

    with pytest.raises(RuntimeError):
        await _handle(
            db, fake_clock, _enabled(settings), gateway, user, event,
            text="我今天几点起床来着？", embedder=fake_embedder,
        )

    rows = await _audits(db)
    assert len(rows) == 1
    assert rows[0].payload["result_count"] == 1
