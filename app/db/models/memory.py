"""memory 相关表：阶段 1 仅建表，阶段 3 实现逻辑。"""

import datetime as dt
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class Memory(Base):
    __tablename__ = "memory"
    __table_args__ = (
        CheckConstraint("type IN ('slot', 'preference', 'episode', 'state_signal')", name="type_values"),
        CheckConstraint(
            "source_class IN ('confirmed', 'stated', 'inferred')", name="source_class_values"
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'retracted', 'pending')", name="status_values"
        ),
        Index("ix_memory_user_status", "user_id", "status"),
        Index("ix_memory_user_type_slot", "user_id", "type", "slot_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    mission_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_item.id"))
    type: Mapped[str] = mapped_column(Text)
    slot_key: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    value: Mapped[dict] = mapped_column(JSONB)
    polarity: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[dict | None] = mapped_column(JSONB)
    source_class: Mapped[str] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(default=0.0)
    confidence: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(Text, default="pending")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memory.id"))
    valid_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    support_days: Mapped[int | None] = mapped_column(Integer)
    contradict_count: Mapped[int | None] = mapped_column(Integer)
    last_reinforced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    suppress_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    extractor_version: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list | None] = mapped_column(Vector(1024))
    embedding_model: Mapped[str | None] = mapped_column(Text)


class MemorySource(Base):
    __tablename__ = "memory_source"

    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memory.id"), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event_log.id"), primary_key=True)


class MemoryDecisionLog(Base):
    __tablename__ = "memory_decision_log"
    __table_args__ = (
        CheckConstraint("action IN ('ADD', 'SUPERSEDE', 'NOOP', 'MERGE', 'ASK')", name="action_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_extraction_run.id"), index=True
    )
    memory_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memory.id"), index=True)
    candidate: Mapped[dict | None] = mapped_column(JSONB)
    neighbors: Mapped[dict | None] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    alias: Mapped[str | None] = mapped_column(Text)
    llm_call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_call.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class MemoryExtractionRun(Base):
    """一次抽取批次；attempts 与退避放在 stats，不额外建字段。"""

    __tablename__ = "memory_extraction_run"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'done', 'failed')", name="status_values"),
        UniqueConstraint(
            "user_id", "to_event_id", "extractor_version", name="uq_memory_extraction_run_target"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    to_event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("event_log.id"))
    extractor_version: Mapped[str] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(Text, default="pending")
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
