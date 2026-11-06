"""The 24 h expiry (app/services/expiry.py): the sweep, the worker's start-up sweep, and the 410.

Synthetic fixture form and values only; no model (rules only). A document is made to expire by
moving its expires_at into the past.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import AuditEvent, Document, FormIRVersion, Job, JobStatus, JobType
from app.db.session import make_sessionmaker
from app.services import expiry
from app.storage import make_storage
from tests.integration.conftest import ClientFactory
from tests.integration.test_fill_api import DOCS
from tests.integration.test_review_api import _filled
from tests.integration.workers import make_worker

pytestmark = pytest.mark.usefixtures("truncate_all")


async def _expire(engine: AsyncEngine, document_id: str) -> None:
    async with make_sessionmaker(engine)() as session:
        await session.execute(
            update(Document)
            .where(Document.id == uuid.UUID(document_id))
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def _rows(engine: AsyncEngine, document_id: str) -> dict[str, int]:
    key = uuid.UUID(document_id)
    async with make_sessionmaker(engine)() as session:
        counts = {"document": int(await session.get(Document, key) is not None)}
        for model in (FormIRVersion, Job, AuditEvent):
            counts[model.__tablename__] = await session.scalar(
                select(func.count()).select_from(model).where(model.document_id == key)
            )
        return counts


async def _owner_id(engine: AsyncEngine, document_id: str) -> uuid.UUID:
    async with make_sessionmaker(engine)() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        assert document is not None
        return document.owner_id


async def test_the_sweep_deletes_expired_documents_and_keeps_the_rest(
    client_for: ClientFactory,
    live_settings: Settings,
    engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = await client_for()
    old = await _filled(client, live_settings)
    fresh = await _filled(client, live_settings)
    owner = await _owner_id(engine, old)
    await _expire(engine, old)
    storage = make_storage(live_settings)
    assert (await _rows(engine, old))["form_ir_versions"] >= 1
    capsys.readouterr()

    first = await expiry.sweep(make_sessionmaker(engine), storage)
    again = await expiry.sweep(make_sessionmaker(engine), storage)

    assert (first, again) == (expiry.SweepResult(1, 0), expiry.SweepResult(0, 0))
    assert await _rows(engine, old) == {
        "document": 0, "form_ir_versions": 0, "jobs": 0, "audit_events": 0,
    }  # fmt: skip
    assert not await storage.exists(f"documents/{old}/original.pdf")
    assert not await storage.exists(f"documents/{old}/pages/0.png")
    assert (await _rows(engine, fresh))["document"] == 1
    assert await storage.exists(f"documents/{fresh}/original.pdf")
    # One audit event on the owner, with no document id, field or value.
    async with make_sessionmaker(engine)() as session:
        events = (
            await session.scalars(select(AuditEvent).where(AuditEvent.event == "document_expired"))
        ).all()
    assert [(e.user_id, e.document_id, e.field_id, e.actor) for e in events] == [
        (owner, None, None, "system")
    ]
    # The logs hold counts only.
    sweeps = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if "expired_documents_swept" in line
    ]
    assert [(s["deleted"], s["busy"]) for s in sweeps] == [(1, 0), (0, 0)]
    assert old not in json.dumps(sweeps)


async def test_an_expired_document_with_a_running_job_waits_for_the_next_sweep(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    await _expire(engine, document_id)
    async with make_sessionmaker(engine)() as session:
        session.add(
            Job(
                document_id=uuid.UUID(document_id), type=JobType.RENDER.value,
                status=JobStatus.RUNNING.value,
            )
        )  # fmt: skip
        await session.commit()

    result = await expiry.sweep(make_sessionmaker(engine), make_storage(live_settings))

    assert result == expiry.SweepResult(deleted=0, busy=1)
    assert (await _rows(engine, document_id))["document"] == 1


async def test_the_worker_sweeps_when_it_starts(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    """A host that slept through the hourly runs deletes expired documents as it wakes."""
    client = await client_for()
    document_id = await _filled(client, live_settings)
    await _expire(engine, document_id)

    worker = make_worker(live_settings)
    try:
        await worker.main()  # burst: startup, no jobs, exit
    finally:
        await worker.close()

    assert (await _rows(engine, document_id))["document"] == 0
    assert not await make_storage(live_settings).exists(f"documents/{document_id}/original.pdf")


async def _job_id(engine: AsyncEngine, document_id: str) -> uuid.UUID:
    async with make_sessionmaker(engine)() as session:
        job_id = await session.scalar(
            select(Job.id).where(Job.document_id == uuid.UUID(document_id)).limit(1)
        )
    assert job_id is not None
    return job_id


async def _requests(client: AsyncClient, document_id: str, job_id: uuid.UUID) -> list[int]:
    base = f"{DOCS}/{document_id}"
    responses = [
        await client.get(base),
        await client.get(f"{base}/ir"),
        await client.get(f"{base}/questions"),
        await client.get(f"{base}/pages/0.png"),
        await client.post(f"{base}/confirm-all"),
        await client.post(f"{base}/render"),
        await client.get(f"{base}/output"),
        await client.get(f"/api/v1/jobs/{job_id}"),
    ]
    return [r.status_code for r in responses]


async def test_an_expired_document_answers_410_until_it_is_swept_and_can_still_be_deleted(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    owner = await client_for()
    document_id = await _filled(owner, live_settings)
    job_id = await _job_id(engine, document_id)
    await _expire(engine, document_id)
    other = await client_for("ravi@example.com")

    gone = await owner.get(f"{DOCS}/{document_id}")

    assert gone.status_code == 410
    assert gone.json()["detail"] == (
        "This form expired: FormPilot deletes forms 24 hours after upload. Upload it again."
    )
    assert await _requests(owner, document_id, job_id) == [410] * 8
    assert await _requests(other, document_id, job_id) == [404] * 8  # nothing to see for others
    assert (await other.delete(f"{DOCS}/{document_id}")).status_code == 404
    assert (await owner.delete(f"{DOCS}/{document_id}")).status_code == 204
    assert (await _rows(engine, document_id))["document"] == 0
