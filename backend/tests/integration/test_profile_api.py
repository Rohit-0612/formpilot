"""Profile vault API (SPEC §6.3, §8, §11): encryption at rest, masking, per-field opt-in, audit
events without values. All values are synthetic."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import AuditEvent, Profile
from app.db.session import make_sessionmaker
from tests.integration.conftest import ClientFactory

pytestmark = pytest.mark.usefixtures("truncate_all")

PROFILE = "/api/v1/profile"
PAN = "ABCDE1234F"
AADHAAR = "2345 6789 0124"


async def _rows(engine: AsyncEngine, model: type) -> list:
    async with make_sessionmaker(engine)() as session:
        return list((await session.scalars(select(model))).all())


async def test_a_new_user_has_an_empty_profile_with_the_field_catalogue(
    client_for: ClientFactory,
) -> None:
    body = (await (await client_for()).get(PROFILE)).json()

    assert body["values"] == {} and body["sensitive_opt_in"] == []
    keys = {f["key"]: f for f in body["fields"]}
    assert keys["pan"]["sensitive"] and not keys["full_name"]["sensitive"]
    assert keys["current_pincode"] == {
        "key": "current_pincode",
        "label": "PIN code",
        "group": "Current address",
        "sensitive": False,
    }


async def test_values_are_normalised_encrypted_at_rest_and_audited_without_values(
    client_for: ClientFactory, engine: AsyncEngine
) -> None:
    client = await client_for()
    update = {
        "values": {
            "full_name": "  Asha   Verma ",
            "date_of_birth": "5/3/1999",
            "phone_mobile": "+91 98765 43210",
            "ifsc": "sbin0001234",
        }
    }

    response = await client.put(PROFILE, json=update)

    assert response.status_code == 200, response.text
    assert response.json()["values"] == {
        "date_of_birth": "1999-03-05",
        "full_name": "Asha Verma",
        "ifsc": "SBIN0001234",
        "phone_mobile": "9876543210",
    }
    [row] = await _rows(engine, Profile)
    assert b"Asha" not in row.encrypted_blob and b"9876543210" not in row.encrypted_blob
    events = await _rows(engine, AuditEvent)
    assert sorted(e.field_id for e in events) == sorted(update["values"])
    assert {e.event for e in events} == {"profile_value_set"}
    assert all(e.document_id is None and e.user_id == row.user_id for e in events)


async def test_a_sensitive_value_needs_its_own_opt_in_and_is_masked(
    client_for: ClientFactory, engine: AsyncEngine
) -> None:
    client = await client_for()

    refused = await client.put(PROFILE, json={"values": {"pan": PAN}})
    assert refused.status_code == 422
    assert refused.json()["detail"][0]["key"] == "pan" and PAN not in refused.text
    assert await _rows(engine, Profile) == []

    # an opt-in for Aadhaar does not cover PAN
    other = await client.put(
        PROFILE, json={"values": {"pan": PAN}, "sensitive_opt_in": {"aadhaar": True}}
    )
    assert other.status_code == 422

    ok = await client.put(PROFILE, json={"values": {"pan": PAN}, "sensitive_opt_in": {"pan": True}})
    assert ok.status_code == 200
    assert ok.json()["values"] == {"pan": "XXXX234F"} and ok.json()["sensitive_opt_in"] == ["pan"]
    assert PAN not in (await client.get(PROFILE)).text


async def test_opting_out_deletes_the_sensitive_value(client_for: ClientFactory) -> None:
    client = await client_for()
    await client.put(
        PROFILE, json={"values": {"aadhaar": AADHAAR}, "sensitive_opt_in": {"aadhaar": True}}
    )

    body = (await client.put(PROFILE, json={"sensitive_opt_in": {"aadhaar": False}})).json()

    assert body["values"] == {} and body["sensitive_opt_in"] == []


async def test_invalid_values_and_unknown_keys_change_nothing(
    client_for: ClientFactory, engine: AsyncEngine
) -> None:
    client = await client_for()
    await client.put(PROFILE, json={"values": {"full_name": "Asha Verma"}})

    response = await client.put(
        PROFILE,
        json={
            "values": {
                "full_name": "Asha K Verma",
                "aadhaar": "2345 6789 0125",
                "current_pincode": "011001",
                "shoe_size": "9",
            },
            "sensitive_opt_in": {"aadhaar": True},
        },
    )

    assert response.status_code == 422
    problems = {p["key"]: p["message"] for p in response.json()["detail"]}
    assert set(problems) == {"aadhaar", "current_pincode", "shoe_size"}
    assert "2345" not in json.dumps(problems) and "011001" not in json.dumps(problems)
    assert (await client.get(PROFILE)).json()["values"] == {"full_name": "Asha Verma"}


async def test_null_deletes_a_value_and_profiles_are_per_user(client_for: ClientFactory) -> None:
    asha = await client_for("asha@example.com")
    ravi = await client_for("ravi@example.com")
    await asha.put(PROFILE, json={"values": {"current_city": "Pune", "email": "a@example.com"}})

    assert (await ravi.get(PROFILE)).json()["values"] == {}
    body = (await asha.put(PROFILE, json={"values": {"current_city": None}})).json()
    assert body["values"] == {"email": "a@example.com"}


async def test_profile_needs_a_login(client_for: ClientFactory) -> None:
    client = await client_for()
    await client.post("/api/v1/auth/logout")
    client.cookies.clear()

    assert (await client.get(PROFILE)).status_code == 401
    assert (await client.put(PROFILE, json={})).status_code == 401
