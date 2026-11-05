"""event_log：append-only，数据库层面禁止 UPDATE 与 DELETE（迁移中创建触发器）。"""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        CheckConstraint("direction IN ('inbound', 'outbound', 'system', 'tool')", name="direction_values"),
        Index("ix_event_log_user_occurred", "user_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    channel: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)  # message | callback | tool_call | tool_result | trigger | delivery | note 等
    payload: Mapped[dict] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    trace_id: Mapped[str] = mapped_column(Text, index=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
