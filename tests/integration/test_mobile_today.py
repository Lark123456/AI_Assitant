"""U2 移动端 Today 只读 API：开发用户头、日期窗口与数据映射。"""

import datetime as dt

import httpx
from fastapi import FastAPI

from app.api.routes.mobile import router
from app.core.clock import UTC, FakeClock
from app.db.models import ChannelIdentity, PlannedBlock, TriggerInstance, User, WorkItem


def _app(db, clock: FakeClock) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.sessionmaker = db
    app.state.clock = clock
    return app


async def _seed(db, clock: FakeClock) -> User:
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

        morning = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="专注写作",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        done_item = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="方案评审",
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        scheduled_item = WorkItem(
            user_id=user.id,
            type="item",
            status="active",
            title="回复邮件",
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
        session.add_all([morning, done_item, scheduled_item, unscheduled_item])
        await session.flush()

        session.add_all(
            [
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=morning.id,
                    starts_at=dt.datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 2, 0, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    compressible=True,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=done_item.id,
                    starts_at=dt.datetime(2026, 1, 1, 2, 30, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
                    status="done",
                    assigned_by="friday",
                    compressible=False,
                    actual_started_at=dt.datetime(2026, 1, 1, 2, 30, tzinfo=UTC),
                    actual_ended_at=dt.datetime(2026, 1, 1, 3, 30, tzinfo=UTC),
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
                PlannedBlock(
                    user_id=user.id,
                    work_item_id=scheduled_item.id,
                    starts_at=dt.datetime(2026, 1, 1, 4, 0, tzinfo=UTC),
                    ends_at=dt.datetime(2026, 1, 1, 5, 0, tzinfo=UTC),
                    status="planned",
                    assigned_by="friday",
                    compressible=True,
                    created_at=clock.now(),
                    updated_at=clock.now(),
                ),
            ]
        )

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
        return user


async def test_today_reads_blocks_reminders_and_unscheduled(db, fake_clock):
    user = await _seed(db, fake_clock)
    app = _app(db, fake_clock)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/mobile/today",
            params={"date": "2026-01-01"},
            headers={"X-Butler-User": str(user.id)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == "2026-01-01"
    assert body["morningBrief"] is None
    assert [item["kind"] for item in body["items"]] == [
        "block",
        "block",
        "reminder",
        "block",
    ]
    first = body["items"][0]
    assert first["title"] == "专注写作"
    assert first["status"] == "planned"
    assert first["start"] == "2026-01-01T09:00:00+08:00"
    assert first["end"] == "2026-01-01T10:00:00+08:00"
    assert first["durationMin"] == 60
    assert body["items"][1]["status"] == "done"
    assert body["items"][2]["title"] == "喝水"
    assert body["items"][2]["status"] == "planned"
    assert body["items"][2]["start"] == "2026-01-01T11:30:00+08:00"
    assert body["items"][3]["title"] == "回复邮件"
    assert body["items"][3]["status"] == "planned"
    assert [item["title"] for item in body["unscheduled"]] == ["整理笔记"]
    assert body["unscheduled"][0]["start"] is None
    assert body["unscheduled"][0]["status"] == "planned"


async def test_today_accepts_open_id_header_and_default_date(db, fake_clock):
    await _seed(db, fake_clock)
    app = _app(db, fake_clock)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/mobile/today", headers={"X-Butler-User": "feishu:ou_test"}
        )
        bare = await client.get(
            "/api/mobile/today", headers={"X-Butler-User": "ou_test"}
        )

    assert response.status_code == 200
    assert response.json()["date"] == "2026-01-01"
    assert bare.status_code == 200


async def test_today_requires_user_header_and_valid_date(db, fake_clock):
    await _seed(db, fake_clock)
    app = _app(db, fake_clock)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/mobile/today")
        invalid = await client.get(
            "/api/mobile/today",
            params={"date": "2026/01/01"},
            headers={"X-Butler-User": "ou_test"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 400
