"""Ollama 嵌入 provider（/api/embed），按模型卡加 query 指令前缀。"""

import asyncio

import httpx

from app.embeddings.base import EmbeddingKind, EmbeddingProvider

QUERY_INSTRUCTION = "Given a user message, retrieve relevant memories about the user"
BATCH_SIZE = 8


class EmbeddingError(RuntimeError):
    """嵌入调用失败（网络、协议或响应结构异常）。"""


class OllamaEmbeddingProvider(EmbeddingProvider):
    """CPU Ollama；批量切块、超时与有限重试。"""

    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 30.0,
        retries: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._retries = retries

    async def embed(self, texts: list[str], *, kind: EmbeddingKind) -> list[list[float]]:
        prepared = [self._format(text, kind) for text in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(prepared), BATCH_SIZE):
            vectors.extend(await self._embed_batch(prepared[start : start + BATCH_SIZE]))
        return vectors

    @staticmethod
    def _format(text: str, kind: EmbeddingKind) -> str:
        # 严格按 Qwen3-Embedding 模型卡：Instruct 与 Query 两行，document 不加前缀
        if kind == "query":
            return f"Instruct: {QUERY_INSTRUCTION}\nQuery:{text}"
        return text

    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        payload = {"model": self.model, "input": batch}
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(f"{self._base_url}/api/embed", json=payload)
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings")
                if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                    raise EmbeddingError(
                        f"ollama 返回向量数量不符：期望 {len(batch)}，实际 {embeddings!r}"
                    )
                return [[float(value) for value in vector] for vector in embeddings]
            except Exception as exc:  # 网络/协议错误统一重试，最终抛 EmbeddingError
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(1.0 * (2 ** attempt))
        raise EmbeddingError(f"ollama embed failed: {last_error}") from last_error
