"""仲裁 IO 外层：组装快照 → evaluate → 决策落库 → 发送/延后/合并/丢弃。

唯一发送出口：本模块的 send 分支。任何主动消息都必须先经过 evaluate。
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.base import ChannelAdapter, OutboundIntent
from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.timeutil import day_window_utc
from app.db.models import Delivery, NotifPrefs, NudgeCandidate, NudgeDecision, TriggerInstance, User
from app.engine.arbiter import CandidateView, Decision, UserStateSnapshot, evaluate
from app.engine.brief import render_brief
from app.engine.delivery import find_sent_delivery_for_trigger
from app.engine.events import append_event
from app.engine.handlers import CandidateDraft
from app.engine.materializer import get_or_create_prefs
from app.llm.gateway import LLMGateway

logger = get_logger(__name__)


@dataclass
class NudgeOutcome:
    decision: str
    text: str | None = None
    delivered: bool = False
    error: str | None = None


async def get_or_create_candidate(
    session: AsyncSession, *, trigger: TriggerInstance, draft: CandidateDraft
) -> NudgeCandidate:
    """候选与来源 trigger 一一对应：重试时复用，不重复落库。"""
    existing = (
        (
            await session.execute(
                select(NudgeCandidate).where(NudgeCandidate.source_trigger_id == trigger.id)
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    row = NudgeCandidate(
        user_id=trigger.user_id,
        class_=draft.class_,
        reason_code=draft.reason_code,
        reason_text=draft.reason_text,
        value_score=draft.value_score,
        expires_at=draft.expires_at,
        dedupe_key=draft.dedupe_key,
        precondition=draft.precondition,
        source_trigger_id=trigger.id,
        explicit=draft.explicit,
    )
    session.add(row)
    await session.flush()
    return row


def _parse_hhmm(value: str, default: dt.time) -> dt.time:
    try:
        hour, minute = value.split(":")
        return dt.time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return default


def _quiet_window(prefs: NotifPrefs) -> tuple[dt.time, dt.time]:
    quiet = prefs.quiet_hours or {}
    return (
        _parse_hhmm(str(quiet.get("start", "23:00")), dt.time(23, 0)),
        _parse_hhmm(str(quiet.get("end", "07:00")), dt.time(7, 0)),
    )


async def build_snapshot(
    session: AsyncSession,
    *,
    user: User,
    prefs: NotifPrefs,
    clock: Clock,
    settings: Settings,
    dedupe_key: str | None,
) -> UserStateSnapshot:
    """预取仲裁所需的全部状态（本函数之外 evaluate 不再触库）。"""
    now = clock.now()
    start, end = day_window_utc(now, user.timezone, user.day_start)

    rows = (
        await session.execute(
            select(NudgeCandidate.class_, NudgeCandidate.reason_code, func.count())
            .join(NudgeDecision, NudgeDecision.candidate_id == NudgeCandidate.id)
            .where(
                NudgeCandidate.user_id == user.id,
                NudgeDecision.decision == "send",
                NudgeDecision.decided_at >= start,
                NudgeDecision.decided_at < end,
            )
            .group_by(NudgeCandidate.class_, NudgeCandidate.reason_code)
        )
    ).all()
    by_reason: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for cls, reason, count in rows:
        by_reason[reason] = by_reason.get(reason, 0) + int(count)
        by_class[cls] = by_class.get(cls, 0) + int(count)

    merged_count = (
        await session.execute(
            select(func.count())
            .select_from(NudgeCandidate)
            .join(NudgeDecision, NudgeDecision.candidate_id == NudgeCandidate.id)
            .where(
                NudgeCandidate.user_id == user.id,
                NudgeCandidate.class_ == "suggestion",
                NudgeDecision.decision == "merge",
                NudgeDecision.decided_at >= start,
                NudgeDecision.decided_at < end,
            )
        )
    ).scalar_one()

    last_at: dt.datetime | None = None
    if dedupe_key:
        last_at = (
            await session.execute(
                select(func.max(NudgeDecision.decided_at))
                .join(NudgeCandidate, NudgeDecision.candidate_id == NudgeCandidate.id)
                .where(
                    NudgeCandidate.user_id == user.id,
                    NudgeCandidate.dedupe_key == dedupe_key,
                )
            )
        ).scalar_one_or_none()

    quiet_start, quiet_end = _quiet_window(prefs)
    return UserStateSnapshot(
        now=now,
        tz=user.timezone,
        day_start=user.day_start,
        quiet_start=quiet_start,
        quiet_end=quiet_end,
        daily_budget=prefs.daily_budget,
        class_enabled=dict(prefs.class_enabled or {}),
        snooze_until=prefs.snooze_until,
        briefs_enabled=prefs.briefs_enabled,
        sent_today_by_reason=by_reason,
        sent_today_by_class=by_class,
        suggestion_budget_used=int(merged_count),
        last_decision_at={dedupe_key: last_at} if (dedupe_key and last_at) else {},
        kill_switch=settings.nudge_kill_switch,
    )


def _commitment_text(trigger: TriggerInstance, *, now: dt.datetime) -> str:
    """承诺类消息正文：迟到标注 + 一句可操作说明。"""
    note = str(trigger.payload.get("note", "")) or trigger.payload.get("title", "提醒")
    late = ""
    if trigger.kind == "reminder" and now > trigger.fire_at:
        minutes = int((now - trigger.fire_at).total_seconds() // 60)
        late = f"（迟到 {minutes} 分钟）"
    if trigger.kind == "reminder":
        hint = "（你设置的提醒；说「取消提醒」可以关闭）"
        return f"{note}{late}\n\n{hint}"
    hint = "（日程开始前的提醒；说「取消这个块的提醒」可以关闭）"
    return f"即将开始：{note}{late}\n\n{hint}"


async def _send(
    session: AsyncSession,
    *,
    user: User,
    candidate: NudgeCandidate,
    decision_row: NudgeDecision,
    text: str,
    block_ids: tuple[str, ...],
    work_item_ids: tuple[str, ...],
    adapter: ChannelAdapter,
    clock: Clock,
) -> Delivery:
    result = await adapter.send(
        OutboundIntent(
            type="nudge",
            user_id=user.id,
            body={"text": text},
            collapse_key=candidate.dedupe_key,
        )
    )
    delivery = Delivery(decision_id=decision_row.id, channel=adapter.channel)
    delivery.provider_msg_id = result.provider_msg_id
    if result.ok:
        delivery.sent_at = clock.now()
    else:
        delivery.error = result.error
    session.add(delivery)
    return delivery


async def process_candidate(
    session: AsyncSession,
    *,
    user: User,
    prefs: NotifPrefs,
    candidate: NudgeCandidate,
    trigger: TriggerInstance | None,
    adapter: ChannelAdapter | None,
    clock: Clock,
    settings: Settings,
    gateway: LLMGateway | None,
    trace_id: str,
) -> NudgeOutcome:
    """完整仲裁与执行：写入 decision，按结论发送/延后/合并/丢弃。"""
    now = clock.now()
    # 发送幂等：同一 trigger 已有成功投递时直接视为完成，避免重试重复发送
    if trigger is not None:
        sent = await find_sent_delivery_for_trigger(session, trigger.id)
        if sent is not None:
            logger.info("skip duplicate trigger delivery: trigger_id=%s", trigger.id)
            return NudgeOutcome(decision="send", delivered=True)
    view = CandidateView(
        class_=candidate.class_,
        reason_code=candidate.reason_code,
        explicit=candidate.explicit,
        dedupe_key=candidate.dedupe_key,
        expires_at=candidate.expires_at,
        precondition_ok=True,
        defer_count=trigger.defer_count if trigger is not None else 0,
    )
    snapshot = await build_snapshot(
        session, user=user, prefs=prefs, clock=clock, settings=settings,
        dedupe_key=candidate.dedupe_key,
    )
    decision: Decision = evaluate(view, snapshot)
    content_text: str | None = None
    content_blocks: tuple[str, ...] = ()
    content_items: tuple[str, ...] = ()
    merged_ids: tuple[uuid.UUID, ...] = ()

    # 简报在发送时才渲染；渲染为空则改判 nothing_to_say
    if decision.decision == "send" and candidate.class_ == "brief":
        content = await render_brief(
            session,
            user=user,
            prefs=prefs,
            kind="brief_morning" if candidate.reason_code == "brief.morning" else "brief_evening",
            clock=clock,
            settings=settings,
            gateway=gateway,
            trace_id=trace_id,
        )
        if content is None:
            reasons = dict(decision.gate_reasons)
            reasons["steps"] = list(reasons.get("steps", [])) + [
                {"rule": "nothing_to_say", "passed": False}
            ]
            reasons["final"] = "drop"
            decision = Decision(
                decision="drop",
                gate_reasons=reasons,
                budget_snapshot=decision.budget_snapshot,
            )
        else:
            content_text = content.text
            content_blocks = content.block_ids
            content_items = content.work_item_ids
            merged_ids = content.merged_ids

    decision_row = NudgeDecision(
        candidate_id=candidate.id,
        decision=decision.decision,
        gate_reasons=decision.gate_reasons,
        policy_version=decision.policy_version,
        budget_snapshot=decision.budget_snapshot,
        decided_at=now,
    )
    session.add(decision_row)
    await session.flush()

    if decision.decision == "defer":
        if trigger is not None and decision.defer_until is not None:
            trigger.status = "pending"
            trigger.next_attempt_at = decision.defer_until
            trigger.attempts = max(0, trigger.attempts - 1)
            trigger.defer_count = (trigger.defer_count or 0) + 1
            trigger.claimed_at = None
        return NudgeOutcome(decision="defer")

    if decision.decision != "send":
        return NudgeOutcome(decision=decision.decision)

    if candidate.class_ == "brief":
        assert content_text is not None
        text = content_text
    else:
        assert trigger is not None
        text = _commitment_text(trigger, now=now)
    assert adapter is not None

    delivery = await _send(
        session,
        user=user,
        candidate=candidate,
        decision_row=decision_row,
        text=text,
        block_ids=content_blocks,
        work_item_ids=content_items,
        adapter=adapter,
        clock=clock,
    )
    await append_event(
        session,
        user_id=user.id,
        channel=adapter.channel,
        direction="outbound",
        type="delivery",
        payload={
            "trigger_id": str(trigger.id) if trigger is not None else None,
            "candidate_id": str(candidate.id),
            "decision": "send",
            "send_ok": delivery.sent_at is not None,
            "provider_msg_id": delivery.provider_msg_id,
            "reason_code": candidate.reason_code,
            "text": text,
            "block_ids": list(content_blocks),
            "work_item_ids": list(content_items),
        },
        trace_id=trace_id,
        clock=clock,
        idempotency_key=(
            f"delivery:{trigger.id}" if trigger is not None else f"delivery-candidate:{candidate.id}"
        ),
    )

    # 被并入的建议：标记落点并追加一条 send 决策（指向简报候选）
    if merged_ids:
        brief_candidate_id = candidate.id
        for merged_id in merged_ids:
            merged_row = await session.get(NudgeCandidate, merged_id)
            if merged_row is None:
                continue
            merged_row.merged_into_candidate_id = brief_candidate_id
            session.add(
                NudgeDecision(
                    candidate_id=brief_candidate_id,
                    decision="send",
                    gate_reasons={
                        "rule": "merged_into_brief",
                        "merged_candidate_id": str(merged_id),
                    },
                    policy_version=decision.policy_version,
                    budget_snapshot=decision.budget_snapshot,
                    decided_at=now,
                )
            )
        await session.flush()

    return NudgeOutcome(
        decision="send",
        text=text,
        delivered=delivery.sent_at is not None,
        error=delivery.error,
    )


async def arbitrate_pending_suggestions(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    clock: Clock,
    settings: Settings,
) -> int:
    """对规则引擎新建的 suggestion 候选执行仲裁（只会 merge/drop，不发送）。"""
    count = 0
    async with sessionmaker() as session:
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            prefs = await get_or_create_prefs(session, user.id, clock)
            rows = (
                (
                    await session.execute(
                        select(NudgeCandidate)
                        .outerjoin(
                            NudgeDecision, NudgeDecision.candidate_id == NudgeCandidate.id
                        )
                        .where(
                            NudgeCandidate.user_id == user.id,
                            NudgeCandidate.class_ == "suggestion",
                            NudgeDecision.id.is_(None),
                        )
                        .order_by(NudgeCandidate.id)
                    )
                )
                .scalars()
                .all()
            )
            for candidate in rows:
                await process_candidate(
                    session,
                    user=user,
                    prefs=prefs,
                    candidate=candidate,
                    trigger=None,
                    adapter=None,
                    clock=clock,
                    settings=settings,
                    gateway=None,
                    trace_id=f"suggestion:{candidate.id}",
                )
                count += 1
        await session.commit()
    if count:
        logger.info("arbitrated %d pending suggestions", count)
    return count
