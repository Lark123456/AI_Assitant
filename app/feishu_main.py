"""飞书长连接独立服务入口（compose 单实例；api 与 worker 不启动长连接）。

与 asyncio 的共存方案与取舍：
- lark-oapi 的 ws.Client 持有「模块级全局事件循环」，且在**模块导入时**就捕获
  当前循环；ws.start() 会对该循环 run_until_complete。因此必须赶在 asyncio.run
  之前完成首次导入（见下方 import lark_oapi.ws.client），让它拿到一个私有的、
  未运行的循环，与进程主 asyncio 循环互不共享；否则它抓到正在运行的主循环，
  会报 RuntimeError: This event loop is already running。
- 阻塞的 ws.start() 经 asyncio.to_thread 放入工作线程，主 asyncio 循环保持可用。
- SDK 回调在其内部线程触发，经 asyncio.run_coroutine_threadsafe 汇入主
  循环；回调线程最多同步等待 ingest 3 秒（见 FeishuAdapter.start），
  process 作为主循环上的独立任务异步执行。
- 取舍：ws.start 长期占用一个 to_thread 工作线程（每进程一条，可接受）；
  SDK 事件循环是模块级全局，一个进程只能有一个长连接客户端，因此
  compose 中 feishu 服务限定单实例。
"""

import asyncio

# 关键：lark_oapi.ws.client 在导入时捕获当前事件循环存为模块级全局（供 ws.start()
# 的 run_until_complete 使用）。此导入必须在 asyncio.run 之前执行，使 SDK 拿到
# 私有的、未运行的循环；若首次导入发生在主循环运行中，SDK 会抓到正在运行的循环
# 并在启动长连接时崩溃。不能移到函数内或适配器中延迟导入。
import lark_oapi.ws.client  # noqa: F401

from app.adapters.base import InboundEvent
from app.adapters.feishu_adapter import FeishuAdapter
from app.adapters.identity import make_identity_resolver
from app.core.clock import Clock
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.tasks import spawn
from app.db.base import make_engine, make_sessionmaker
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.providers.openai_compat import OpenAICompatProvider

logger = get_logger(__name__)


async def _dispatch(pipeline: InboundPipeline, event: InboundEvent) -> None:
    """回调协程：ingest（3 秒内落库）后把 process 放入后台（引用由 spawn 持有）。"""
    ingested = await pipeline.ingest(event)
    if ingested is None:
        return
    if ingested.created:
        spawn(pipeline.process(ingested))


async def _run(pipeline: InboundPipeline, feishu: FeishuAdapter) -> None:
    recovered = await pipeline.recover_unfinished()
    if recovered:
        logger.info("startup: recovered %d unfinished inbound events", recovered)
    await feishu.start(lambda event: _dispatch(pipeline, event))


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    if not (settings.feishu_app_id and settings.feishu_app_secret):
        raise SystemExit("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置，无法启动长连接服务")
    clock = Clock()
    engine = make_engine(settings.database_url)
    sessionmaker = make_sessionmaker(engine)
    gateway = LLMGateway(
        aliases_path=settings.aliases_path,
        providers={
            "openai_compat": OpenAICompatProvider(settings.llm_base_url, settings.llm_api_key),
            "openai_compat_agent": OpenAICompatProvider(
                settings.llm_agent_base_url, settings.llm_agent_api_key
            ),
        },
        sessionmaker=sessionmaker,
        clock=clock,
        daily_limit=settings.llm_daily_limit,
    )
    feishu = FeishuAdapter(
        make_identity_resolver(sessionmaker, "feishu"),
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
    )
    pipeline = InboundPipeline(
        sessionmaker=sessionmaker,
        clock=clock,
        settings=settings,
        gateway=gateway,
        adapters={"feishu": feishu},
    )
    try:
        asyncio.run(_run(pipeline, feishu))
    except KeyboardInterrupt:
        logger.info("feishu service stopped")


if __name__ == "__main__":
    main()
