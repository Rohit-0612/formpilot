"""Phase 5 rendering: confirm -> render job -> download, end to end on the synthetic persona form.

Covers the acceptance check "only confirmed fields are rendered": the downloaded PDF holds the
confirmed values and none of the others. Synthetic values only; no model.
"""

import uuid

import pymupdf
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import AuditEvent
from app.db.session import make_sessionmaker
from tests.integration.conftest import ClientFactory
from tests.integration.test_fill_api import DOCS, _run_worker
from tests.integration.test_review_api import _fields, _filled

pytestmark = pytest.mark.usefixtures("truncate_all")


def _text(pdf: bytes) -> str:
    with pymupdf.open("pdf", pdf) as doc:
        return " ".join(page.get_text() for page in doc)


async def _render(client: AsyncClient, settings: Settings, document_id: str) -> None:
    response = await client.post(f"{DOCS}/{document_id}/render")
    assert response.status_code == 202, response.text
    assert (await client.get(f"{DOCS}/{document_id}")).json()["status"] == "rendering"
    await _run_worker(settings)


async def test_confirmed_fields_are_printed_and_downloaded(
    client_for: ClientFactory, live_settings: Settings, engine: AsyncEngine
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    assert (await client.post(f"{DOCS}/{document_id}/confirm-all")).status_code == 200

    await _render(client, live_settings, document_id)

    document = (await client.get(f"{DOCS}/{document_id}")).json()
    assert document["status"] == "done" and document["job"]["status"] == "done"
    output = await client.get(f"{DOCS}/{document_id}/output")
    assert output.status_code == 200
    assert output.headers["content-type"] == "application/pdf"
    assert output.headers["content-disposition"] == "attachment; filename*=UTF-8''form-filled.pdf"
    text = _text(output.content)
    assert "Asha Verma" in text and "Pune" in text and "411001" in text
    async with make_sessionmaker(engine)() as session:
        events = set(
            (
                await session.scalars(
                    select(AuditEvent.event).where(AuditEvent.document_id == uuid.UUID(document_id))
                )
            ).all()
        )
    assert {"render_requested", "output_downloaded"} <= events


async def test_only_confirmed_fields_are_rendered(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    fields = await _fields(client, document_id)
    city = fields["City"]
    assert fields["Full name"]["status"] == "filled"  # filled from the profile, not confirmed
    confirmed = await client.patch(
        f"{DOCS}/{document_id}/fields/{city['id']}", json={"confirmed": True}
    )
    assert confirmed.status_code == 200

    await _render(client, live_settings, document_id)

    text = _text((await client.get(f"{DOCS}/{document_id}/output")).content)
    assert "Pune" in text
    assert "Asha Verma" not in text and "411001" not in text


async def test_a_change_after_printing_takes_the_output_back(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)
    await client.post(f"{DOCS}/{document_id}/confirm-all")
    await _render(client, live_settings, document_id)
    city = (await _fields(client, document_id))["City"]

    await client.patch(f"{DOCS}/{document_id}/fields/{city['id']}", json={"value": "Nagpur"})

    assert (await client.get(f"{DOCS}/{document_id}")).json()["status"] == "ready"
    assert (await client.get(f"{DOCS}/{document_id}/output")).status_code == 404


async def test_nothing_confirmed_nothing_to_print(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _filled(client, live_settings)

    response = await client.post(f"{DOCS}/{document_id}/render")

    assert response.status_code == 409
    assert response.json()["detail"] == "Confirm at least one field before printing the form."
    assert (await client.get(f"{DOCS}/{document_id}/output")).status_code == 404


async def test_someone_elses_output_is_not_found(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    owner = await client_for()
    document_id = await _filled(owner, live_settings)
    await owner.post(f"{DOCS}/{document_id}/confirm-all")
    await _render(owner, live_settings, document_id)
    other = await client_for("ravi@example.com")

    assert (await other.get(f"{DOCS}/{document_id}/output")).status_code == 404
    assert (await other.post(f"{DOCS}/{document_id}/render")).status_code == 404
