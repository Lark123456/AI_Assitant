"""移动端应用内提醒 API（U2 B3）：返回当前时间窗内已到点的提醒。"""

import datetime as dt
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.mobile import get_mobile_user, get_session
from app.db.models import TriggerInstance, User

router = APIRouter(prefix="/api/mobile")

DEFAULT_GRACE_MINUTES = 30
MAX_GRACE_MINUTES = 240
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
VISIBLE_STATUSES = ("pending", "claimed", "fired")


def _iso(value: dt.datetime, tz: str) -> str:
    return value.astimezone(ZoneInfo(tz)).isoformat()


@router.get("/reminders/due")
async def list_due_reminders(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    grace_minutes: int = Query(default=DEFAULT_GRACE_MINUTES, alias="graceMinutes"),
    limit: int = Query(default=DEFAULT_LIMIT),
) -> dict:
    """返回 fire_at 在 [now-grace, now] 内且未过期的提醒，供 App 前台提示。"""
    if grace_minutes < 1 or grace_minutes > MAX_GRACE_MINUTES:
        raise HTTPException(status_code=400, detail="graceMinutes 必须在 1-240 之间")
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(status_code=400, detail="limit 必须在 1-100 之间")

    now = request.app.state.clock.now()
    since = now - dt.timedelta(minutes=grace_minutes)
    rows = (
        (
            await session.execute(
                select(TriggerInstance)
                .where(
                    TriggerInstance.user_id == user.id,
                    TriggerInstance.kind == "reminder",
                    TriggerInstance.fire_at <= now,
                    TriggerInstance.fire_at >= since,
                    TriggerInstance.status.in_(VISIBLE_STATUSES),
                    or_(
                        TriggerInstance.expires_at.is_(None),
                        TriggerInstance.expires_at > now,
                    ),
                )
                .order_by(TriggerInstance.fire_at.asc(), TriggerInstance.id.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    tz = user.timezone
    reminders = [
        {
            "id": str(row.id),
            "note": str((row.payload or {}).get("note", "")),
            "fireAt": _iso(row.fire_at, tz),
            "expiresAt": _iso(row.expires_at, tz) if row.expires_at else None,
            "status": row.status,
        }
        for row in rows
    ]
    return {"reminders": reminders}
