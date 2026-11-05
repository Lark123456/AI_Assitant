"""llm_call：每次模型调用都落库。"""

import datetime as dt
import uuid

from sqlalchemy import DateTime, Integer, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_uuid7
from app.db.base import Base


class LLMCall(Base):
    __tablename__ = "llm_call"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid7)
    trace_id: Mapped[str] = mapped_column(Text, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    alias: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSONB)
    request: Mapped[dict | None] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ttft_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
