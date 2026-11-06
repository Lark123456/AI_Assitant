"""嵌入服务：provider 抽象、Ollama 实现、确定性假实现与服务封装。"""

from app.embeddings.base import EmbeddingKind, EmbeddingProvider
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.ollama import OllamaEmbeddingProvider
from app.embeddings.service import (
    EmbeddingError,
    EmbeddingService,
    build_embedding_service,
)

__all__ = [
    "EmbeddingError",
    "EmbeddingKind",
    "EmbeddingProvider",
    "EmbeddingService",
    "FakeEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "build_embedding_service",
]
