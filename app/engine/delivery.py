"""投递：候选 → 仲裁决策 → adapter 发送 → delivery 与 event_log 落库。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import ChannelAdapter, OutboundIntent
from app.core.clock import Clock
from app.core.logging import get_logger
from app.db.models import Delivery, NudgeCandidate, NudgeDecision, TriggerInstance
from app.engine.events import append_event
from app.engine.gate import GateOutcome, PassthroughGate
from app.engine.reasons import reason_for_trigger

DEFAULT_GATE = PassthroughGate()

logger = get_logger(__name__)


async def find_sent_delivery_for_trigger(
    session: AsyncSession, trigger_id: object
) -> Delivery | None:
    """发送幂等（方案 A）：同一 source_trigger 已有 sent_at 非空的 delivery 则视为已发送。"""
    row = (
        await session.execute(
            select(Delivery)
            .join(NudgeDecision, Delivery.decision_id == NudgeDecision.id)
            .join(NudgeCandidate, NudgeDecision.candidate_id == NudgeCandidate.id)
            .where(
                NudgeCandidate.source_trigger_id == trigger_id,
                Delivery.sent_at.is_not(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


async def deliver_trigger_nudge(
    session: AsyncSession,
    *,
    trigger: TriggerInstance,
    adapter: ChannelAdapter,
    clock: Clock,
    gate: PassthroughGate = DEFAULT_GATE,
) -> Delivery:
    """把到期 trigger 走完 候选→gate→发送→delivery 全链路；同一 trigger 不会重复发送。"""
    existing = await find_sent_delivery_for_trigger(session, trigger.id)
    if existing is not None:
        logger.info("skip duplicate trigger delivery: trigger_id=%s", trigger.id)
        return existing

    note = trigger.payload.get("note", "")
    candidate = NudgeCandidate(
        user_id=trigger.user_id,
        class_="commitment",
        reason_code=reason_for_trigger(trigger.kind),
        reason_text=note,
        value_score=1.0,
        expires_at=trigger.expires_at,
        dedupe_key=trigger.key,
        precondition=trigger.precondition,
        source_trigger_id=trigger.id,
    )
    session.add(candidate)
    await session.flush()

    outcome: GateOutcome = gate.decide(
        {"kind": trigger.kind, "note": note, "dedupe_key": trigger.key}
    )
    decision = NudgeDecision(
        candidate_id=candidate.id,
        decision=outcome.decision,
        gate_reasons=outcome.gate_reasons,
        policy_version=outcome.policy_version,
        budget_snapshot=None,
        decided_at=clock.now(),
    )
    session.add(decision)
    await session.flush()

    delivery = Delivery(decision_id=decision.id, channel=adapter.channel)
    if outcome.decision == "send":
        intent = OutboundIntent(
            type="nudge", user_id=trigger.user_id, body={"text": note}, collapse_key=trigger.key
        )
        result = await adapter.send(intent)
        delivery.provider_msg_id = result.provider_msg_id
        if result.ok:
            delivery.sent_at = clock.now()
        else:
            delivery.error = result.error
    else:
        delivery.error = f"gate decision: {outcome.decision}"
    session.add(delivery)

    await append_event(
        session,
        user_id=trigger.user_id,
        channel=adapter.channel,
        direction="outbound",
        type="delivery",
        payload={
            "trigger_id": str(trigger.id),
            "note": note,
            "decision": outcome.decision,
            "send_ok": delivery.sent_at is not None,
            "provider_msg_id": delivery.provider_msg_id,
        },
        trace_id=trigger.payload.get("trace_id", ""),
        clock=clock,
        idempotency_key=f"delivery:{trigger.id}",
    )
    return delivery
