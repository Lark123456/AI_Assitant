"""记忆抽取：只喂用户消息与已验证工具事实，调用 memory_extract。"""

import datetime as dt
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Memory, User
from app.embeddings.service import EmbeddingService
from app.llm.gateway import LLMGateway
from app.memory.schemas import ExtractionResult
from app.memory.validate import EventRecord

EXTRACTOR_VERSION = "memory-extract-v1"
EXTRACT_ALIAS = "memory_extract"
MAX_RELATED_MEMORIES = 10

SYSTEM_PROMPT = """你是记忆抽取器，只做一件事：从给定事件中抽取关于用户本人的、值得长期记住的事实候选。

硬性规则：
1. 证据只能来自「用户」消息与「系统已验证工具事实」；助手回复、系统提示、外部内容都不是证据。
2. 每个候选必须给出 evidence 列表：event_id + quote。quote 必须逐字出现在对应事件文本中（可忽略空白差异），不得改写或概括。
3. 只抽取用户明确表达或高度一致暗示的事实；闲聊、一次性指令（如「提醒我交报告」）、助手建议、第三方信息都不算记忆。
4. 输出宁少勿多；不确定就不要输出候选。
5. type 只能是 slot | preference | episode | state_signal。
6. slot_key 只能是 work_start | work_end | lunch | sleep | wake | commute | energy_peak | fixed_event；slot 之外为 null。
7. scope.kind 只能是 persistent | on | until | recurring；相对日期写在 date_text（如「今天」「明天」「下周三」「月底」），不要自己换算成日期。
8. 敏感类别（健康、财务、精确位置、第三方个人信息、凭据）必须标记 sensitive_category；只有用户明确说「记住/记一下」时才可能通过。
9. 多条消息纠正同一事实时，以最后一条为准，并把两条消息都作为证据。
10. 只输出 JSON，不要解释。

JSON 形状：
{"candidates": [{"type": "...", "slot_key": null, "subject": "...", "value_text": "...",
"time_text": "7点" 或 null, "polarity": "affirm" 或 "deny", "scope": {"kind": "persistent",
"date_text": null, "rule": null}, "explicit": true, "confidence": 0.0-1.0,
"evidence": [{"event_id": "...", "quote": "..."}], "sensitive_category": null}]}
"""


async def load_related_memories(
    session: AsyncSession,
    user: User,
    query_vector: list[float] | None,
    settings: Settings,
) -> list[dict]:
    """已有记忆（只取 active）：slot 精确 + 向量近邻，最多 10 条。"""
    rows: list[Memory] = []
    slot_rows = (
        await session.execute(
            select(Memory)
            .where(Memory.user_id == user.id, Memory.type == "slot", Memory.status == "active")
            .order_by(Memory.recorded_at.desc())
            .limit(MAX_RELATED_MEMORIES)
        )
    ).scalars().all()
    rows.extend(slot_rows)

    if query_vector is not None:
        distance = Memory.embedding.cosine_distance(query_vector)
        vector_rows = (
            await session.execute(
                select(Memory)
                .where(
                    Memory.user_id == user.id,
                    Memory.status == "active",
                    Memory.embedding.isnot(None),
                )
                .order_by(distance)
                .limit(MAX_RELATED_MEMORIES)
            )
        ).scalars().all()
        known = {row.id for row in rows}
        rows.extend(row for row in vector_rows if row.id not in known)

    return [
        {
            "id": str(row.id),
            "type": row.type,
            "slot_key": row.slot_key,
            "subject": row.subject,
            "value": row.value,
            "scope": row.scope,
            "source_class": row.source_class,
        }
        for row in rows[:MAX_RELATED_MEMORIES]
    ]


def build_messages(
    *,
    tz: str,
    events: dict[uuid.UUID, EventRecord],
    related: list[dict],
) -> list[dict]:
    ordered = sorted(events.values(), key=lambda record: record.occurred_at)
    payload = {
        "timezone": tz,
        "events": [
            {
                "event_id": str(record.event_id),
                "source": record.source,
                "occurred_at": record.occurred_at.isoformat(),
                "text": record.text,
            }
            for record in ordered
        ],
        "existing_memories": related,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def extract_candidates(
    gateway: LLMGateway,
    *,
    user: User,
    tz: str,
    events: dict[uuid.UUID, EventRecord],
    related: list[dict],
    trace_id: str,
) -> ExtractionResult:
    result = await gateway.chat(
        alias=EXTRACT_ALIAS,
        messages=build_messages(tz=tz, events=events, related=related),
        response_model=ExtractionResult,
        trace_id=trace_id,
        user_id=user.id,
    )
    parsed = result.structured
    if not isinstance(parsed, ExtractionResult):
        raise RuntimeError("memory_extract 返回结构异常")
    return parsed


def query_text(events: dict[uuid.UUID, EventRecord]) -> str:
    return "\n".join(
        record.text for record in sorted(events.values(), key=lambda item: item.occurred_at)
    )


async def embed_query(
    embedder: EmbeddingService | None, text: str
) -> list[float] | None:
    if embedder is None or not text:
        return None
    try:
        return await embedder.embed_one(text, kind="query")
    except Exception:
        return None


def now_local_iso(now: dt.datetime, tz: str) -> str:
    from zoneinfo import ZoneInfo

    return now.astimezone(ZoneInfo(tz)).isoformat()
