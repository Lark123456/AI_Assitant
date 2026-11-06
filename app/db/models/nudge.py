"""nudge 相关表与 delivery、notif_prefs。阶段 1 建表；gate 仅写直通 decision 与 delivery。"""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    Time,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class NudgeCandidate(Base):
    __tablename__ = "nudge_candidate"
    __table_args__ = (
        CheckConstraint("class IN ('commitment', 'brief', 'suggestion')", name="class_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    class_: Mapped[str] = mapped_column("class", Text)
    reason_code: Mapped[str] = mapped_column(Text)
    reason_text: Mapped[str] = mapped_column(Text)
    value_score: Mapped[float] = mapped_column()
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str | None] = mapped_column(Text, index=True)
    precondition: Mapped[dict | None] = mapped_column(JSONB)
    source_trigger_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("trigger_instance.id"))
    # 阶段 2：用户明确设置的承诺类；holdout/propensity 本阶段只留字段
    explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    holdout_group: Mapped[str | None] = mapped_column(Text)
    propensity: Mapped[float | None] = mapped_column(Float)
    # 建议被并入简报后指向简报候选
    merged_into_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nudge_candidate.id")
    )


class NudgeDecision(Base):
    __tablename__ = "nudge_decision"
    __table_args__ = (
        CheckConstraint("decision IN ('send', 'defer', 'merge', 'drop')", name="decision_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nudge_candidate.id"), index=True)
    decision: Mapped[str] = mapped_column(Text)
    gate_reasons: Mapped[dict | None] = mapped_column(JSONB)
    policy_version: Mapped[str] = mapped_column(Text, default="passthrough-v0")
    budget_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    decided_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Delivery(Base):
    __tablename__ = "delivery"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    decision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nudge_decision.id"), index=True)
    channel: Mapped[str] = mapped_column(Text)
    provider_msg_id: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    acted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class NotifPrefs(Base):
    __tablename__ = "notif_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), primary_key=True)
    daily_budget: Mapped[int] = mapped_column(Integer, default=4)
    quiet_hours: Mapped[dict | None] = mapped_column(JSONB)
    class_enabled: Mapped[dict | None] = mapped_column(JSONB)
    snooze_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # 阶段 2：简报时间（用户本地时间）与开关
    morning_brief_time: Mapped[dt.time] = mapped_column(Time, default=dt.time(8, 30))
    evening_brief_time: Mapped[dt.time] = mapped_column(Time, default=dt.time(21, 0))
    briefs_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
