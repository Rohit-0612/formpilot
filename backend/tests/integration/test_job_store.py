"""Job status transitions against Postgres. JobStore opens its own sessions, so rows are really
committed: these tests clean up with TRUNCATE (truncate_all) instead of a rollback [A1]."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Document, Job, User
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
    assert running.started_at is not None
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


async def test_started_at_is_set_only_when_running(engine: AsyncEngine, store: JobStore) -> None:
    job_id = await _queued_job(engine)
    queued = await store.get(job_id)
    assert queued is not None
    assert queued.started_at is None

    await store.mark_running(job_id)

    running = await store.get(job_id)
    assert running is not None
    assert running.started_at is not None
    assert running.started_at >= running.created_at


# --- stale jobs (decision D6) ------------------------------------------------------

TIMEOUT = 300
LONG_AGO = timedelta(seconds=TIMEOUT + 60)
RECENTLY = timedelta(seconds=TIMEOUT - 60)


async def _seed(engine: AsyncEngine, rows: dict[str, dict]) -> dict[str, uuid.UUID]:
    """Insert one job per name (with an own document if "document" is given); return job ids.

    Each spec holds the job's status, how long ago it started ("started", None = NULL) and was
    created ("created"), and optionally its document's status.
    """
    now = datetime.now(UTC)
    ids: dict[str, uuid.UUID] = {}
    async with make_sessionmaker(engine)() as session:
        owner = User(email="owner@example.com", password_hash="$argon2id$not-a-real-hash")
        session.add(owner)
        await session.flush()
        for name, spec in rows.items():
            document_id = None
            if "document" in spec:
                document = Document(
                    owner_id=owner.id,
                    original_filename="blank-form.pdf",
                    sha256="0" * 64,
                    status=spec["document"],
                    expires_at=now + timedelta(hours=24),
                )
                session.add(document)
                await session.flush()
                document_id = document.id
            started = spec.get("started")
            job = Job(
                type="analyze" if document_id else "ping",
                document_id=document_id,
                status=spec["status"],
                created_at=now - spec.get("created", LONG_AGO),
                started_at=None if started is None else now - started,
                finished_at=now if spec["status"] in ("done", "failed") else None,
            )
            session.add(job)
            await session.flush()
            ids[name] = job.id
        await session.commit()
    return ids


async def _document_status(engine: AsyncEngine, job_id: uuid.UUID) -> str:
    async with make_sessionmaker(engine)() as session:
        job = await session.get(Job, job_id)
        assert job is not None and job.document_id is not None
        document = await session.get(Document, job.document_id)
        assert document is not None
        return document.status


async def test_fail_stale_fails_only_jobs_running_longer_than_the_timeout(
    engine: AsyncEngine, store: JobStore
) -> None:
    ids = await _seed(
        engine,
        {
            "stale": {"status": "running", "started": LONG_AGO, "document": "analyzing"},
            "fresh": {"status": "running", "started": RECENTLY, "document": "analyzing"},
            # A job created long ago that waited in the queue is not stale once it starts.
            "late_start": {"status": "running", "started": RECENTLY, "created": LONG_AGO},
            "queued": {"status": "queued", "created": LONG_AGO},
            "done": {"status": "done", "started": LONG_AGO},
            "failed": {"status": "failed", "started": LONG_AGO},
            # Rows from before migration 0002 have no started_at: created_at decides.
            "legacy_stale": {"status": "running", "started": None, "created": LONG_AGO},
            "legacy_fresh": {"status": "running", "started": None, "created": RECENTLY},
        },
    )

    failed = await store.fail_stale(TIMEOUT)

    assert set(failed) == {ids["stale"], ids["legacy_stale"]}
    for name in ("stale", "legacy_stale"):
        job = await store.get(ids[name])
        assert job is not None
        assert (job.status, job.error) == ("failed", "Stale"), name
        assert job.finished_at is not None
    expected_unchanged = {
        "fresh": "running",
        "late_start": "running",
        "queued": "queued",
        "done": "done",
        "failed": "failed",
        "legacy_fresh": "running",
    }
    for name, status in expected_unchanged.items():
        job = await store.get(ids[name])
        assert job is not None
        assert (job.status, job.error) == (status, None), name
    assert await _document_status(engine, ids["stale"]) == "failed"
    assert await _document_status(engine, ids["fresh"]) == "analyzing"


async def test_fail_stale_only_moves_analyzing_documents(
    engine: AsyncEngine, store: JobStore
) -> None:
    ids = await _seed(
        engine,
        {
            "analyzing": {"status": "running", "started": LONG_AGO, "document": "analyzing"},
            "ready": {"status": "running", "started": LONG_AGO, "document": "ready"},
        },
    )

    assert set(await store.fail_stale(TIMEOUT)) == {ids["analyzing"], ids["ready"]}

    assert await _document_status(engine, ids["analyzing"]) == "failed"
    assert await _document_status(engine, ids["ready"]) == "ready"


async def test_fail_stale_with_nothing_stale_returns_no_ids(
    engine: AsyncEngine, store: JobStore
) -> None:
    await _seed(engine, {"fresh": {"status": "running", "started": RECENTLY}})

    assert await store.fail_stale(TIMEOUT) == []
