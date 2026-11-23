"""移动端任务列表 API（U2 B1）：只读列表；写操作复用 Today 端点。"""

import datetime as dt
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.mobile import get_mobile_user, get_session
from app.db.models import PlannedBlock, User, WorkItem

router = APIRouter(prefix="/api/mobile")

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "open": ("active",),
    "done": ("done",),
    "all": ("active", "done", "dropped"),
}
STATUS_MAP = {"active": "open", "done": "done", "dropped": "skipped"}


def _iso(value: dt.datetime, tz: str) -> str:
    return value.astimezone(ZoneInfo(tz)).isoformat()


def _block_item(block: PlannedBlock, tz: str) -> dict:
    return {
        "id": str(block.id),
        "start": _iso(block.starts_at, tz),
        "end": _iso(block.ends_at, tz),
        "status": block.status,
    }


@router.get("/tasks")
async def list_tasks(
    request: Request,
    user: Annotated[User, Depends(get_mobile_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status: str = Query(default="open", description="open | done | all"),
    limit: int = Query(default=DEFAULT_LIMIT),
) -> dict:
    """列出当前用户的任务；upcomingBlock 取最早的未来计划块。"""
    statuses = STATUS_FILTERS.get(status)
    if statuses is None:
        raise HTTPException(status_code=400, detail="status 只能是 open、done 或 all")
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(status_code=400, detail="limit 必须在 1-100 之间")

    now = request.app.state.clock.now()
    rows = (
        (
            await session.execute(
                select(WorkItem)
                .where(
                    WorkItem.user_id == user.id,
                    WorkItem.type == "item",
                    WorkItem.status.in_(statuses),
                )
                .order_by(WorkItem.updated_at.desc(), WorkItem.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return {"tasks": []}

    blocks = (
        (
            await session.execute(
                select(PlannedBlock)
                .where(
                    PlannedBlock.user_id == user.id,
                    PlannedBlock.work_item_id.in_([row.id for row in rows]),
                    PlannedBlock.status == "planned",
                    PlannedBlock.ends_at >= now,
                )
                .order_by(PlannedBlock.starts_at.asc())
            )
        )
        .scalars()
        .all()
    )
    # 查询已按开始时间升序，每个任务保留第一个（最早的未来块）
    upcoming: dict[object, PlannedBlock] = {}
    for block in blocks:
        upcoming.setdefault(block.work_item_id, block)

    tz = user.timezone
    tasks = [
        {
            "id": str(row.id),
            "title": row.title,
            "description": row.description,
            "status": STATUS_MAP.get(row.status, "open"),
            "createdAt": _iso(row.created_at, tz),
            "updatedAt": _iso(row.updated_at, tz),
            "upcomingBlock": (
                _block_item(upcoming[row.id], tz) if row.id in upcoming else None
            ),
        }
        for row in rows
    ]
    return {"tasks": tasks}
