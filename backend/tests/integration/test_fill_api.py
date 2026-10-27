"""Phase 4 end to end: profile -> upload -> filled form -> questions -> answers -> profile.

Covers the Phase 4 acceptance checks on a synthetic fixture form (decision P4-D4): with a full
profile, only the field the fill policy cannot type is asked; sensitive and phone values are
encrypted in stored IR versions and never appear in the logs. Synthetic values only; the tests
run without a model (rules only).
"""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import FormIRVersion
from app.db.session import make_sessionmaker
from app.services.filling import answers_key
from app.storage import make_storage
from tests.fixtures import pdfs
from tests.integration.conftest import ClientFactory
from tests.integration.workers import make_worker

pytestmark = pytest.mark.usefixtures("truncate_all")

DOCS = "/api/v1/documents"
PAN = "AAAPV1234A"
AADHAAR = "230000000017"  # Verhoeff-valid synthetic
MOBILE = "9000012345"
EMAIL = "asha.verma@example.com"
FULL = {
    "full_name": "Asha Verma",
    "father_name": "Ramesh Verma",
    "date_of_birth": "1996-03-05",
    "phone_mobile": MOBILE,
    "email": EMAIL,
    "current_city": "Pune",
    "current_pincode": "411001",
    "pan": PAN,
}
SECRETS = (PAN, MOBILE, "90000 12345", EMAIL, "Ramesh", AADHAAR)


async def _run_worker(settings: Settings) -> None:
    worker = make_worker(settings)
    try:
        await worker.main()
    finally:
        await worker.close()


async def _analysed(client: AsyncClient, settings: Settings) -> str:
    data = pdfs.get("flat_persona_form").data
    response = await client.post(DOCS, files={"file": ("form.pdf", data, "application/pdf")})
    assert response.status_code == 202, response.text
    await _run_worker(settings)
    return str(response.json()["document_id"])


async def _questions(client: AsyncClient, document_id: str) -> list[dict]:
    response = await client.get(f"{DOCS}/{document_id}/questions")
    assert response.status_code == 200, response.text
    return list(response.json()["questions"])


async def test_with_a_full_profile_only_the_untyped_field_is_asked(
    client_for: ClientFactory, live_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    client = await client_for()
    saved = await client.put(
        "/api/v1/profile", json={"values": FULL, "sensitive_opt_in": {"pan": True}}
    )
    assert saved.status_code == 200, saved.text

    document_id = await _analysed(client, live_settings)

    questions = await _questions(client, document_id)
    assert [q["prompt"] for q in questions] == ["The form asks: “Remarks”. What should go here?"]
    ir = (await client.get(f"{DOCS}/{document_id}/ir")).json()
    values = {f["label_text"]: f["value"] for f in ir["fields"]}
    assert values == {
        "Full name": "Asha Verma",
        "Father's name": "Ramesh Verma",
        "Date of birth (DD/MM/YYYY)": "05/03/1996",
        "Mobile number": MOBILE,  # the owner's own phone is shown (masking exception)
        "Email": EMAIL,
        "City": "Pune",
        "PIN code": "411001",
        "Remarks": None,
        "PAN": "XXXX234A",  # masked
    }
    captured = capsys.readouterr()
    for secret in SECRETS:
        assert secret not in captured.out + captured.err, secret


async def test_a_partial_profile_asks_what_it_lacks_and_answers_fill_and_save(
    client_for: ClientFactory,
    live_settings: Settings,
    engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = await client_for()
    partial = {k: v for k, v in FULL.items() if k not in ("email", "pan", "phone_mobile")}
    await client.put("/api/v1/profile", json={"values": partial})
    document_id = await _analysed(client, live_settings)

    questions = {q["prompt"]: q for q in await _questions(client, document_id)}
    assert set(questions) == {
        "What is your mobile number?",
        "What is your email address?",
        "The form asks: “Remarks”. What should go here?",
        "What is your PAN?",
    }
    pan_q = questions["What is your PAN?"]
    assert pan_q["can_save"] and pan_q["parts"][0]["sensitive"]

    answers = [
        {"question_id": questions["What is your email address?"]["id"], "value": EMAIL,
         "save_to_profile": True},
        {"question_id": pan_q["id"], "value": PAN.lower(), "save_to_profile": True,
         "sensitive_opt_in": ["pan"]},
        {"question_id": questions["What is your mobile number?"]["id"], "value": "+91 90000 12345"},
        {"question_id": questions["The form asks: “Remarks”. What should go here?"]["id"],
         "value": "Aadhaar 2300 0000 0017 on file"},
    ]  # fmt: skip
    accepted = await client.post(f"{DOCS}/{document_id}/answers", json={"answers": answers})
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    storage = make_storage(live_settings)
    key = answers_key(uuid.UUID(document_id), uuid.UUID(job_id))
    sealed = await storage.get(key)
    assert all(s.encode() not in sealed for s in SECRETS)  # stored encrypted

    await _run_worker(live_settings)

    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert (job["type"], job["status"]) == ("answers", "done"), job
    assert not await storage.exists(key)  # used once, then deleted
    assert await _questions(client, document_id) == []
    ir = (await client.get(f"{DOCS}/{document_id}/ir")).json()
    by_label = {f["label_text"]: f for f in ir["fields"]}
    assert (
        by_label["PAN"]["value"] == "XXXX234A" and by_label["PAN"]["value_source"] == "user_answer"
    )
    assert by_label["Mobile number"]["value"] == MOBILE
    # an Aadhaar inside a note: shown to its owner (masking matches whole values, a known
    # limitation) but encrypted in the database (checked below)
    assert by_label["Remarks"]["value"] == "Aadhaar 2300 0000 0017 on file"
    profile = (await client.get("/api/v1/profile")).json()
    assert profile["values"]["email"] == EMAIL and profile["values"]["pan"] == "XXXX234A"
    assert "phone_mobile" not in profile["values"]  # not ticked for saving

    async with make_sessionmaker(engine)() as session:
        rows = (
            await session.scalars(
                select(FormIRVersion.ir_json).where(
                    FormIRVersion.document_id == uuid.UUID(document_id)
                )
            )
        ).all()
    stored = json.dumps(list(rows))
    for secret in (PAN, MOBILE, AADHAAR, "2300 0000 0017"):
        assert secret not in stored, secret
    captured = capsys.readouterr()
    for secret in (*SECRETS, "2300 0000 0017"):
        assert secret not in captured.out + captured.err, secret


async def test_answers_for_questions_not_asked_are_refused(
    client_for: ClientFactory, live_settings: Settings
) -> None:
    client = await client_for()
    document_id = await _analysed(client, live_settings)

    response = await client.post(
        f"{DOCS}/{document_id}/answers",
        json={"answers": [{"question_id": "q_p9_f999", "value": "x"}]},
    )

    assert response.status_code == 409
    other = await client_for("ravi@example.com")
    assert (await other.get(f"{DOCS}/{document_id}/questions")).status_code == 404
