"""U2 B2：移动端我的页资料 API。"""

import datetime as dt

import httpx
from fastapi import FastAPI

from app.api.routes.mobile_profile import router as profile_router
from app.core.config import Settings
from app.db.models import ChannelIdentity, User


def _app(db, clock, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(profile_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    return app


async def _seed(db, clock) -> tuple[User, User]:
    async with db() as session:
        first = User(
            display_name="张三",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
            created_at=dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.UTC),
            updated_at=clock.now(),
        )
        second = User(
            display_name="李四",
            timezone="Asia/Tokyo",
            day_start=dt.time(5, 0),
            created_at=dt.datetime(2026, 2, 1, 3, 0, tzinfo=dt.UTC),
            updated_at=clock.now(),
        )
        session.add_all([first, second])
        await session.flush()
        session.add_all(
            [
                ChannelIdentity(
                    user_id=first.id, channel="feishu", external_id="ou_profile_a"
                ),
                ChannelIdentity(
                    user_id=second.id, channel="feishu", external_id="ou_profile_b"
                ),
            ]
        )
        await session.commit()
        return first, second


async def test_profile_returns_current_user(db, fake_clock):
    first, second = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response_a = await client.get(
            "/api/mobile/profile", headers={"X-Butler-User": str(first.id)}
        )
        response_b = await client.get(
            "/api/mobile/profile", headers={"X-Butler-User": str(second.id)}
        )

    body_a = response_a.json()
    assert response_a.status_code == 200
    assert body_a["displayName"] == "张三"
    assert body_a["timezone"] == "Asia/Shanghai"
    assert body_a["dayStart"] == "04:00"
    assert body_a["createdAt"] == "2026-01-01T08:00:00+08:00"

    body_b = response_b.json()
    assert body_b["displayName"] == "李四"
    assert body_b["timezone"] == "Asia/Tokyo"
    assert body_b["dayStart"] == "05:00"
    assert body_b["createdAt"] == "2026-02-01T12:00:00+09:00"


async def test_profile_auth_required_and_whitelist(db, fake_clock):
    user, _ = await _seed(db, fake_clock)
    settings = Settings(_env_file=None, allowed_open_ids="ou_other")
    app = _app(db, fake_clock, settings)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/api/mobile/profile")
        blocked = await client.get(
            "/api/mobile/profile", headers={"X-Butler-User": str(user.id)}
        )

    assert missing.status_code == 401
    assert blocked.status_code == 403
