"""嵌入：假 provider 的维度/归一化/确定性，以及 query 指令前缀。"""

import math

import pytest

from app.embeddings.base import EmbeddingKind, EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.ollama import QUERY_INSTRUCTION, OllamaEmbeddingProvider
from app.embeddings.service import EmbeddingError, EmbeddingService


async def test_fake_provider_is_deterministic_and_normalized() -> None:
    service = EmbeddingService(FakeEmbeddingProvider(1024), 1024)
    first = await service.embed_one("我平时7点起床", kind="document")
    second = await service.embed_one("我平时7点起床", kind="document")
    assert len(first) == 1024
    assert first == second
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0, rel_tol=1e-9)


async def test_service_truncates_to_configured_dimension() -> None:
    service = EmbeddingService(FakeEmbeddingProvider(8), 4)
    vector = await service.embed_one("你好")
    assert len(vector) == 4
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)


class _ZeroProvider(EmbeddingProvider):
    name = "zero"
    model = "zero-model"

    async def embed(self, texts: list[str], *, kind: EmbeddingKind) -> list[list[float]]:
        return [[0.0, 0.0, 0.0, 0.0] for _ in texts]


async def test_zero_vector_is_rejected() -> None:
    service = EmbeddingService(_ZeroProvider(), 4)
    with pytest.raises(EmbeddingError):
        await service.embed_one("你好")


def test_query_instruction_matches_model_card() -> None:
    assert OllamaEmbeddingProvider._format("为什么天是蓝的", "query") == (
        f"Instruct: {QUERY_INSTRUCTION}\nQuery:为什么天是蓝的"
    )
    assert OllamaEmbeddingProvider._format("文档内容", "document") == "文档内容"
