"""解释记忆：为什么存在、依据哪句话、经历过哪些裁决（只读）。

用法：
    uv run python scripts/explain_memory.py <user_id> [memory_id]
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
from app.db.base import make_engine, make_sessionmaker  # noqa: E402
from app.db.models import (  # noqa: E402
    EventLog,
    Memory,
    MemoryDecisionLog,
    MemoryExtractionRun,
    MemorySource,
    User,
)
from app.memory.weights import effective_weight  # noqa: E402


def _local(instant: dt.datetime | None, tz: str) -> str:
    return "-" if instant is None else instant.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")


def _event_text(event: EventLog) -> str:
    payload = event.payload or {}
    text = payload.get("text") or payload.get("message")
    if text:
        return str(text)
    return str(payload)[:200]


async def main_async(user_id: uuid.UUID, memory_id: str | None) -> int:
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
        if memory_id:
            try:
                target_id = uuid.UUID(memory_id)
            except ValueError:
                print(f"memory_id 不是合法 UUID：{memory_id}")
                return 2
            memory = await session.get(Memory, target_id)
            if memory is None:
                print(f"记忆不存在：{memory_id}")
                return 1
            print(
                f"记忆 {memory.id}\n"
                f"  status={memory.status} type={memory.type} slot={memory.slot_key}\n"
                f"  subject={memory.subject} value={memory.value} scope={memory.scope}\n"
                f"  source_class={memory.source_class} weight={memory.weight} "
                f"effective={effective_weight(memory.source_class, memory.weight, memory.last_reinforced_at or memory.recorded_at, clock.now()):.3f}\n"
                f"  support_days={memory.support_days} contradict={memory.contradict_count} "
                f"embedding={memory.embedding_model}\n"
                f"  recorded={_local(memory.recorded_at, tz)} "
                f"superseded={_local(memory.superseded_at, tz)} suppress={_local(memory.suppress_until, tz)}"
            )
            chain = []
            parent_id = memory.supersedes_id
            while parent_id is not None and len(chain) < 10:
                parent = await session.get(Memory, parent_id)
                if parent is None:
                    break
                chain.append(parent)
                parent_id = parent.supersedes_id
            if chain:
                print("\n替代链：")
                for row in chain:
                    print(f"  {row.id} {row.status} {row.subject}={row.value}")

            sources = (
                await session.execute(
                    select(EventLog)
                    .join(MemorySource, MemorySource.event_id == EventLog.id)
                    .where(MemorySource.memory_id == memory.id)
                    .order_by(EventLog.occurred_at)
                )
            ).scalars().all()
            print(f"\n证据事件（{len(sources)}）：")
            for event in sources:
                print(f"  {_local(event.occurred_at, tz)} {event.direction}/{event.type} {_event_text(event)[:100]}")

            logs = (
                await session.execute(
                    select(MemoryDecisionLog)
                    .where(MemoryDecisionLog.memory_id == memory.id)
                    .order_by(MemoryDecisionLog.created_at)
                )
            ).scalars().all()
            print(f"\n决策历史（{len(logs)}）：")
            for log in logs:
                print(f"  {_local(log.created_at, tz)} {log.action} reason={log.reason} run={log.run_id}")
                evidence = (log.candidate or {}).get("evidence") or []
                for item in evidence:
                    print(f"    证据片段：{item.get('quote')}")
            run_ids = {log.run_id for log in logs if log.run_id}
            for run_id in run_ids:
                run = await session.get(MemoryExtractionRun, run_id)
                if run is not None:
                    print(
                        f"\n所属 run {run.id}: status={run.status} version={run.extractor_version} "
                        f"events={run.event_count} stats={run.stats}"
                    )
            return 0

        memories = (
            await session.execute(
                select(Memory).where(Memory.user_id == user.id).order_by(Memory.recorded_at)
            )
        ).scalars().all()
        print(f"用户 {user.display_name}（{user.id}）共 {len(memories)} 条记忆")
        for row in memories:
            print(
                f"- {_local(row.recorded_at, tz)} {row.id} [{row.status}] {row.type} "
                f"{row.slot_key or ''} {row.subject}={row.value}"
            )
    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="解释记忆（只读）")
    parser.add_argument("user_id")
    parser.add_argument("memory_id", nargs="?")
    args = parser.parse_args()
    try:
        user_id = uuid.UUID(args.user_id)
    except ValueError:
        print(f"user_id 不是合法 UUID：{args.user_id}")
        sys.exit(2)
    sys.exit(asyncio.run(main_async(user_id, args.memory_id)))


if __name__ == "__main__":
    main()
