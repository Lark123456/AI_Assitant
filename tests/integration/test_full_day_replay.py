"""整日回放：FakeClock 以 5 分钟步进驱动 24 小时，断言消息序列、免打扰延后与建议并入。

编排（本地 Asia/Shanghai，day_start=04:00，免打扰 11:00–12:00）：
- 09:10 块「写报告」→ 09:00 提醒；09:55 标记完成（不再产生逾期信号）
- 11:00 块「复盘」→ 10:50 提醒（免打扰前）
- 11:10 块「写周报」→ 11:00 提醒落在免打扰内 → 延后到 12:00 发出
- 晨报改到 11:15 → 同样延后到 12:00 发出（验证不会被自己的 defer 决策锁死）
- 14:00 块「整理笔记」→ 13:50 提醒
- 15:00 提醒「交报告」；21:00 晚间复盘（2 条逾期建议并入）
"""

import datetime as dt

from sqlalchemy import select

from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import UTC, FakeClock
from app.db.models import (
    ChannelIdentity,
    EventLog,
    NudgeCandidate,
    NudgeDecision,
    TriggerInstance,
    User,
)
from app.engine.materializer import run_materializer
from app.engine.nudge import arbitrate_pending_suggestions
from app.engine.triggers import claim_due_triggers, reclaim_expired_leases
from app.tools.base import ToolContext
from app.tools.registry import execute_tool
from app.worker.runner import process_claimed_trigger

LOCAL = dt.timezone(dt.timedelta(hours=8))
QUIET_START = dt.time(11, 0)
QUIET_END = dt.time(12, 0)


async def _call_tool(db, clock, settings, user_id, event_id, name, args, call_index):
    async with db() as session:
        user = await session.get(User, user_id)
        assert user is not None
        ctx = ToolContext(
            session=session,
            clock=clock,
            settings=settings,
            user=user,
            trace_id="replay",
            channel="console",
            source_event_id=event_id,
        )
        result = await execute_tool(ctx, name, args, call_index=call_index)
        await session.commit()
        return result


async def test_full_day_replay(db, settings) -> None:
    clock = FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))  # 本地 08:00
    async with db() as session:
        user = User(display_name="u1", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        session.add(
            ChannelIdentity(user_id=user.id, channel="console", external_id="u1", rev=1)
        )
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": "setup"},
            trace_id="replay",
            occurred_at=clock.now(),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        user_id = user.id
        event_id = event.id

    blocks = [
        ("写报告", "2026-01-01T09:10:00+08:00", "2026-01-01T10:00:00+08:00"),
        ("复盘", "2026-01-01T11:00:00+08:00", "2026-01-01T12:00:00+08:00"),
        ("整理笔记", "2026-01-01T14:00:00+08:00", "2026-01-01T15:00:00+08:00"),
        ("写周报", "2026-01-01T11:10:00+08:00", "2026-01-01T12:00:00+08:00"),
    ]
    block_ids: list[str] = []
    for index, (title, starts_at, ends_at) in enumerate(blocks, start=1):
        result = await _call_tool(
            db, clock, settings, user_id, event_id,
            "schedule_block",
            {"title": title, "starts_at": starts_at, "ends_at": ends_at},
            call_index=index,
        )
        assert result.status == "ok"
        block_ids.append(str(result.data["block_id"]))

    await _call_tool(
        db, clock, settings, user_id, event_id,
        "set_reminder",
        {"fire_at": "2026-01-01T15:00:00+08:00", "note": "交报告"},
        call_index=5,
    )
    # 免打扰改到白天 11:00–12:00，晨报也落在其中，便于在 24 小时内验证 defer → send
    prefs_result = await _call_tool(
        db, clock, settings, user_id, event_id,
        "set_notif_prefs",
        {"quiet_hours": "11:00-12:00", "morning_brief_time": "11:15"},
        call_index=6,
    )
    assert prefs_result.status == "ok"

    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    adapters = {"console": console}
    await run_materializer(db, clock=clock, settings=settings)

    done_first_block = False
    for _step in range(24 * 12):
        clock.advance(300)
        now = clock.now()
        if not done_first_block and now == dt.datetime(2026, 1, 1, 1, 55, tzinfo=UTC):
            await _call_tool(
                db, clock, settings, user_id, event_id,
                "update_block_status", {"block_id": block_ids[0], "status": "done"},
                call_index=10,
            )
            done_first_block = True
        await run_materializer(db, clock=clock, settings=settings)
        await arbitrate_pending_suggestions(db, clock=clock, settings=settings)
        async with db() as session:
            await reclaim_expired_leases(session, now=now, lease_seconds=300)
            claimed = await claim_due_triggers(session, now=now, limit=10)
            await session.commit()
        for trigger in claimed:
            await process_claimed_trigger(
                db,
                trigger_id=trigger.id,
                adapters=adapters,
                clock=clock,
                settings=settings,
                gateway=None,
            )

    texts = [m["body"]["text"] for m in console.messages_for("u1")]
    assert len(texts) == 7

    # 09:00 / 10:50 正常提醒
    assert texts[0].startswith("即将开始：写报告")
    assert texts[1].startswith("即将开始：复盘")
    # 11:00 落在免打扰 → 延后到 12:00 发出；晨报同理（不会被自己的 defer 决策锁死）
    assert texts[2].startswith("即将开始：写周报")
    assert texts[3].startswith("早上好")
    assert "今日安排" in texts[3]
    assert "11:15" in texts[3]
    assert "今日提醒：交报告" in texts[3]
    # 13:50 提醒 + 15:00 提醒 + 21:00 晚间复盘
    assert texts[4].startswith("即将开始：整理笔记")
    assert texts[5].startswith("交报告")
    assert texts[6].startswith("晚上好")
    assert "今日回顾" in texts[6]
    assert "[已完成]" in texts[6] and "[未完成]" in texts[6]
    assert "建议：过去 24 小时有 2 个计划块逾期未完成" in texts[6]

    async with db() as session:
        triggers = (
            await session.execute(select(TriggerInstance))
        ).scalars().all()
        deliveries = (
            await session.execute(
                select(EventLog).where(EventLog.user_id == user_id, EventLog.type == "delivery")
            )
        ).scalars().all()
        signals = (
            await session.execute(
                select(EventLog).where(EventLog.user_id == user_id, EventLog.type == "signal")
            )
        ).scalars().all()
        decisions = (
            await session.execute(
                select(NudgeDecision.decision, NudgeCandidate.dedupe_key)
                .join(NudgeCandidate, NudgeDecision.candidate_id == NudgeCandidate.id)
            )
        ).all()

    # 回放期间不应出现错过、失败或重复投递
    assert [row for row in triggers if row.status in ("missed", "failed")] == []
    assert len(deliveries) == 7
    assert len(signals) == 3

    # 两条被延后的 trigger：先 defer 再 send，defer_count=1，attempts 未被 defer 消耗
    deferred = [
        row
        for row in triggers
        if (row.kind == "block_start" and row.key.startswith(f"block_start:{block_ids[3]}:"))
        or (row.kind == "brief_morning" and row.fire_at == dt.datetime(2026, 1, 1, 3, 15, tzinfo=UTC))
    ]
    assert len(deferred) == 2
    for row in deferred:
        assert row.status == "fired"
        assert row.defer_count == 1
        assert row.attempts == 1
        key_decisions = sorted(d for d, key in decisions if key == row.key)
        assert key_decisions == ["defer", "send"]

    # 免打扰时段（11:00–12:00 本地）内没有投递
    for row in deliveries:
        local = row.occurred_at.astimezone(LOCAL)
        assert not (QUIET_START <= local.time() < QUIET_END)
