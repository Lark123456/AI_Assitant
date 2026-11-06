"""inbound_processing：入站事件的处理状态（event_log 只追加，状态放独立表）。"""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InboundProcessing(Base):
    __tablename__ = "inbound_processing"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'done', 'failed')", name="status_values"
        ),
        Index("ix_inbound_processing_status", "status"),
    )

    # 主键即 event_log 外键：一条入站事件至多一行
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    status: Mapped[str] = mapped_column(Text, default="processing")
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
