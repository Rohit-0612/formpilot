# Phase 1 — Skeleton and infrastructure: decision record

> Status: **draft, in progress.** Updated after each step; finalised with `/end-phase 1`.

## What was built

| Step | What | Where |
|---|---|---|
| 0 | AGPL-3.0 license, README stub, `.env.example` (placeholders only), decisions folder | `LICENSE`, `README.md`, `.env.example` |
| 1 | FastAPI app factory, pydantic-settings config, structlog JSON logging, request-logging middleware, `GET /api/v1/health` (Postgres + Redis probes with timeout, 503 when degraded) | `backend/app/{main,config,logging}.py`, `backend/app/api/`, `backend/app/services/health.py` |
| 2 | SQLAlchemy 2.0 models for the six SPEC §7 tables, Alembic initial migration `0001`, async session dependency, integration test harness (savepoint sessions, truncate helper), compose `postgres` + `redis`, first Makefile targets | `backend/app/db/`, `backend/alembic.ini`, `backend/tests/integration/`, `docker-compose.yml`, `Makefile` |
| 3 | Auth: Argon2id password hashing, HS256 JWT in an `fp_session` httpOnly cookie, `POST /auth/register`, `/auth/login`, `/auth/logout`, `GET /auth/me`, `current_user` dependency, value-free 422 and 500 responses | `backend/app/security.py`, `backend/app/services/users.py`, `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`, `backend/app/api/errors.py` |

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
- **`audit_events.document_id` is NOT NULL**, as in SPEC §7. Audit events for profile changes
  (no document) are a Phase 4 decision; see "Notes for the next phase".
- **Test isolation [A1].** `savepoint_session()` = one connection + outer transaction +
  `join_transaction_mode="create_savepoint"`; a test proves a `commit()` inside it leaves no row.
  `truncate_all_tables()` is for code with its own engine (the worker test in step 5).
  Integration tests use throwaway databases `formpilot_test` and `formpilot_test_migrations`,
  never the dev database. Alternative: `pytest-postgresql` / testcontainers — extra dependencies.
- **Drift check.** `compare_metadata` does not compare CHECK constraints, so a second test compares
  CHECK constraint names between the models and the migrated database, and a third inserts
  every Python enum value (catches a value added in code without a migration).

### Step 3 decisions
- **Argon2id via `argon2-cffi` defaults** (RFC 9106 low-memory profile). Hashing and verifying
  run in `asyncio.to_thread` so the ~50 ms of CPU does not block the event loop.
- **Unknown email costs the same as a wrong password.** Login verifies against a dummy hash when
  the email is unknown, and both cases return the same 401 body, so neither timing nor response
  reveals which emails exist at login.
- **Password rules [A4]:** register requires 8–128 characters (the upper bound stops a huge body
  from making Argon2 hash megabytes). Login only requires 1–128, so a short wrong password gets
  the normal 401, not a 422 that hints at the rules.
- **JWT claims:** `sub` (user id), `iat`, `exp`, all required; only HS256 accepted (tests reject
  HS512, `none`, another secret, tampering, expiry). Cookie: `HttpOnly; SameSite=Lax; Path=/`,
  `Max-Age` = `JWT_TTL_MINUTES`, `Secure` when `COOKIE_SECURE=true`.
- **Cookie auth in OpenAPI** via `APIKeyCookie(auto_error=False)`, so generated clients and
  `/docs` know about it while we still control the 401 body.
- **No values in errors or logs [A5]:**
  - FastAPI's default 422 body echoes each invalid `input` (e.g. the rejected password). A custom
    handler drops `input` and `url` from every validation error. This matters more in Phase 4,
    when Aadhaar/PAN values are validated.
  - Unhandled exceptions: the request middleware logs `exc_type` and the stack frames, never the
    exception message (an `IntegrityError` message contains `Key (email)=(...)`), and returns a
    500 with the request id itself, so uvicorn does not log the full exception either.
  - Auth logs carry `user_id` only; failed logins and duplicate registrations log no identifier.
- **Duplicate registration is detected by the unique constraint**, not a pre-check query, so
  two concurrent registrations cannot both succeed.

## Known limitations

- Cookie auth relies on the web app and API being same-site (true for `localhost:3000` →
  `localhost:8000`). A split-domain deployment (Phase 7) needs this revisited.
- Logout clears the cookie but does not revoke the JWT: a copied token stays valid until it
  expires (`JWT_TTL_MINUTES`, default 60). Revocation would need a server-side denylist or
  session table.
- No rate limiting or lockout on login or register.
- `POST /auth/register` returns 409 for an existing email, so registration reveals whether an
  email has an account (login does not).
- Only request-level exception logging strips messages. Code that calls `log.exception()`
  elsewhere would still log the message; app code must not do that with untrusted data.

## Open issues

### Known issues
- **Starlette `httpx2` deprecation warning (suppressed).** Starlette 1.7 warns that its
  `TestClient` should use `httpx2` instead of `httpx`. We did not add a dependency. A pytest
  `filterwarnings` entry in `backend/pyproject.toml` ignores exactly that message from exactly
  `starlette.exceptions.StarletteDeprecationWarning`; any other warning (including other
  Starlette deprecations) stays visible. Revisit when FastAPI's `TestClient` moves to `httpx2`,
  or before upgrading Starlette to a version that removes httpx support.

## Notes for the next phase

- **Phase 4 — audit events without a document.** The profile vault arrives in Phase 4, and
  profile changes are user actions with no document. `audit_events.document_id` is NOT NULL
  (SPEC §7), so Phase 4 must decide how these events are stored (e.g. make `document_id`
  nullable, or a separate `profile_audit_events` table) and add a migration if needed.
  Tracked as a Phase 4 deliverable in `docs/PLAN.md`.

_The rest is written at the end of Phase 1._

## In my own words

