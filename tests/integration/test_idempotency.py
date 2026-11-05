"""幂等与 event_log 只追加约束（需要 Postgres）。

阶段 1 修订：写工具幂等键由代码从入站事件派生
（inbound_event_id + 工具名 + 调用序号），同一入站事件重放只产生一个任务。
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.models import User, WorkItem
from app.engine.events import append_event
from app.engine.users import get_or_create_user
from app.tools.base import ToolContext
from app.tools.registry import execute_tool


@pytest.fixture
async def user(db, fake_clock):
    async with db() as session:
        u, _ = await get_or_create_user(
            session,
            channel="console",
            external_id="u1",
            tenant_id=None,
            display_name="u1",
            default_timezone="Asia/Shanghai",
            clock=fake_clock,
        )
        await session.commit()
        return u.id


@pytest.fixture
async def inbound_event(db, user, fake_clock):
    """工具派生幂等键的来源：一条入站 event_log 记录。"""
    async with db() as session:
        row, _ = await append_event(
            session, user_id=user, channel="console", direction="inbound", type="message",
            payload={"text": "建个任务"}, trace_id="t1", clock=fake_clock,
            idempotency_key="evt-tool-1",
        )
        await session.commit()
        return row.id


def _ctx(session, user_row, clock, settings, event_id: uuid.UUID) -> ToolContext:
    return ToolContext(
        session=session, clock=clock, settings=settings, user=user_row,
        trace_id="t", channel="console", source_event_id=event_id,
    )


async def test_duplicate_idempotency_key_returns_existing(db, user, fake_clock):
    async with db() as session:
        first, created1 = await append_event(
            session, user_id=user, channel="console", direction="inbound", type="message",
            payload={"text": "hi"}, trace_id="t1", clock=fake_clock, idempotency_key="evt-1",
        )
        await session.commit()
    async with db() as session:
        second, created2 = await append_event(
            session, user_id=user, channel="console", direction="inbound", type="message",
            payload={"text": "hi"}, trace_id="t2", clock=fake_clock, idempotency_key="evt-1",
        )
        await session.commit()
    assert created1 and not created2
    assert second.id == first.id


async def test_event_log_forbids_update_and_delete(db, user, fake_clock):
    async with db() as session:
        event, _ = await append_event(
            session, user_id=user, channel="console", direction="inbound", type="message",
            payload={}, trace_id="t1", clock=fake_clock,
        )
        await session.commit()
        event_id = event.id

    async with db() as session:
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE event_log SET payload = '{}' WHERE id = :id"), {"id": event_id}
            )
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM event_log WHERE id = :id"), {"id": event_id})
        await session.rollback()


async def test_user_onboarding_is_idempotent(db, fake_clock):
    async with db() as session:
        u1, new1 = await get_or_create_user(
            session, channel="feishu", external_id="open-1", tenant_id="t",
            display_name="x", default_timezone="Asia/Shanghai", clock=fake_clock,
        )
        await session.commit()
    async with db() as session:
        u2, new2 = await get_or_create_user(
            session, channel="feishu", external_id="open-1", tenant_id="t",
            display_name="x", default_timezone="Asia/Shanghai", clock=fake_clock,
        )
        await session.commit()
    assert u1.id == u2.id
    assert new1 and not new2


async def test_write_tool_requires_source_event(db, user, fake_clock, settings):
    async with db() as session:
        u = (await session.execute(select(User).where(User.id == user))).scalar_one()
        ctx = ToolContext(
            session=session, clock=fake_clock, settings=settings, user=u,
            trace_id="t", channel="console", source_event_id=None,
        )
        result = await execute_tool(ctx, "create_task", {"title": "无来源"}, call_index=1)
        assert result.status == "error"
        assert "入站事件" in result.message


async def test_same_inbound_event_replay_creates_one_task(
    db, user, inbound_event, fake_clock, settings
):
    """同一入站事件重放两次（同序号）：只产生一个任务，第二次返回上次结果。"""
    args = {"title": "交报告"}
    results = []
    for _ in range(2):
        async with db() as session:
            u = (await session.execute(select(User).where(User.id == user))).scalar_one()
            result = await execute_tool(
                _ctx(session, u, fake_clock, settings, inbound_event),
                "create_task", args, call_index=1,
            )
            await session.commit()
            results.append(result)

    assert all(r.status == "ok" for r in results)
    assert results[0].data["task_id"] == results[1].data["task_id"]
    async with db() as session:
        items = (
            await session.execute(select(WorkItem).where(WorkItem.user_id == user))
        ).scalars().all()
        assert len(items) == 1


async def test_same_inbound_event_different_call_index_creates_two(
    db, user, inbound_event, fake_clock, settings
):
    """同一条消息里两次 create_task（不同调用序号）：各自执行。"""
    for index, title in ((1, "任务 A"), (2, "任务 B")):
        async with db() as session:
            u = (await session.execute(select(User).where(User.id == user))).scalar_one()
            result = await execute_tool(
                _ctx(session, u, fake_clock, settings, inbound_event),
                "create_task", {"title": title}, call_index=index,
            )
            await session.commit()
            assert result.status == "ok"

    async with db() as session:
        items = (
            await session.execute(select(WorkItem).where(WorkItem.user_id == user))
        ).scalars().all()
        assert sorted(i.title for i in items) == ["任务 A", "任务 B"]


async def test_complete_task_repeated_calls_are_idempotent(
    db, user, inbound_event, fake_clock, settings
):
    async with db() as session:
        item = WorkItem(
            user_id=user, type="item", status="active", title="写报告",
            created_at=fake_clock.now(), updated_at=fake_clock.now(),
        )
        session.add(item)
        await session.commit()
        item_id = item.id

    # 同一入站事件同序号重复执行：第一次标记完成，第二次重放上次结果
    for _ in range(2):
        async with db() as session:
            u = (await session.execute(select(User).where(User.id == user))).scalar_one()
            result = await execute_tool(
                _ctx(session, u, fake_clock, settings, inbound_event),
                "complete_task", {"task_id": str(item_id)}, call_index=1,
            )
            await session.commit()
            assert result.status == "ok"
            assert result.data["status"] == "done"

    async with db() as session:
        items = (
            await session.execute(select(WorkItem).where(WorkItem.user_id == user))
        ).scalars().all()
        assert len(items) == 1
        assert items[0].status == "done"
