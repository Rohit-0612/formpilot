"""Phase 5 review API: edit, clear, confirm and unconfirm a field, confirm all, delete a document.

Synthetic fixture form and values only; no model (rules only). Each action is stored as the next
IR version with audit events that never hold a value.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import AuditEvent, Document, FormIRVersion, Job
from app.db.session import make_sessionmaker
from app.storage import make_storage
from tests.fixtures import pdfs
from tests.integration.conftest import ClientFactory
from tests.integration.test_fill_api import DOCS, FULL, PAN, _run_worker

pytestmark = pytest.mark.usefixtures("truncate_all")


async def _filled(
    client: AsyncClient, settings: Settings, fixture: str = "flat_persona_form"
) -> str:
    saved = await client.put(
        "/api/v1/profile", json={"values": FULL, "sensitive_opt_in": {"pan": True}}
    )
    assert saved.status_code == 200, saved.text
    data = pdfs.get(fixture).data
    response = await client.post(DOCS, files={"file": ("form.pdf", data, "application/pdf")})
    assert response.status_code == 202, response.text
    await _run_worker(settings)
    return str(response.json()["document_id"])


async def _fields(client: AsyncClient, document_id: str) -> dict[str, dict]:
    ir = (await client.get(f"{DOCS}/{document_id}/ir")).json()
    return {f["label_text"]: f for f in ir["fields"]}


async def test_confirm_edit_unconfirm_and_clear_a_field(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    fields = await _fields(client, document_id)
    name, pan = fields["Full name"], fields["PAN"]
    assert name["status"] == "filled"

    confirmed = await client.patch(
        f"{DOCS}/{document_id}/fields/{name['id']}", json={"confirmed": True}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["changed"] == 1
    by_id = {f["id"]: f for f in confirmed.json()["ir"]["fields"]}
    assert by_id[name["id"]]["status"] == "confirmed"
    assert PAN not in confirmed.text  # the response is masked like GET /ir

    edited = await client.patch(
        f"{DOCS}/{document_id}/fields/{name['id']}", json={"value": "  Asha  K  Verma "}
    )
    field = {f["id"]: f for f in edited.json()["ir"]["fields"]}[name["id"]]
    assert (field["value"], field["value_source"], field["status"]) == (
        "Asha K Verma", "user_edit", "filled",
    )  # fmt: skip

    cleared = await client.patch(f"{DOCS}/{document_id}/fields/{pan['id']}", json={"value": None})
    field = {f["id"]: f for f in cleared.json()["ir"]["fields"]}[pan["id"]]
    assert (field["value"], field["status"]) == (None, "needs_input")
    questions = (await client.get(f"{DOCS}/{document_id}/questions")).json()["questions"]
    assert any(pan["id"] in [i for p in q["parts"] for i in p["field_ids"]] for q in questions)

    async with make_sessionmaker(engine)() as session:
        events = (
            await session.scalars(
                select(AuditEvent.event)
                .where(AuditEvent.document_id == uuid.UUID(document_id))
                .order_by(AuditEvent.created_at)
            )
        ).all()
        versions = await session.scalar(
            select(func.count())
            .select_from(FormIRVersion)
            .where(FormIRVersion.document_id == uuid.UUID(document_id))
        )
        stored = " ".join(
            str(row) for row in (await session.execute(select(AuditEvent.__table__))).all()
        )
    assert events[-3:] == ["field_confirmed", "field_edited", "field_cleared"]
    assert versions == 6  # detection, understanding, filling + three review actions
    assert "Asha" not in stored and PAN not in stored


async def test_confirm_all_confirms_checked_profile_values(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)

    response = await client.post(f"{DOCS}/{document_id}/confirm-all")

    assert response.status_code == 200, response.text
    statuses = {f["label_text"]: f["status"] for f in response.json()["ir"]["fields"]}
    assert statuses["Full name"] == statuses["PAN"] == "confirmed"
    assert statuses["Remarks"] == "needs_input"  # nothing to confirm
    assert response.json()["changed"] == sum(s == "confirmed" for s in statuses.values())
    again = await client.post(f"{DOCS}/{document_id}/confirm-all")
    assert again.json()["changed"] == 0


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({}, 422),  # neither a value nor a confirm
        ({"value": "x" * 501}, 422),
        ({"confirmed": True, "extra": 1}, 422),
    ],
)
async def test_invalid_edits_are_refused(
    client_for: ClientFactory, live_settings: Settings, body: dict, code: int
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    field_id = (await _fields(client, document_id))["Full name"]["id"]

    response = await client.patch(f"{DOCS}/{document_id}/fields/{field_id}", json=body)

    assert response.status_code == code


async def test_unknown_never_filled_and_empty_fields(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings, "flat_office_use_box")
    office = (await _fields(client, document_id))["Ref. no."]

    unknown = await client.patch(f"{DOCS}/{document_id}/fields/p9_f999", json={"confirmed": True})
    never = await client.patch(f"{DOCS}/{document_id}/fields/{office['id']}", json={"value": "1"})

    assert unknown.status_code == 404
    assert (
        never.status_code == 409 and never.json()["detail"] == "FormPilot never fills this field."
    )


async def test_review_waits_for_a_running_job(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    question = (await client.get(f"{DOCS}/{document_id}/questions")).json()["questions"][0]
    queued = await client.post(
        f"{DOCS}/{document_id}/answers",
        json={"answers": [{"question_id": question["id"], "value": "none"}]},
    )
    assert queued.status_code == 202  # the answers job is queued, not run

    response = await client.post(f"{DOCS}/{document_id}/confirm-all")
    deleting = await client.delete(f"{DOCS}/{document_id}")

    assert response.status_code == deleting.status_code == 409


async def test_delete_removes_the_document_its_files_and_rows(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    storage = make_storage(live_settings)
    assert await storage.exists(f"documents/{document_id}/original.pdf")

    response = await client.delete(f"{DOCS}/{document_id}")

    assert response.status_code == 204
    assert (await client.get(f"{DOCS}/{document_id}")).status_code == 404
    assert not await storage.exists(f"documents/{document_id}/original.pdf")
    assert not await storage.exists(f"documents/{document_id}/pages/0.png")
    async with make_sessionmaker(engine)() as session:
        key = uuid.UUID(document_id)
        assert await session.get(Document, key) is None
        for model in (FormIRVersion, Job, AuditEvent):
            count = await session.scalar(
                select(func.count()).select_from(model).where(model.document_id == key)
            )
            assert count == 0


async def test_someone_elses_document_is_not_found(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    owner = await client_for()
    document_id = await _filled(owner, live_settings)
    field_id = (await _fields(owner, document_id))["Full name"]["id"]
    other = await client_for("ravi@example.com")

    responses = [
        await other.patch(f"{DOCS}/{document_id}/fields/{field_id}", json={"confirmed": True}),
        await other.post(f"{DOCS}/{document_id}/confirm-all"),
        await other.delete(f"{DOCS}/{document_id}"),
    ]

    assert [r.status_code for r in responses] == [404, 404, 404]
    assert (await owner.get(f"{DOCS}/{document_id}")).status_code == 200
