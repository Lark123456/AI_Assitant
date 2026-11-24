"""pending 记忆的用户确认/拒绝：升为 confirmed 或 retracted。

调用方持有事务；本模块不 commit。确认时同时锁 pending 与旧记忆，避免与
其它写入链路竞争；同一旧记忆下只允许一条 pending 最终变为 active。
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import Memory, MemoryDecisionLog, User
from app.memory.weights import initial_weight

CONFIRMED = "confirmed"
REJECTED = "rejected"


class PendingMemoryNotFound(Exception):
    """pending 记忆不存在或不属于当前用户。"""


async def _lock_memory(
    session: AsyncSession, memory_id: uuid.UUID, user_id: uuid.UUID
) -> Memory | None:
    return (
        await session.execute(
            select(Memory)
            .where(Memory.id == memory_id, Memory.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


def _log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    action: str,
    reason: str,
    clock: Clock,
) -> None:
    session.add(
        MemoryDecisionLog(
            user_id=user_id,
            run_id=None,
            memory_id=memory_id,
            candidate={"source": "user_confirmation"},
            neighbors={"items": []},
            action=action,
            reason=reason,
            alias=None,
            llm_call_id=None,
            created_at=clock.now(),
        )
    )


async def decide_pending_memory(
    session: AsyncSession,
    *,
    user: User,
    pending_id: uuid.UUID,
    confirm: bool,
    clock: Clock,
) -> str:
    """确认或拒绝一条 pending 记忆，返回 confirmed / rejected。"""
    memory = await _lock_memory(session, pending_id, user.id)
    if memory is None:
        raise PendingMemoryNotFound

    if memory.status != "pending":
        if memory.status == "active" and memory.source_class == "confirmed":
            return CONFIRMED
        return REJECTED

    if not confirm:
        memory.status = "retracted"
        memory.rejected_at = clock.now()
        _log(
            session,
            user_id=user.id,
            memory_id=memory.id,
            action="NOOP",
            reason="user_rejected",
            clock=clock,
        )
        await session.flush()
        return REJECTED

    old: Memory | None = None
    if memory.supersedes_id is not None:
        old = await _lock_memory(session, memory.supersedes_id, user.id)
        if old is None or old.status != "active":
            # 旧事实已被别的链路替换：不再激活，避免同槽位出现两个 active。
            memory.status = "retracted"
            memory.rejected_at = clock.now()
            _log(
                session,
                user_id=user.id,
                memory_id=memory.id,
                action="NOOP",
                reason="stale_target",
                clock=clock,
            )
            await session.flush()
            return REJECTED

        siblings = (
            (
                await session.execute(
                    select(Memory)
                    .where(
                        Memory.user_id == user.id,
                        Memory.status == "pending",
                        Memory.supersedes_id == old.id,
                        Memory.id != memory.id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for sibling in siblings:
            sibling.status = "retracted"
            sibling.rejected_at = clock.now()
            _log(
                session,
                user_id=user.id,
                memory_id=sibling.id,
                action="NOOP",
                reason="superseded_pending",
                clock=clock,
            )

    memory.status = "active"
    memory.source_class = "confirmed"
    memory.weight = initial_weight("confirmed")
    if old is not None:
        old.status = "superseded"
        old.superseded_at = clock.now()
    _log(
        session,
        user_id=user.id,
        memory_id=memory.id,
        action="SUPERSEDE",
        reason="user_confirmed",
        clock=clock,
    )
    await session.flush()
    return CONFIRMED
