"""user_id -> 渠道外部 id 的解析器工厂（供 adapter 注入使用）。"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChannelIdentity


def make_identity_resolver(
    sessionmaker: async_sessionmaker[AsyncSession], channel: str
) -> Callable[[uuid.UUID], Awaitable[str | None]]:
    """生成指定渠道的 user_id -> external_id 解析函数。"""

    async def resolve(user_id: uuid.UUID) -> str | None:
        async with sessionmaker() as session:
            row = (
                await session.execute(
                    select(ChannelIdentity).where(
                        ChannelIdentity.user_id == user_id,
                        ChannelIdentity.channel == channel,
                    )
                )
            ).scalar_one_or_none()
            return row.external_id if row else None

    return resolve
