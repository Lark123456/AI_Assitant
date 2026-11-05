"""OpenAI 兼容 provider：httpx 异步、超时、有限重试、SSE 流式。

时间说明：latency/ttft 用 time.perf_counter 测量耗时，属于性能度量，
不属于业务时间语义，不受 Clock 注入约束。
"""

import asyncio
import json
import time

import httpx

from app.llm.providers.base import BaseProvider
from app.llm.schemas import LLMResult, ToolCall, Usage

MAX_ATTEMPTS = 3  # 1 次原始调用 + 2 次重试
STREAM = True


class OpenAICompatProvider(BaseProvider):
    """标准 /chat/completions 端点的实现（DeepSeek 等兼容端均可）。"""

    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport  # 测试注入 MockTransport 用；生产为 None

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        params: dict,
    ) -> LLMResult:
        payload: dict = {"model": model, "messages": messages, **params}
        if tools:
            payload["tools"] = tools
        if STREAM:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return await self._request_with_retries(payload, timeout=params.get("timeout", 30))

    async def _request_with_retries(self, payload: dict, timeout: float) -> LLMResult:
        last_exc: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                return await self._do_request(payload, timeout)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                last_exc = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
            await asyncio.sleep(0.2 * (2**attempt))
        assert last_exc is not None
        raise last_exc

    async def _do_request(self, payload: dict, timeout: float) -> LLMResult:
        start = time.perf_counter()
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(timeout, connect=10.0),
            transport=self._transport,
        ) as client:
            if payload.get("stream"):
                result = await self._stream_once(client, payload, start)
            else:
                result = await self._non_stream_once(client, payload, start)
        return result

    async def _non_stream_once(self, client: httpx.AsyncClient, payload: dict, start: float) -> LLMResult:
        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        body = resp.json()
        return self._from_full_response(body, latency_ms=_ms_since(start), ttft_ms=None)

    async def _stream_once(self, client: httpx.AsyncClient, payload: dict, start: float) -> LLMResult:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        usage = Usage(input=None, cached=None, output=None, reasoning=None)
        ttft_ms: int | None = None
        model_id = ""

        async with client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if ttft_ms is None:
                    ttft_ms = _ms_since(start)
                model_id = model_id or chunk.get("model", "")
                u = chunk.get("usage")
                if u:
                    usage = _parse_usage(u)
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        content_parts.append(delta["content"])
                    reasoning_chunk = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning_chunk:
                        reasoning_parts.append(str(reasoning_chunk))
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]

        calls = [
            ToolCall(id=slot["id"], name=slot["name"], arguments=_parse_json_args(slot["arguments"]))
            for slot in tool_calls.values()
            if slot["name"]
        ]
        return LLMResult(
            content="".join(content_parts) or None,
            tool_calls=calls,
            reasoning="".join(reasoning_parts) or None,
            usage=usage,
            model_id=model_id,
            latency_ms=_ms_since(start),
            ttft_ms=ttft_ms,
        )

    def _from_full_response(self, body: dict, latency_ms: int, ttft_ms: int | None) -> LLMResult:
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=(tc.get("function") or {}).get("name", ""),
                arguments=_parse_json_args((tc.get("function") or {}).get("arguments")),
            )
            for tc in message.get("tool_calls") or []
        ]
        return LLMResult(
            content=message.get("content"),
            tool_calls=calls,
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            usage=_parse_usage(body.get("usage") or {}),
            model_id=body.get("model", ""),
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
        )


def _parse_json_args(raw: str | None) -> dict:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("tool call arguments must be a JSON object")
    return parsed


def _parse_usage(u: dict) -> Usage:
    completion_details = u.get("completion_tokens_details") or {}
    prompt_details = u.get("prompt_tokens_details") or {}
    cached = u.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = prompt_details.get("cached_tokens")
    return Usage(
        input=u.get("prompt_tokens"),
        cached=cached,
        output=u.get("completion_tokens"),
        reasoning=completion_details.get("reasoning_tokens"),
    )


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
