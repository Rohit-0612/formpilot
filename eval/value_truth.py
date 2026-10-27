"""What the right value of a reference field is, for the fill eval's value check (Phase 5).

The reference says a field's semantic type; the right value usually follows from the type and the
persona. Two layouts break that, and are read from the human boxes (eval/labels/) and the
reference types only, never from the detector, so that every detector version is scored alike:

- **Repeated rows**: fields of one type stacked directly below each other in one column (the
  rows of an education table, an office and a home phone). A profile holds one value per type,
  so no profile value is right in any of them: a fill there counts as a wrong value.
- **Date parts**: fields of one date type side by side on one row (DD | MM | YYYY, "this ___ day
  of ___ 20__") are, left to right, the day, the month and the year of one date.

Values are compared as printed (upper-casing included), case and spacing ignored; date parts by
number (a month also by its name, a year also by its last two digits when only two are written).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.ir.semantic_types import SemanticType as T
from eval.labelling.schema import LabelField

type DatePart = Literal["day", "month", "year"]
PARTS: tuple[DatePart, ...] = ("day", "month", "year")
DATE_TYPES = frozenset({T.DATE_OF_BIRTH, T.DATE_OF_FILLING})
ROW_TOLERANCE = 3.0  # points between the tops of boxes on one row
MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
)  # fmt: skip


@dataclass(frozen=True)
class Role:
    repeated: bool = False  # in a run of repeated rows: no profile value is right
    part: DatePart | None = None  # a part of a date split over several boxes


NO_ROLE = Role()


def _x_overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return min(a[2], b[2]) - max(a[0], b[0])


def _stacked(upper: LabelField, lower: LabelField) -> bool:
    """`lower` is the next row below `upper` in the same column."""
    a, b = upper.bbox, lower.bbox
    narrower = min(a[2] - a[0], b[2] - b[0])
    gap = b[1] - a[3]
    return _x_overlap(a, b) >= 0.5 * narrower and 0 <= gap <= a[3] - a[1]


def roles(fields: Sequence[LabelField], reference: Mapping[str, T]) -> dict[str, Role]:
    """The label field ids in a repeated row or a date part, with their role."""
    typed = [f for f in fields if f.id in reference]
    out: dict[str, Role] = {}
    for a in typed:
        for b in typed:
            if (
                a is not b
                and a.page == b.page
                and reference[a.id] is reference[b.id]
                and _stacked(a, b)
            ):
                out[a.id] = out[b.id] = Role(repeated=True)
    for a in typed:
        if reference[a.id] not in DATE_TYPES or a.id in out:
            continue
        row = sorted(
            (
                b
                for b in typed
                if b.page == a.page
                and reference[b.id] is reference[a.id]
                and abs(b.bbox[1] - a.bbox[1]) <= ROW_TOLERANCE
                and b.id not in out
            ),
            key=lambda f: f.bbox[0],
        )
        if 2 <= len(row) <= len(PARTS):
            for field, part in zip(row, PARTS, strict=False):
                out[field.id] = Role(part=part)
    return out


def _number(text: str, part: DatePart) -> int | None:
    word = text.strip().casefold().rstrip(".")
    if part == "month":
        for i, name in enumerate(MONTHS, 1):
            if len(word) >= 3 and name.startswith(word):
                return i
    return int(word) if word.isdigit() else None


def part_right(printed: str, born: date, part: DatePart) -> bool:
    number = _number(printed, part)
    if number is None:
        return False
    if part == "day":
        return number == born.day
    if part == "month":
        return number == born.month
    digits = printed.strip()
    return number == born.year or (len(digits) == 2 and number == born.year % 100)


def same_text(printed: str, expected: str) -> bool:
    return " ".join(printed.split()).casefold() == " ".join(expected.split()).casefold()
