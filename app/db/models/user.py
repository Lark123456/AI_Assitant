"""user 与 channel_identity。"""

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    display_name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text)  # IANA，如 Asia/Shanghai
    day_start: Mapped[dt.time] = mapped_column(Time, default=dt.time(4, 0))
    rev: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelIdentity(Base):
    __tablename__ = "channel_identity"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_channel_external"),
        CheckConstraint("channel IN ('feishu', 'console')", name="channel_values"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), index=True)
    channel: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    rev: Mapped[int] = mapped_column(BigInteger, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
