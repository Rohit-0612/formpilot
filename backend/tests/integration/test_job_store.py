"""Job status transitions against Postgres. JobStore opens its own sessions, so rows are really
committed: these tests clean up with TRUNCATE (truncate_all) instead of a rollback [A1]."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Job
from app.db.session import make_sessionmaker
from app.services.jobs import JobStore

pytestmark = pytest.mark.usefixtures("truncate_all")


@pytest.fixture
def store(engine: AsyncEngine) -> JobStore:
    return JobStore(make_sessionmaker(engine))


async def _queued_job(engine: AsyncEngine) -> uuid.UUID:
    async with make_sessionmaker(engine)() as session:
        job = Job(type="ping")
        session.add(job)
        await session.commit()
        return job.id


async def test_queued_to_running_to_done(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)

    assert await store.mark_running(job_id)
    running = await store.get(job_id)
    assert running is not None
    assert running.status == "running"
    assert running.finished_at is None

    assert await store.mark_done(job_id)
    done = await store.get(job_id)
    assert done is not None
    assert done.status == "done"
    assert done.finished_at is not None
    assert done.error is None


async def test_running_to_failed_records_the_reason(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)
    await store.mark_running(job_id)

    assert await store.mark_failed(job_id, "ValueError")

    failed = await store.get(job_id)
    assert failed is not None
    assert (failed.status, failed.error) == ("failed", "ValueError")
    assert failed.finished_at is not None


async def test_queued_can_fail_directly(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)

    assert await store.mark_failed(job_id, "EnqueueFailed:ConnectionError")


async def test_a_job_runs_at_most_once(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)

    assert await store.mark_running(job_id)
    assert not await store.mark_running(job_id)


@pytest.mark.parametrize("final", ["done", "failed"])
async def test_finished_jobs_cannot_change(
    engine: AsyncEngine, store: JobStore, final: str
) -> None:
    job_id = await _queued_job(engine)
    await store.mark_running(job_id)
    await (store.mark_done(job_id) if final == "done" else store.mark_failed(job_id, "X"))

    assert not await store.mark_running(job_id)
    assert not await store.mark_done(job_id)
    assert not await store.mark_failed(job_id, "Y")
    job = await store.get(job_id)
    assert job is not None
    assert job.status == final


async def test_done_requires_running(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)

    assert not await store.mark_done(job_id)


async def test_unknown_job_is_refused(store: JobStore) -> None:
    assert not await store.mark_running(uuid.uuid4())
