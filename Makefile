# FormPilot developer commands. Works with GNU make 3.81 (macOS default).
SHELL := /bin/bash
COMPOSE := docker compose
BACKEND := cd backend &&

.PHONY: vault-key up down migrate ping logs types services test test-int lint label-tasks label-convert label-semantic label-semantic-merge label-semantic-reference label-examples label-images eval-detect eval eval-fill eval-validators eval-questions eval-address render-samples

# Created once from .env.example with a freshly generated JWT_SECRET. Never overwritten.
.env:
	@cp .env.example .env && chmod 600 .env
	@sed -i.bak "s/^JWT_SECRET=$$/JWT_SECRET=$$(openssl rand -hex 32)/" .env && rm -f .env.bak
	@echo "Created .env with a generated JWT_SECRET"

## Give .env a generated VAULT_KEY (a Fernet key) if it has none; an existing key is never changed
vault-key: .env
	@if ! grep -q '^VAULT_KEY=.' .env; then \
		key=$$(openssl rand -base64 32 | tr '+/' '-_'); \
		if grep -q '^VAULT_KEY=' .env; then \
			sed -i.bak "s|^VAULT_KEY=$$|VAULT_KEY=$$key|" .env && rm -f .env.bak; \
		else [ -z "$$(tail -c 1 .env)" ] || echo >> .env; echo "VAULT_KEY=$$key" >> .env; fi; \
		echo "Added a generated VAULT_KEY to .env"; fi

## Build and start everything and wait until healthy (the one-shot migrate service applies the
## migrations before api and worker start)
up: .env vault-key
	$(COMPOSE) up -d --build --wait

## Stop all containers (data volumes are kept)
down:
	$(COMPOSE) down

## Apply Alembic migrations inside the api container (e.g. a new migration on a running stack)
migrate:
	$(COMPOSE) exec -T api alembic upgrade head

## Enqueue a ping job and wait until the worker marks it done (exit 1 otherwise)
ping:
	$(COMPOSE) exec -T api python -m app.jobs.cli ping --wait 30

## Follow the logs of all services
logs:
	$(COMPOSE) logs -f --tail=100

## Regenerate web/openapi.json and the web app's API types from the backend (no server needed)
types:
	$(BACKEND) uv run python -m app.openapi_export ../web/openapi.json
	cd web && npm run --silent types

## Start only Postgres and Redis (for integration tests and host-side development)
services: .env vault-key
	$(COMPOSE) up -d --wait postgres redis

## Unit tests (no network, no database)
test:
	$(BACKEND) uv run pytest -m unit

## Integration tests against the compose Postgres and Redis
test-int: services
	$(BACKEND) uv run pytest -m integration

## Lint, format check and type check (backend and web)
lint:
	$(BACKEND) uv run ruff check . ../eval && uv run ruff format --check . ../eval
	cd web && npm run --silent lint && npm run --silent typecheck

# ---------- Labelling (eval/labelling/README.md) ----------
# Run from the repo root: eval/ is importable from here, app/ through PYTHONPATH.
EVAL_PY := PYTHONPATH=backend uv run --project backend python -m

## Render the dev pages and write Label Studio tasks (with detector pre-annotations)
label-tasks:
	$(EVAL_PY) eval.labelling.tasks

## Convert a Label Studio JSON export into eval/labels/<form>.json (run by the human labeller)
label-convert:
	@test -n "$(EXPORT)" || (echo "usage: make label-convert EXPORT=path/to/export.json [OVERWRITE=1]" && exit 2)
	$(EVAL_PY) eval.labelling.convert "$(EXPORT)" $(if $(OVERWRITE),--overwrite,)

## Blind semantic-type labelling (Phase 3): write the local labelling page (gitignored)
label-semantic:
	$(EVAL_PY) eval.labelling.semantic sheet

## Merge a semantic-label export into eval/labels/ (only semantic_type is written)
label-semantic-merge:
	@test -n "$(EXPORT)" || (echo "usage: make label-semantic-merge EXPORT=path/to/export.json [OVERWRITE=1]" && exit 2)
	$(EVAL_PY) eval.labelling.semantic merge "$(EXPORT)" $(if $(OVERWRITE),--overwrite,)

## Write semantic reference labels (Claude-written, decision P3-D6) into eval/labels_semantic/
label-semantic-reference:
	@test -n "$(EXPORT)" || (echo "usage: make label-semantic-reference EXPORT=path/to/export.json BY='who labelled'" && exit 2)
	$(EVAL_PY) eval.labelling.semantic reference "$(EXPORT)" --by "$(BY)" $(if $(OVERWRITE),--overwrite,)

## Render the README example images from the synthetic fixtures (committed)
label-images:
	$(EVAL_PY) eval.labelling.examples --synthetic

## Render the same examples on the dev forms (local only, never committed)
label-examples:
	$(EVAL_PY) eval.labelling.examples

## Detection eval on the dev split: detector boxes vs eval/labels -> eval/reports/ (Phase 2)
## Optional TAG=<name> names the run, e.g. make eval-detect TAG=pre-step11-tuning
eval-detect:
	$(EVAL_PY) eval.detection --split dev $(if $(TAG),--tag $(TAG),)

## Understanding eval on the dev split (Phase 3): MODE=hybrid|llm|rules; replays the recorded model
## answers by default, RECORD=1 asks the model and records them, LIVE=1 skips the cache.
## PROVIDER=ollama|groq and MODEL=<name> pick the model (default Ollama qwen3:8b); Groq reads
## GROQ_API_KEY from .env
eval:
	$(EVAL_PY) eval.run_eval --split dev --mode $(or $(MODE),hybrid) $(if $(PROVIDER),--provider $(PROVIDER),) $(if $(MODEL),--model $(MODEL),) --cache $(if $(RECORD),record,$(if $(LIVE),off,replay)) $(if $(TAG),--tag $(TAG),) $(if $(BASELINE),--write-baseline,)

## Fill eval on the dev split (Phase 4): candidate fill policies x personas, replaying the
## recorded understanding answers; PROVIDER/MODEL as for eval (default Groq gpt-oss-120b, P4-D1)
eval-fill:
	$(EVAL_PY) eval.fill_eval $(if $(PROVIDER),--provider $(PROVIDER),) $(if $(MODEL),--model $(MODEL),) $(if $(TAG),--tag $(TAG),) $(if $(BASELINE),--write-baseline,)

## Validator eval (Phase 4): catch rate on eval/invalid_inputs.json, false rejects on the personas
eval-validators:
	$(EVAL_PY) eval.validator_eval

## Questions eval (Phase 5): suggestions per floor, questions per form before / after, readability;
## replays the recorded understanding answers (default Groq, P4-D1). SAMPLE=1 writes the frozen
## faithfulness sample once (eval/readability/sample-dev.json)
eval-questions:
	$(EVAL_PY) eval.questions_eval $(if $(PROVIDER),--provider $(PROVIDER),) $(if $(MODEL),--model $(MODEL),) $(if $(TAG),--tag $(TAG),) $(if $(SAMPLE),--write-sample,)

## Free-text address eval (Phase 5): 30 synthetic addresses split by the answers prompt; replays the
## recorded answers by default, RECORD=1 asks the model (PROVIDER/MODEL as for eval-fill)
eval-address:
	$(EVAL_PY) eval.address_eval $(if $(PROVIDER),--provider $(PROVIDER),) $(if $(MODEL),--model $(MODEL),) --cache $(if $(RECORD),record,replay)

## Phase 5 acceptance check: the dev forms rendered with the full persona, to eval/renders/
## (git-ignored); replays the recorded understanding answers (PROVIDER/MODEL as for eval-fill)
render-samples:
	$(EVAL_PY) eval.render_samples $(if $(PROVIDER),--provider $(PROVIDER),) $(if $(MODEL),--model $(MODEL),)
