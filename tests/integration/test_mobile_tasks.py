"""U2 B1：移动端任务列表 API。"""

import datetime as dt

import httpx
from fastapi import FastAPI

from app.api.routes.mobile_tasks import router as tasks_router
from app.core.clock import UTC, FakeClock
from app.core.config import Settings
from app.db.models import ChannelIdentity, PlannedBlock, User, WorkItem


def _app(db, clock: FakeClock, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(tasks_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    return app


async def _seed(db, clock: FakeClock) -> tuple[User, User]:
    async with db() as session:
        user = User(
            display_name="任务用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        other = User(display_name="其他用户", timezone="Asia/Shanghai")
        session.add_all([user, other])
        await session.flush()
        session.add(
            ChannelIdentity(
                user_id=user.id, channel="feishu", external_id="ou_tasks"
            )
        )

        def at(minutes_ago: int) -> dt.datetime:
            return clock.now() - dt.timedelta(minutes=minutes_ago)

        active_a = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="写报告",
            description="季度总结",
            created_at=at(60),
            updated_at=at(10),
        )
        active_b = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="整理笔记",
            created_at=at(50),
            updated_at=at(5),
        )
        done_c = WorkItem(
            user_id=user.id,
            type="item",
            status="done",
            title="回复邮件",
            created_at=at(40),
            updated_at=at(20),
        )
        dropped_d = WorkItem(
            user_id=user.id,
            type="item",
            status="dropped",
            title="取消的事",
            created_at=at(30),
            updated_at=at(30),
        )
        other_item = WorkItem(
            user_id=other.id,
            type="item",
            status="active",
            title="别人的任务",
            updated_at=at(1),
        )
        session.add_all([active_a, active_b, done_c, dropped_d, other_item])
        await session.flush()

        session.add_all(
            [
                # A 的过去块（已结束，不应成为 upcomingBlock）
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=active_a.id,
                    starts_at=dt.datetime(2025, 12, 31, 23, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2025, 12, 31, 23, 30, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
                # A 的未来块：09:00–10:00 +08
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=active_a.id,
                    starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
                # A 的更晚块：14:00–15:00 +08
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=active_a.id,
                    starts_at=dt.datetime(2026, 1, 1, 6, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 7, 0, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
                # B 的未来块：10:00–11:00 +08
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=active_b.id,
                    starts_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 3, 0, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
            ]
        )
        await session.commit()
        return user, other


async def test_list_tasks_filters_and_upcoming_block(db, fake_clock, settings):
    user, _ = await _seed(db, fake_clock)
    app = _app(db, fake_clock, settings)
    headers = {"X-Butler-User": str(user.id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        opened = await client.get("/api/mobile/tasks", headers=headers)
        done = await client.get(
            "/api/mobile/tasks", params={"status": "done"}, headers=headers
        )
        all_tasks = await client.get(
            "/api/mobile/tasks", params={"status": "all"}, headers=headers
        )

    open_tasks = opened.json()["tasks"]
    assert [task["title"] for task in open_tasks] == ["整理笔记", "写报告"]
    assert [task["status"] for task in open_tasks] == ["open", "open"]
    assert open_tasks[1]["description"] == "季度总结"
    assert open_tasks[1]["upcomingBlock"]["start"] == "2026-01-01T09:00:00+08:00"
    assert open_tasks[1]["upcomingBlock"]["end"] == "2026-01-01T10:00:00+08:00"
    assert open_tasks[0]["upcomingBlock"]["start"] == "2026-01-01T10:00:00+08:00"

    done_tasks = done.json()["tasks"]
    assert [task["title"] for task in done_tasks] == ["回复邮件"]
    assert done_tasks[0]["status"] == "done"
    assert done_tasks[0]["upcomingBlock"] is None

    all_items = all_tasks.json()["tasks"]
    assert [task["title"] for task in all_items] == [
        "整理笔记",
        "写报告",
        "回复邮件",
        "取消的事",
    ]
    assert [task["status"] for task in all_items] == [
        "open",
        "open",
        "done",
        "skipped",
    ]
    assert all(task["title"] != "别人的任务" for task in all_items)


async def test_list_tasks_limit_and_validation(db, fake_clock):
    user, _ = await _seed(db, fake_clock)
    settings = Settings(_env_file=None)
    app = _app(db, fake_clock, settings)
    headers = {"X-Butler-User": str(user.id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        limited = await client.get(
            "/api/mobile/tasks", params={"limit": 1}, headers=headers
        )
        bad_status = await client.get(
            "/api/mobile/tasks", params={"status": "nope"}, headers=headers
        )
        zero = await client.get(
            "/api/mobile/tasks", params={"limit": 0}, headers=headers
        )
        overflow = await client.get(
            "/api/mobile/tasks", params={"limit": 101}, headers=headers
        )

    assert [task["title"] for task in limited.json()["tasks"]] == ["整理笔记"]
    assert bad_status.status_code == 400
    assert zero.status_code == 400
    assert overflow.status_code == 400


async def test_list_tasks_auth_required_and_whitelist(db, fake_clock):
    user, _ = await _seed(db, fake_clock)
    settings = Settings(_env_file=None, allowed_open_ids="ou_other")
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/mobile/tasks")
        blocked = await client.get(
            "/api/mobile/tasks", headers={"X-Butler-User": str(user.id)}
        )

    assert missing.status_code == 401
    assert blocked.status_code == 403
