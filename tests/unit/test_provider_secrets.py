"""密钥安全（纯单元，无 DB）：API 密钥只出现在请求头，不进入请求体 / 响应 / 落库内容。"""

import json

import httpx

from app.llm.providers.openai_compat import OpenAICompatProvider

SECRET = "sk-test-secret-do-not-leak"


def _sse_handler(captured: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        chunks = [
            {"model": "deepseek-chat", "choices": [{"delta": {"content": "你好"}}]},
            {
                "model": "deepseek-chat",
                "choices": [{"delta": {}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        ]
        lines = "".join(f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks)
        lines += "data: [DONE]\n\n"
        return httpx.Response(
            200, content=lines.encode(), headers={"content-type": "text/event-stream"}
        )

    return handler


async def test_api_key_only_in_headers():
    captured: dict = {}
    provider = OpenAICompatProvider(
        "https://api.example.com/v1", SECRET, transport=httpx.MockTransport(_sse_handler(captured))
    )
    messages = [{"role": "user", "content": "hi"}]
    result = await provider.complete(
        model="deepseek-chat", messages=messages, tools=None, params={"timeout": 5}
    )

    # 密钥在 Authorization 头中（这是它唯一出现的位置）
    assert captured["headers"].get("authorization") == f"Bearer {SECRET}"
    # 请求体只含模型参数，不含密钥
    body_dump = json.dumps(captured["body"], ensure_ascii=False)
    assert SECRET not in body_dump
    assert captured["body"]["messages"] == messages
    # URL 不含密钥
    assert SECRET not in captured["url"]

    # 网关落库的内容（messages + 解析后的响应）同样不含密钥
    logged_dump = json.dumps(
        {"messages": messages, "response": {"content": result.content, "model_id": result.model_id}},
        ensure_ascii=False,
        default=str,
    )
    assert SECRET not in logged_dump
    assert result.content == "你好"


async def test_retry_on_server_error_then_success():
    """5xx 触发重试，密钥仍然只在头部。"""
    captured: dict = {}
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        captured["headers"] = dict(request.headers)
        if calls["n"] == 1:
            return httpx.Response(500)
        return httpx.Response(
            200,
            content=b'data: {"model": "m", "choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    provider = OpenAICompatProvider(
        "https://api.example.com/v1", SECRET, transport=httpx.MockTransport(handler)
    )
    result = await provider.complete(
        model="m", messages=[{"role": "user", "content": "x"}], tools=None, params={"timeout": 5}
    )
    assert calls["n"] == 2
    assert result.content == "ok"
    assert captured["headers"]["authorization"] == f"Bearer {SECRET}"
