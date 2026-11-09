"""记忆裁决：规则优先，规则无法判定时调用 memory_resolve。"""

import datetime as dt
import json
import uuid
from dataclasses import dataclass

from app.llm.gateway import LLMGateway
from app.memory.schemas import ResolveDecision
from app.memory.validate import ValidatedCandidate

RESOLVE_ALIAS = "memory_resolve"


@dataclass(frozen=True)
class Neighbor:
    id: uuid.UUID
    type: str
    slot_key: str | None
    subject: str
    value: dict
    scope: dict | None
    source_class: str
    status: str
    weight: float
    suppress_until: dt.datetime | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class RuleDecision:
    action: str  # ADD | SUPERSEDE | NOOP | MERGE | ASK | NEEDS_LLM
    reason: str
    target_id: uuid.UUID | None = None
    needs_llm: bool = False


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def value_equal(left: dict, right: dict) -> bool:
    return _canonical(left) == _canonical(right)


def scope_equal(left: dict | None, right: dict | None) -> bool:
    return _canonical(left or {}) == _canonical(right or {})


def _same_topic(candidate: ValidatedCandidate, neighbor: Neighbor) -> bool:
    if candidate.type == "slot" and neighbor.type == "slot":
        return candidate.slot_key == neighbor.slot_key
    return candidate.subject.strip().casefold() == neighbor.subject.strip().casefold()


def resolve_rules(
    candidate: ValidatedCandidate,
    neighbors: list[Neighbor],
    *,
    now: dt.datetime,
    threshold: float,
) -> RuleDecision:
    """确定性裁决；无法确定时返回 NEEDS_LLM。"""
    for neighbor in neighbors:
        if (
            neighbor.status == "active"
            and neighbor.suppress_until is not None
            and neighbor.suppress_until > now
            and _same_topic(candidate, neighbor)
        ):
            return RuleDecision("NOOP", "suppressed", neighbor.id)

    if candidate.type == "slot":
        for neighbor in neighbors:
            if (
                neighbor.type != "slot"
                or neighbor.status != "active"
                or neighbor.slot_key != candidate.slot_key
                or not scope_equal(neighbor.scope, candidate.scope)
            ):
                continue
            if value_equal(neighbor.value, candidate.value):
                return RuleDecision("NOOP", "duplicate_slot", neighbor.id)
            if candidate.scope.get("kind") in ("on", "until") and (neighbor.scope or {}).get(
                "kind"
            ) == "persistent":
                continue
            return RuleDecision("ASK", "slot_conflict_pending", neighbor.id)
        return RuleDecision("ADD", "slot_new")

    same_type = [
        neighbor
        for neighbor in neighbors
        if neighbor.type == candidate.type and neighbor.status == "active"
    ]
    for neighbor in same_type:
        if _canonical_subject_value(neighbor) != _canonical_subject_value_dict(candidate):
            continue
        # episode 只在同一日期范围内视为重复；不同日期的同类事件是独立事实
        if candidate.type == "episode" and not scope_equal(neighbor.scope, candidate.scope):
            continue
        return RuleDecision("NOOP", "duplicate_open_fact", neighbor.id)

    similar = [
        neighbor
        for neighbor in same_type
        if (neighbor.similarity or 0.0) >= threshold
    ]

    if candidate.scope.get("kind") in ("on", "until"):
        similar = [
            neighbor
            for neighbor in similar
            if (neighbor.scope or {}).get("kind") != "persistent"
        ]

    if candidate.source_class == "inferred":
        stronger = [
            neighbor for neighbor in similar if neighbor.source_class in ("stated", "confirmed")
        ]
        if stronger:
            strongest = max(stronger, key=lambda neighbor: neighbor.weight)
            return RuleDecision("ASK", "inferred_cannot_override", strongest.id)

    return RuleDecision("NEEDS_LLM", "ambiguous", needs_llm=True)


def _canonical_subject_value(neighbor: Neighbor) -> str:
    return _canonical({"subject": neighbor.subject.strip().casefold(), "value": neighbor.value})


def _canonical_subject_value_dict(candidate: ValidatedCandidate) -> str:
    return _canonical({"subject": candidate.subject.strip().casefold(), "value": candidate.value})


def _neighbor_payload(neighbor: Neighbor) -> dict:
    return {
        "id": str(neighbor.id),
        "type": neighbor.type,
        "slot_key": neighbor.slot_key,
        "subject": neighbor.subject,
        "value": neighbor.value,
        "scope": neighbor.scope,
        "source_class": neighbor.source_class,
        "status": neighbor.status,
        "weight": round(neighbor.weight, 3),
        "similarity": None if neighbor.similarity is None else round(neighbor.similarity, 3),
    }


async def resolve_with_llm(
    gateway: LLMGateway | None,
    candidate: ValidatedCandidate,
    neighbors: list[Neighbor],
    *,
    now: dt.datetime,
    threshold: float,
    trace_id: str,
    user_id: uuid.UUID,
) -> tuple[RuleDecision, bool]:
    """规则优先；NEEDS_LLM 时调用模型。返回 (决策, 是否发生降级)。"""
    rules = resolve_rules(candidate, neighbors, now=now, threshold=threshold)
    if not rules.needs_llm:
        return rules, False
    if gateway is None:
        return RuleDecision("NOOP", "llm_unavailable_conservative"), True

    candidate_payload = {
        "type": candidate.type,
        "slot_key": candidate.slot_key,
        "subject": candidate.subject,
        "value": candidate.value,
        "scope": candidate.scope,
        "source_class": candidate.source_class,
        "explicit": candidate.explicit,
        "confidence": candidate.confidence,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是记忆裁决器。只输出 JSON：action（ADD|SUPERSEDE|NOOP|MERGE|ASK）、"
                "target_id（必须是给定邻居 id 或 null）、reason（不超过 100 字）。"
                "规则：候选与邻居完全重复选 NOOP；候选推断类（inferred）不得覆盖 "
                "stated/confirmed，只能 ASK；on/until 的例外事实不得覆盖 persistent；"
                "拿不准选 NOOP；不得编造邻居。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "candidate": candidate_payload,
                    "neighbors": [_neighbor_payload(neighbor) for neighbor in neighbors],
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        result = await gateway.chat(
            alias=RESOLVE_ALIAS,
            messages=messages,
            response_model=ResolveDecision,
            trace_id=trace_id,
            user_id=user_id,
        )
        parsed = result.structured
        if not isinstance(parsed, ResolveDecision):
            raise RuntimeError("memory_resolve 返回结构异常")
        return _apply_llm_decision(parsed, candidate, neighbors), False
    except Exception:
        return RuleDecision("NOOP", "llm_failed_conservative"), True


def _apply_llm_decision(
    parsed: ResolveDecision,
    candidate: ValidatedCandidate,
    neighbors: list[Neighbor],
) -> RuleDecision:
    neighbor_ids = {neighbor.id for neighbor in neighbors}
    target = parsed.target_id
    if target is not None and target not in neighbor_ids:
        return RuleDecision("NOOP", "llm_target_not_in_neighbors")
    if parsed.action in ("SUPERSEDE", "ASK") and target is None:
        return RuleDecision("NOOP", "llm_target_missing")
    if parsed.action == "MERGE":
        # 本阶段不实现合并，按 NOOP + 强化处理
        return RuleDecision("NOOP", "merge_as_noop", target)
    target_neighbor = next((n for n in neighbors if n.id == target), None)
    if parsed.action == "SUPERSEDE" and target_neighbor is not None:
        if candidate.scope.get("kind") in ("on", "until") and (
            target_neighbor.scope or {}
        ).get("kind") == "persistent":
            return RuleDecision("NOOP", "exception_cannot_override", target)
        if candidate.source_class == "inferred" and target_neighbor.source_class in (
            "stated",
            "confirmed",
        ):
            return RuleDecision("ASK", "inferred_cannot_override", target)
    return RuleDecision(parsed.action, parsed.reason or "llm", target)
