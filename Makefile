# FormPilot developer commands. Works with GNU make 3.81 (macOS default).
SHELL := /bin/bash
COMPOSE := docker compose
BACKEND := cd backend &&

.PHONY: up down migrate ping logs services test test-int lint

# Created once from .env.example with a freshly generated JWT_SECRET. Never overwritten.
.env:
	@cp .env.example .env && chmod 600 .env
	@sed -i.bak "s/^JWT_SECRET=$$/JWT_SECRET=$$(openssl rand -hex 32)/" .env && rm -f .env.bak
	@echo "Created .env with a generated JWT_SECRET"

## Build and start everything, wait until healthy, then apply migrations
up: .env
	$(COMPOSE) up -d --build --wait
	$(MAKE) migrate

## Stop all containers (data volumes are kept)
down:
	$(COMPOSE) down

## Apply Alembic migrations inside the api container
migrate:
	$(COMPOSE) exec -T api alembic upgrade head

## Enqueue a ping job and wait until the worker marks it done (exit 1 otherwise)
ping:
	$(COMPOSE) exec -T api python -m app.jobs.cli ping --wait 30

## Follow the logs of all services
logs:
	$(COMPOSE) logs -f --tail=100

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
