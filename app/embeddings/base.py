"""嵌入 provider 接口。"""

from abc import ABC, abstractmethod
from typing import Literal

EmbeddingKind = Literal["query", "document"]


class EmbeddingProvider(ABC):
    """嵌入提供方的最小接口；失败必须抛异常，不得吞掉。"""

    name: str
    model: str

    @abstractmethod
    async def embed(self, texts: list[str], *, kind: EmbeddingKind) -> list[list[float]]:
        """返回与 texts 等长的向量列表（尚未归一化）。"""
