"""LLM 网关的数据结构。"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """一次工具调用的规范化表示。"""

    id: str
    name: str
    arguments: dict


@dataclass
class Usage:
    """四类 token 计数（缺失时为 None）。"""

    input: int | None
    cached: int | None
    output: int | None
    reasoning: int | None


@dataclass
class LLMResult:
    """chat() 的统一返回；provider 差异已在 provider 内消化。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str | None = None
    usage: Usage | None = None
    model_id: str = ""
    latency_ms: int = 0
    ttft_ms: int | None = None
    structured: Any | None = None  # response_model 校验通过后的对象
