"""A value the user typed, checked and put in its canonical form for its semantic type.

Used for profile values and for answers. Canonical forms: dates ISO (YYYY-MM-DD; formatted per
form by the match and answers passes), identifiers upper-case without spaces, mobile numbers as
10 digits, other text with single spaces. Errors carry a message, never the value.
"""

import re
from datetime import date

from app.ir.semantic_types import SemanticType as T
from app.validators import common, india
from app.validators.dates import parse_date

MAX_TEXT = 200
_SPACES = re.compile(r"\s+")
_YEAR = re.compile(r"(19|20)[0-9]{2}")
_DATE_TYPES = frozenset({T.DATE_OF_BIRTH, T.DATE_OF_FILLING})
_COMPACT_CHECKS = {
    T.PAN: india.pan_format,
    T.IFSC: india.ifsc_format,
    T.CURRENT_PINCODE: india.pincode_format,
    T.PERMANENT_PINCODE: india.pincode_format,
}


class InvalidValueError(ValueError):
    """The message is safe to show and to log: it never contains the value."""


def normalize(semantic_type: T, raw: str, today: date) -> str:
    value = _SPACES.sub(" ", raw).strip()
    if not value:
        raise InvalidValueError("The value is empty.")
    if len(value) > MAX_TEXT:
        raise InvalidValueError(f"The value is longer than {MAX_TEXT} characters.")
    if semantic_type in _DATE_TYPES:
        parsed = parse_date(value)
        if parsed is None:
            raise InvalidValueError("This is not a date (try DD/MM/YYYY).")
        if semantic_type is T.DATE_OF_BIRTH and parsed > today:
            raise InvalidValueError("A date of birth cannot be in the future.")
        return parsed.isoformat()
    if semantic_type in _COMPACT_CHECKS:
        return _checked(_COMPACT_CHECKS[semantic_type](value), india.compact(value))
    if semantic_type is T.AADHAAR:
        digits = india.compact(value)
        return _checked(india.aadhaar_format(value) or india.aadhaar_verhoeff(value), digits)
    if semantic_type in (T.PHONE_MOBILE, T.PHONE_ALTERNATE):
        mobile = india.mobile_digits(value)
        if mobile is None:
            raise InvalidValueError(india.phone_in(value) or "")
        return mobile
    if semantic_type is T.EMAIL:
        return _checked(common.email_format(value), value)
    if semantic_type is T.PASSING_YEAR:
        return _checked(None if _YEAR.fullmatch(value) else "Enter a year such as 2024.", value)
    if semantic_type in (T.PASSPORT_NUMBER, T.VOTER_ID, T.BANK_ACCOUNT_NUMBER):
        return india.compact(value)
    return value


def _checked(message: str | None, value: str) -> str:
    if message is not None:
        raise InvalidValueError(message)
    return value
