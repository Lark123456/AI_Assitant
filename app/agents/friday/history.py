"""从 event_log 重建 Friday 的短期对话窗口。

规则：最近 24 小时内、最多 12 条消息事件，取较少者；总长度约 4000 字符，
超出时从最旧的开始裁剪。简报（delivery 事件）以 assistant 消息进入窗口，
并附上方括号系统注记，使「第一个做完了」这类回复能解析到 block_id。
"""

import datetime as dt
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import EventLog

MAX_EVENTS = 12
MAX_CHARS = 4000
WINDOW_HOURS = 24


def _delivery_content(payload: dict) -> str:
    text = str(payload.get("text", "")).strip()
    blocks = payload.get("block_ids") or []
    items = payload.get("work_item_ids") or []
    note_parts = []
    if blocks:
        note_parts.append(f"block_ids={','.join(str(b) for b in blocks)}")
    if items:
        note_parts.append(f"work_item_ids={','.join(str(i) for i in items)}")
    if note_parts:
        return f"{text}\n[系统附注: {'; '.join(note_parts)}]"
    return text


async def build_history(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    exclude_event_id: uuid.UUID | None,
    clock: Clock,
) -> list[dict]:
    """返回可直接拼进 messages 的历史（升序，不含当前消息）。"""
    now = clock.now()
    conditions = [
        EventLog.user_id == user_id,
        EventLog.occurred_at >= now - dt.timedelta(hours=WINDOW_HOURS),
        or_(
            and_(EventLog.direction == "inbound", EventLog.type == "message"),
            and_(EventLog.direction == "outbound", EventLog.type == "message"),
            and_(EventLog.direction == "outbound", EventLog.type == "delivery"),
        ),
    ]
    if exclude_event_id is not None:
        conditions.append(EventLog.id != exclude_event_id)
    rows = (
        (
            await session.execute(
                select(EventLog)
                .where(*conditions)
                .order_by(EventLog.occurred_at.desc())
                .limit(MAX_EVENTS)
            )
        )
        .scalars()
        .all()
    )

    ordered: list[dict] = []
    for row in reversed(rows):
        if row.direction == "inbound":
            text = str(row.payload.get("text", "")).strip()
            if not text:
                continue
            ordered.append({"role": "user", "content": text})
        elif row.type == "delivery":
            content = _delivery_content(row.payload)
            if not content.strip():
                continue
            ordered.append({"role": "assistant", "content": content})
        else:
            text = str(row.payload.get("text", "")).strip()
            if not text:
                continue
            ordered.append({"role": "assistant", "content": text})

    # 从最旧开始裁剪，保证总长度不超过上限
    kept: list[dict] = []
    total = 0
    for message in reversed(ordered):
        length = len(str(message["content"]))
        if total + length > MAX_CHARS:
            break
        kept.append(message)
        total += length
    return list(reversed(kept))
