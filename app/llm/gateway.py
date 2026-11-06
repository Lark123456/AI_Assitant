"""LLM 网关：别名路由、response_model 校验与修复重试、每日限额、llm_call 落库。"""

import json
import uuid
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.clock import UTC, Clock
from app.core.logging import get_logger
from app.db.models import LLMCall, User
from app.llm.aliases import AliasConfig, load_aliases
from app.llm.providers.base import BaseProvider
from app.llm.schemas import LLMResult

MAX_REPAIR_ATTEMPTS = 2

logger = get_logger(__name__)


class UnknownAliasError(KeyError):
    pass


class StructuredOutputError(RuntimeError):
    """response_model 校验在修复重试后仍失败。"""


class BudgetExceededError(RuntimeError):
    """超出每用户每日 LLM 调用上限。"""


class LLMGateway:
    """所有模型调用唯一入口。"""

    def __init__(
        self,
        *,
        aliases_path: str,
        providers: dict[str, BaseProvider],
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        daily_limit: int = 0,
    ) -> None:
        self._aliases: dict[str, AliasConfig] = load_aliases(aliases_path)
        self._providers = providers
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._daily_limit = daily_limit

    async def chat(
        self,
        *,
        alias: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_model: type[BaseModel] | None = None,
        trace_id: str = "",
        user_id: uuid.UUID | None = None,
    ) -> LLMResult:
        """按别名调用模型；response_model 校验失败时最多修复重试 2 次。"""
        if self._daily_limit > 0 and user_id is not None:
            await self._enforce_daily_limit(user_id)
        cfg = self._aliases.get(alias)
        if cfg is None:
            raise UnknownAliasError(alias)
        provider = self._providers.get(cfg.provider)
        if provider is None:
            raise UnknownAliasError(f"provider {cfg.provider} not registered")

        work_messages = list(messages)
        result: LLMResult | None = None
        if response_model is None:
            result = await self._call_and_log(alias, provider, cfg, work_messages, tools, trace_id, user_id)
        else:
            error: str | None = None
            for _attempt in range(MAX_REPAIR_ATTEMPTS + 1):
                result = await self._call_and_log(
                    alias, provider, cfg, work_messages, tools, trace_id, user_id
                )
                parsed, error = _validate_structured(result.content, response_model)
                if parsed is not None:
                    result.structured = parsed
                    break
                work_messages = work_messages + [
                    {"role": "assistant", "content": result.content or ""},
                    {"role": "user", "content": f"输出未通过校验：{error}\n请严格按 JSON Schema 重新输出。"},
                ]
            else:
                raise StructuredOutputError(f"alias {alias}: {error}")
        assert result is not None
        return result

    async def _enforce_daily_limit(self, user_id: uuid.UUID) -> None:
        """每用户每日调用上限：按用户时区当日 0 点起计数 llm_call，超限抛 BudgetExceededError。"""
        async with self._sessionmaker() as session:
            tz = (
                await session.execute(select(User.timezone).where(User.id == user_id))
            ).scalar_one_or_none()
            day_start_local = self._clock.now_tz(tz or "UTC").replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            day_start_utc = day_start_local.astimezone(UTC)
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(LLMCall)
                    .where(LLMCall.user_id == user_id, LLMCall.created_at >= day_start_utc)
                )
            ).scalar_one()
        if count >= self._daily_limit:
            logger.warning(
                "llm daily limit exceeded: user_id=%s count=%d limit=%d",
                user_id, count, self._daily_limit,
            )
            raise BudgetExceededError(
                f"daily limit reached: user={user_id} count={count} limit={self._daily_limit}"
            )

    async def _call_and_log(
        self,
        alias: str,
        provider: BaseProvider,
        cfg: AliasConfig,
        messages: list[dict],
        tools: list[dict] | None,
        trace_id: str,
        user_id: uuid.UUID | None,
    ) -> LLMResult:
        error: str | None = None
        result: LLMResult | None = None
        try:
            result = await provider.complete(
                model=cfg.model, messages=messages, tools=tools, params=cfg.params
            )
        except Exception as exc:  # 记录后原样上抛，不吞异常
            error = f"{type(exc).__name__}: {exc}"
            await self._write_llm_call(alias, cfg, provider, messages, tools, trace_id, user_id, None, error)
            raise
        await self._write_llm_call(alias, cfg, provider, messages, tools, trace_id, user_id, result, None)
        assert result is not None
        return result

    async def _write_llm_call(
        self,
        alias: str,
        cfg: AliasConfig,
        provider: BaseProvider,
        messages: list[dict],
        tools: list[dict] | None,
        trace_id: str,
        user_id: uuid.UUID | None,
        result: LLMResult | None,
        error: str | None,
    ) -> None:
        """每次模型调用（含失败）都写入 llm_call 表；model_id 优先记模型实际返回的 id。"""
        row = LLMCall(
            trace_id=trace_id,
            user_id=user_id,
            alias=alias,
            provider=provider.name,
            # 实际模型 id 以响应为准（控制台切换模型时与配置不同）；缺失时回退配置
            model_id=(result.model_id or cfg.model) if result is not None else cfg.model,
            params=cfg.params,
            request={"messages": messages, "tools": tools},
            response=None
            if result is None
            else {
                "content": result.content,
                "reasoning": result.reasoning,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls
                ],
            },
            input_tokens=None if result is None or result.usage is None else result.usage.input,
            cached_tokens=None if result is None or result.usage is None else result.usage.cached,
            output_tokens=None if result is None or result.usage is None else result.usage.output,
            reasoning_tokens=None if result is None or result.usage is None else result.usage.reasoning,
            latency_ms=None if result is None else result.latency_ms,
            ttft_ms=None if result is None else result.ttft_ms,
            error=error,
            created_at=self._clock.now(),
        )
        async with self._sessionmaker() as session:
            session.add(row)
            await session.commit()


def _validate_structured(content: str | None, model: type[BaseModel]) -> tuple[Any | None, str | None]:
    if not content:
        return None, "empty content"
    try:
        return model.model_validate_json(content), None
    except ValidationError as exc:
        return None, json.dumps(exc.errors(), ensure_ascii=False)
