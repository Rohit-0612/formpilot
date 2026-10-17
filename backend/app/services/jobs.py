"""Background jobs: creating and enqueueing them, and recording their status.

The `jobs` row is the source of truth for a job's status; arq only delivers the work.
Job arguments are ids only: arq logs them when a job starts.

Status transitions (anything else is refused):
    queued  -> running           (worker picked it up)
    running -> done | failed     (work finished)
    queued  -> failed            (enqueueing failed)

A job left `running` longer than the job timeout (its worker crashed) is failed with error
"Stale" when a worker starts (JobStore.fail_stale, decision D6).
"""

import uuid
from datetime import timedelta
from typing import Any, Protocol

from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import QueueSettings
from app.db.models import Document, DocumentStatus, Job, JobStatus, JobType
from app.logging import get_logger

log = get_logger(__name__)

QUEUE_NAME = "formpilot:jobs"
STALE_ERROR = "Stale"


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any: ...


class JobEnqueueError(Exception):
    pass


async def create_queue(settings: QueueSettings) -> ArqRedis:
    return await create_pool(
        RedisSettings.from_dsn(settings.redis_url), default_queue_name=QUEUE_NAME
    )


class JobService:
    """Used by the API and the CLI to start jobs."""

    def __init__(self, session: AsyncSession, queue: JobQueue) -> None:
        self._session = session
        self._queue = queue

    async def create_job(self, job_type: JobType, document_id: uuid.UUID | None = None) -> Job:
        job = Job(type=job_type.value, document_id=document_id)
        self._session.add(job)
        # Commit before enqueueing, so the worker always finds the row.
        await self._session.commit()
        job_id = str(job.id)
        try:
            enqueued = await self._queue.enqueue_job(job_type.value, job_id, _job_id=job_id)
            if enqueued is None:  # arq refuses a job id it already has
                raise JobEnqueueError("job id already queued")
        except Exception as exc:
            log.exception("job_enqueue_failed", job_id=job_id, job_type=job_type.value)
            job.status = JobStatus.FAILED.value
            job.error = f"EnqueueFailed:{type(exc).__qualname__}"
            job.finished_at = func.now()
            await self._session.commit()
            await self._session.refresh(job)
            raise JobEnqueueError(job_id) from exc
        log.info(
            "job_enqueued",
            job_id=job_id,
            job_type=job_type.value,
            document_id=str(document_id) if document_id else None,
        )
        return job


class JobStore:
    """Used by the worker. Each call is its own short transaction."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, job_id: uuid.UUID) -> Job | None:
        async with self._sessionmaker() as session:
            return await session.get(Job, job_id)

    async def mark_running(self, job_id: uuid.UUID) -> bool:
        return await self._transition(
            job_id, {JobStatus.QUEUED}, JobStatus.RUNNING, started_at=func.now()
        )

    async def mark_done(self, job_id: uuid.UUID) -> bool:
        return await self._transition(
            job_id, {JobStatus.RUNNING}, JobStatus.DONE, finished_at=func.now()
        )

    async def mark_failed(self, job_id: uuid.UUID, error: str) -> bool:
        """error is a short reason such as an exception class name, never a value."""
        return await self._transition(
            job_id,
            {JobStatus.QUEUED, JobStatus.RUNNING},
            JobStatus.FAILED,
            finished_at=func.now(),
            error=error,
        )

    async def fail_stale(self, timeout_seconds: int) -> list[uuid.UUID]:
        """Fail jobs `running` for longer than timeout_seconds; return their ids.

        Such a job's worker died without recording an outcome (arq itself cancels a job at the
        timeout, and run_tracked records that). Rows without started_at (created before
        migration 0002) use created_at. Documents of these jobs that are still `analyzing`
        become `failed`. One transaction, so a job and its document change together.
        """
        stale_jobs = (
            update(Job)
            .where(
                Job.status == JobStatus.RUNNING.value,
                func.coalesce(Job.started_at, Job.created_at)
                < func.now() - timedelta(seconds=timeout_seconds),
            )
            .values(status=JobStatus.FAILED.value, error=STALE_ERROR, finished_at=func.now())
            .returning(Job.id, Job.document_id)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stale_jobs)).all()
            document_ids = {document_id for _, document_id in rows if document_id is not None}
            if document_ids:
                await session.execute(
                    update(Document)
                    .where(
                        Document.id.in_(document_ids),
                        Document.status == DocumentStatus.ANALYZING.value,
                    )
                    .values(status=DocumentStatus.FAILED.value)
                )
            await session.commit()
        job_ids = [job_id for job_id, _ in rows]
        if job_ids:
            log.warning("stale_jobs_failed", count=len(job_ids), job_ids=[str(i) for i in job_ids])
        return job_ids

    async def _transition(
        self,
        job_id: uuid.UUID,
        from_statuses: set[JobStatus],
        to_status: JobStatus,
        **values: Any,
    ) -> bool:
        """Conditional UPDATE: only succeeds if the job is currently in one of from_statuses."""
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status.in_([status.value for status in from_statuses]))
            .values(status=to_status.value, **values)
        )
        async with self._sessionmaker() as session:
            result = await session.execute(statement)
            await session.commit()
        changed = result.rowcount == 1  # type: ignore[attr-defined]
        if not changed:
            log.warning("job_transition_refused", job_id=str(job_id), to_status=to_status.value)
        return changed
