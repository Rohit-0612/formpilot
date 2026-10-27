"""Dates in forms (SPEC §6.6): reading a date the user typed, and writing it in the format the
form asks for (a hint such as "DD/MM/YYYY" in the label; DD/MM/YYYY by default)."""

import re
from datetime import date, datetime

from app.ir.models import Field

DEFAULT_FORMAT = "%d/%m/%Y"

# Hint tokens in labels, e.g. "Date of Birth (DD-MM-YYYY)" or "dd/mm/yy".
_HINT = re.compile(r"\b(dd|mm|yyyy|yy)\s*([/.\-]?)\s*(dd|mm)\s*\2\s*(dd|mm|yyyy|yy)\b", re.I)
_TOKEN = {"dd": "%d", "mm": "%m", "yyyy": "%Y", "yy": "%y"}
# Box captions without separators, possibly spaced out: "DDMMYYYY", "D D M M Y Y Y Y".
_COMPACT = re.compile(
    r"\b(d\s?d\s?m\s?m\s?y\s?y(?:\s?y\s?y)?|y\s?y\s?y\s?y\s?m\s?m\s?d\s?d)\b", re.I
)
_COMPACT_FORMAT = {"ddmmyyyy": "%d%m%Y", "yyyymmdd": "%Y%m%d", "ddmmyy": "%d%m%y"}

# Formats a user may type, tried in order (day first: the Indian convention).
_INPUT_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %m %Y", "%Y-%m-%d", "%d%m%Y",
    "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%d/%m/%y", "%d-%m-%y",
)  # fmt: skip


def date_format_for(field: Field) -> str:
    """The strftime format the field asks for: its part of the date for a DD | MM | YYYY box
    (decision P5-D8), else from the hint in its label or context."""
    if field.date_part == "day":
        return "%d"
    if field.date_part == "month":
        return "%m"
    if field.date_part == "year":
        return "%y" if field.max_chars == 2 else "%Y"
    for text in (field.label_text, field.context_text):
        if not text:
            continue
        compact = _COMPACT.search(text)
        if compact:
            return _COMPACT_FORMAT[compact.group(1).replace(" ", "").lower()]
        hint = _HINT.search(text)
        if hint:
            first, sep, middle, last = hint.groups()
            parts = [_TOKEN[first.lower()], _TOKEN[middle.lower()], _TOKEN[last.lower()]]
            if len({p.lower() for p in parts}) == 3:
                return sep.join(parts)
    if field.max_chars == 8:  # eight boxes: a date without separators
        return "%d%m%Y"
    return DEFAULT_FORMAT


def parse_date(text: str) -> date | None:
    """A date the user typed, in any common format (day before month), or None."""
    cleaned = re.sub(r"\s+", " ", text.strip().replace(",", " ")).strip()
    cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", cleaned)
    for fmt in _INPUT_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value: date, fmt: str) -> str:
    return value.strftime(fmt)


def parse_in_format(text: str, fmt: str) -> date | None:
    """The date if `text` is written exactly in `fmt`, else None."""
    try:
        parsed = datetime.strptime(text.strip(), fmt).date()
    except ValueError:
        return None
    return parsed if format_date(parsed, fmt) == text.strip() else None
