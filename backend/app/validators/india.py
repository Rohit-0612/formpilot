"""Indian identifier and contact formats (SPEC §6.6). Each check returns None when the value is
valid, else a message that never contains the value."""

import re

from app.validators import verhoeff

_SPACES = re.compile(r"[\s\-]+")
_PAN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
_AADHAAR = re.compile(r"[2-9][0-9]{11}")
_IFSC = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")
_PINCODE = re.compile(r"[1-9][0-9]{5}")
_MOBILE = re.compile(r"(?:\+91|0)?([6-9][0-9]{9})")


def compact(value: str) -> str:
    """Spaces and hyphens removed, letters upper-cased."""
    return _SPACES.sub("", value).upper()


def pan_format(value: str) -> str | None:
    if _PAN.fullmatch(compact(value)):
        return None
    return "A PAN has 5 letters, 4 digits and a letter (e.g. ABCDE1234F)."


def aadhaar_format(value: str) -> str | None:
    if _AADHAAR.fullmatch(compact(value)):
        return None
    return "An Aadhaar number has 12 digits and does not start with 0 or 1."


def aadhaar_verhoeff(value: str) -> str | None:
    digits = compact(value)
    if not _AADHAAR.fullmatch(digits) or verhoeff.is_valid(digits):
        return None  # a format error is reported by aadhaar_format only
    return "This Aadhaar number has a wrong check digit; please check it for a typo."


def ifsc_format(value: str) -> str | None:
    if _IFSC.fullmatch(compact(value)):
        return None
    return "An IFSC has 4 letters, a 0, and 6 letters or digits (e.g. SBIN0001234)."


def pincode_format(value: str) -> str | None:
    if _PINCODE.fullmatch(compact(value)):
        return None
    return "A PIN code has 6 digits and does not start with 0."


def mobile_digits(value: str) -> str | None:
    """The 10-digit Indian mobile number in `value` (optional +91 or 0), or None."""
    match = _MOBILE.fullmatch(compact(value))
    return match.group(1) if match else None


def phone_in(value: str) -> str | None:
    if mobile_digits(value) is not None:
        return None
    return "A mobile number has 10 digits starting with 6, 7, 8 or 9 (optionally +91 or 0)."
