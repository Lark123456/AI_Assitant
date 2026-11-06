"""阶段 2 工具：块管理、提醒管理、通知偏好。"""

import datetime as dt
import uuid

from sqlalchemy import select

from app.db.models import EventLog, PlannedBlock, TriggerInstance, User, WorkItem
from app.tools.base import ToolContext
from app.tools.registry import execute_tool


async def _seed(db, clock) -> tuple[User, uuid.UUID]:
    async with db() as session:
        user = User(display_name="tools", timezone="Asia/Shanghai", day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.flush()
        event = EventLog(
            user_id=user.id,
            channel="console",
            direction="inbound",
            type="message",
            payload={"text": "test"},
            trace_id="tool-test",
            occurred_at=clock.now(),
            recorded_at=clock.now(),
        )
        session.add(event)
        await session.commit()
        return user, event.id


def _ctx(session, clock, settings, user, event_id: uuid.UUID) -> ToolContext:
    return ToolContext(
        session=session,
        clock=clock,
        settings=settings,
        user=user,
        trace_id="tool-test",
        channel="console",
        source_event_id=event_id,
    )


async def _block_triggers(db, block_id: uuid.UUID) -> list[TriggerInstance]:
    async with db() as session:
        return list(
            (
                await session.execute(
                    select(TriggerInstance).where(
                        TriggerInstance.key.like(f"%{block_id}%"),
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_schedule_block_creates_item_and_triggers(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "schedule_block",
            {
                "title": "写报告",
                "starts_at": "2026-01-01T09:00:00+08:00",
                "ends_at": "2026-01-01T10:00:00+08:00",
            },
            call_index=1,
        )
        await session.commit()
    assert result.status == "ok", result.message
    assert result.data["triggers_created"] == 2
    block_id = uuid.UUID(str(result.data["block_id"]))
    triggers = await _block_triggers(db, block_id)
    assert {t.kind for t in triggers} == {"block_start", "overdue_check"}


async def test_schedule_block_with_duration_and_existing_item(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        item = WorkItem(user_id=user.id, type="item", status="active", title="复盘")
        session.add(item)
        await session.flush()
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "schedule_block",
            {
                "work_item_id": str(item.id),
                "starts_at": "2026-01-01T11:00:00+08:00",
                "duration_min": 90,
            },
            call_index=1,
        )
        await session.commit()
    assert result.status == "ok", result.message
    assert result.data["ends_at"].endswith("+08:00")


async def test_list_schedule_returns_blocks(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "schedule_block",
            {
                "title": "写报告",
                "starts_at": "2026-01-01T09:00:00+08:00",
                "ends_at": "2026-01-01T10:00:00+08:00",
            },
            call_index=1,
        )
        await session.commit()
    async with db() as session:
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id), "list_schedule", {}, call_index=2
        )
    assert result.status == "ok", result.message
    assert len(result.data["blocks"]) == 1
    assert result.data["blocks"][0]["title"] == "写报告"


async def test_update_status_cancels_pending_triggers(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        created = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "schedule_block",
            {
                "title": "写报告",
                "starts_at": "2026-01-01T09:00:00+08:00",
                "ends_at": "2026-01-01T10:00:00+08:00",
            },
            call_index=1,
        )
        await session.commit()
    block_id = str(created.data["block_id"])

    async with db() as session:
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "update_block_status",
            {"block_id": block_id, "status": "done"},
            call_index=2,
        )
        await session.commit()
    assert result.status == "ok", result.message
    triggers = await _block_triggers(db, uuid.UUID(block_id))
    assert all(t.status != "pending" for t in triggers)


async def test_reschedule_rebuilds_triggers(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        created = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "schedule_block",
            {
                "title": "写报告",
                "starts_at": "2026-01-01T09:00:00+08:00",
                "ends_at": "2026-01-01T10:00:00+08:00",
            },
            call_index=1,
        )
        await session.commit()
    block_id = str(created.data["block_id"])

    async with db() as session:
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "reschedule_block",
            {
                "block_id": block_id,
                "starts_at": "2026-01-01T14:00:00+08:00",
                "ends_at": "2026-01-01T15:00:00+08:00",
            },
            call_index=2,
        )
        await session.commit()
    assert result.status == "ok", result.message
    async with db() as session:
        block = await session.get(PlannedBlock, uuid.UUID(block_id))
        assert block is not None
        assert block.rev == 2
        assert block.starts_at == dt.datetime(2026, 1, 1, 6, 0, tzinfo=dt.UTC)


async def test_reminder_list_and_cancel(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        created = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "set_reminder",
            {"fire_at": "2026-01-01T15:00:00+08:00", "note": "交报告"},
            call_index=1,
        )
        await session.commit()
    trigger_id = str(created.data["trigger_id"])

    async with db() as session:
        listed = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id), "list_reminders", {}, call_index=2
        )
    assert listed.status == "ok"
    assert len(listed.data["reminders"]) == 1

    async with db() as session:
        cancelled = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "cancel_reminder",
            {"trigger_id": trigger_id},
            call_index=3,
        )
        await session.commit()
    assert cancelled.status == "ok"
    async with db() as session:
        row = await session.get(TriggerInstance, uuid.UUID(trigger_id))
        assert row is not None and row.status == "dropped"


async def test_set_notif_prefs_reschedules_briefs(db, fake_clock, settings) -> None:
    user, event_id = await _seed(db, fake_clock)
    async with db() as session:
        await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id), "set_notif_prefs", {}, call_index=1
        )
        result = await execute_tool(
            _ctx(session, fake_clock, settings, user, event_id),
            "set_notif_prefs",
            {"morning_brief_time": "09:00", "briefs_enabled": True, "quiet_hours": "22:00-06:00"},
            call_index=2,
        )
        await session.commit()
    assert result.status == "ok", result.message
    assert result.data["morning_brief_time"] == "09:00"
    assert result.data["quiet_hours"] == {"start": "22:00", "end": "06:00"}
    assert result.data["brief_triggers_created"] == 3
    assert result.data["brief_triggers_superseded"] == 3
