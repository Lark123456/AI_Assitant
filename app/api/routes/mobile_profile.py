"""移动端我的页 API（U2 B2）：只读用户资料。"""

import datetime as dt
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.routes.mobile import get_mobile_user
from app.db.models import User

router = APIRouter(prefix="/api/mobile")


@router.get("/profile")
async def get_profile(
    user: Annotated[User, Depends(get_mobile_user)],
) -> dict:
    """当前用户的只读资料；手机端用于我的页展示。"""
    tz = ZoneInfo(user.timezone)
    created_at: dt.datetime = user.created_at
    return {
        "displayName": user.display_name,
        "timezone": user.timezone,
        "dayStart": user.day_start.strftime("%H:%M"),
        "createdAt": created_at.astimezone(tz).isoformat(),
    }
