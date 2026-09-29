# FormPilot developer commands. Works with GNU make 3.81 (macOS default).
SHELL := /bin/bash
COMPOSE := docker compose
BACKEND := cd backend &&

.PHONY: services test test-int lint down

# Created once from .env.example with a freshly generated JWT_SECRET. Never overwritten.
.env:
	@cp .env.example .env && chmod 600 .env
	@sed -i.bak "s/^JWT_SECRET=$$/JWT_SECRET=$$(openssl rand -hex 32)/" .env && rm -f .env.bak
	@echo "Created .env with a generated JWT_SECRET"

## Start only Postgres and Redis (for integration tests and host-side development)
services: .env
	$(COMPOSE) up -d --wait postgres redis

## Unit tests (no network, no database)
test:
	$(BACKEND) uv run pytest -m unit

## Integration tests against the compose Postgres and Redis
test-int: services
	$(BACKEND) uv run pytest -m integration

## Lint and format check
lint:
	$(BACKEND) uv run ruff check . && uv run ruff format --check .

## Stop all containers (data volumes are kept)
down:
	$(COMPOSE) down
