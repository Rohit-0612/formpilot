"""Masking of sensitive values in Form IRs returned to the client (CLAUDE.md §3, decision D2).

Rule (SPEC §8): every Form IR that leaves the API is masked. The stored IR keeps the real values
(the renderer needs them); only the response is masked. A field value is masked when
- the field's semantic type is sensitive (D2: aadhaar, pan, bank_account_number,
  passport_number, voter_id), or
- defence in depth: the value itself looks like one of those identifiers, whatever the field's
  semantic type (e.g. an Aadhaar number typed into a field understood as `other`).

Mask format: "XXXX" + the last 4 characters (separators removed) for values of 8 or more
characters, else "XXXX". The prefix has a fixed length, so the mask does not reveal the value's
length. Masking is idempotent.
"""

import re
from typing import Any

from app.ir.semantic_types import SENSITIVE_TYPES, SemanticType

MASK = "XXXX"
_SHOW_TAIL_FROM_LENGTH = 8
_TAIL = 4
_SEPARATORS = re.compile(r"[\s\-]+")

# The D2 identifiers as Indian formats, matched against the whole value with spaces, hyphens and
# a leading "+" removed and letters upper-cased. Deliberately broad: masking too much is safe,
# too little is not.
SENSITIVE_PATTERNS: dict[SemanticType, re.Pattern[str]] = {
    SemanticType.AADHAAR: re.compile(r"[2-9][0-9]{11}"),  # checksum not required
    SemanticType.PAN: re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]"),
    SemanticType.PASSPORT_NUMBER: re.compile(r"[A-Z][0-9]{7}"),
    SemanticType.VOTER_ID: re.compile(r"[A-Z]{3}[0-9]{7}"),
    SemanticType.BANK_ACCOUNT_NUMBER: re.compile(r"[0-9]{9,18}"),
}

# Phone exception (human, 2026-10-19): a mobile number matches the bank account pattern (and
# "+91" + 10 digits looks like an Aadhaar). In a field understood as a phone number, a value in
# Indian mobile format (10 digits starting 6-9, optional "+91" or leading "0"; SPEC §6.6) is not
# masked. Any other value in a phone field is checked like everywhere else. Known limitation: a
# bank account field misclassified as a phone field, holding a mobile-shaped number, is not masked.
_PHONE_TYPES = frozenset({SemanticType.PHONE_MOBILE, SemanticType.PHONE_ALTERNATE})
_INDIAN_MOBILE = re.compile(r"(?:\+91|0)?[6-9][0-9]{9}")


def _compact(value: str) -> str:
    return _SEPARATORS.sub("", value).upper()


def mask_value(value: str) -> str:
    compact = _compact(value)
    if len(compact) < _SHOW_TAIL_FROM_LENGTH:
        return MASK
    return MASK + compact[-_TAIL:]


def looks_sensitive(value: str, semantic_type: SemanticType) -> bool:
    """True if the value matches a D2 identifier pattern (the phone exception aside).

    Only whole values are matched: an identifier inside a longer value (e.g. an address) is not
    caught (known limitation).
    """
    compact = _compact(value)
    if semantic_type in _PHONE_TYPES and _INDIAN_MOBILE.fullmatch(compact):
        return False
    candidate = compact.removeprefix("+")
    return any(pattern.fullmatch(candidate) for pattern in SENSITIVE_PATTERNS.values())


def must_mask(value: str | None, semantic_type: SemanticType) -> bool:
    if value is None:
        return False
    return semantic_type in SENSITIVE_TYPES or looks_sensitive(value, semantic_type)


def mask_ir_data(data: dict[str, Any]) -> dict[str, Any]:
    """A copy of a Form IR (as a dict, e.g. from model_dump or the database) with values masked.

    Only `fields[*].value` can hold a user's value: option values and labels come from the form,
    and trace events and validation messages never contain values (SPEC §4, §6.6).
    """
    fields = []
    for field in data.get("fields", []):
        field = dict(field)
        semantic_type = SemanticType(field.get("semantic_type", SemanticType.UNKNOWN))
        if must_mask(field.get("value"), semantic_type):
            field["value"] = mask_value(field["value"])
        fields.append(field)
    return {**data, "fields": fields}
