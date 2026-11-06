"""嵌入服务封装：维度校验、截断、L2 归一化与 provider 组装。"""

import math

from app.core.config import Settings
from app.embeddings.base import EmbeddingKind, EmbeddingProvider
from app.embeddings.ollama import OllamaEmbeddingProvider


class EmbeddingError(RuntimeError):
    """嵌入结果不可用（维度不足、数量不符或零向量）。"""


class EmbeddingService:
    """业务侧唯一嵌入入口；向量统一到固定维度并做 L2 归一化。"""

    def __init__(self, provider: EmbeddingProvider, dim: int) -> None:
        self._provider = provider
        self._dim = dim

    @property
    def model_name(self) -> str:
        return self._provider.model

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(
        self, texts: list[str], *, kind: EmbeddingKind = "document"
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors = await self._provider.embed(texts, kind=kind)
        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"嵌入数量不符：texts={len(texts)} vectors={len(vectors)}"
            )
        return [self._normalize(vector) for vector in vectors]

    async def embed_one(self, text: str, *, kind: EmbeddingKind = "document") -> list[float]:
        return (await self.embed([text], kind=kind))[0]

    def _normalize(self, vector: list[float]) -> list[float]:
        if len(vector) < self._dim:
            raise EmbeddingError(f"向量维度不足：{len(vector)} < {self._dim}")
        truncated = [float(value) for value in vector[: self._dim]]
        norm = math.sqrt(sum(value * value for value in truncated))
        if norm == 0.0:
            raise EmbeddingError("嵌入返回零向量")
        return [value / norm for value in truncated]


def build_embedding_service(settings: Settings) -> EmbeddingService:
    """按配置组装 Ollama provider。"""
    provider = OllamaEmbeddingProvider(
        settings.embedding_base_url,
        settings.embedding_model,
    )
    return EmbeddingService(provider, settings.embedding_dim)
