"""JobService with a fake queue (the real queue is covered in test_worker.py)."""

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Job, JobType
from app.services.jobs import JobEnqueueError, JobService


class FakeQueue:
    def __init__(self, result: Any = "enqueued", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple] = []

    async def enqueue_job(self, function: str, *args: Any, _job_id: str | None = None) -> Any:
        self.calls.append((function, args, _job_id))
        if self.error:
            raise self.error
        return self.result


async def test_create_job_commits_a_queued_row_and_enqueues_by_id(
    db_session: AsyncSession,
) -> None:
    queue = FakeQueue()

    job = await JobService(db_session, queue).create_job(JobType.PING)

    assert job.status == "queued"
    assert job.type == "ping"
    assert job.document_id is None
    # Arguments are the job id only (arq logs arguments); arq's job id is ours too.
    assert queue.calls == [("ping", (str(job.id),), str(job.id))]


@pytest.mark.parametrize(
    ("queue", "expected_error"),
    [
        (
            FakeQueue(error=ConnectionError("redis://user:secret@host")),
            "EnqueueFailed:ConnectionError",
        ),
        (FakeQueue(result=None), "EnqueueFailed:JobEnqueueError"),
    ],
)
async def test_enqueue_failure_marks_the_row_failed(
    db_session: AsyncSession, queue: FakeQueue, expected_error: str
) -> None:
    with pytest.raises(JobEnqueueError) as excinfo:
        await JobService(db_session, queue).create_job(JobType.PING)

    (_, (job_id,), _) = queue.calls[0]
    assert str(excinfo.value) == job_id
    job = await db_session.get(Job, uuid.UUID(job_id))
    assert job is not None
    assert job.status == "failed"
    assert job.error == expected_error
    assert job.finished_at is not None
