"""人工验收嵌入：打印维度、范数与句对相似度。

用法（宿主机，Ollama 已发布 127.0.0.1:11434）：
    make check-embedding
"""

import asyncio
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.embeddings.service import build_embedding_service  # noqa: E402

GROUPS = [
    ["我平时七点起床", "我习惯早上七点起床", "今天加班到九点"],
    ["我喜欢喝美式咖啡", "我更喜欢拿铁", "今天天气不错"],
]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


async def main_async() -> int:
    settings = get_settings()
    service = build_embedding_service(settings)
    print(f"base_url={settings.embedding_base_url} model={service.model_name} dim={service.dim}")
    for group_index, group in enumerate(GROUPS, start=1):
        vectors = await service.embed(group, kind="document")
        print(f"\n组 {group_index}")
        for text, vector in zip(group, vectors, strict=False):
            norm = math.sqrt(sum(value * value for value in vector))
            print(f"  dim={len(vector)} norm={norm:.4f}  {text}")
        print(f"  cosine[0,1]={cosine(vectors[0], vectors[1]):.4f}")
        print(f"  cosine[0,2]={cosine(vectors[0], vectors[2]):.4f}")
    query_vector = await service.embed_one("我通常几点起床？", kind="query")
    print(f"\nquery 前缀向量：dim={len(query_vector)}")
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception as exc:
        print(f"嵌入检查失败：{type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
