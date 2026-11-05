"""event_log 追加助手与幂等去重。

event_log 是 append-only 叙事日志：带幂等键的写入用 ON CONFLICT 去重，
并发竞争下也不会产生第二条记录。
"""

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.ids import new_uuid7
from app.db.models import EventLog


async def find_event_by_idempotency_key(session: AsyncSession, key: str) -> EventLog | None:
    """按幂等键查找既有事件。"""
    return (
        await session.execute(select(EventLog).where(EventLog.idempotency_key == key))
    ).scalar_one_or_none()


async def append_event(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: str,
    direction: str,
    type: str,
    payload: dict,
    trace_id: str,
    clock: Clock,
    idempotency_key: str | None = None,
    occurred_at: dt.datetime | None = None,
) -> tuple[EventLog, bool]:
    """追加事件。返回 (事件, 是否新写入)；幂等键命中时返回既有事件与 False。"""
    values: dict = {
        "id": new_uuid7(),
        "user_id": user_id,
        "channel": channel,
        "direction": direction,
        "type": type,
        "payload": payload,
        "idempotency_key": idempotency_key,
        "trace_id": trace_id,
        "occurred_at": occurred_at or clock.now(),
        "recorded_at": clock.now(),
    }
    if idempotency_key is not None:
        stmt = (
            pg_insert(EventLog)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(EventLog)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            return row, True
        existing = await find_event_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise RuntimeError("event_log insert conflicted but no existing row found")
        return existing, False
    event = EventLog(**values)
    session.add(event)
    await session.flush()
    return event, True
