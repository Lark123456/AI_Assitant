"""记忆检索：只取 active、模型隔离、有效期过滤、降级与数量上限。"""

import datetime as dt
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.models import Memory, User
from app.embeddings.service import EmbeddingService
from app.memory.retrieve import retrieve_memory_context

MODEL = "fake-hash-1024"


async def _user(db: async_sessionmaker[AsyncSession]) -> User:
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.commit()
        return user


def _relaxed(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"memory_inject_min_similarity": 0.0, "memory_inject_topk": 8}
    )


async def _add_memory(
    db: async_sessionmaker[AsyncSession],
    embedder: EmbeddingService,
    user: User,
    *,
    type_: str = "preference",
    subject: str = "咖啡",
    text: str = "喜欢美式",
    embedding_text: str | None = "preference 咖啡 喜欢美式",
    embedding_model: str | None = None,
    status: str = "active",
    scope: dict | None = None,
    valid_to: dt.datetime | None = None,
    slot_key: str | None = None,
    source_class: str = "stated",
    now: dt.datetime,
) -> uuid.UUID:
    embedding = None
    model = embedding_model
    if embedding_text is not None:
        embedding = await embedder.embed_one(embedding_text)
        model = model or MODEL
    async with db() as session:
        memory = Memory(
            user_id=user.id,
            type=type_,
            slot_key=slot_key,
            subject=subject,
            value={"text": text},
            scope=scope or {"kind": "persistent"},
            source_class=source_class,
            weight=0.8,
            confidence=0.9,
            status=status,
            recorded_at=now,
            support_days=1,
            contradict_count=0,
            last_reinforced_at=now,
            embedding=embedding,
            embedding_model=model,
            valid_to=valid_to,
        )
        session.add(memory)
        await session.commit()
        return memory.id


async def test_only_active_and_unexpired_memories_are_injected(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    active_id = await _add_memory(db, fake_embedder, user, now=now)
    await _add_memory(db, fake_embedder, user, now=now, status="pending", text="喜欢摩卡")
    await _add_memory(db, fake_embedder, user, now=now, status="superseded", text="喜欢拿铁")
    expired_id = await _add_memory(
        db, fake_embedder, user, type_="episode", subject="加班", text="加班到九点",
        scope={"kind": "on", "date": "2025-12-31"}, valid_to=now - dt.timedelta(hours=1), now=now,
    )
    future_id = await _add_memory(
        db, fake_embedder, user, type_="episode", subject="加班", text="加班到十点",
        scope={"kind": "on", "date": "2026-01-01"}, valid_to=now + dt.timedelta(days=1), now=now,
    )

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="咖啡", embedder=fake_embedder,
            settings=_relaxed(settings), clock=fake_clock,
        )
    ids = set(context.memory_ids())
    assert str(active_id) in ids
    assert str(future_id) in ids
    assert str(expired_id) not in ids
    assert len(context.preferences) == 1


async def test_vectors_from_other_embedding_models_are_not_compared(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    current_id = await _add_memory(db, fake_embedder, user, now=now)
    stale_id = await _add_memory(
        db, fake_embedder, user, now=now, text="喜欢摩卡", embedding_model="other-model"
    )

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="咖啡", embedder=fake_embedder,
            settings=_relaxed(settings), clock=fake_clock,
        )
    ids = set(context.memory_ids())
    assert str(current_id) in ids
    assert str(stale_id) not in ids


async def test_slots_are_included_even_without_embedding(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    slot_id = await _add_memory(
        db, fake_embedder, user, type_="slot", slot_key="wake", subject="起床时间",
        text="7点", embedding_text=None, now=now,
    )

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="明天几点叫我", embedder=fake_embedder,
            settings=_relaxed(settings), clock=fake_clock,
        )
    assert [str(item.id) for item in context.slots] == [str(slot_id)]


async def test_embedding_failure_degrades_to_slots(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    await _add_memory(
        db, fake_embedder, user, type_="slot", slot_key="wake", subject="起床时间",
        text="7点", embedding_text=None, now=now,
    )
    await _add_memory(db, fake_embedder, user, now=now)

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="咖啡", embedder=None,
            settings=_relaxed(settings), clock=fake_clock,
        )
    assert context.degraded is True
    assert context.degraded_reason == "embedder_unavailable"
    assert len(context.slots) == 1
    assert context.preferences == ()


async def test_min_similarity_filters_unrelated_memories(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    await _add_memory(db, fake_embedder, user, now=now)
    strict = settings.model_copy(
        update={"memory_inject_min_similarity": 0.999, "memory_inject_topk": 8}
    )

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="完全不相关的天气问题", embedder=fake_embedder,
            settings=strict, clock=fake_clock,
        )
    assert context.preferences == ()


async def test_episodes_are_capped_at_three(
    db, fake_clock: FakeClock, settings: Settings, fake_embedder: EmbeddingService
) -> None:
    user = await _user(db)
    now = fake_clock.now()
    for index in range(5):
        await _add_memory(
            db, fake_embedder, user, type_="episode", subject=f"加班{index}",
            text=f"加班到九点{index}", scope={"kind": "on", "date": "2026-01-01"},
            valid_to=now + dt.timedelta(days=10), now=now,
        )

    async with db() as session:
        context = await retrieve_memory_context(
            session, user=user, query="今天加班吗", embedder=fake_embedder,
            settings=_relaxed(settings), clock=fake_clock,
        )
    assert len(context.episodes) == 3
