"""长期记忆检索与提示词渲染：只读、确定、按嵌入模型隔离。

约束：
- 只取 active；pending / superseded / retracted 一律不参与。
- 向量检索只比较 embedding_model 与当前嵌入模型相同的记忆；模型升级后旧向量
  不会被错误地拿来比较（结构化槽位不依赖向量，仍然可用）。
- 预算裁剪按 槽位 → 偏好 → episode 的优先级整条取舍，绝不截断半句话。
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.db.models import Memory, User
from app.embeddings.service import EmbeddingService
from app.memory.weights import effective_weight

SLOT_ORDER: tuple[str, ...] = (
    "wake",
    "sleep",
    "work_start",
    "work_end",
    "lunch",
    "commute",
    "energy_peak",
    "fixed_event",
)
MAX_EPISODES = 3
SOURCE_LABELS: dict[str, str] = {
    "stated": "用户明说",
    "confirmed": "已确认",
    "inferred": "推断，仅供参考",
}
BLOCK_HEADER = "【已知长期信息】（仅作参考，不得编造；推断类不得用于修改日程、提醒时间或主动提醒时机）"
SECTION_TITLES: dict[str, str] = {
    "slot": "长期作息：",
    "preference": "稳定偏好：",
    "episode": "近期事件：",
}


@dataclass(frozen=True)
class MemoryItem:
    """一条可注入的记忆；similarity 仅对向量召回的条目有意义。"""

    id: uuid.UUID
    type: str
    slot_key: str | None
    subject: str
    value: dict
    scope: dict | None
    source_class: str
    weight: float
    effective: float
    similarity: float | None
    valid_to: dt.datetime | None


@dataclass(frozen=True)
class MemoryContext:
    slots: tuple[MemoryItem, ...] = ()
    preferences: tuple[MemoryItem, ...] = ()
    episodes: tuple[MemoryItem, ...] = ()
    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.slots or self.preferences or self.episodes)

    def memory_ids(self) -> list[str]:
        return [
            str(item.id)
            for item in (*self.slots, *self.preferences, *self.episodes)
        ]


def _to_item(
    memory: Memory,
    *,
    now: dt.datetime,
    similarity: float | None,
) -> MemoryItem:
    effective = effective_weight(
        memory.source_class,
        float(memory.weight or 0.0),
        memory.last_reinforced_at or memory.recorded_at,
        now,
    )
    return MemoryItem(
        id=memory.id,
        type=memory.type,
        slot_key=memory.slot_key,
        subject=memory.subject,
        value=dict(memory.value or {}),
        scope=dict(memory.scope) if memory.scope else None,
        source_class=memory.source_class,
        weight=float(memory.weight or 0.0),
        effective=effective,
        similarity=similarity,
        valid_to=memory.valid_to,
    )


def _slot_sort_key(item: MemoryItem) -> tuple[int, str]:
    try:
        index = SLOT_ORDER.index(item.slot_key or "")
    except ValueError:
        index = len(SLOT_ORDER)
    return index, item.subject


def _similarity_sort_key(item: MemoryItem) -> tuple[float, float]:
    return (-(item.similarity or 0.0), -item.effective)


async def _load_slots(session: AsyncSession, user: User, now: dt.datetime) -> list[MemoryItem]:
    rows = (
        await session.execute(
            select(Memory)
            .where(
                Memory.user_id == user.id,
                Memory.type == "slot",
                Memory.status == "active",
            )
            .order_by(Memory.recorded_at.desc())
            .limit(32)
        )
    ).scalars().all()
    items = [_to_item(row, now=now, similarity=None) for row in rows]
    return sorted(items, key=_slot_sort_key)


async def _load_open_facts(
    session: AsyncSession,
    user: User,
    query_vector: list[float],
    model_name: str,
    settings: Settings,
    now: dt.datetime,
) -> tuple[list[MemoryItem], list[MemoryItem]]:
    """向量召回偏好与有效期内 episode；只比较同一嵌入模型的向量。"""
    distance = Memory.embedding.cosine_distance(query_vector)
    rows = (
        await session.execute(
            select(Memory, distance.label("distance"))
            .where(
                Memory.user_id == user.id,
                Memory.status == "active",
                Memory.type.in_(("preference", "episode")),
                Memory.embedding.isnot(None),
                Memory.embedding_model == model_name,
                (Memory.type != "episode")
                | (Memory.valid_to.is_(None))
                | (Memory.valid_to > now),
            )
            .order_by(distance)
            .limit(max(settings.memory_inject_topk * 3, 12))
        )
    ).all()

    preferences: list[MemoryItem] = []
    episodes: list[MemoryItem] = []
    for memory, distance_value in rows:
        similarity = 1.0 - float(distance_value)
        if similarity < settings.memory_inject_min_similarity:
            continue
        item = _to_item(memory, now=now, similarity=similarity)
        (episodes if item.type == "episode" else preferences).append(item)
    preferences.sort(key=_similarity_sort_key)
    episodes.sort(key=_similarity_sort_key)
    return preferences[: settings.memory_inject_topk], episodes[:MAX_EPISODES]


async def retrieve_memory_context(
    session: AsyncSession,
    *,
    user: User,
    query: str,
    embedder: EmbeddingService | None,
    settings: Settings,
    clock: Clock,
) -> MemoryContext:
    """检索本轮要注入的记忆；嵌入失败时降级为只给结构化槽位。"""
    now = clock.now()
    slots = await _load_slots(session, user, now)
    if embedder is None:
        return MemoryContext(
            slots=tuple(slots),
            degraded=True,
            degraded_reason="embedder_unavailable",
        )
    if not query.strip():
        return MemoryContext(slots=tuple(slots))

    try:
        query_vector = await embedder.embed_one(query, kind="query")
    except Exception as exc:
        return MemoryContext(
            slots=tuple(slots),
            degraded=True,
            degraded_reason=f"embedding_failed: {type(exc).__name__}",
        )

    preferences, episodes = await _load_open_facts(
        session, user, query_vector, embedder.model_name, settings, now
    )
    return MemoryContext(
        slots=tuple(slots),
        preferences=tuple(preferences),
        episodes=tuple(episodes),
    )


def _render_item(item: MemoryItem) -> str:
    """整条渲染；空文本返回空串，由调用方跳过。"""
    text = str(item.value.get("text", "")).strip()
    time_text = str(item.value.get("time", "") or "").strip()
    if item.type == "slot":
        # 槽位只关心锚点时间，避免「7点（07:00）」重复
        body = time_text or text
    elif time_text and text and text != time_text:
        body = f"{text}（{time_text}）"
    else:
        body = time_text or text
    if not body:
        return ""
    if item.type == "episode":
        date_text = str((item.scope or {}).get("date", ""))
        prefix = f"{date_text[5:]} " if len(date_text) >= 10 else ""
        return f"- {prefix}{body}（{SOURCE_LABELS.get(item.source_class, item.source_class)}）"
    subject = item.subject.strip()
    if not subject:
        return ""
    return f"- {subject}：{body}（{SOURCE_LABELS.get(item.source_class, item.source_class)}）"


def render_memory_block(
    context: MemoryContext,
    *,
    max_chars: int,
    item_max_chars: int,
) -> str:
    """按 槽位 → 偏好 → episode 的顺序整条装入预算；超预算的条目整条跳过。"""
    if context.is_empty:
        return ""
    sections = (
        ("slot", context.slots),
        ("preference", context.preferences),
        ("episode", context.episodes),
    )
    lines: list[str] = [BLOCK_HEADER]
    total = len(BLOCK_HEADER)
    for kind, items in sections:
        title = SECTION_TITLES[kind]
        section_lines: list[str] = []
        for item in items:
            line = _render_item(item)
            if not line or len(line) > item_max_chars:
                continue
            extra = len(line) + 1
            if not section_lines:
                extra += len(title) + 1
            if total + extra > max_chars:
                continue
            section_lines.append(line)
            total += extra
        if section_lines:
            lines.append(title)
            lines.extend(section_lines)
    return "\n".join(lines) if len(lines) > 1 else ""
