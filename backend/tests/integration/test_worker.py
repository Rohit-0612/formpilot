"""The real arq worker against real Redis and Postgres.

The worker and CLI use their own engines and commit for real, so these tests clean up with
TRUNCATE (truncate_all) and a flushed Redis test database (redis_url) [A1].
"""

import asyncio
import contextlib
import uuid
from typing import Any

import pytest
from arq import func
from arq.connections import RedisSettings
from arq.worker import Worker

from app.config import Settings
from app.db.models import Job
from app.db.session import make_engine, make_sessionmaker
from app.jobs.cli import enqueue_ping, run
from app.jobs.tasks import run_tracked
from app.jobs.worker import WorkerSettings
from app.services.jobs import QUEUE_NAME, JobStore, create_queue

pytestmark = pytest.mark.usefixtures("truncate_all")

LEAKY_EMAIL = "asha.verma@example.com"


def _worker(
    settings: Settings, *, burst: bool = True, extra_functions: list | None = None
) -> Worker:
    """A Worker configured exactly like WorkerSettings, but on the test Redis and database."""
    return Worker(
        functions=[*WorkerSettings.functions, *(extra_functions or [])],
        queue_name=WorkerSettings.queue_name,
        on_startup=WorkerSettings.on_startup,
        on_shutdown=WorkerSettings.on_shutdown,
        job_timeout=WorkerSettings.job_timeout,
        max_tries=WorkerSettings.max_tries,
        retry_jobs=WorkerSettings.retry_jobs,
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        ctx={"settings": settings},
        burst=burst,
        handle_signals=False,
        poll_delay=0.05,
    )


async def _job(settings: Settings, job_id: uuid.UUID) -> Job:
    engine = make_engine(settings)
    try:
        job = await JobStore(make_sessionmaker(engine)).get(job_id)
    finally:
        await engine.dispose()
    assert job is not None
    return job


def test_worker_settings_do_not_retry_and_use_our_queue() -> None:
    assert WorkerSettings.queue_name == QUEUE_NAME
    assert WorkerSettings.max_tries == 1
    assert WorkerSettings.retry_jobs is False
    assert "ping" in {function.__name__ for function in WorkerSettings.functions}


async def test_ping_job_goes_from_queued_to_done(live_settings: Settings) -> None:
    job_id = await enqueue_ping(live_settings)
    assert (await _job(live_settings, job_id)).status == "queued"

    worker = _worker(live_settings)
    try:
        await worker.main()
    finally:
        await worker.close()

    job = await _job(live_settings, job_id)
    assert job.status == "done"
    assert job.finished_at is not None
    assert job.error is None
    assert worker.jobs_complete == 1
    assert worker.jobs_failed == 0


async def test_failing_job_is_recorded_and_arq_never_sees_the_exception(
    live_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    async def boom() -> None:
        raise ValueError(f"could not parse the address of {LEAKY_EMAIL}")

    async def explode(ctx: dict[str, Any], job_id: str) -> str:
        return await run_tracked(ctx, job_id, boom)

    # A real job row, delivered to the failing test function.
    engine = make_engine(live_settings)
    async with make_sessionmaker(engine)() as session:
        row = Job(type="ping")
        session.add(row)
        await session.commit()
        job_id = row.id
    await engine.dispose()
    queue = await create_queue(live_settings)
    await queue.enqueue_job("explode", str(job_id), _job_id=str(job_id))
    await queue.aclose()

    worker = _worker(live_settings, extra_functions=[func(explode, name="explode")])
    try:
        await worker.main()
    finally:
        await worker.close()

    job = await _job(live_settings, job_id)
    assert (job.status, job.error) == ("failed", "ValueError")
    assert worker.jobs_failed == 0  # arq saw a normal return, so it logged/stored no exception
    output = capsys.readouterr()
    assert LEAKY_EMAIL not in output.out + output.err
    assert '"event": "job_failed"' in output.out


async def test_cli_ping_waits_for_the_worker(live_settings: Settings) -> None:
    worker = _worker(live_settings, burst=False)
    worker_task = asyncio.create_task(worker.main())
    try:
        exit_code = await run(["ping", "--wait", "15"], live_settings)
    finally:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
        await worker.close()

    assert exit_code == 0


async def test_cli_ping_without_worker_times_out_with_exit_code_1(live_settings: Settings) -> None:
    assert await run(["ping", "--wait", "0.5"], live_settings) == 1


async def test_cli_ping_without_wait_only_enqueues(live_settings: Settings) -> None:
    assert await run(["ping"], live_settings) == 0
