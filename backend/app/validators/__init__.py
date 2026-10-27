"""Deterministic validators (SPEC §6.6). The LLM never validates (invariant 3).

`validate_field` runs the semantic type's default validators (semantic_types.py) plus the
field-shape checks (options, max_chars). A result's message never contains the value.
"""

from collections.abc import Callable
from datetime import date

from app.ir.models import Field, FieldKind, ValidationResult
from app.ir.semantic_types import type_info
from app.validators import common, india

type Check = Callable[[str, Field, date], str | None]

VALIDATORS: dict[str, Check] = {
    "pan_format": lambda v, f, t: india.pan_format(v),
    "aadhaar_format": lambda v, f, t: india.aadhaar_format(v),
    "aadhaar_verhoeff": lambda v, f, t: india.aadhaar_verhoeff(v),
    "ifsc_format": lambda v, f, t: india.ifsc_format(v),
    "pincode_format": lambda v, f, t: india.pincode_format(v),
    "phone_in": lambda v, f, t: india.phone_in(v),
    "email_format": lambda v, f, t: common.email_format(v),
    "date": lambda v, f, t: common.date_valid(v, f),
    "dob_not_future": common.dob_not_future,
    "option": lambda v, f, t: common.option_valid(v, f),
    "max_chars": lambda v, f, t: common.max_chars(v, f),
}

_OPTION_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO, FieldKind.CHOICE})


def validator_names(field: Field) -> list[str]:
    names = list(type_info(field.semantic_type).validators)
    if field.kind in _OPTION_KINDS and field.options:
        names.append("option")
    if field.max_chars is not None:
        names.append("max_chars")
    return names


def validate_field(field: Field, today: date) -> list[ValidationResult]:
    """One result per applicable validator; [] for a field without a value."""
    if field.value is None or field.value == "":
        return []
    results = []
    for name in validator_names(field):
        message = VALIDATORS[name](field.value, field, today)
        results.append(ValidationResult(validator=name, ok=message is None, message=message))
    return results
