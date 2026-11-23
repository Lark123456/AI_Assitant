"""U2-A4：手机渠道日常工具端到端（任务/提醒/笔记/改期）。"""

import datetime as dt
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.api.routes.mobile import router as mobile_today_router
from app.core.clock import UTC, FakeClock
from app.core.config import Settings
from app.db.models import (
    ChannelIdentity,
    EventLog,
    PlannedBlock,
    TriggerInstance,
    User,
    WorkItem,
)
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, ToolCall
from app.tools.base import ToolContext
from app.tools.registry import execute_tool
from tests.conftest import TEST_ALIASES, FakeProvider


async def _seed_user(
    db, clock: FakeClock, external_id: str = "ou_tools"
) -> tuple[User, uuid.UUID]:
    """用户 + 一条入站事件（写工具幂等键的来源）。"""
    async with db() as session:
        user = User(
            display_name="工具用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        session.add(user)
        await session.flush()
        session.add(
            ChannelIdentity(user_id=user.id, channel="feishu", external_id=external_id)
        )
        event = EventLog(
            user_id=user.id,
            channel="mobile",
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


def _ctx(
    session,
    clock: FakeClock,
    settings: Settings,
    user: User,
    event_id: uuid.UUID,
    channel: str = "mobile",
) -> ToolContext:
    return ToolContext(
        session=session,
        clock=clock,
        settings=settings,
        user=user,
        trace_id="tool-test",
        channel=channel,
        source_event_id=event_id,
    )


async def _run(
    db,
    clock: FakeClock,
    settings: Settings,
    user: User,
    event_id: uuid.UUID,
    name: str,
    args: dict,
    *,
    call_index: int = 1,
    channel: str = "mobile",
):
    async with db() as session:
        result = await execute_tool(
            _ctx(session, clock, settings, user, event_id, channel),
            name,
            args,
            call_index=call_index,
        )
        await session.commit()
        return result


async def test_update_task_changes_fields_in_place(db, fake_clock, settings):
    user, event_id = await _seed_user(db, fake_clock)
    created = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "create_task",
        {"title": "写周报"},
        call_index=1,
    )
    assert created.status == "ok", created.message
    task_id = str(created.data["task_id"])

    updated = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "update_task",
        {"task_id": task_id, "title": "写季度总结", "description": "下周一前"},
        call_index=2,
    )
    assert updated.status == "ok", updated.message
    assert updated.data["task_id"] == task_id

    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
    assert len(items) == 1
    assert items[0].title == "写季度总结"
    assert items[0].description == "下周一前"
    assert items[0].status == "active"
    assert items[0].rev == 2

    # 同一入站事件重放同一调用序号：返回原结果，不再次累加 rev
    replay = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "update_task",
        {"task_id": task_id, "title": "写季度总结", "description": "下周一前"},
        call_index=2,
    )
    assert replay.status == "ok"
    async with db() as session:
        row = await session.get(WorkItem, uuid.UUID(task_id))
    assert row is not None and row.rev == 2


async def test_update_task_rejects_other_users_task(db, fake_clock, settings):
    owner, owner_event = await _seed_user(db, fake_clock, external_id="ou_owner")
    created = await _run(
        db,
        fake_clock,
        settings,
        owner,
        owner_event,
        "create_task",
        {"title": "别人的任务"},
        call_index=1,
    )
    other, other_event = await _seed_user(db, fake_clock, external_id="ou_other")

    result = await _run(
        db,
        fake_clock,
        settings,
        other,
        other_event,
        "update_task",
        {"task_id": str(created.data["task_id"]), "title": "越权修改"},
        call_index=1,
    )

    assert result.status == "error"
    assert "任务不存在" in result.message
    async with db() as session:
        row = await session.get(WorkItem, uuid.UUID(str(created.data["task_id"])))
    assert row is not None and row.title == "别人的任务"


async def test_update_reminder_updates_same_trigger_in_place(db, fake_clock, settings):
    user, event_id = await _seed_user(db, fake_clock)
    created = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "set_reminder",
        {"fire_at": "2026-01-01T15:00:00+08:00", "note": "交报告"},
        call_index=1,
    )
    assert created.status == "ok", created.message
    trigger_id = str(created.data["trigger_id"])

    updated = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "update_reminder",
        {
            "trigger_id": trigger_id,
            "fire_at": "2026-01-01T16:30:00+08:00",
            "note": "改为 16:30 交报告",
        },
        call_index=2,
    )
    assert updated.status == "ok", updated.message
    assert updated.data["trigger_id"] == trigger_id

    async with db() as session:
        triggers = (
            await session.execute(
                select(TriggerInstance).where(TriggerInstance.kind == "reminder")
            )
        ).scalars().all()
        audits = (
            await session.execute(select(EventLog).where(EventLog.type == "trigger"))
        ).scalars().all()

    # 直接更新原 trigger，不取消重建
    assert len(triggers) == 1
    trigger = triggers[0]
    assert str(trigger.id) == trigger_id
    assert trigger.fire_at == dt.datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    assert trigger.expires_at == trigger.fire_at + dt.timedelta(
        hours=settings.reminder_late_window_hours
    )
    assert trigger.payload["note"] == "改为 16:30 交报告"
    assert trigger.status == "pending"

    updated_audits = [row for row in audits if row.payload.get("status") == "updated"]
    assert len(updated_audits) == 1
    assert updated_audits[0].channel == "mobile"
    assert updated_audits[0].payload["reason"] == "user_updated"


async def test_update_reminder_rejects_claimed_or_foreign_trigger(db, fake_clock, settings):
    user, event_id = await _seed_user(db, fake_clock)
    created = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "set_reminder",
        {"fire_at": "2026-01-01T15:00:00+08:00", "note": "交报告"},
        call_index=1,
    )
    trigger_id = str(created.data["trigger_id"])
    async with db() as session:
        trigger = await session.get(TriggerInstance, uuid.UUID(trigger_id))
        assert trigger is not None
        trigger.status = "claimed"
        await session.commit()

    rejected = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "update_reminder",
        {"trigger_id": trigger_id, "note": "不应该改成功"},
        call_index=2,
    )
    assert rejected.status == "error"
    assert "无法修改" in rejected.message

    other, other_event = await _seed_user(db, fake_clock, external_id="ou_reminder_other")
    foreign = await _run(
        db,
        fake_clock,
        settings,
        other,
        other_event,
        "update_reminder",
        {"trigger_id": trigger_id, "note": "越权修改"},
        call_index=1,
    )
    assert foreign.status == "error"
    assert "提醒不存在" in foreign.message

    async with db() as session:
        trigger = await session.get(TriggerInstance, uuid.UUID(trigger_id))
    assert trigger is not None
    assert trigger.status == "claimed"
    assert trigger.payload["note"] == "交报告"


async def test_list_notes_returns_recent_notes_per_user(db, fake_clock, settings):
    user, event_id = await _seed_user(db, fake_clock)
    await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "capture_note",
        {"text": "第一条笔记"},
        call_index=1,
    )
    fake_clock.advance(60)
    await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "capture_note",
        {"text": "第二条笔记"},
        call_index=2,
    )
    other, other_event = await _seed_user(db, fake_clock, external_id="ou_notes_other")
    await _run(
        db,
        fake_clock,
        settings,
        other,
        other_event,
        "capture_note",
        {"text": "别人的笔记"},
        call_index=1,
    )

    listed = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "list_notes",
        {"limit": 10},
        call_index=3,
    )
    assert listed.status == "ok", listed.message
    assert [note["text"] for note in listed.data["notes"]] == ["第二条笔记", "第一条笔记"]

    limited = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "list_notes",
        {"limit": 1},
        call_index=4,
    )
    assert [note["text"] for note in limited.data["notes"]] == ["第二条笔记"]

    invalid = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "list_notes",
        {"limit": 101},
        call_index=5,
    )
    assert invalid.status == "error"


class _BlockSeed:
    def __init__(
        self,
        user: User,
        event_id: uuid.UUID,
        block: PlannedBlock,
        done_block: PlannedBlock,
        today_block: PlannedBlock,
    ) -> None:
        self.user = user
        self.event_id = event_id
        self.block = block
        self.done_block = done_block
        self.today_block = today_block


async def _seed_blocks(db, clock: FakeClock) -> _BlockSeed:
    user, event_id = await _seed_user(db, clock, external_id="ou_blocks")
    async with db() as session:
        item = WorkItem(
            user_id=user.id, type="item", status="active", title="写报告"
        )
        done_item = WorkItem(
            user_id=user.id, type="item", status="active", title="方案评审"
        )
        session.add_all([item, done_item])
        await session.flush()
        block = PlannedBlock(
            user_id=user.id,
            work_item_id=item.id,
            starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),  # 09:00 +08
            ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
            status="planned",
            assigned_by="friday",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        done_block = PlannedBlock(
            user_id=user.id,
            work_item_id=done_item.id,
            starts_at=dt.datetime(2026, 1, 1, 2, 30, tzinfo=UTC),
            ends_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
            status="done",
            assigned_by="friday",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        today_block = PlannedBlock(
            user_id=user.id,
            work_item_id=item.id,
            starts_at=dt.datetime(2026, 1, 1, 4, 0, tzinfo=UTC),  # 12:00 +08
            ends_at=dt.datetime(2026, 1, 1, 5, 0, tzinfo=UTC),
            status="planned",
            assigned_by="friday",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add_all([block, done_block, today_block])
        await session.commit()
        return _BlockSeed(user, event_id, block, done_block, today_block)


async def test_reschedule_block_uses_today_rules(db, fake_clock, settings):
    seeded = await _seed_blocks(db, fake_clock)

    cross_day = await _run(
        db,
        fake_clock,
        settings,
        seeded.user,
        seeded.event_id,
        "reschedule_block",
        {
            "block_id": str(seeded.block.id),
            "starts_at": "2025-12-31T09:00:00+08:00",
            "ends_at": "2025-12-31T09:30:00+08:00",
        },
        call_index=1,
    )
    assert cross_day.status == "error"
    assert "跨天" in cross_day.message

    too_short = await _run(
        db,
        fake_clock,
        settings,
        seeded.user,
        seeded.event_id,
        "reschedule_block",
        {
            "block_id": str(seeded.block.id),
            "starts_at": "2026-01-01T09:00:00+08:00",
            "ends_at": "2026-01-01T09:04:00+08:00",
        },
        call_index=2,
    )
    assert too_short.status == "error"
    assert "5 分钟" in too_short.message

    terminal = await _run(
        db,
        fake_clock,
        settings,
        seeded.user,
        seeded.event_id,
        "reschedule_block",
        {
            "block_id": str(seeded.done_block.id),
            "starts_at": "2026-01-01T10:30:00+08:00",
            "ends_at": "2026-01-01T11:30:00+08:00",
        },
        call_index=3,
    )
    assert terminal.status == "error"
    assert "未结束" in terminal.message

    # 与 Today 一致：允许把当天已逾期的块修正到过去时刻
    past = await _run(
        db,
        fake_clock,
        settings,
        seeded.user,
        seeded.event_id,
        "reschedule_block",
        {
            "block_id": str(seeded.block.id),
            "starts_at": "2026-01-01T07:30:00+08:00",
            "ends_at": "2026-01-01T07:45:00+08:00",
        },
        call_index=4,
    )
    assert past.status == "ok", past.message
    async with db() as session:
        block = await session.get(PlannedBlock, seeded.block.id)
    assert block is not None
    assert block.starts_at == dt.datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    assert block.rev == 2


async def test_reschedule_tool_and_today_api_agree(db, fake_clock, settings):
    """同一跨天/过短/终态输入，Chat 工具与 Today 接口得到一致的拒绝。"""
    seeded = await _seed_blocks(db, fake_clock)
    app = FastAPI()
    app.include_router(mobile_today_router)
    app.state.sessionmaker = db
    app.state.clock = fake_clock
    app.state.settings = settings
    headers = {"X-Butler-User": str(seeded.user.id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        cross_day = await client.post(
            f"/api/mobile/today/items/{seeded.today_block.id}/reschedule",
            json={"startsAt": "2025-12-31T23:30:00+08:00"},
            headers={**headers, "Idempotency-Key": "a4-cross-day"},
        )
        too_short = await client.post(
            f"/api/mobile/today/items/{seeded.today_block.id}/reschedule",
            json={"startsAt": "2026-01-01T12:56:00+08:00"},
            headers={**headers, "Idempotency-Key": "a4-too-short"},
        )
        terminal = await client.post(
            f"/api/mobile/today/items/{seeded.done_block.id}/reschedule",
            json={"startsAt": "2026-01-01T10:30:00+08:00"},
            headers={**headers, "Idempotency-Key": "a4-terminal"},
        )
        past = await client.post(
            f"/api/mobile/today/items/{seeded.today_block.id}/reschedule",
            json={"startsAt": "2026-01-01T07:30:00+08:00"},
            headers={**headers, "Idempotency-Key": "a4-past"},
        )

    assert cross_day.status_code == 400
    assert "跨天" in cross_day.json()["detail"]
    assert too_short.status_code == 400
    assert "5 分钟" in too_short.json()["detail"]
    assert terminal.status_code == 400
    assert "未结束" in terminal.json()["detail"]
    assert past.status_code == 200

    tool_cross_day = await _run(
        db,
        fake_clock,
        settings,
        seeded.user,
        seeded.event_id,
        "reschedule_block",
        {
            "block_id": str(seeded.block.id),
            "starts_at": "2025-12-31T09:00:00+08:00",
            "ends_at": "2025-12-31T09:30:00+08:00",
        },
        call_index=1,
    )
    assert tool_cross_day.status == "error"
    assert "跨天" in tool_cross_day.message


async def test_mobile_chat_tool_call_creates_task_with_mobile_events(
    db, fake_clock, settings
):
    """手机消息经 Friday 调用工具：业务数据落库，工具事件归属手机渠道与入站事件。"""
    user, _ = await _seed_user(db, fake_clock)

    def responder(messages: list[dict]) -> LLMResult:
        if any(message.get("role") == "tool" for message in messages):
            return LLMResult(content="记好了")
        return LLMResult(
            content="",
            tool_calls=[
                ToolCall(id="c1", name="create_task", arguments={"title": "写周报"})
            ],
        )

    provider = FakeProvider(responder)
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": provider},
        sessionmaker=db,
        clock=fake_clock,
        daily_limit=0,
    )
    pipeline = InboundPipeline(
        sessionmaker=db,
        clock=fake_clock,
        settings=settings,
        gateway=gateway,
        adapters={"mobile": MobileAdapter(make_identity_resolver(db, "mobile"))},
    )
    ingested = await pipeline.ingest_for_user(
        InboundEvent(
            channel="mobile",
            external_user_id=str(user.id),
            kind="message",
            text="记一下：写周报",
            idempotency_key=f"mobile-chat:{user.id}:c1",
        ),
        user,
        client_message_id="c1",
    )
    await pipeline.process(ingested)

    async with db() as session:
        items = (await session.execute(select(WorkItem))).scalars().all()
        tool_events = (
            await session.execute(select(EventLog).where(EventLog.direction == "tool"))
        ).scalars().all()
        outbound = (
            await session.execute(
                select(EventLog).where(EventLog.direction == "outbound")
            )
        ).scalars().all()

    assert len(items) == 1
    assert items[0].title == "写周报"
    assert items[0].user_id == user.id

    calls = [event for event in tool_events if event.type == "tool_call"]
    results = [event for event in tool_events if event.type == "tool_result"]
    assert len(calls) == 1 and len(results) == 1
    assert calls[0].payload["tool"] == "create_task"
    assert calls[0].channel == "mobile"
    assert calls[0].idempotency_key == (
        f"tool-call:{ingested.event_id}:create_task:1"
    )
    assert results[0].channel == "mobile"

    assert len(outbound) == 1
    assert outbound[0].payload["delivery"] == "persisted"


async def test_mobile_and_console_tools_share_user_data(db, fake_clock, settings):
    """同一 user 在手机与 Console 渠道创建/查询的是同一份业务数据。"""
    user, event_id = await _seed_user(db, fake_clock)
    await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "create_task",
        {"title": "手机建的任务"},
        call_index=1,
        channel="mobile",
    )
    console_list = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "list_tasks",
        {},
        call_index=2,
        channel="console",
    )
    console_titles = sorted(task["title"] for task in console_list.data["tasks"])
    assert console_titles == ["手机建的任务"]

    await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "create_task",
        {"title": "飞书建的任务"},
        call_index=3,
        channel="console",
    )
    mobile_list = await _run(
        db,
        fake_clock,
        settings,
        user,
        event_id,
        "list_tasks",
        {},
        call_index=4,
        channel="mobile",
    )
    mobile_titles = sorted(task["title"] for task in mobile_list.data["tasks"])
    assert mobile_titles == ["手机建的任务", "飞书建的任务"]
