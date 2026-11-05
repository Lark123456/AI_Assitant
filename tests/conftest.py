"""测试公共设施：DB（不可用则跳过集成测试，REQUIRE_DB=1 时改为失败）、FakeClock、假 LLM provider、管道工厂。"""

import asyncio
import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path

# 必须在导入 app 模块前设置，保证 get_settings 与 Alembic 用同一地址
# ruff: noqa: E402
TEST_DATABASE_URL = os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://butler:butler@localhost:5432/butler"
)

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import UTC, FakeClock
from app.core.config import Settings
from app.db.base import make_engine, make_sessionmaker
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.providers.base import BaseProvider
from app.llm.schemas import LLMResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_ALIASES = Path(__file__).parent / "fixtures" / "aliases_test.yaml"
ALL_TABLES = (
    "memory_decision_log, memory_source, memory, llm_call, notif_prefs, delivery, "
    "nudge_decision, nudge_candidate, trigger_instance, planned_block, work_item, "
    "event_log, channel_identity, \"user\""
)


def _run_migrations() -> None:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def db_ready() -> bool:
    """Postgres 可达则跑迁移；不可用时：REQUIRE_DB=1 失败，否则跳过集成测试。"""

    async def _check() -> bool:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
        finally:
            await engine.dispose()

    if not asyncio.run(_check()):
        if os.environ.get("REQUIRE_DB") == "1":
            pytest.fail("REQUIRE_DB=1 但 Postgres 不可用：先 make up 再跑集成测试")
        pytest.skip("Postgres 不可用：先 make up 再跑集成测试")
    _run_migrations()
    return True


@pytest.fixture
async def db(db_ready):
    """清空表并提供会话工厂。"""
    engine = make_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {ALL_TABLES}"))
    sessionmaker = make_sessionmaker(engine)
    yield sessionmaker
    await engine.dispose()


@pytest.fixture
def fake_clock() -> FakeClock:
    """固定起点 2026-01-01T00:00Z（北京时间 08:00）。"""
    return FakeClock(dt.datetime(2026, 1, 1, 0, 0, tzinfo=UTC))


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


class FakeProvider(BaseProvider):
    """假 LLM：不联网，按脚本回调返回结果，并记录全部调用。"""

    name = "fake"

    def __init__(self, responder: Callable[[list[dict]], LLMResult]) -> None:
        self._responder = responder
        self.calls: list[list[dict]] = []

    async def complete(
        self, *, model: str, messages: list[dict], tools: list[dict] | None, params: dict
    ) -> LLMResult:
        self.calls.append([dict(m) for m in messages])
        result = self._responder(messages)
        return LLMResult(
            content=result.content,
            tool_calls=result.tool_calls,
            reasoning=result.reasoning,
            usage=result.usage,
            model_id="fake-model",
            latency_ms=1,
            ttft_ms=1,
        )


@pytest.fixture
def make_gateway(db, fake_clock):
    """构造注入假 provider 的 LLM 网关。"""

    def _make(responder: Callable[[list[dict]], LLMResult], *, daily_limit: int = 0):
        return LLMGateway(
            aliases_path=str(TEST_ALIASES),
            providers={"fake": FakeProvider(responder)},
            sessionmaker=db,
            clock=fake_clock,
            daily_limit=daily_limit,
        )

    return _make


@pytest.fixture
def make_pipeline(db, fake_clock, settings, make_gateway):
    """构造注入了假 LLM 与 Console 渠道的完整管道。"""

    def _make(responder: Callable[[list[dict]], LLMResult], *, daily_limit: int = 0):
        gateway = make_gateway(responder, daily_limit=daily_limit)
        console = ConsoleAdapter(make_identity_resolver(db, "console"))
        pipeline = InboundPipeline(
            sessionmaker=db,
            clock=fake_clock,
            settings=settings,
            gateway=gateway,
            adapters={"console": console},
        )
        return pipeline, console

    return _make
