"""阶段 1 修订新增行为（需要 Postgres）：
- 飞书 open_id 白名单
- 首答告知所用时区（仅首次）
- set_timezone 工具
- 每用户每日 LLM 调用上限
- llm_call 与日志不含 API 密钥
"""

import logging
from collections.abc import Callable

from sqlalchemy import select

from app.adapters.base import InboundEvent
from app.adapters.console_adapter import ConsoleAdapter
from app.adapters.identity import make_identity_resolver
from app.core.config import Settings
from app.db.models import EventLog, LLMCall, User
from app.engine.pipeline import InboundPipeline
from app.llm.gateway import LLMGateway
from app.llm.schemas import LLMResult, ToolCall, Usage
from tests.conftest import TEST_ALIASES, FakeProvider

SECRET = "sk-sentinel-key-abc123"


def _console_event(text: str, key: str, user: str = "u1") -> InboundEvent:
    return InboundEvent(
        channel="console", external_user_id=user, kind="message", text=text, idempotency_key=key
    )


def _feishu_event(open_id: str, key: str, text: str = "hi") -> InboundEvent:
    return InboundEvent(
        channel="feishu", external_user_id=open_id, kind="message", text=text, idempotency_key=key
    )


def _plain_responder(text: str) -> Callable[[list[dict]], LLMResult]:
    def responder(messages: list[dict]) -> LLMResult:
        return LLMResult(content=text, usage=Usage(input=1, cached=0, output=1, reasoning=0))

    return responder


def _make_pipeline(db, fake_clock, settings) -> tuple[InboundPipeline, ConsoleAdapter]:
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": FakeProvider(_plain_responder("你好！"))},
        sessionmaker=db,
        clock=fake_clock,
        daily_limit=0,
    )
    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    pipeline = InboundPipeline(
        sessionmaker=db, clock=fake_clock, settings=settings, gateway=gateway,
        adapters={"console": console},
    )
    return pipeline, console


async def test_feishu_whitelist_drops_unlisted_open_id(db, fake_clock):
    settings = Settings(_env_file=None, allowed_open_ids="ou_alice,ou_bob")
    pipeline, _ = _make_pipeline(db, fake_clock, settings)

    # 白名单外：静默丢弃，不建用户、不写事件
    assert await pipeline.ingest(_feishu_event("ou_mallory", "f-1")) is None
    async with db() as session:
        users = (await session.execute(select(User))).scalars().all()
        events = (await session.execute(select(EventLog))).scalars().all()
    assert users == []
    assert events == []

    # 白名单内：正常落库
    ingested = await pipeline.ingest(_feishu_event("ou_alice", "f-2"))
    assert ingested is not None and ingested.created

    # console 渠道不受白名单限制
    ingested = await pipeline.ingest(_console_event("hello", "c-1", user="anyone"))
    assert ingested is not None and ingested.created


async def test_first_reply_includes_timezone_notice_only_once(db, fake_clock, settings):
    pipeline, console = _make_pipeline(db, fake_clock, settings)

    await pipeline.handle(_console_event("你好", "tz-1"))
    first_replies = console.messages_for("u1")
    assert any("当前使用时区 Asia/Shanghai" in m["body"]["text"] for m in first_replies)

    await pipeline.handle(_console_event("再来一句", "tz-2"))
    replies = console.messages_for("u1")
    # 只有首答带时区说明
    assert sum("当前使用时区" in m["body"]["text"] for m in replies) == 1


def _timezone_script():
    """假 LLM：调用 set_timezone 工具，然后确认。"""
    state = {"phase": 0}

    def responder(messages: list[dict]) -> LLMResult:
        if state["phase"] == 0:
            state["phase"] = 1
            return LLMResult(
                content=None,
                tool_calls=[
                    ToolCall(id="c1", name="set_timezone", arguments={"timezone": "Asia/Tokyo"})
                ],
                usage=Usage(input=1, cached=0, output=1, reasoning=0),
            )
        return LLMResult(content="时区已更新。", usage=Usage(input=1, cached=0, output=1, reasoning=0))

    return responder


async def test_set_timezone_tool_updates_user(db, fake_clock, settings, make_pipeline):
    pipeline, console = make_pipeline(_timezone_script())
    await pipeline.handle(_console_event("把时区改成东京时间", "settz-1"))

    async with db() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.timezone == "Asia/Tokyo"
        assert user.rev == 2  # 创建 1 次 + 修改 1 次

    # 同一入站事件重放：不会重复处理（ingest 去重）
    await pipeline.handle(_console_event("把时区改成东京时间", "settz-1"))
    async with db() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.rev == 2

    # 换一条新消息再调 set_timezone：目标时区与现值相同，rev 不再递增
    await pipeline.handle(_console_event("再设一次东京时区", "settz-2"))
    async with db() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.rev == 2
        assert user.timezone == "Asia/Tokyo"


async def test_set_timezone_rejects_unknown_zone(db, fake_clock, settings, make_pipeline):
    def responder(messages: list[dict]) -> LLMResult:
        if any(m.get("role") == "tool" for m in messages):
            return LLMResult(content="已处理。", usage=Usage(input=1, cached=0, output=1, reasoning=0))
        return LLMResult(
            content=None,
            tool_calls=[ToolCall(id="c1", name="set_timezone", arguments={"timezone": "Mars/Olympus"})],
            usage=Usage(input=1, cached=0, output=1, reasoning=0),
        )

    pipeline, console = make_pipeline(responder)
    await pipeline.handle(_console_event("把时区改成火星时间", "settz-bad"))

    async with db() as session:
        user = (await session.execute(select(User))).scalar_one()
        assert user.timezone == "Asia/Shanghai"  # 未被修改
        tool_results = (
            await session.execute(select(EventLog).where(EventLog.type == "tool_result"))
        ).scalars().all()
    assert len(tool_results) == 1
    assert tool_results[0].payload["status"] == "error"
    assert "未知时区" in tool_results[0].payload["message"]


async def test_llm_daily_limit_blocks_and_agent_replies(db, fake_clock, settings):
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": FakeProvider(_plain_responder("你好！"))},
        sessionmaker=db,
        clock=fake_clock,
        daily_limit=1,
    )
    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    pipeline = InboundPipeline(
        sessionmaker=db, clock=fake_clock, settings=settings, gateway=gateway,
        adapters={"console": console},
    )

    await pipeline.handle(_console_event("第一句", "limit-1"))
    assert console.messages_for("u1")[-1]["body"]["text"].startswith("你好")

    # 当日第 2 次调用被拒绝：agent 回固定文案，不再计费
    await pipeline.handle(_console_event("第二句", "limit-2"))
    assert "额度" in console.messages_for("u1")[-1]["body"]["text"]

    async with db() as session:
        calls = (
            await session.execute(select(LLMCall).where(LLMCall.user_id.is_not(None)))
        ).scalars().all()
    assert len(calls) == 1  # 只有第一次真正到达了模型


async def test_provider_failure_gets_fallback_reply(db, fake_clock, settings, make_pipeline):
    """LLM 调用失败时用户收到兜底回复（而非沉默），outbound 事件照常落库。"""

    def responder(messages: list[dict]) -> LLMResult:
        raise RuntimeError("provider down")

    pipeline, console = make_pipeline(responder)
    await pipeline.handle(_console_event("你好", "err-1"))

    replies = console.messages_for("u1")
    assert any("出了点故障" in m["body"]["text"] for m in replies)
    # 兜底回复带 trace 片段，可据此定位日志与 llm_call.error
    assert "trace" in replies[-1]["body"]["text"]

    async with db() as session:
        calls = (await session.execute(select(LLMCall))).scalars().all()
        outbound = (
            await session.execute(select(EventLog).where(EventLog.direction == "outbound"))
        ).scalars().all()
    assert calls and calls[-1].error  # 网关已如实记录故障
    assert len(outbound) == 1 and outbound[0].payload["send_ok"] is True


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


async def test_secrets_absent_from_llm_call_and_logs(db, fake_clock):
    """带哨兵密钥跑一轮完整链路：llm_call 全字段与日志都不含密钥。"""
    from app.core.logging import JsonFormatter

    sentinel_settings = Settings(_env_file=None, llm_api_key=SECRET)
    gateway = LLMGateway(
        aliases_path=str(TEST_ALIASES),
        providers={"fake": FakeProvider(_plain_responder("收到"))},
        sessionmaker=db,
        clock=fake_clock,
        daily_limit=0,
    )
    console = ConsoleAdapter(make_identity_resolver(db, "console"))
    pipeline = InboundPipeline(
        sessionmaker=db, clock=fake_clock, settings=sentinel_settings, gateway=gateway,
        adapters={"console": console},
    )

    handler = _ListHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        await pipeline.handle(_console_event("记一下：买牛奶", "sec-1"))
    finally:
        root.removeHandler(handler)

    assert SECRET not in "\n".join(handler.lines)

    async with db() as session:
        calls = (await session.execute(select(LLMCall))).scalars().all()
    assert len(calls) >= 1
    for call in calls:
        dump = str(
            [call.alias, call.provider, call.model_id, call.params, call.request, call.response, call.error]
        )
        assert SECRET not in dump
