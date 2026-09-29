# Phase 1 — Skeleton and infrastructure: decision record

> Status: **draft, in progress.** Updated after each step; finalised with `/end-phase 1`.

## What was built

| Step | What | Where |
|---|---|---|
| 0 | AGPL-3.0 license, README stub, `.env.example` (placeholders only), decisions folder | `LICENSE`, `README.md`, `.env.example` |
| 1 | FastAPI app factory, pydantic-settings config, structlog JSON logging, request-logging middleware, `GET /api/v1/health` (Postgres + Redis probes with timeout, 503 when degraded) | `backend/app/{main,config,logging}.py`, `backend/app/api/`, `backend/app/services/health.py` |
| 2 | SQLAlchemy 2.0 models for the six SPEC §7 tables, Alembic initial migration `0001`, async session dependency, integration test harness (savepoint sessions, truncate helper), compose `postgres` + `redis`, first Makefile targets | `backend/app/db/`, `backend/alembic.ini`, `backend/tests/integration/`, `docker-compose.yml`, `Makefile` |

## Key decisions and alternatives considered

### Taken when the plan was approved
- **uv** for Python packaging and locking (alternative: pip + venv — slower, no built-in lockfile).
- **JWT in an httpOnly, SameSite=Lax cookie** (alternative: Bearer token in localStorage —
  simpler, but any XSS could read the token; the app will hold PAN/Aadhaar).
- Dependencies not named in SPEC §9, approved: `uvicorn[standard]`, `psycopg[binary]` v3,
  `argon2-cffi`, `PyJWT`, `email-validator`, `structlog`, dev `pytest-asyncio` + `httpx`,
  web `openapi-fetch`.
- **Schema interpretation of SPEC §7:** UUID primary keys; `timestamptz`; enum-like columns as
  `VARCHAR` + `CHECK` (not native PG enums, so values can be added by a new migration);
  `jobs.type` gains `ping`; `jobs.document_id` nullable; `jobs.status` =
  `queued | running | done | failed`.
- **API additions to SPEC §8:** `POST /auth/logout` (clears the cookie), `GET /auth/me`
  (the dashboard needs to know who is logged in). The `ping` job is enqueued by a CLI, not an
  endpoint; `GET /jobs/{id}` is deferred to Phase 2.
- Amendments from review: savepoint-joined test sessions [A1]; no web service in compose until
  it has a real Dockerfile [A2]; `make up` generates `JWT_SECRET` [A3]; minimum password
  length 8 [A4]; never log email addresses [A5].

### Step 1 deviations (approved)
- **Router-level API prefix.** Each route module declares `APIRouter(prefix=API_PREFIX)`
  instead of `include_router(..., prefix="/api/v1")`. FastAPI 0.141 includes routers lazily
  and no longer bakes the include prefix into `route.path`, so the request log showed
  `/health`. The full template is only reachable through FastAPI private internals, which we
  do not want to depend on. Guarded by `test_request_log_route_includes_api_prefix` and
  `test_every_api_route_template_carries_the_prefix`.
  Alternative: mount the API as a sub-application and log `root_path + route.path` — rejected,
  it splits the OpenAPI document and middleware stack.
- **httpx / httpcore capped at WARNING.** The logging test caught `httpx` logging full URLs
  (including query strings) at INFO. That would leak data once the LLM provider makes HTTP
  calls. Alternative: a redaction processor — more code, and it can miss formats.
- **Early engine factory.** `app/db/session.py` was created in step 1 with only
  `make_engine()`, because the health check needs an engine. Sessions are added in step 2.
- **`redis` as an explicit dependency.** It was approved as part of `arq`, but the health check
  imports it directly, so it is declared explicitly in `pyproject.toml`.

### Step 2 decisions and deviations
- **Compose and Makefile started in step 2, not step 6.** Integration tests need Postgres, so
  `docker-compose.yml` (postgres + redis only) and `make services / test / test-int / lint /
  down` landed now. The `.env` bootstrap from [A3] is implemented here too (generated
  `JWT_SECRET`, file mode 600, never overwritten). Step 6 adds `api`, `worker` and the rest.
- **`DatabaseSettings` split out of `Settings`.** Alembic and the test harness only need
  `DATABASE_URL`; requiring `JWT_SECRET` to run a migration would be wrong. `Settings` extends it.
- **Schema details beyond SPEC §7** (all within the approved interpretation):
  `users.email` has a `CHECK (email = lower(email))` so lower-casing is enforced by the database,
  not only by the service; `documents.sha256` must be 64 chars; `page_count` is NULL or > 0;
  `form_ir_versions.version >= 1`; `documents.source_kind` is nullable until analysis runs.
  Status columns have **server** defaults (`uploaded`, `queued`) so raw SQL inserts match ORM
  inserts. Deterministic constraint names via a naming convention.
- **No separate index on `form_ir_versions.document_id`.** The unique
  `(document_id, version)` index already starts with it.
- **`audit_events.document_id` is NOT NULL**, as in SPEC §7. Phase 5 may want audit events for
  profile changes (no document); that would need a new migration and a decision.
- **Test isolation [A1].** `savepoint_session()` = one connection + outer transaction +
  `join_transaction_mode="create_savepoint"`; a test proves a `commit()` inside it leaves no row.
  `truncate_all_tables()` is for code with its own engine (the worker test in step 5).
  Integration tests use throwaway databases `formpilot_test` and `formpilot_test_migrations`,
  never the dev database. Alternative: `pytest-postgresql` / testcontainers — extra dependencies.
- **Drift check.** `compare_metadata` does not compare CHECK constraints, so a second test compares
  CHECK constraint names between the models and the migrated database, and a third inserts
  every Python enum value (catches a value added in code without a migration).

## Known limitations

- Cookie auth relies on the web app and API being same-site (true for `localhost:3000` →
  `localhost:8000`). A split-domain deployment (Phase 7) needs this revisited.

## Open issues

### Known issues
- **Starlette `httpx2` deprecation warning (suppressed).** Starlette 1.7 warns that its
  `TestClient` should use `httpx2` instead of `httpx`. We did not add a dependency. A pytest
  `filterwarnings` entry in `backend/pyproject.toml` ignores exactly that message from exactly
  `starlette.exceptions.StarletteDeprecationWarning`; any other warning (including other
  Starlette deprecations) stays visible. Revisit when FastAPI's `TestClient` moves to `httpx2`,
  or before upgrading Starlette to a version that removes httpx support.

## Notes for the next phase

_To be written at the end of Phase 1._

## In my own words

