"""FastAPI 应用入口（api 服务）。

阶段 1 修订：api 不再启动飞书长连接——长连接移入独立 feishu 服务
（app/feishu_main.py，compose 单实例）。
阶段 1 修订 2：Console 路由由 ENABLE_CONSOLE 控制（默认关闭）；
启动时补处理上次未完成的入站事件（inbound_processing.status=processing）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.base import ChannelAdapter
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.adapters.mobile_adapter import MobileAdapter
from app.api.routes.console import router as console_router
from app.api.routes.health import router as health_router
from app.api.routes.mobile import router as mobile_router
from app.api.routes.mobile_chat import router as mobile_chat_router
from app.api.routes.mobile_profile import router as mobile_profile_router
from app.api.routes.mobile_reminders import router as mobile_reminders_router
from app.api.routes.mobile_tasks import router as mobile_tasks_router
from app.core.clock import Clock
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.base import make_engine, make_sessionmaker
from app.embeddings.service import build_embedding_service
from app.engine.pipeline import InboundPipeline
from app.engine.streaming import ChatStreamBroker
from app.llm.gateway import LLMGateway
from app.llm.providers.base import BaseProvider
from app.llm.providers.openai_compat import OpenAICompatProvider

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """组装依赖与路由；渠道细节集中在 adapters。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    clock = Clock()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    stream_broker = ChatStreamBroker()

    providers: dict[str, BaseProvider] = {
        "openai_compat": OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key),
        "openai_compat_agent": OpenAICompatProvider(settings.llm_agent_base_url, settings.llm_agent_api_key),
    }
    gateway = LLMGateway(
        aliases_path=settings.aliases_path,
        providers=providers,
        sessionmaker=sessionmaker,
        clock=clock,
        daily_limit=settings.llm_daily_limit,
    )

    adapters: dict[str, ChannelAdapter] = {
        "console": ConsoleAdapter(make_identity_resolver(sessionmaker, "console"))
    }
    if settings.enable_mobile_api:
        # 注册而非推送：手机回复由 Pipeline 落库，App 通过 chat API 轮询获取；
        # 注册同时让本服务的 recover_unfinished 接手未完成的手机消息。
        adapters["mobile"] = MobileAdapter(
            make_identity_resolver(sessionmaker, "mobile")
        )

    pipeline = InboundPipeline(
        sessionmaker=sessionmaker,
        clock=clock,
        settings=settings,
        gateway=gateway,
        adapters=adapters,
        embedder=build_embedding_service(settings),
        stream_broker=stream_broker,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        recovered = await pipeline.recover_unfinished()
        if recovered:
            logger.info("startup: recovered %d unfinished inbound events", recovered)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.pipeline = pipeline
    app.state.adapters = adapters
    app.state.clock = clock
    app.state.sessionmaker = sessionmaker
    app.state.settings = settings
    app.state.chat_stream_broker = stream_broker
    if settings.enable_console:
        app.include_router(console_router)
    if settings.enable_mobile_api:
        if not settings.allowed_open_ids.strip():
            logger.warning("mobile API enabled without ALLOWED_OPEN_IDS: dev auth only")
        app.include_router(mobile_router)
        app.include_router(mobile_chat_router)
        app.include_router(mobile_tasks_router)
        app.include_router(mobile_profile_router)
        app.include_router(mobile_reminders_router)
    app.include_router(health_router)
    return app


app = create_app()
