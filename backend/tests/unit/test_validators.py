"""Validators (SPEC §6.6): published and known-valid / known-invalid vectors.

Identifier values are synthetic and format-valid only.
"""

from datetime import date

import pytest

from app.ir.models import BBox, Field, FieldKind, Option
from app.ir.semantic_types import SemanticType as T
from app.validators import VALIDATORS, common, india, validate_field, validator_names, verhoeff
from app.validators.dates import date_format_for, parse_date, parse_in_format

TODAY = date(2026, 10, 27)


def _field(
    semantic_type: T = T.OTHER,
    value: str | None = None,
    label: str | None = None,
    kind: FieldKind = FieldKind.TEXT,
    options: list[Option] | None = None,
    max_chars: int | None = None,
) -> Field:
    return Field(
        id="p0_f000",
        kind=kind,
        native_name=None,
        label_text=label,
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10, x1=200, y1=24),
        semantic_type=semantic_type,
        value=value,
        options=options or [],
        max_chars=max_chars,
    )


# --- Verhoeff (published vectors) ----------------------------------------------------------


@pytest.mark.parametrize(("digits", "check"), [("236", "3"), ("75872", "2"), ("12345", "1")])
def test_verhoeff_published_check_digits(digits: str, check: str) -> None:
    assert verhoeff.check_digit(digits) == check
    assert verhoeff.is_valid(digits + check)


def test_verhoeff_catches_every_single_digit_error_and_adjacent_swap() -> None:
    number = "234567890124"  # synthetic, valid
    assert verhoeff.is_valid(number)
    for i in range(len(number)):
        for d in "0123456789":
            if d != number[i]:
                assert not verhoeff.is_valid(number[:i] + d + number[i + 1 :])
    for i in range(len(number) - 1):
        if number[i] != number[i + 1]:
            swapped = number[:i] + number[i + 1] + number[i] + number[i + 2 :]
            assert not verhoeff.is_valid(swapped)


@pytest.mark.parametrize("bad", ["", "12a4", "١٢٣"])
def test_verhoeff_rejects_non_ascii_digits(bad: str) -> None:
    assert not verhoeff.is_valid(bad)


# --- Indian formats ----------------------------------------------------------------------


FORMAT_VECTORS = [
    (
        india.pan_format,
        ["ABCDE1234F", "abcde1234f", "ABCDE 1234 F"],
        ["ABCD1234F", "ABCDE12345", "12345ABCDE"],
    ),
    (
        india.aadhaar_format,
        ["2345 6789 0124", "234567890124", "2345-6789-0124"],
        ["1234 5678 9012", "0345 6789 0124", "2345678901", "23456789012a"],
    ),
    (
        india.ifsc_format,
        ["SBIN0001234", "hdfc0abc123"],
        ["SBIN1001234", "SBI0001234", "SBIN00012345"],
    ),
    (india.pincode_format, ["411001", "110 001"], ["011001", "41100", "4110011"]),
    (
        india.phone_in,
        ["9876543210", "+91 98765 43210", "09876543210", "+91-9876543210"],
        ["5876543210", "987654321", "+44 9876543210", "98765432100"],
    ),
]


@pytest.mark.parametrize(("check", "valid", "invalid"), FORMAT_VECTORS)
def test_indian_formats(check: object, valid: list[str], invalid: list[str]) -> None:
    for value in valid:
        assert check(value) is None, value  # type: ignore[operator]
    for value in invalid:
        assert check(value) is not None, value  # type: ignore[operator]


def test_aadhaar_checksum_is_reported_separately_from_the_format() -> None:
    assert india.aadhaar_verhoeff("2345 6789 0124") is None
    assert india.aadhaar_verhoeff("2345 6789 0125") is not None  # wrong check digit
    assert india.aadhaar_verhoeff("12") is None  # a format error, reported by aadhaar_format


@pytest.mark.parametrize(
    "value", ["ABCDE12345", "2345 6789 0125", "9876543", "SBIN1001234", "011001", "a@b"]
)
def test_messages_never_contain_the_value(value: str) -> None:
    field = _field(value=value)
    for name, check in VALIDATORS.items():
        message = check(value, field, TODAY)
        assert message is None or value not in message, name


# --- email, dates, options, length -----------------------------------------------------------


def test_email() -> None:
    assert common.email_format("asha.verma@example.com") is None
    for bad in ["asha", "asha@", "@example.com", "asha verma@example.com"]:
        assert common.email_format(bad) is not None, bad


@pytest.mark.parametrize(
    ("label", "max_chars", "fmt"),
    [
        (None, None, "%d/%m/%Y"),
        ("Date of Birth (DD-MM-YYYY)", None, "%d-%m-%Y"),
        ("Date (dd/mm/yy)", None, "%d/%m/%y"),
        ("DOB YYYY-MM-DD", None, "%Y-%m-%d"),
        ("Date of birth D D M M Y Y Y Y", None, "%d%m%Y"),
        ("Date of birth", 8, "%d%m%Y"),
    ],
)
def test_date_format_comes_from_the_label_hint(
    label: str | None, max_chars: int | None, fmt: str
) -> None:
    assert date_format_for(_field(label=label, max_chars=max_chars)) == fmt


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("05/03/1999", date(1999, 3, 5)),
        ("5-3-1999", date(1999, 3, 5)),
        ("1999-03-05", date(1999, 3, 5)),
        ("5 March 1999", date(1999, 3, 5)),
        ("5th Mar, 1999", date(1999, 3, 5)),
        ("31/02/1999", None),
        ("tomorrow", None),
    ],
)
def test_parse_date_reads_day_first_dates(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


def test_date_validator_wants_the_forms_format_and_a_real_date() -> None:
    field = _field(T.DATE_OF_BIRTH, label="Date of Birth (DD/MM/YYYY)")

    assert common.date_valid("05/03/1999", field) is None
    assert common.date_valid("1999-03-05", field) is not None  # another format
    assert common.date_valid("31/02/1999", field) is not None  # not a date
    assert parse_in_format("5/3/1999", "%d/%m/%Y") is None  # not zero-padded


def test_dob_cannot_be_in_the_future() -> None:
    field = _field(T.DATE_OF_BIRTH)

    assert common.dob_not_future("27/10/2026", field, TODAY) is None
    assert common.dob_not_future("28/10/2026", field, TODAY) is not None


def test_options_and_max_chars() -> None:
    radio = _field(kind=FieldKind.RADIO, options=[Option(value="M"), Option(value="F")])

    assert common.option_valid("F", radio) is None
    assert common.option_valid("X", radio) is not None
    assert common.max_chars("123456", _field(max_chars=6)) is None
    assert common.max_chars("1234567", _field(max_chars=6)) is not None


# --- running a field's validators ------------------------------------------------------------


def test_a_field_runs_its_types_validators_plus_shape_checks() -> None:
    field = _field(T.AADHAAR, value="2345 6789 0125", max_chars=14)

    results = validate_field(field, TODAY)

    assert validator_names(field) == ["aadhaar_format", "aadhaar_verhoeff", "max_chars"]
    assert [(r.validator, r.ok) for r in results] == [
        ("aadhaar_format", True),
        ("aadhaar_verhoeff", False),
        ("max_chars", True),
    ]


def test_a_field_without_a_value_has_no_results() -> None:
    assert validate_field(_field(T.PAN), TODAY) == []
    assert validate_field(_field(T.PAN, value=""), TODAY) == []
