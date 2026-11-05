.PHONY: up down migrate test test-strict lint

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
