"""阶段 3b：手机 Chat 卡片序列化与确认接口。"""

import datetime as dt
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from app.api.routes.mobile_chat import router as chat_router
from app.core.clock import FakeClock
from app.core.config import Settings
from app.db.models import ChannelIdentity, Memory, MemoryDecisionLog, User
from app.engine.events import append_event


def _app(db, clock: FakeClock, settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.state.sessionmaker = db
    app.state.clock = clock
    app.state.settings = settings
    return app


async def _seed(
    db,
    clock: FakeClock,
    *,
    old_status: str = "active",
    external_id: str = "ou_card",
) -> dict[str, uuid.UUID]:
    async with db() as session:
        user = User(
            display_name="卡片用户",
            timezone="Asia/Shanghai",
            day_start=dt.time(4, 0),
        )
        other = User(display_name="别人", timezone="Asia/Shanghai")
        session.add_all([user, other])
        await session.flush()
        session.add(
            ChannelIdentity(
                user_id=user.id, channel="feishu", external_id=external_id
            )
        )
        old = Memory(
            user_id=user.id,
            type="slot",
            slot_key="wake",
            subject="起床时间",
            value={"text": "7点", "time": "07:00"},
            scope={"kind": "persistent"},
            source_class="stated",
            weight=0.8,
            confidence=0.9,
            status=old_status,
            recorded_at=clock.now(),
            support_days=1,
            contradict_count=0,
        )
        session.add(old)
        await session.flush()
        pending = Memory(
            user_id=user.id,
            type="slot",
            slot_key="wake",
            subject="起床时间",
            value={"text": "8点", "time": "08:00"},
            scope={"kind": "persistent"},
            source_class="stated",
            weight=0.8,
            confidence=0.9,
            status="pending",
            supersedes_id=old.id,
            recorded_at=clock.now(),
            support_days=1,
            contradict_count=0,
        )
        session.add(pending)
        await session.flush()

        reply, _ = await append_event(
            session,
            user_id=user.id,
            channel="mobile",
            direction="outbound",
            type="message",
            payload={"text": "已有记录，要替换吗？", "delivery": "persisted"},
            trace_id="card",
            clock=clock,
        )
        card, _ = await append_event(
            session,
            user_id=user.id,
            channel="mobile",
            direction="outbound",
            type="card",
            payload={
                "card_type": "memory_confirm",
                "text": "有一条记忆需要确认",
                "items": [
                    {
                        "item_id": str(pending.id),
                        "label": "起床时间：8点（原 7点）",
                    }
                ],
            },
            trace_id="card",
            clock=clock,
            occurred_at=reply.occurred_at + dt.timedelta(microseconds=1),
        )
        await session.commit()
        return {
            "user": user.id,
            "other": other.id,
            "old": old.id,
            "pending": pending.id,
            "reply": reply.id,
            "card": card.id,
        }


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Butler-User": str(user_id)}


async def test_chat_history_returns_memory_card_and_state(db, fake_clock):
    ids = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        history = await client.get(
            "/api/mobile/chat/messages", headers=_headers(ids["user"])
        )
        card_after = await client.get(
            "/api/mobile/chat/messages",
            params={"after": str(ids["card"])},
            headers=_headers(ids["user"]),
        )

    messages = history.json()["messages"]
    assert [message["kind"] for message in messages] == ["text", "memory_confirm"]
    card = messages[1]
    assert card["items"] == [
        {
            "itemId": str(ids["pending"]),
            "label": "起床时间：8点（原 7点）",
            "state": "pending",
        }
    ]
    assert card["allHandled"] is False
    assert card_after.status_code == 200


async def test_confirm_card_upgrades_memory_and_refreshes_state(db, fake_clock):
    ids = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        action = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "confirm", "itemId": str(ids["pending"])},
            headers=_headers(ids["user"]),
        )
        history = await client.get(
            "/api/mobile/chat/messages", headers=_headers(ids["user"])
        )

    assert action.status_code == 200
    body = action.json()
    assert body["items"][0]["state"] == "confirmed"
    assert body["allConfirmed"] is True
    card = history.json()["messages"][1]
    assert card["items"][0]["state"] == "confirmed"

    async with db() as session:
        old = await session.get(Memory, ids["old"])
        pending = await session.get(Memory, ids["pending"])
    assert old is not None and old.status == "superseded"
    assert pending is not None
    assert pending.status == "active"
    assert pending.source_class == "confirmed"
    assert pending.weight == 1.0


async def test_reject_card_keeps_old_memory(db, fake_clock):
    ids = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        action = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "reject"},
            headers=_headers(ids["user"]),
        )

    assert action.status_code == 200
    assert action.json()["items"][0]["state"] == "rejected"
    async with db() as session:
        old = await session.get(Memory, ids["old"])
        pending = await session.get(Memory, ids["pending"])
    assert old is not None and old.status == "active"
    assert old.weight == 0.8
    assert pending is not None and pending.status == "retracted"


async def test_card_action_validation(db, fake_clock):
    ids = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))
    other_card = await _seed(db, fake_clock, external_id="ou_card_other")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        foreign = await client.post(
            f"/api/mobile/chat/messages/{other_card['card']}/card-actions",
            json={"action": "confirm"},
            headers=_headers(ids["user"]),
        )
        wrong_item = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "confirm", "itemId": str(uuid.uuid4())},
            headers=_headers(ids["user"]),
        )
        text_as_card = await client.post(
            f"/api/mobile/chat/messages/{ids['reply']}/card-actions",
            json={"action": "confirm"},
            headers=_headers(ids["user"]),
        )
        missing_header = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "confirm"},
        )

    assert foreign.status_code == 404
    assert wrong_item.status_code == 400
    assert text_as_card.status_code == 404
    assert missing_header.status_code == 401


async def test_card_states_reflect_retracted_memory(db, fake_clock):
    ids = await _seed(db, fake_clock)
    async with db() as session:
        pending = await session.get(Memory, ids["pending"])
        assert pending is not None
        pending.status = "retracted"
        pending.rejected_at = fake_clock.now()
        await session.commit()
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        history = await client.get(
            "/api/mobile/chat/messages", headers=_headers(ids["user"])
        )

    card = history.json()["messages"][1]
    assert card["items"][0]["state"] == "rejected"
    assert card["allHandled"] is True


async def test_repeated_confirm_is_idempotent(db, fake_clock):
    ids = await _seed(db, fake_clock)
    app = _app(db, fake_clock, Settings(_env_file=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "confirm"},
            headers=_headers(ids["user"]),
        )
        second = await client.post(
            f"/api/mobile/chat/messages/{ids['card']}/card-actions",
            json={"action": "confirm"},
            headers=_headers(ids["user"]),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["items"][0]["state"] == "confirmed"
    async with db() as session:
        logs = (
            await session.execute(select(MemoryDecisionLog))
        ).scalars().all()
    assert len(logs) == 1
