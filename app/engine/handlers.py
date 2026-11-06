"""触发处理器：按 kind 产出 0 到 N 个候选；不发送、不仲裁。

候选内容在发送时才渲染（brief 主体由 brief 模块确定性渲染），此处只给出元数据。
"""

import datetime as dt
from dataclasses import dataclass

from app.db.models import TriggerInstance
from app.engine.reasons import reason_for_trigger


@dataclass(frozen=True)
class CandidateDraft:
    """待落库的候选草稿。"""

    class_: str
    reason_code: str
    reason_text: str
    value_score: float
    explicit: bool
    dedupe_key: str | None
    expires_at: dt.datetime | None
    precondition: dict | None


@dataclass(frozen=True)
class TriggerResult:
    candidates: tuple[CandidateDraft, ...] = ()
    signal: dict | None = None


def build_candidates(trigger: TriggerInstance) -> TriggerResult:
    """把到期的 trigger 转成候选；overdue_check 只产出信号。"""
    kind = trigger.kind
    if kind == "reminder":
        return TriggerResult(
            candidates=(
                CandidateDraft(
                    class_="commitment",
                    reason_code="commitment.reminder",
                    reason_text=trigger.payload.get("note", "提醒"),
                    value_score=1.0,
                    explicit=True,
                    dedupe_key=trigger.key,
                    expires_at=trigger.expires_at,
                    precondition=trigger.precondition,
                ),
            )
        )
    if kind == "block_start":
        title = trigger.payload.get("title") or "计划块"
        return TriggerResult(
            candidates=(
                CandidateDraft(
                    class_="commitment",
                    reason_code="commitment.block_start",
                    reason_text=f"即将开始：{title}",
                    value_score=0.9,
                    explicit=False,
                    dedupe_key=trigger.key,
                    expires_at=trigger.expires_at,
                    precondition=trigger.precondition,
                ),
            )
        )
    if kind == "overdue_check":
        return TriggerResult(
            signal={
                "block_id": trigger.payload.get("block_id"),
                "work_item_id": trigger.payload.get("work_item_id"),
                "title": trigger.payload.get("title"),
                "kind": "overdue_check",
            }
        )
    if kind in ("brief_morning", "brief_evening"):
        label = "晨间简报" if kind == "brief_morning" else "晚间复盘"
        return TriggerResult(
            candidates=(
                CandidateDraft(
                    class_="brief",
                    reason_code=reason_for_trigger(kind),
                    reason_text=label,
                    value_score=0.8,
                    explicit=False,
                    dedupe_key=trigger.key,
                    expires_at=trigger.expires_at,
                    precondition=trigger.precondition,
                ),
            )
        )
    raise ValueError(f"unregistered trigger kind: {kind}")
