"""trigger_instance：worker 用 FOR UPDATE SKIP LOCKED 领取 pending 且到期的记录。"""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class TriggerInstance(Base):
    __tablename__ = "trigger_instance"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('reminder', 'brief_morning', 'brief_evening', 'block_start', 'overdue_check')",
            name="kind_values",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'fired', 'dropped', 'missed', 'failed')",
            name="status_values",
        ),
        Index("ix_trigger_instance_status_fire_at", "status", "fire_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, unique=True)
    fire_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    tz: Mapped[str] = mapped_column(Text)
    precondition: Mapped[dict | None] = mapped_column(JSONB)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="pending")
    plan_rev: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    # 阶段 1 修订：重试与租约
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # 阶段 2：仲裁延后计数（defer 不消耗 attempts，最多 3 次）
    defer_count: Mapped[int] = mapped_column(Integer, default=0)
