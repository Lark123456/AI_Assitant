"""确定性假嵌入：字符 unigram/bigram 特征哈希，测试不联网。"""

import hashlib
import math

from app.embeddings.base import EmbeddingKind, EmbeddingProvider


def _features(text: str) -> list[str]:
    cleaned = "".join(text.lower().split())
    feats = list(cleaned)
    feats.extend(cleaned[i : i + 2] for i in range(len(cleaned) - 1))
    return feats


class FakeEmbeddingProvider(EmbeddingProvider):
    """可复现的哈希嵌入；共享字词越多相似度越高。"""

    name = "fake"

    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim
        self.model = f"fake-hash-{dim}"

    async def embed(self, texts: list[str], *, kind: EmbeddingKind) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for feature in _features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]
