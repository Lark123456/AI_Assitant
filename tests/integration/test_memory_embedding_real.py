"""真实 Ollama 嵌入：默认跳过，REQUIRE_EMBEDDING=1 时必须通过。"""

import math
import os

import pytest

from app.core.config import Settings
from app.embeddings.service import build_embedding_service

pytestmark = pytest.mark.requires_embedding


@pytest.mark.skipif(
    os.environ.get("REQUIRE_EMBEDDING") != "1",
    reason="需要真实 Ollama：设置 REQUIRE_EMBEDDING=1",
)
async def test_real_embedding_dimension_and_semantic_similarity() -> None:
    settings = Settings(_env_file=None)
    service = build_embedding_service(settings)
    vectors = await service.embed(
        ["我平时七点起床", "我习惯早上七点起床", "今天加班到九点"],
        kind="document",
    )
    assert len(vectors) == 3
    assert all(len(vector) == settings.embedding_dim for vector in vectors)
    for vector in vectors:
        assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-5)

    def cosine(left: list[float], right: list[float]) -> float:
        return sum(a * b for a, b in zip(left, right, strict=False))

    similar = cosine(vectors[0], vectors[1])
    unrelated = cosine(vectors[0], vectors[2])
    assert similar > unrelated
    assert similar >= 0.75
