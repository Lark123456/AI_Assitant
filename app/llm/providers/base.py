"""Provider 抽象：provider 差异（推理内容、缓存字段、流式细节）封装在实现内部。"""

from abc import ABC, abstractmethod

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
    ) -> LLMResult:
        """执行一次对话补全，返回规范化 LLMResult。失败必须抛异常，不得吞掉。"""
