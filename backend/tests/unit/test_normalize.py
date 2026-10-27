"""Normalising typed values per semantic type (profile values and answers). Synthetic values."""

from datetime import date

import pytest

from app.ir.semantic_types import SEMANTIC_TYPES
from app.ir.semantic_types import SemanticType as T
from app.validators.normalize import InvalidValueError, normalize
from app.vault.fields import BY_KEY, PROFILE_FIELDS

TODAY = date(2026, 10, 27)


@pytest.mark.parametrize(
    ("semantic_type", "raw", "canonical"),
    [
        (T.FULL_NAME, "  Asha \t Verma ", "Asha Verma"),
        (T.DATE_OF_BIRTH, "5 March 1999", "1999-03-05"),
        (T.DATE_OF_BIRTH, "05/03/1999", "1999-03-05"),
        (T.PAN, "abcde 1234 f", "ABCDE1234F"),
        (T.AADHAAR, "2345-6789-0124", "234567890124"),
        (T.IFSC, "sbin0001234", "SBIN0001234"),
        (T.CURRENT_PINCODE, "411 001", "411001"),
        (T.PHONE_MOBILE, "+91 98765-43210", "9876543210"),
        (T.EMAIL, " asha@example.com ", "asha@example.com"),
        (T.PASSING_YEAR, "2024", "2024"),
        (T.BANK_ACCOUNT_NUMBER, "0012 3456 7890", "001234567890"),
    ],
)
def test_canonical_forms(semantic_type: T, raw: str, canonical: str) -> None:
    assert normalize(semantic_type, raw, TODAY) == canonical


@pytest.mark.parametrize(
    ("semantic_type", "raw"),
    [
        (T.FULL_NAME, "   "),
        (T.FULL_NAME, "x" * 201),
        (T.DATE_OF_BIRTH, "31/02/1999"),
        (T.DATE_OF_BIRTH, "01/01/2027"),
        (T.PAN, "ABCDE12345"),
        (T.AADHAAR, "2345 6789 0125"),
        (T.PHONE_ALTERNATE, "12345"),
        (T.EMAIL, "asha@"),
        (T.PASSING_YEAR, "99"),
    ],
)
def test_invalid_values_are_refused_without_echoing_them(semantic_type: T, raw: str) -> None:
    with pytest.raises(InvalidValueError) as error:
        normalize(semantic_type, raw, TODAY)
    assert raw.strip() == "" or raw.strip() not in str(error.value)


def test_profile_catalogue_covers_every_profile_key_once() -> None:
    keys = [f.key for f in PROFILE_FIELDS]
    expected = [i.profile_key for i in SEMANTIC_TYPES.values() if i.profile_key is not None]

    assert keys == expected and len(set(keys)) == len(keys)
    assert {k for k, f in BY_KEY.items() if f.sensitive} == {
        "pan",
        "aadhaar",
        "passport_number",
        "voter_id",
        "bank_account_number",
    }
    assert BY_KEY["father_name"].label == "Father's name"
    assert BY_KEY["permanent_city"].group == "Permanent address"
