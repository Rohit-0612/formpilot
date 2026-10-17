import asyncio
import io
import uuid

import pytest

from app.config import Settings
from app.jobs.tasks import FUNCTIONS, ping, run_tracked, shutdown, startup
from app.logging import configure_logging
from app.services.jobs import JobStore
from app.storage.local import LocalStorage

JOB_ID = str(uuid.UUID("00000000-0000-4000-8000-00000000000a"))
LEAKY_EMAIL = "asha.verma@example.com"


class FakeJobStore:
    def __init__(self, runnable: bool = True) -> None:
        self.runnable = runnable
        self.calls: list[tuple] = []

    async def mark_running(self, job_id: uuid.UUID) -> bool:
        self.calls.append(("running", job_id))
        return self.runnable

    async def mark_done(self, job_id: uuid.UUID) -> bool:
        self.calls.append(("done", job_id))
        return True

    async def mark_failed(self, job_id: uuid.UUID, error: str) -> bool:
        self.calls.append(("failed", job_id, error))
        return True


def _ctx(store: FakeJobStore) -> dict:
    return {"job_store": store}


async def test_ping_goes_running_then_done() -> None:
    store = FakeJobStore()

    outcome = await ping(_ctx(store), JOB_ID)

    assert outcome == "done"
    assert store.calls == [("running", uuid.UUID(JOB_ID)), ("done", uuid.UUID(JOB_ID))]


async def test_work_runs_between_running_and_done() -> None:
    store = FakeJobStore()
    seen: list[list[tuple]] = []

    async def work() -> None:
        seen.append(list(store.calls))

    await run_tracked(_ctx(store), JOB_ID, work)

    assert seen == [[("running", uuid.UUID(JOB_ID))]]


async def test_failure_is_recorded_as_class_name_and_not_raised() -> None:
    """Raising to arq would make arq log the exception message and store it in Redis."""
    store = FakeJobStore()
    stream = io.StringIO()
    configure_logging("INFO", json=True, stream=stream)

    async def work() -> None:
        raise ValueError(f"cannot read field for {LEAKY_EMAIL}")

    outcome = await run_tracked(_ctx(store), JOB_ID, work)

    assert outcome == "failed"
    assert store.calls[-1] == ("failed", uuid.UUID(JOB_ID), "ValueError")
    assert ("done", uuid.UUID(JOB_ID)) not in store.calls
    output = stream.getvalue()
    assert LEAKY_EMAIL not in output
    assert '"event": "job_failed"' in output
    assert '"exc_type": "ValueError"' in output
    assert f'"job_id": "{JOB_ID}"' in output


async def test_job_that_is_not_queued_is_skipped_without_running_work() -> None:
    store = FakeJobStore(runnable=False)
    ran = False

    async def work() -> None:
        nonlocal ran
        ran = True

    outcome = await run_tracked(_ctx(store), JOB_ID, work)

    assert outcome == "skipped"
    assert not ran
    assert store.calls == [("running", uuid.UUID(JOB_ID))]


async def test_cancellation_is_recorded_and_propagated() -> None:
    store = FakeJobStore()

    async def work() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_tracked(_ctx(store), JOB_ID, work)

    assert store.calls[-1] == ("failed", uuid.UUID(JOB_ID), "Cancelled")


def test_ping_is_registered_with_the_worker() -> None:
    assert ping in FUNCTIONS


# --- worker startup -------------------------------------------------------------------


async def test_startup_fails_stale_jobs_with_the_job_timeout_and_provides_storage(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeouts: list[int] = []

    async def fake_fail_stale(self: JobStore, timeout_seconds: int) -> list[uuid.UUID]:
        timeouts.append(timeout_seconds)
        return []

    monkeypatch.setattr(JobStore, "fail_stale", fake_fail_stale)
    ctx: dict = {"settings": settings.model_copy(update={"job_timeout_seconds": 123})}

    await startup(ctx)
    await shutdown(ctx)

    assert timeouts == [123]
    assert isinstance(ctx["job_store"], JobStore)
    assert isinstance(ctx["storage"], LocalStorage)


async def test_startup_survives_a_failing_stale_job_check(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a fresh database the worker starts before the migrations (`make up`)."""

    async def missing_table(self: JobStore, timeout_seconds: int) -> list[uuid.UUID]:
        raise RuntimeError('relation "jobs" does not exist')

    monkeypatch.setattr(JobStore, "fail_stale", missing_table)
    ctx: dict = {"settings": settings}

    await startup(ctx)  # does not raise
    await shutdown(ctx)

    output = capsys.readouterr().out
    assert '"event": "stale_jobs_check_failed"' in output
    assert '"event": "worker_started"' in output
