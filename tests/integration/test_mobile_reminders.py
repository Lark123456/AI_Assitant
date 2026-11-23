"""U2 B3：移动端应用内提醒 API。"""

import datetime as dt

import httpx
from fastapi import FastAPI

from app.api.routes.mobile_reminders import router as reminders_router
from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.models import ChannelIdentity, TriggerInstance, User


def _app(db, clock: FakeClock, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(reminders_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    return app


async def _seed(db, clock: FakeClock) -> tuple[User, User]:
    async with db() as session:
        user = User(display_name="提醒用户", timezone="Asia/Shanghai")
        other = User(display_name="其他用户", timezone="Asia/Shanghai")
        session.add_all([user, other])
        await session.flush()
        session.add(
            ChannelIdentity(
                user_id=user.id, channel="feishu", external_id="ou_reminders"
            )
        )

        def ago(minutes: float) -> dt.datetime:
            return clock.now() - dt.timedelta(minutes=minutes)

        def ahead(hours: float) -> dt.datetime:
            return clock.now() + dt.timedelta(hours=hours)

        def reminder(
            *,
            key: str,
            note: str,
            fire_at: dt.datetime,
            status: str,
            owner: User,
            expires_at: dt.datetime | None = None,
        ) -> TriggerInstance:
            return TriggerInstance(
                user_id=owner.id,
                kind="reminder",
                key=key,
                fire_at=fire_at,
                tz="Asia/Shanghai",
                payload={"note": note},
                status=status,
                expires_at=expires_at or ahead(20),
                created_at=clock.now(),
            )

        session.add_all(
            [
                reminder(
                    key="due-pending",
                    note="交报告",
                    fire_at=ago(5),
                    status="pending",
                    owner=user,
                ),
                reminder(
                    key="due-claimed",
                    note="开会",
                    fire_at=ago(2),
                    status="claimed",
                    owner=user,
                ),
                reminder(
                    key="due-fired",
                    note="喝水",
                    fire_at=ago(1),
                    status="fired",
                    owner=user,
                ),
                reminder(
                    key="too-old",
                    note="很久以前",
                    fire_at=ago(60),
                    status="fired",
                    owner=user,
                ),
                reminder(
                    key="future",
                    note="还没到",
                    fire_at=ahead(0.2),
                    status="pending",
                    owner=user,
                ),
                reminder(
                    key="expired",
                    note="已过期",
                    fire_at=ago(5),
                    status="pending",
                    owner=user,
                    expires_at=ago(1),
                ),
                reminder(
                    key="dropped",
                    note="已取消",
                    fire_at=ago(5),
                    status="dropped",
                    owner=user,
                ),
                reminder(
                    key="other-user",
                    note="别人的提醒",
                    fire_at=ago(2),
                    status="pending",
                    owner=other,
                ),
            ]
        )
        await session.commit()
        return user, other


async def test_due_reminders_time_window_and_status(db, fake_clock):
    user, _ = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))
    headers = {"X-Butler-User": str(user.id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        default = await client.get("/api/mobile/reminders/due", headers=headers)
        wider = await client.get(
            "/api/mobile/reminders/due",
            params={"graceMinutes": 90},
            headers=headers,
        )
        limited = await client.get(
            "/api/mobile/reminders/due",
            params={"limit": 1},
            headers=headers,
        )

    default_notes = [item["note"] for item in default.json()["reminders"]]
    assert default_notes == ["交报告", "开会", "喝水"]
    assert default.json()["reminders"][0]["status"] == "pending"
    assert default.json()["reminders"][0]["fireAt"].endswith("+08:00")

    wider_notes = [item["note"] for item in wider.json()["reminders"]]
    assert wider_notes == ["很久以前", "交报告", "开会", "喝水"]

    assert [item["note"] for item in limited.json()["reminders"]] == ["交报告"]
    assert all(
        item["note"] != "别人的提醒" for item in default.json()["reminders"]
    )


async def test_due_reminders_validation_and_auth(db, fake_clock):
    user, _ = await _seed(db, fake_clock)
    open_settings = Settings(_env_file=None)
    app = _app(db, fake_clock, open_settings)
    headers = {"X-Butler-User": str(user.id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        zero_grace = await client.get(
            "/api/mobile/reminders/due",
            params={"graceMinutes": 0},
            headers=headers,
        )
        overflow_grace = await client.get(
            "/api/mobile/reminders/due",
            params={"graceMinutes": 241},
            headers=headers,
        )
        zero_limit = await client.get(
            "/api/mobile/reminders/due", params={"limit": 0}, headers=headers
        )
        missing = await client.get("/api/mobile/reminders/due")

    assert zero_grace.status_code == 400
    assert overflow_grace.status_code == 400
    assert zero_limit.status_code == 400
    assert missing.status_code == 401

    limited_app = _app(
        db, fake_clock, Settings(_env_file=None, allowed_open_ids="ou_other")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited_app), base_url="http://test"
    ) as client:
        blocked = await client.get(
            "/api/mobile/reminders/due", headers=headers
        )
    assert blocked.status_code == 403
