"""单日时间线：解释某用户某个本地日期收到了什么、为什么收到（只读，不写库）。

用法：
    uv run python scripts/explain_day.py <user_id> [YYYY-MM-DD]

输出四段：日程块、触发实例、候选决策、实际投递与信号。
日期缺省为「用户时区的今天」；日的边界按 user.day_start（默认 04:00）。
"""

import argparse
import asyncio
import datetime as dt
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.clock import Clock  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.timeutil import day_window_for_date, local_date_of  # noqa: E402
from app.db.base import make_engine, make_sessionmaker  # noqa: E402
from app.db.models import (  # noqa: E402
    EventLog,
    NudgeCandidate,
    NudgeDecision,
    PlannedBlock,
    TriggerInstance,
    User,
    WorkItem,
)


def _local(instant: dt.datetime | None, tz: str) -> str:
    if instant is None:
        return "-"
    return instant.astimezone(ZoneInfo(tz)).strftime("%H:%M")


def _gate_summary(gate: dict | None) -> str:
    if not gate:
        return "-"
    if gate.get("rule") == "merged_into_brief":
        return "并入简报"
    steps = [s for s in gate.get("steps", []) if not s.get("passed")]
    return str(steps[0].get("rule")) if steps else "全部通过"


async def main_async(user_id: uuid.UUID, day_arg: str | None) -> int:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    clock = Clock()

    async with sessionmaker() as session:
        user = await session.get(User, user_id)
        if user is None:
            print(f"用户不存在：{user_id}")
            return 1
        tz = user.timezone
        day = dt.date.fromisoformat(day_arg) if day_arg else local_date_of(
            clock.now(), tz, user.day_start
        )
        start, end = day_window_for_date(day, tz, user.day_start)

        blocks = (
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
        triggers = (
            await session.execute(
                select(TriggerInstance)
                .where(
                    TriggerInstance.user_id == user.id,
                    TriggerInstance.fire_at >= start,
                    TriggerInstance.fire_at < end,
                )
                .order_by(TriggerInstance.fire_at)
            )
        ).scalars().all()
        decisions = (
            await session.execute(
                select(NudgeDecision, NudgeCandidate)
                .join(NudgeCandidate, NudgeDecision.candidate_id == NudgeCandidate.id)
                .where(
                    NudgeCandidate.user_id == user.id,
                    NudgeDecision.decided_at >= start,
                    NudgeDecision.decided_at < end,
                )
                .order_by(NudgeDecision.decided_at)
            )
        ).all()
        deliveries = (
            await session.execute(
                select(EventLog)
                .where(
                    EventLog.user_id == user.id,
                    EventLog.type == "delivery",
                    EventLog.occurred_at >= start,
                    EventLog.occurred_at < end,
                )
                .order_by(EventLog.occurred_at)
            )
        ).scalars().all()
        signals = (
            await session.execute(
                select(EventLog)
                .where(
                    EventLog.user_id == user.id,
                    EventLog.type == "signal",
                    EventLog.occurred_at >= start,
                    EventLog.occurred_at < end,
                )
                .order_by(EventLog.occurred_at)
            )
        ).scalars().all()

    banner = (
        f"用户 {user.display_name} ({user.id})\n"
        f"日期 {day}（{tz}，日界 {user.day_start.strftime('%H:%M')}，"
        f"UTC {start.isoformat()} ~ {end.isoformat()}）"
    )
    print(banner)

    print(f"\n日程块（{len(blocks)}）")
    for block, title in blocks:
        span = f"{_local(block.starts_at, tz)}–{_local(block.ends_at, tz)}"
        extra = ""
        if block.actual_ended_at is not None:
            extra = f" 实际结束 {_local(block.actual_ended_at, tz)}"
        print(f"- {span} {title} [{block.status}]{extra}")

    print(f"\n触发实例（{len(triggers)}）")
    for row in triggers:
        print(
            f"- {_local(row.fire_at, tz)} {row.kind} [{row.status}] "
            f"attempts={row.attempts} defer={row.defer_count}"
            + (f" 错误={row.last_error}" if row.last_error else "")
        )

    print(f"\n候选决策（{len(decisions)}）")
    for decision, candidate in decisions:
        note = _gate_summary(decision.gate_reasons)
        merge = (
            f" -> 候选 {candidate.merged_into_candidate_id}"
            if candidate.merged_into_candidate_id
            else ""
        )
        print(
            f"- {_local(decision.decided_at, tz)} {candidate.class_} "
            f"{candidate.reason_code} => {decision.decision}（{note}）{merge}"
        )

    print(f"\n实际投递（{len(deliveries)}）")
    for event in deliveries:
        payload = event.payload or {}
        first_line = str(payload.get("text", "")).splitlines()[0] if payload.get("text") else "-"
        ok = "成功" if payload.get("send_ok") else "失败"
        print(
            f"- {_local(event.occurred_at, tz)} {event.channel} {payload.get('reason_code', '')} "
            f"{ok}：{first_line}"
        )

    print(f"\n信号（{len(signals)}）")
    for event in signals:
        payload = event.payload or {}
        print(f"- {_local(event.occurred_at, tz)} {payload.get('title', '')} ({payload.get('kind', '')})")

    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="解释某用户某天的主动消息与决策（只读）")
    parser.add_argument("user_id", help="用户 UUID")
    parser.add_argument("date", nargs="?", help="本地日期 YYYY-MM-DD，缺省为今天")
    args = parser.parse_args()
    try:
        user_id = uuid.UUID(args.user_id)
    except ValueError:
        print(f"user_id 不是合法 UUID：{args.user_id}")
        sys.exit(2)
    sys.exit(asyncio.run(main_async(user_id, args.date)))


if __name__ == "__main__":
    main()
