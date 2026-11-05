"""用户引导：按渠道身份查找或创建 user + channel_identity。"""


from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import Clock
from app.db.models import ChannelIdentity, User


class UserOnboardingError(RuntimeError):
    pass


async def get_or_create_user(
    session: AsyncSession,
    *,
    channel: str,
    external_id: str,
    tenant_id: str | None,
    display_name: str,
    default_timezone: str,
    clock: Clock,
) -> tuple[User, bool]:
    """按 (channel, external_id) 查找用户；不存在则创建 user 与渠道身份。返回 (user, 是否新建)。"""
    identity = (
        await session.execute(
            select(ChannelIdentity).where(
                ChannelIdentity.channel == channel,
                ChannelIdentity.external_id == external_id,
            )
        )
    ).scalar_one_or_none()
    if identity is not None:
        user = (
            await session.execute(select(User).where(User.id == identity.user_id))
        ).scalar_one()
        return user, False

    user = User(
        display_name=display_name,
        timezone=default_timezone,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    session.add(user)
    await session.flush()
    identity = ChannelIdentity(
        user_id=user.id,
        channel=channel,
        external_id=external_id,
        tenant_id=tenant_id,
        created_at=clock.now(),
        updated_at=clock.now(),
    )
    session.add(identity)
    try:
        await session.flush()
    except IntegrityError as exc:  # 并发创建同一身份
        await session.rollback()
        raise UserOnboardingError(f"concurrent onboarding for {channel}:{external_id}") from exc
    return user, True
