"""Field-level encryption of sensitive and phone values in stored IRs (decision P4-D5).

All values are synthetic and format-valid only.
"""

import json
import uuid

import pytest
from pydantic import SecretStr

from app.ir.models import BBox, Field, FieldKind, FormIR, PageInfo, SourceKind, TextLayer
from app.ir.semantic_types import PHONE_TYPES, SENSITIVE_TYPES
from app.ir.semantic_types import SemanticType as T
from app.services.ir_store import SEALED_PREFIX, SEALED_TYPES, seal, unseal
from app.vault.crypto import VaultCipher, VaultError
from tests.conftest import TEST_VAULT_KEY

PAN = "ABCDE1234F"
AADHAAR = "2345 6789 0124"
PHONE = "9876543210"
NAME = "Asha Verma"


@pytest.fixture
def cipher() -> VaultCipher:
    return VaultCipher(SecretStr(TEST_VAULT_KEY))


def _ir(*fields: tuple[T, str | None]) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=[
            Field(
                id=f"p0_f{i:03d}",
                kind=FieldKind.TEXT,
                native_name=None,
                label_text=None,
                context_text=None,
                bbox=BBox(page=0, x0=10, y0=10, x1=100, y1=22),
                semantic_type=t,
                value=v,
            )
            for i, (t, v) in enumerate(fields)
        ],
    )


def test_sealed_types_are_the_d2_types_and_the_phones() -> None:
    assert SEALED_TYPES == SENSITIVE_TYPES | PHONE_TYPES
    assert len(SEALED_TYPES) == 7


def test_sensitive_and_phone_values_are_encrypted_the_rest_stays_plain(
    cipher: VaultCipher,
) -> None:
    ir = _ir((T.PAN, PAN), (T.PHONE_MOBILE, PHONE), (T.FULL_NAME, NAME), (T.EMAIL, None))

    stored = seal(ir, cipher)
    text = json.dumps(stored)

    assert PAN not in text and PHONE not in text
    values = [f["value"] for f in stored["fields"]]
    assert values[0].startswith(SEALED_PREFIX) and values[1].startswith(SEALED_PREFIX)
    assert values[2:] == [NAME, None]


def test_identifier_shaped_values_are_encrypted_in_any_field(cipher: VaultCipher) -> None:
    """Defence in depth, like masking: an Aadhaar typed into a field understood as `other`."""
    stored = seal(_ir((T.OTHER, AADHAAR), (T.UNKNOWN, PAN)), cipher)

    assert AADHAAR not in json.dumps(stored) and PAN not in json.dumps(stored)


def test_a_plain_value_that_looks_like_a_token_is_sealed_too(cipher: VaultCipher) -> None:
    tricky = SEALED_PREFIX + "not-a-token"
    stored = seal(_ir((T.OTHER, tricky)), cipher)

    assert unseal(stored, cipher)["fields"][0]["value"] == tricky


def test_unseal_restores_the_ir_exactly(cipher: VaultCipher) -> None:
    ir = _ir((T.AADHAAR, AADHAAR), (T.PHONE_ALTERNATE, PHONE), (T.CURRENT_CITY, "Pune"))

    assert FormIR.model_validate(unseal(seal(ir, cipher), cipher)) == ir


def test_unseal_does_not_change_the_stored_data(cipher: VaultCipher) -> None:
    stored = seal(_ir((T.PAN, PAN)), cipher)
    before = json.dumps(stored)

    unseal(stored, cipher)

    assert json.dumps(stored) == before


def test_a_changed_token_fails_loudly(cipher: VaultCipher) -> None:
    stored = seal(_ir((T.PAN, PAN)), cipher)
    stored["fields"][0]["value"] = SEALED_PREFIX + "garbage"

    with pytest.raises(VaultError):
        unseal(stored, cipher)


def test_a_value_containing_an_identifier_or_phone_is_encrypted(cipher: VaultCipher) -> None:
    note = "Aadhaar 2345 6789 0124 on file"
    call = "call 90000 12345 after 6"

    stored = json.dumps(
        seal(_ir((T.OTHER, note), (T.OTHER, call), (T.OTHER, "Pune 411001")), cipher)
    )

    assert "2345 6789 0124" not in stored and "90000 12345" not in stored
    assert "Pune 411001" in stored  # a PIN code is not an identifier
