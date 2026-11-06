"""简报渲染：主体由确定性模板生成，LLM 只允许写一句开场语。

约束：
- 清单内容全部来自数据库查询，LLM 输出只取第一行且限长，不能新增/删除/改写任务。
- 调用失败或超时（别名 timeout=3 秒）时回退模板开场语。
- 没有任何可说的内容时返回 None，由仲裁器以 nothing_to_say 丢弃。
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.core.config import Settings
from app.core.logging import get_logger
from app.core.timeutil import day_window_utc
from app.db.models import (
    NotifPrefs,
    NudgeCandidate,
    NudgeDecision,
    PlannedBlock,
    TriggerInstance,
    User,
    WorkItem,
)
from app.llm.gateway import LLMGateway

logger = get_logger(__name__)

BRIEF_ALIAS = "brief_compose"
MAX_UNSCHEDULED_TASKS = 5


@dataclass(frozen=True)
class BriefContent:
    text: str
    block_ids: tuple[str, ...]
    work_item_ids: tuple[str, ...]
    merged_ids: tuple[uuid.UUID, ...]


# 因为英文单词 + 中文标点容易误读，此处集中排版工具
def _hhmm(instant: dt.datetime, tz: str) -> str:
    return instant.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _minutes(start: dt.datetime, end: dt.datetime) -> int:
    return int((end - start).total_seconds() // 60)


async def _collect_merged(
    session: AsyncSession, user: User, now: dt.datetime
) -> list[NudgeCandidate]:
    """收集已判 merge、尚未并入、仍未过期的建议候选。"""
    rows = (
        (
            await session.execute(
                select(NudgeCandidate)
                .join(NudgeDecision, NudgeDecision.candidate_id == NudgeCandidate.id)
                .where(
                    NudgeCandidate.user_id == user.id,
                    NudgeCandidate.class_ == "suggestion",
                    NudgeCandidate.merged_into_candidate_id.is_(None),
                    NudgeDecision.decision == "merge",
                    (NudgeCandidate.expires_at.is_(None)) | (NudgeCandidate.expires_at > now),
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _today_blocks(
    session: AsyncSession, user: User, start: dt.datetime, end: dt.datetime
) -> list[tuple[PlannedBlock, str]]:
    rows = (
        await session.execute(
            select(PlannedBlock, WorkItem.title)
            .join(WorkItem, PlannedBlock.work_item_id == WorkItem.id)
            .where(
                PlannedBlock.user_id == user.id,
                PlannedBlock.starts_at >= start,
                PlannedBlock.starts_at < end,
            )
            .order_by(PlannedBlock.starts_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def _unscheduled_tasks(
    session: AsyncSession, user: User, scheduled_work_item_ids: tuple[uuid.UUID, ...]
) -> list[str]:
    query = select(WorkItem.title).where(
        WorkItem.user_id == user.id, WorkItem.status == "active"
    )
    if scheduled_work_item_ids:
        query = query.where(WorkItem.id.not_in(scheduled_work_item_ids))
    return list(
        (await session.execute(query.order_by(WorkItem.created_at).limit(MAX_UNSCHEDULED_TASKS)))
        .scalars()
        .all()
    )


async def _today_reminders(
    session: AsyncSession, user: User, start: dt.datetime, end: dt.datetime
) -> list[str]:
    query = select(TriggerInstance.payload).where(
        TriggerInstance.user_id == user.id,
        TriggerInstance.kind == "reminder",
        TriggerInstance.status == "pending",
        TriggerInstance.fire_at >= start,
        TriggerInstance.fire_at < end,
    )
    payloads = (await session.execute(query.order_by(TriggerInstance.fire_at))).scalars().all()
    return [str(p.get("note", "提醒")) for p in payloads]


async def _yesterday_stats(
    session: AsyncSession, user: User, today_start: dt.datetime
) -> tuple[int, int]:
    """昨日完成数与未完成数（按昨日窗口内的计划块状态）。"""
    yesterday_start = today_start - dt.timedelta(days=1)
    rows = (
        await session.execute(
            select(PlannedBlock.status, func.count())
            .where(
                PlannedBlock.user_id == user.id,
                PlannedBlock.starts_at >= yesterday_start,
                PlannedBlock.starts_at < today_start,
            )
            .group_by(PlannedBlock.status)
        )
    ).all()
    done = sum(count for status, count in rows if status in ("done", "skipped"))
    pending = sum(count for status, count in rows if status in ("planned", "moved"))
    return done, pending


async def _opening(
    gateway: LLMGateway | None,
    *,
    user: User,
    kind: str,
    facts: dict,
    trace_id: str,
) -> str:
    """让 LLM 写一句开场语；失败/超时/空输出都回退模板。只取第一行并限长。"""
    fallback = "早上好。" if kind == "brief_morning" else "晚上好。"
    if gateway is None:
        return fallback
    try:
        result = await gateway.chat(
            alias=BRIEF_ALIAS,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你只需输出一句简短的开场语（不超过 30 字），不要列出任何清单，"
                        "不要编造事实，只依据给定事实说话。"
                    ),
                },
                {"role": "user", "content": str(facts)},
            ],
            trace_id=trace_id,
            user_id=user.id,
        )
        first_line = (result.content or "").strip().splitlines()[0].strip()
        return first_line[:40] if first_line else fallback
    except Exception:
        logger.warning("brief opening failed, using fallback", exc_info=True)
        return fallback


async def render_brief(
    session: AsyncSession,
    *,
    user: User,
    prefs: NotifPrefs,
    kind: str,
    clock: Clock,
    settings: Settings,
    gateway: LLMGateway | None,
    trace_id: str,
) -> BriefContent | None:
    """渲染晨间/晚间简报；没有可说的内容时返回 None。"""
    now = clock.now()
    today_start, today_end = day_window_utc(now, user.timezone, user.day_start)
    blocks = await _today_blocks(session, user, today_start, today_end)
    scheduled_work_ids = tuple({block.work_item_id for block, _ in blocks})
    merged = await _collect_merged(session, user, now)
    is_morning = kind == "brief_morning"

    lines: list[str] = []
    if blocks:
        lines.append("今日安排：" if is_morning else "今日回顾：")
        for block, work_title in blocks:
            span = f"{_hhmm(block.starts_at, user.timezone)}–{_hhmm(block.ends_at, user.timezone)}"
            duration = f"{_minutes(block.starts_at, block.ends_at)} 分钟"
            mark = ""
            if not is_morning:
                mark = " [已完成]" if block.status in ("done", "skipped") else " [未完成]"
            lines.append(f"- {span} {work_title}（{duration}）{mark}")

    if is_morning:
        unscheduled = await _unscheduled_tasks(session, user, scheduled_work_ids)
        if unscheduled:
            lines.append("未排期任务：" + "、".join(unscheduled))
        reminders = await _today_reminders(session, user, today_start, today_end)
        if reminders:
            lines.append("今日提醒：" + "、".join(reminders))
        done, pending = await _yesterday_stats(session, user, today_start)
        if done or pending:
            lines.append(f"昨天：完成 {done} 项，未完成 {pending} 项")

    if merged:
        lines.append("建议：" + "；".join(c.reason_text for c in merged))

    if not lines:
        return None

    facts = {
        "kind": kind,
        "block_count": len(blocks),
        "unscheduled_count": len(await _unscheduled_tasks(session, user, scheduled_work_ids)),
        "merged_count": len(merged),
        "timezone": user.timezone,
    }
    opening = await _opening(gateway, user=user, kind=kind, facts=facts, trace_id=trace_id)
    body = "\n".join(lines)
    brief_time = (
        prefs.morning_brief_time if is_morning else prefs.evening_brief_time
    ).strftime("%H:%M")
    lead = settings.block_lead_minutes
    if is_morning:
        footer = (
            f"\n\n这是每天 {brief_time} 的晨间简报；日程开始前 {lead} 分钟会单独提醒。"
            f"说「把简报改到 9 点」或「关闭简报」可以调整。"
        )
    else:
        footer = (
            f"\n\n这是每天 {brief_time} 的晚间复盘；回复「第一个做完了」可更新块状态。"
            "说「把复盘改到 22 点」或「关闭简报」可以调整。"
        )
    text = f"{opening}\n\n{body}{footer}"
    logger.info("brief rendered: user_id=%s kind=%s merged=%d", user.id, kind, len(merged))
    return BriefContent(
        text=text,
        block_ids=tuple(str(block.id) for block, _ in blocks),
        work_item_ids=tuple(str(block.work_item_id) for block, _ in blocks),
        merged_ids=tuple(c.id for c in merged),
    )
