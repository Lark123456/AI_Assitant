.PHONY: up down migrate test test-strict lint ollama-pull check-embedding memory-evals test-embedding

up:
	docker compose up -d --build

down:
	docker compose down

migrate:
	docker compose run --rm api uv run --no-dev alembic upgrade head

test:
	uv run pytest -q

test-strict:
	# DB 不可用时集成测试直接失败（CI 用），而不是跳过
	REQUIRE_DB=1 uv run pytest -q

lint:
	uv run ruff check app tests scripts
	uv run mypy app

# 一次性拉取嵌入模型（639MB）；之后 make up 即可
ollama-pull:
	docker compose up -d ollama
	docker compose exec ollama ollama pull qwen3-embedding:0.6b

# 人工验收嵌入：宿主机直连 127.0.0.1:11434
check-embedding:
	uv run python scripts/check_embedding.py

# 真实模型记忆评测（手动运行，不进 CI）
memory-evals:
	uv run python scripts/run_memory_evals.py

# 真实 Ollama 的嵌入测试（默认跳过）
test-embedding:
	REQUIRE_DB=1 REQUIRE_EMBEDDING=1 uv run pytest -q -m requires_embedding
