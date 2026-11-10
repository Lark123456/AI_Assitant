"""Friday 记忆注入：注入内容、审计事件与嵌入失败降级。"""

import datetime as dt

from sqlalchemy import select

from app.agents.friday.agent import FridayAgent
from app.db.models import EventLog, Memory, User
from app.llm.schemas import LLMResult

MODEL = "fake-hash-1024"


async def _seed(db, clock, text: str = "我今天几点起床来着？") -> tuple[User, EventLog]:
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


def _reply(text: str):
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text)

    return responder


async def test_friday_injects_slot_and_writes_audit(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    gateway = make_gateway(_reply("你平时 7:00 起床。"))

    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        reply = await FridayAgent(gateway).handle(
            session=session,
            clock=fake_clock,
            settings=settings,
            user=fresh_user,
            trace_id="trace-friday",
            channel="console",
            source_event_id=event.id,
            text="我今天几点起床来着？",
            embedder=fake_embedder,
        )
        await session.commit()

    assert reply == "你平时 7:00 起床。"
    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    system_prompt = str(provider.calls[0][0]["content"])
    assert "【已知长期信息】" in system_prompt
    assert "长期作息：" in system_prompt
    assert "起床时间：07:00" in system_prompt
    assert "用户明说" in system_prompt

    async with db() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_context")
            )
        ).scalars().all()
    assert len(rows) == 1
    payload = rows[0].payload
    assert payload["degraded"] is False
    assert payload["memory_ids"]
    assert payload["block_chars"] > 0


async def test_friday_without_memories_writes_no_audit(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed(db, fake_clock, "今天天气不错")
    gateway = make_gateway(_reply("是挺好的。"))

    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        await FridayAgent(gateway).handle(
            session=session,
            clock=fake_clock,
            settings=settings,
            user=fresh_user,
            trace_id="trace-friday",
            channel="console",
            source_event_id=event.id,
            text="今天天气不错",
            embedder=fake_embedder,
        )
        await session.commit()

    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    assert "【已知长期信息】" not in str(provider.calls[0][0]["content"])
    async with db() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_context")
            )
        ).scalars().all()
    assert rows == []


async def test_friday_degrades_when_embedder_missing(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    gateway = make_gateway(_reply("你平时 7:00 起床。"))

    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        reply = await FridayAgent(gateway).handle(
            session=session,
            clock=fake_clock,
            settings=settings,
            user=fresh_user,
            trace_id="trace-friday",
            channel="console",
            source_event_id=event.id,
            text="我今天几点起床来着？",
            embedder=None,
        )
        await session.commit()

    assert reply == "你平时 7:00 起床。"
    async with db() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_context")
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload["degraded"] is True
    assert rows[0].payload["degraded_reason"] == "embedder_unavailable"


async def test_friday_does_not_inject_when_disabled(
    db, fake_clock, settings, make_gateway, fake_embedder
) -> None:
    user, event = await _seed(db, fake_clock)
    await _add_slot(db, fake_clock, fake_embedder, user)
    disabled = settings.model_copy(update={"memory_inject_enabled": False})
    gateway = make_gateway(_reply("你平时 7:00 起床。"))

    async with db() as session:
        fresh_user = await session.get(User, user.id)
        assert fresh_user is not None
        await FridayAgent(gateway).handle(
            session=session,
            clock=fake_clock,
            settings=disabled,
            user=fresh_user,
            trace_id="trace-friday",
            channel="console",
            source_event_id=event.id,
            text="我今天几点起床来着？",
            embedder=fake_embedder,
        )
        await session.commit()

    provider = gateway._providers["fake"]  # type: ignore[attr-defined]
    assert "【已知长期信息】" not in str(provider.calls[0][0]["content"])
    async with db() as session:
        rows = (
            await session.execute(
                select(EventLog).where(EventLog.type == "memory_context")
            )
        ).scalars().all()
    assert rows == []
