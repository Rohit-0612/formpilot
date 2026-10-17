"""arq task functions and worker lifecycle hooks.

Rules for every task:
- arguments are ids only (arq logs them);
- never raise to arq: arq would log the exception *message* and store the exception in Redis.
  run_tracked catches the error, records its class name on the job row and returns "failed".
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import Settings, get_settings
from app.db.session import make_engine, make_sessionmaker
from app.logging import configure_logging, get_logger
from app.services.jobs import JobStore
from app.storage import make_storage

log = get_logger(__name__)

Work = Callable[[], Awaitable[None]]


async def run_tracked(ctx: dict[str, Any], job_id: str, work: Work) -> str:
    """Run work for a job row: queued -> running -> done | failed. Returns the outcome."""
    store: JobStore = ctx["job_store"]
    job_uuid = uuid.UUID(job_id)
    job_log = log.bind(job_id=job_id)

    if not await store.mark_running(job_uuid):
        job_log.warning("job_skipped", reason="not_queued")
        return "skipped"
    job_log.info("job_started")
    try:
        await work()
    except asyncio.CancelledError:
        # Timeout or shutdown. Record it, then let arq see the cancellation.
        await asyncio.shield(store.mark_failed(job_uuid, "Cancelled"))
        job_log.warning("job_cancelled")
        raise
    except Exception as exc:
        job_log.exception("job_failed")
        await store.mark_failed(job_uuid, type(exc).__qualname__)
        return "failed"
    await store.mark_done(job_uuid)
    job_log.info("job_done")
    return "done"


async def _no_work() -> None:
    return None


async def ping(ctx: dict[str, Any], job_id: str) -> str:
    """No-op job that proves the enqueue -> worker -> job status path works."""
    return await run_tracked(ctx, job_id, _no_work)


FUNCTIONS = [ping]


async def startup(ctx: dict[str, Any]) -> None:
    # Tests pass their own settings in ctx; the real worker reads the environment.
    settings: Settings = ctx.get("settings") or get_settings()
    ctx["settings"] = settings
    configure_logging(settings.log_level, settings.log_json)
    engine = make_engine(settings)
    ctx["engine"] = engine
    ctx["job_store"] = store = JobStore(make_sessionmaker(engine))
    ctx["storage"] = make_storage(settings)
    await _fail_stale_jobs(store, settings.job_timeout_seconds)
    log.info("worker_started")


async def _fail_stale_jobs(store: JobStore, timeout_seconds: int) -> None:
    """Once per worker start (decision D6). A failure is logged at ERROR, not raised.

    Compose runs the migrations before the worker starts, so a failure here means a real
    problem (database down, schema behind). It is a safety net: the worker still starts, queued
    jobs can run, and the check runs again on the next start.
    """
    try:
        await store.fail_stale(timeout_seconds)
    except Exception:
        log.exception("stale_jobs_check_failed")  # structlog: level "error"


async def shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()
    log.info("worker_stopped")
