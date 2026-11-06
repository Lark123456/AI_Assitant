"""投递查询：发送幂等判定（同一来源 trigger 已有成功投递则视为已发送）。"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Delivery, NudgeCandidate, NudgeDecision


async def find_sent_delivery_for_trigger(
    session: AsyncSession, trigger_id: object
) -> Delivery | None:
    """同一 source_trigger 已有 sent_at 非空的 delivery 则视为已发送。"""
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
