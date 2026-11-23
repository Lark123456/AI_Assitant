"""Provider 抽象：provider 差异（推理内容、缓存字段、流式细节）封装在实现内部。"""

from abc import ABC, abstractmethod
from collections.abc import Callable

from app.llm.schemas import LLMResult


class BaseProvider(ABC):
    """LLM 提供方的最小接口。"""

    name: str

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        params: dict,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResult:
        """执行一次对话补全，返回规范化 LLMResult。失败必须抛异常，不得吞掉。

        on_delta 收到的是「本次调用累计文本」，用于向外透传流式文本；
        实现可按自身流式能力调用，不要求逐 token。
        """
