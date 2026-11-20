"""U2 移动端 Today 写操作：完成/跳过/撤销/改期/排期/复盘与幂等。"""

import asyncio
import datetime as dt

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select

from app.api.routes.mobile import router
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


def _app(db, clock: FakeClock, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    return app


class _Seed:
    def __init__(self, user: User, morning: PlannedBlock, afternoon: PlannedBlock) -> None:
        self.user = user
        self.morning = morning
        self.afternoon = afternoon


async def _seed(db, clock: FakeClock) -> _Seed:
    async with db() as session:
        user = User(display_name="测试用户", timezone="Asia/Shanghai", day_start=dt.time(4, 0))
        session.add(user)
        await session.flush()

        session.add(
            ChannelIdentity(
                user_id=user.id,
                channel="feishu",
                external_id="ou_test",
                tenant_id="tenant-1",
            )
        )

        morning_item = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="专注写作",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        afternoon_item = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="方案评审",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        unscheduled_item = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="整理笔记",
            description="还没安排时间",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add_all([morning_item, afternoon_item, unscheduled_item])
        await session.flush()

        morning = PlannedBlock(
            user_id=user.id,
            work_item_id=morning_item.id,
            starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
            status="planned",
            assigned_by="friday",
            compressible=True,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        afternoon = PlannedBlock(
            user_id=user.id,
            work_item_id=afternoon_item.id,
            starts_at=dt.datetime(2026, 1, 1, 4, 0, tzinfo=UTC),
            ends_at=dt.datetime(2026, 1, 1, 5, 0, tzinfo=UTC),
            status="skipped",
            assigned_by="friday",
            compressible=False,
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add_all([morning, afternoon])

        session.add(
            TriggerInstance(
                user_id=user.id,
                kind="reminder",
                key=f"reminder:{user.id}:test",
                fire_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
                tz=user.timezone,
                payload={"note": "喝水"},
                status="pending",
                created_at=clock.now(),
            )
        )
        await session.commit()
        return _Seed(user=user, morning=morning, afternoon=afternoon)


def _headers(user: User, key: str = "k1") -> dict[str, str]:
    return {"X-Butler-User": str(user.id), "Idempotency-Key": key}


async def test_complete_block_is_idempotent(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/complete",
            headers=_headers(seeded.user, "complete-1"),
        )
        replay = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/complete",
            headers=_headers(seeded.user, "complete-1"),
        )

    assert first.status_code == 200
    assert first.json()["status"] == "done"
    assert replay.status_code == 200
    assert replay.json() == first.json()

    async with db() as session:
        block = await session.get(PlannedBlock, seeded.morning.id)
        assert block is not None
        assert block.status == "done"
        assert block.actual_ended_at == fake_clock.now()
        count = (
            await session.execute(
                select(func.count())
                .select_from(EventLog)
                .where(
                    EventLog.idempotency_key
                    == f"mobile:{seeded.user.id}:complete:complete-1"
                )
            )
        ).scalar_one()
        assert count == 1


async def test_skip_and_restore_block(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        skipped = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/skip",
            headers=_headers(seeded.user, "skip-1"),
        )
        restored = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/restore",
            headers=_headers(seeded.user, "restore-1"),
        )

    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert restored.status_code == 200
    assert restored.json()["status"] == "planned"

    async with db() as session:
        trigger = (
            await session.execute(
                select(TriggerInstance).where(TriggerInstance.kind == "block_start")
            )
        ).scalars().first()
        assert trigger is not None
        assert trigger.status == "pending"


async def test_reschedule_block_validates_status_duration_and_day(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        moved = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/reschedule",
            json={"startsAt": "2026-01-01T09:30:00+08:00"},
            headers=_headers(seeded.user, "reschedule-1"),
        )
        invalid = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/reschedule",
            json={"startsAt": "2026-01-01T10:30:00+08:00"},
            headers=_headers(seeded.user, "reschedule-2"),
        )
        task_invalid = await client.post(
            f"/api/mobile/today/items/{task.id}/reschedule",
            json={"startsAt": "2026-01-01T10:30:00+08:00"},
            headers=_headers(seeded.user, "reschedule-3"),
        )
        short = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/reschedule",
            json={"startsAt": "2026-01-01T09:56:00+08:00"},
            headers=_headers(seeded.user, "reschedule-short"),
        )
        five_minutes = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/reschedule",
            json={"startsAt": "2026-01-01T09:55:00+08:00"},
            headers=_headers(seeded.user, "reschedule-five"),
        )
        cross_day = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/reschedule",
            json={"startsAt": "2025-12-31T09:00:00+08:00"},
            headers=_headers(seeded.user, "reschedule-cross-day"),
        )
        terminal = await client.post(
            f"/api/mobile/today/items/{seeded.afternoon.id}/reschedule",
            json={"startsAt": "2026-01-01T12:30:00+08:00"},
            headers=_headers(seeded.user, "reschedule-terminal"),
        )

    assert moved.status_code == 200
    assert moved.json()["start"] == "2026-01-01T09:30:00+08:00"
    assert moved.json()["end"] == "2026-01-01T10:00:00+08:00"
    assert moved.json()["durationMin"] == 30
    assert invalid.status_code == 400
    assert task_invalid.status_code == 400
    assert short.status_code == 400
    assert five_minutes.status_code == 200
    assert five_minutes.json()["durationMin"] == 5
    assert cross_day.status_code == 400
    assert terminal.status_code == 400


async def test_complete_and_restore_unscheduled_task(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        completed = await client.post(
            f"/api/mobile/today/items/{task.id}/complete",
            headers=_headers(seeded.user, "task-complete"),
        )
        after_complete = await client.get(
            "/api/mobile/today?date=2026-01-01",
            headers={"X-Butler-User": str(seeded.user.id)},
        )
        restored = await client.post(
            f"/api/mobile/today/items/{task.id}/restore",
            headers=_headers(seeded.user, "task-restore"),
        )
        after_restore = await client.get(
            "/api/mobile/today?date=2026-01-01",
            headers={"X-Butler-User": str(seeded.user.id)},
        )

    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert [item["title"] for item in after_complete.json()["unscheduled"]] == []
    assert restored.status_code == 200
    assert restored.json()["status"] == "planned"
    assert [item["title"] for item in after_restore.json()["unscheduled"]] == ["整理笔记"]


async def test_schedule_task_creates_single_block(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            f"/api/mobile/today/tasks/{task.id}/schedule",
            json={"startsAt": "2026-01-01T18:00:00+08:00", "durationMin": 45},
            headers=_headers(seeded.user, "schedule-1"),
        )
        replay = await client.post(
            f"/api/mobile/today/tasks/{task.id}/schedule",
            json={"startsAt": "2026-01-01T18:00:00+08:00", "durationMin": 45},
            headers=_headers(seeded.user, "schedule-1"),
        )
        day = await client.get(
            "/api/mobile/today?date=2026-01-01",
            headers={"X-Butler-User": str(seeded.user.id)},
        )

    assert first.status_code == 200
    assert first.json()["kind"] == "block"
    assert first.json()["start"] == "2026-01-01T18:00:00+08:00"
    assert first.json()["end"] == "2026-01-01T18:45:00+08:00"
    assert replay.json() == first.json()
    assert [item["title"] for item in day.json()["unscheduled"]] == []
    assert "整理笔记" in [item["title"] for item in day.json()["items"]]

    async with db() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(PlannedBlock)
                .where(PlannedBlock.work_item_id == task.id)
            )
        ).scalar_one()
        assert count == 1


async def test_schedule_task_allows_multiple_blocks(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    path = f"/api/mobile/today/tasks/{task.id}/schedule"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            path,
            json={"startsAt": "2026-01-01T18:00:00+08:00"},
            headers=_headers(seeded.user, "multi-1"),
        )
        second = await client.post(
            path,
            json={"startsAt": "2026-01-01T20:00:00+08:00"},
            headers=_headers(seeded.user, "multi-2"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]

    async with db() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(PlannedBlock)
                .where(PlannedBlock.work_item_id == task.id)
            )
        ).scalar_one()
        assert count == 2


async def test_schedule_task_rejects_past_start(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        past = await client.post(
            f"/api/mobile/today/tasks/{task.id}/schedule",
            json={"startsAt": "2026-01-01T07:00:00+08:00"},
            headers=_headers(seeded.user, "schedule-past"),
        )
        now = await client.post(
            f"/api/mobile/today/tasks/{task.id}/schedule",
            json={"startsAt": "2026-01-01T08:00:00+08:00"},
            headers=_headers(seeded.user, "schedule-now"),
        )

    assert past.status_code == 400
    assert now.status_code == 400


async def test_schedule_task_same_key_concurrent_creates_one_block(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        task = (
            await session.execute(
                select(WorkItem).where(
                    WorkItem.user_id == seeded.user.id, WorkItem.title == "整理笔记"
                )
            )
        ).scalar_one()

    path = f"/api/mobile/today/tasks/{task.id}/schedule"
    body = {"startsAt": "2026-01-01T18:00:00+08:00", "durationMin": 45}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first, second = await asyncio.gather(
            client.post(path, json=body, headers=_headers(seeded.user, "concurrent-1")),
            client.post(path, json=body, headers=_headers(seeded.user, "concurrent-1")),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    async with db() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(PlannedBlock)
                .where(PlannedBlock.work_item_id == task.id)
            )
        ).scalar_one()
        assert count == 1


async def test_reminder_rejects_failed_and_cancelled_states(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    async with db() as session:
        failed = TriggerInstance(
            user_id=seeded.user.id,
            kind="reminder",
            key=f"reminder:{seeded.user.id}:failed",
            fire_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
            tz=seeded.user.timezone,
            payload={"note": "失败提醒"},
            status="failed",
            created_at=fake_clock.now(),
        )
        cancelled = TriggerInstance(
            user_id=seeded.user.id,
            kind="reminder",
            key=f"reminder:{seeded.user.id}:cancelled",
            fire_at=dt.datetime(2026, 1, 1, 4, 30, tzinfo=UTC),
            tz=seeded.user.timezone,
            payload={"note": "已取消提醒"},
            status="dropped",
            created_at=fake_clock.now(),
        )
        session.add_all([failed, cancelled])
        await session.commit()

    app = _app(db, fake_clock, settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for trigger, label in ((failed, "failed"), (cancelled, "cancelled")):
            for action in ("complete", "skip", "restore"):
                response = await client.post(
                    f"/api/mobile/today/items/{trigger.id}/{action}",
                    headers=_headers(seeded.user, f"{label}-{action}"),
                )
                assert response.status_code == 409, (label, action, response.text)


async def test_reminder_complete_cancels_trigger_and_restore_reopens(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with db() as session:
        trigger = (
            await session.execute(
                select(TriggerInstance).where(
                    TriggerInstance.user_id == seeded.user.id,
                    TriggerInstance.kind == "reminder",
                )
            )
        ).scalar_one()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        completed = await client.post(
            f"/api/mobile/today/items/{trigger.id}/complete",
            headers=_headers(seeded.user, "reminder-complete"),
        )
        day = await client.get(
            "/api/mobile/today?date=2026-01-01",
            headers={"X-Butler-User": str(seeded.user.id)},
        )
        restored = await client.post(
            f"/api/mobile/today/items/{trigger.id}/restore",
            headers=_headers(seeded.user, "reminder-restore"),
        )

    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    reminder = next(item for item in day.json()["items"] if item["kind"] == "reminder")
    assert reminder["status"] == "done"
    assert restored.status_code == 200
    assert restored.json()["status"] == "planned"

    async with db() as session:
        row = await session.get(TriggerInstance, trigger.id)
        assert row is not None
        assert row.status == "pending"
        assert "ack" not in row.payload


async def test_review_marks_done_and_keeps_unchecked_status(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/mobile/today/review",
            json={
                "results": [
                    {"itemId": str(seeded.morning.id), "done": True},
                    {"itemId": str(seeded.afternoon.id), "done": False},
                ]
            },
            headers=_headers(seeded.user, "review-1"),
        )

    assert response.status_code == 200
    assert response.json() == {"updated": 1, "skipped_ids": []}

    async with db() as session:
        morning = await session.get(PlannedBlock, seeded.morning.id)
        afternoon = await session.get(PlannedBlock, seeded.afternoon.id)
        assert morning is not None and morning.status == "done"
        assert afternoon is not None and afternoon.status == "skipped"


async def test_review_skips_invalid_and_unactionable_items(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    async with db() as session:
        failed = TriggerInstance(
            user_id=seeded.user.id,
            kind="reminder",
            key=f"reminder:{seeded.user.id}:review-failed",
            fire_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
            tz=seeded.user.timezone,
            payload={"note": "失败提醒"},
            status="failed",
            created_at=fake_clock.now(),
        )
        session.add(failed)
        await session.commit()

    missing = "00000000-0000-0000-0000-000000000000"
    app = _app(db, fake_clock, settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/mobile/today/review",
            json={
                "results": [
                    {"itemId": str(seeded.morning.id), "done": True},
                    {"itemId": missing, "done": True},
                    {"itemId": str(failed.id), "done": True},
                    {"itemId": str(seeded.afternoon.id), "done": False},
                ]
            },
            headers=_headers(seeded.user, "review-skip"),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["updated"] == 1
    assert set(body["skipped_ids"]) == {missing, str(failed.id)}

    async with db() as session:
        morning = await session.get(PlannedBlock, seeded.morning.id)
        afternoon = await session.get(PlannedBlock, seeded.afternoon.id)
        trigger = await session.get(TriggerInstance, failed.id)
        assert morning is not None and morning.status == "done"
        assert afternoon is not None and afternoon.status == "skipped"
        assert trigger is not None and trigger.status == "failed"


async def test_write_requires_idempotency_key_and_valid_item(db, fake_clock, settings):
    seeded = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing_key = await client.post(
            f"/api/mobile/today/items/{seeded.morning.id}/complete",
            headers={"X-Butler-User": str(seeded.user.id)},
        )
        unknown = await client.post(
            "/api/mobile/today/items/00000000-0000-0000-0000-000000000000/complete",
            headers=_headers(seeded.user, "unknown-1"),
        )

    assert missing_key.status_code == 400
    assert unknown.status_code == 404
