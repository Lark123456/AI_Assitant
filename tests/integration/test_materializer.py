"""物化器：幂等、设置变更重算、夏令时换算、块变更替换。"""

import datetime as dt

from sqlalchemy import select

from app.core.clock import UTC, FakeClock
from app.db.models import NotifPrefs, PlannedBlock, TriggerInstance, User, WorkItem
from app.engine.materializer import ensure_block_triggers, run_materializer


async def _create_user(db, tz: str = "Asia/Shanghai") -> User:
    async with db() as session:
        user = User(display_name="tester", timezone=tz, day_start=dt.time(4, 0), rev=1)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _brief_fire_ats(db, user_id: object) -> list[dt.datetime]:
    async with db() as session:
        rows = (
            await session.execute(
                select(TriggerInstance.fire_at)
                .where(
                    TriggerInstance.user_id == user_id,
                    TriggerInstance.kind.in_(("brief_morning", "brief_evening")),
                )
                .order_by(TriggerInstance.fire_at)
            )
        ).scalars()
        return list(rows.all())


async def test_brief_materialization_is_idempotent(db, fake_clock, settings) -> None:
    user = await _create_user(db)
    first = await run_materializer(db, clock=fake_clock, settings=settings)
    # 今天 + 明天 + 后天，晨/晚两条
    assert first.brief_created == 6
    second = await run_materializer(db, clock=fake_clock, settings=settings)
    assert second.brief_created == 0
    assert second.brief_superseded == 0
    assert len(await _brief_fire_ats(db, user.id)) == 6


async def test_brief_time_change_supersedes_and_rebuilds(db, fake_clock, settings) -> None:
    user = await _create_user(db)
    await run_materializer(db, clock=fake_clock, settings=settings)
    async with db() as session:
        prefs = await session.get(NotifPrefs, user.id)
        assert prefs is not None
        prefs.evening_brief_time = dt.time(22, 0)
        await session.commit()
    stats = await run_materializer(db, clock=fake_clock, settings=settings)
    assert stats.brief_superseded == 3
    assert stats.brief_created == 3
    # 晚间简报的新时刻：22:00+08 == 14:00Z
    ats = await _brief_fire_ats(db, user.id)
    assert sum(1 for at in ats if at.hour == 14) == 3


async def test_briefs_disabled_drops_all_pending(db, fake_clock, settings) -> None:
    user = await _create_user(db)
    await run_materializer(db, clock=fake_clock, settings=settings)
    async with db() as session:
        prefs = await session.get(NotifPrefs, user.id)
        assert prefs is not None
        prefs.briefs_enabled = False
        await session.commit()
    stats = await run_materializer(db, clock=fake_clock, settings=settings)
    assert stats.brief_superseded == 6
    assert stats.brief_created == 0
    assert await _brief_fire_ats(db, user.id) == []


async def test_block_triggers_and_reschedule(db, fake_clock, settings) -> None:
    user = await _create_user(db)
    async with db() as session:
        item = WorkItem(user_id=user.id, type="item", status="active", title="写报告")
        session.add(item)
        await session.flush()
        block = PlannedBlock(
            user_id=user.id,
            work_item_id=item.id,
            starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
            status="planned",
            assigned_by="friday",
            rev=1,
        )
        session.add(block)
        await session.flush()
        created, superseded = await ensure_block_triggers(
            session, block=block, user=user, title="写报告", settings=settings, clock=fake_clock
        )
        await session.commit()
        block_id = block.id
    assert (created, superseded) == (2, 0)

    async with db() as session:
        block = await session.get(PlannedBlock, block_id)
        assert block is not None
        block.starts_at = dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
        block.ends_at = dt.datetime(2026, 1, 1, 4, 0, tzinfo=UTC)
        block.rev = 2
        created, superseded = await ensure_block_triggers(
            session, block=block, user=user, title="写报告", settings=settings, clock=fake_clock
        )
        await session.commit()
    assert (created, superseded) == (2, 2)


async def test_block_becomes_done_cancels_pending(db, fake_clock, settings) -> None:
    user = await _create_user(db)
    async with db() as session:
        item = WorkItem(user_id=user.id, type="item", status="active", title="写报告")
        session.add(item)
        await session.flush()
        block = PlannedBlock(
            user_id=user.id,
            work_item_id=item.id,
            starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
            status="planned",
            assigned_by="friday",
            rev=1,
        )
        session.add(block)
        await session.flush()
        await ensure_block_triggers(
            session, block=block, user=user, title="写报告", settings=settings, clock=fake_clock
        )
        await session.commit()
        block_id = block.id

    async with db() as session:
        block = await session.get(PlannedBlock, block_id)
        assert block is not None
        block.status = "done"
        block.rev = 2
        created, superseded = await ensure_block_triggers(
            session, block=block, user=user, title="写报告", settings=settings, clock=fake_clock
        )
        await session.commit()
    assert (created, superseded) == (0, 2)


async def test_brief_fire_at_across_dst(db, settings) -> None:
    # America/Los_Angeles：3-08 02:00 拨快 → 3-07 的 08:30 是 PST，3-08 的是 PDT
    user = await _create_user(db, tz="America/Los_Angeles")
    clock = FakeClock(dt.datetime(2026, 3, 7, 12, 0, tzinfo=UTC))
    await run_materializer(db, clock=clock, settings=settings)
    ats = await _brief_fire_ats(db, user.id)
    assert dt.datetime(2026, 3, 7, 16, 30, tzinfo=UTC) in ats
    assert dt.datetime(2026, 3, 8, 15, 30, tzinfo=UTC) in ats
