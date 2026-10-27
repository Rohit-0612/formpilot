"""Upload -> analyze job -> read endpoints, against real Postgres, Redis, storage and worker.

The API and the worker commit through their own engines, so these tests clean up with TRUNCATE
(truncate_all) and a flushed Redis test database (redis_url) [A1]. Synthetic data only.
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.deps import get_queue
from app.config import Settings
from app.db.models import Document, FormIRVersion
from app.db.session import make_sessionmaker
from app.ir.semantic_types import SemanticType
from app.main import create_app
from app.services import ir_store
from app.storage import make_storage
from app.vault.crypto import VaultCipher
from tests.fixtures import pdfs
from tests.integration.workers import make_worker

pytestmark = pytest.mark.usefixtures("truncate_all")

DOCS = "/api/v1/documents"
PASSWORD = "correct-horse-7"
# A file name that must never reach a log line.
SECRET_NAME = "asha-verma-aadhaar-234567890124.pdf"

ClientFactory = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture
async def client_for(live_settings: Settings) -> AsyncIterator[ClientFactory]:
    """Logged-in clients on one app (lifespan running), one per user; settings overridable."""
    stack: list[Any] = []

    async def make(
        email: str = "asha@example.com", settings: Settings | None = None, **overrides: Any
    ) -> AsyncClient:
        app = create_app(settings or live_settings)
        for dependency, override in overrides.items():
            app.dependency_overrides[{"get_queue": get_queue}[dependency]] = override
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
        stack.append((client, lifespan))
        credentials = {"email": email, "password": PASSWORD}
        await client.post("/api/v1/auth/register", json=credentials)
        assert (await client.post("/api/v1/auth/login", json=credentials)).status_code == 200
        return client

    yield make
    for client, lifespan in reversed(stack):
        await client.aclose()
        await lifespan.__aexit__(None, None, None)


async def _upload(client: AsyncClient, data: bytes, name: str = SECRET_NAME) -> Response:
    return await client.post(DOCS, files={"file": (name, data, "application/pdf")})


async def _run_worker(settings: Settings) -> None:
    worker = make_worker(settings)
    try:
        await worker.main()
    finally:
        await worker.close()


async def _count(engine: AsyncEngine, model: type) -> int:
    async with make_sessionmaker(engine)() as session:
        return await session.scalar(select(func.count()).select_from(model)) or 0


# --- happy path ----------------------------------------------------------------------------


async def test_upload_analyze_and_read_back(
    client_for: ClientFactory,
    live_settings: Settings,
    engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = await client_for()
    fixture = pdfs.get("flat_boxes")

    uploaded = await _upload(client, fixture.data)
    assert uploaded.status_code == 202
    ids = uploaded.json()
    document_id, job_id = ids["document_id"], ids["job_id"]
    assert set(ids) == {"document_id", "job_id"}

    before = (await client.get(f"{DOCS}/{document_id}")).json()
    assert (before["status"], before["source_kind"], before["page_count"]) == (
        "uploaded",
        None,
        None,
    )
    assert before["job"] == {"id": job_id, "status": "queued", "error_message": None}
    assert before["original_filename"] == SECRET_NAME
    not_yet = await client.get(f"{DOCS}/{document_id}/ir")
    assert not_yet.status_code == 404

    await _run_worker(live_settings)

    document = (await client.get(f"{DOCS}/{document_id}")).json()
    assert (document["status"], document["source_kind"], document["page_count"]) == (
        "ready",
        "flat_text",
        1,
    )
    assert document["job"] == {"id": job_id, "status": "done", "error_message": None}

    ir = (await client.get(f"{DOCS}/{document_id}/ir")).json()
    assert ir["document_id"] == document_id
    assert len(ir["fields"]) == len(fixture.fields)
    # Version 2 (understanding, rules only in tests) is the one served.
    assert {e["pass_name"] for e in ir["trace"]} == {"frontend.flat", "understand"}
    assert any(f["semantic_method"] == "rule" for f in ir["fields"])
    async with make_sessionmaker(engine)() as session:
        versions = await session.scalars(
            select(FormIRVersion.version).where(FormIRVersion.document_id == uuid.UUID(document_id))
        )
        assert sorted(versions) == [1, 2]

    page = await client.get(f"{DOCS}/{document_id}/pages/0.png")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.headers["cache-control"] == "private, no-store"
    assert page.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert (await client.get(f"{DOCS}/{document_id}/pages/1.png")).status_code == 404

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert (job["type"], job["status"], job["document_id"]) == ("analyze", "done", document_id)

    storage = make_storage(live_settings)
    assert await storage.get(f"documents/{document_id}/original.pdf") == fixture.data
    assert await storage.exists(f"documents/{document_id}/pages/0.png")

    logs = capsys.readouterr()
    assert '"event": "document_uploaded"' in logs.out
    assert '"event": "document_analyzed"' in logs.out
    assert '"event": "document_understood"' in logs.out
    assert SECRET_NAME not in logs.out + logs.err
    assert "234567890124" not in logs.out + logs.err


async def test_a_fillable_pdf_is_analysed_by_the_acroform_frontend(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    fixture = pdfs.get("fillable_basic")
    document_id = (await _upload(client, fixture.data)).json()["document_id"]

    await _run_worker(live_settings)

    document = (await client.get(f"{DOCS}/{document_id}")).json()
    assert (document["status"], document["source_kind"]) == ("ready", "fillable")
    ir = (await client.get(f"{DOCS}/{document_id}/ir")).json()
    assert [f["native_name"] for f in ir["fields"]] == [f.native_name for f in fixture.fields]
    assert [f["kind"] for f in ir["fields"]] == ["text", "text", "checkbox", "radio", "choice"]


# --- rejected uploads ----------------------------------------------------------------------


async def test_a_non_pdf_is_rejected_with_415_and_nothing_is_stored(
    client_for: ClientFactory, engine: AsyncEngine, live_settings: Settings
) -> None:
    client = await client_for()

    response = await _upload(client, b"\x89PNG\r\n\x1a\n not a pdf", name="photo.png")

    assert response.status_code == 415
    assert response.json() == {"detail": "The file is not a PDF."}
    assert await _count(engine, Document) == 0
    assert not (live_settings.storage_root / "documents").exists()


async def test_an_oversized_file_is_rejected_with_413_and_nothing_is_stored(
    client_for: ClientFactory, engine: AsyncEngine, live_settings: Settings
) -> None:
    small_limit = live_settings.model_copy(update={"max_upload_mb": 1})
    client = await client_for(settings=small_limit)

    response = await _upload(client, b"%PDF-1.7\n" + b"0" * (1024 * 1024))

    assert response.status_code == 413
    assert response.json() == {"detail": "The file is larger than 1 MB."}
    assert await _count(engine, Document) == 0


async def test_an_upload_without_a_file_is_rejected_with_422(client_for: ClientFactory) -> None:
    client = await client_for()

    response = await client.post(DOCS, data={"file": "not a file"})

    assert response.status_code == 422


# --- failures in the worker ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "error"),
    [
        ("too_many_pages", "The PDF has more than 50 pages."),
        ("encrypted", "The PDF is password-protected. Upload a copy without a password."),
    ],
)
async def test_a_pdf_the_worker_cannot_analyze_fails_with_a_readable_message(
    client_for: ClientFactory, live_settings: Settings, fixture: str, error: str
) -> None:
    client = await client_for()
    document_id = (await _upload(client, pdfs.get(fixture).data)).json()["document_id"]

    await _run_worker(live_settings)

    document = (await client.get(f"{DOCS}/{document_id}")).json()
    assert document["status"] == "failed"
    assert document["job"]["status"] == "failed"
    assert document["job"]["error_message"] == error
    assert (await client.get(f"{DOCS}/{document_id}/ir")).status_code == 404
    assert (await client.get(f"{DOCS}/{document_id}/pages/0.png")).status_code == 404


async def test_an_enqueue_failure_marks_the_document_failed(
    client_for: ClientFactory, engine: AsyncEngine
) -> None:
    class RefusingQueue:
        async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
            return None  # what arq returns for a job id it already has

    client = await client_for(get_queue=lambda: RefusingQueue())

    response = await _upload(client, pdfs.get("flat_boxes").data)

    assert response.status_code == 503
    async with make_sessionmaker(engine)() as session:
        (document,) = (await session.scalars(select(Document))).all()
    assert document.status == "failed"
    shown = (await client.get(f"{DOCS}/{document.id}")).json()
    assert shown["job"]["error_message"] == (
        "The analysis could not be started. Please upload the file again."
    )


# --- access --------------------------------------------------------------------------------


async def test_other_users_get_404_and_anonymous_users_401(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    owner = await client_for("asha@example.com")
    other = await client_for("ravi@example.com")
    ids = (await _upload(owner, pdfs.get("flat_boxes").data)).json()
    await _run_worker(live_settings)
    paths = [
        f"{DOCS}/{ids['document_id']}",
        f"{DOCS}/{ids['document_id']}/ir",
        f"{DOCS}/{ids['document_id']}/pages/0.png",
        f"/api/v1/jobs/{ids['job_id']}",
    ]

    for path in paths:
        assert (await owner.get(path)).status_code == 200, path
        assert (await other.get(path)).status_code == 404, path
        other.cookies.clear()
        assert (await other.get(path)).status_code == 401, path
        await other.post(
            "/api/v1/auth/login", json={"email": "ravi@example.com", "password": PASSWORD}
        )
    assert (await owner.get(f"{DOCS}/{uuid.uuid4()}")).status_code == 404
    assert (await owner.get(f"/api/v1/jobs/{uuid.uuid4()}")).status_code == 404


# --- masking -------------------------------------------------------------------------------


async def test_ir_values_are_masked_in_the_response_and_encrypted_in_the_database(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    """Masked in the response (SPEC §8); in the stored row, sensitive and phone values are
    encrypted and the rest is plain (decision P4-D5, PLAN Phase 4 acceptance). A version with
    values is added through the IR store, as the Phase 4 passes do."""
    client = await client_for()
    document_id = uuid.UUID(
        (await _upload(client, pdfs.get("flat_boxes").data)).json()["document_id"]
    )
    await _run_worker(live_settings)
    cipher = VaultCipher(live_settings.vault_key)
    async with make_sessionmaker(engine)() as session:
        ir = await ir_store.latest(session, document_id, cipher)
        assert ir is not None
        values = [
            ("aadhaar", "2345 6789 0124"),
            ("other", "ABCDE1234F"),  # defence in depth
            ("phone_mobile", "9876543210"),
            ("full_name", "Asha Verma"),
        ]
        fields = [
            f.model_copy(update={"semantic_type": SemanticType(t), "value": v})
            for f, (t, v) in zip(ir.fields, values, strict=False)
        ]
        ir = ir.model_copy(update={"fields": fields + ir.fields[len(fields) :]})
        version = await ir_store.add_version(session, document_id, ir, cipher)
        await session.commit()

    response = (await client.get(f"{DOCS}/{document_id}/ir")).json()

    assert [f["value"] for f in response["fields"][:4]] == [
        "XXXX0124",
        "XXXX234F",
        "9876543210",  # the phone exception: the user's own number is shown
        "Asha Verma",
    ]
    async with make_sessionmaker(engine)() as session:
        row = await session.scalar(
            select(FormIRVersion.ir_json).where(
                FormIRVersion.document_id == document_id, FormIRVersion.version == version
            )
        )
    assert row is not None
    text = json.dumps(row)
    for secret in ("2345 6789 0124", "ABCDE1234F", "9876543210"):
        assert secret not in text
    assert row["fields"][3]["value"] == "Asha Verma"
    assert all(f["value"].startswith(ir_store.SEALED_PREFIX) for f in row["fields"][:3])
