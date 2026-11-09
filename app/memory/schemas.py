"""记忆候选与裁决的 Pydantic 模型（LLM response_model 与内部校验共用）。"""

import uuid
from typing import Literal

from pydantic import BaseModel, Field

SLOT_KEYS: frozenset[str] = frozenset(
    {
        "work_start",
        "work_end",
        "lunch",
        "sleep",
        "wake",
        "commute",
        "energy_peak",
        "fixed_event",
    }
)
SENSITIVE_CATEGORIES: frozenset[str] = frozenset(
    {"health", "finance", "exact_location", "third_party", "credentials"}
)
TIME_SLOT_KEYS: frozenset[str] = frozenset(SLOT_KEYS - {"fixed_event"})
# 抽取器只输出这三类；state_signal 仅保留数据库枚举，供历史数据使用
ALLOWED_TYPES: frozenset[str] = frozenset({"slot", "preference", "episode"})
SYNC_TYPES: frozenset[str] = frozenset({"slot", "preference", "episode"})
TOOL_EVIDENCE_TOOLS: frozenset[str] = frozenset(
    {"schedule_block", "update_block_status", "reschedule_block", "set_notif_prefs"}
)


class EvidenceItem(BaseModel):
    event_id: uuid.UUID
    quote: str = Field(min_length=1, max_length=300)


class ScopeSpec(BaseModel):
    kind: Literal["persistent", "on", "until", "recurring"] = "persistent"
    date_text: str | None = Field(default=None, max_length=50)
    rule: str | None = Field(default=None, max_length=200)


class MemoryCandidate(BaseModel):
    type: Literal["slot", "preference", "episode"]
    slot_key: str | None = None
    subject: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=500)
    time_text: str | None = Field(default=None, max_length=50)
    polarity: Literal["affirm", "deny"] = "affirm"
    scope: ScopeSpec = Field(default_factory=ScopeSpec)
    explicit: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(min_length=1, max_length=10)
    sensitive_category: str | None = None


class ExtractionResult(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list, max_length=20)


class ResolveDecision(BaseModel):
    action: Literal["ADD", "SUPERSEDE", "NOOP", "MERGE", "ASK"]
    target_id: uuid.UUID | None = None
    reason: str = Field(default="", max_length=300)
