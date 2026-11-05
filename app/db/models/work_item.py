"""work_item 与 planned_block。阶段 1 只使用 type=item、status=active/done。"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class WorkItem(Base):
    __tablename__ = "work_item"
    __table_args__ = (
        CheckConstraint("type IN ('seed', 'item', 'project', 'mission')", name="type_values"),
        CheckConstraint(
            "status IN ('seed', 'clarifying', 'active', 'dormant', 'done', 'dropped')", name="status_values"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    type: Mapped[str] = mapped_column(Text, default="item")
    status: Mapped[str] = mapped_column(Text, default="active")
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_item.id"))
    mission_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_item.id"))
    clarity_score: Mapped[float | None] = mapped_column()
    size_estimate_min: Mapped[int | None] = mapped_column(Integer)
    revisit_trigger: Mapped[dict | None] = mapped_column(JSONB)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("event_log.id"))
    rev: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlannedBlock(Base):
    __tablename__ = "planned_block"
    __table_args__ = (
        CheckConstraint("status IN ('planned', 'done', 'skipped', 'moved')", name="status_values"),
        CheckConstraint("assigned_by IN ('user', 'friday', 'jarvis')", name="assigned_by_values"),
        CheckConstraint("difficulty IS NULL OR difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        CheckConstraint("energy IS NULL OR energy IN ('low', 'mid', 'high')", name="energy_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    work_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_item.id"))
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="planned")
    assigned_by: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int | None] = mapped_column(Integer)
    energy: Mapped[str | None] = mapped_column(Text)
    compressible: Mapped[bool] = mapped_column(default=True)
    plan_rev: Mapped[int | None] = mapped_column(Integer)
    actual_started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    actual_ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rev: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
