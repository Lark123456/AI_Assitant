"""SQLAlchemy 基类与引擎/会话工厂。"""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类，统一约束命名以便 Alembic 生成稳定迁移。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(url: str) -> AsyncEngine:
    """按 DATABASE_URL 创建异步引擎。"""
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """创建异步会话工厂。"""
    return async_sessionmaker(engine, expire_on_commit=False)
