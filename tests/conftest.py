"""测试公共设施：独立测试库（自动创建、与运行中的服务隔离）、FakeClock、假 LLM provider、管道工厂。"""

import asyncio
import datetime as dt
import os
from collections.abc import Callable
from pathlib import Path

# 必须在导入 app 模块前设置：测试一律使用独立的 butler_test 库。
# 若与 docker compose 中运行中的 worker/api 共用 butler 库，worker 会抢走测试创建的
# trigger 并按真实时钟判定过期，导致「missed」等不可预测结果。
# ruff: noqa: E402
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://butler:butler@localhost:5432/butler_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import text

from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import UTC, FakeClock
from app.core.config import Settings
from app.db.base import make_engine, make_sessionmaker
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.service import EmbeddingService
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.providers.base import BaseProvider
from app.llm.schemas import LLMResult

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_ALIASES = Path(__file__).parent / "fixtures" / "aliases_test.yaml"
ALL_TABLES = (
    "memory_extraction_run, inbound_processing, memory_decision_log, memory_source, memory, "
    "llm_call, notif_prefs, delivery, nudge_decision, nudge_candidate, trigger_instance, "
    "planned_block, work_item, event_log, channel_identity, \"user\""
)


def _run_migrations() -> None:
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    command.upgrade(cfg, "head")


def _ensure_database() -> bool:
    """连维护库创建测试库（已存在则跳过）；维护库不可达时返回 False。"""

    async def _run() -> None:
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import create_async_engine

        url = make_url(TEST_DATABASE_URL)
        name = url.database or ""
        admin_url = url.set(database="postgres")
        engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                exists = (
                    await conn.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": name},
                    )
                ).first()
                if exists is None:
                    await conn.execute(text(f'CREATE DATABASE "{name}"'))
        finally:
            await engine.dispose()

    try:
        asyncio.run(_run())
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_ready() -> bool:
    """准备独立测试库并跑迁移；不可用时：REQUIRE_DB=1 失败，否则跳过集成测试。"""

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

    ready = _ensure_database() and asyncio.run(_check())
    if not ready:
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
def fake_embedder() -> EmbeddingService:
    """确定性的假嵌入（字符 bigram 特征哈希）。"""
    return EmbeddingService(FakeEmbeddingProvider(1024), 1024)


@pytest.fixture
def make_pipeline(db, fake_clock, settings, make_gateway, fake_embedder):
    """构造注入了假 LLM、假嵌入与 Console 渠道的完整管道。"""

    def _make(responder: Callable[[list[dict]], LLMResult], *, daily_limit: int = 0):
        gateway = make_gateway(responder, daily_limit=daily_limit)
        console = ConsoleAdapter(make_identity_resolver(db, "console"))
        pipeline = InboundPipeline(
            sessionmaker=db,
            clock=fake_clock,
            settings=settings,
            gateway=gateway,
            adapters={"console": console},
            embedder=fake_embedder,
        )
        return pipeline, console

    return _make
