"""Parts of one value written in neighbouring boxes, shared by the passes and the render checks.

A date in DD | MM | YYYY boxes is several fields, each with `date_part` (decision P5-D8). The
parts of one date are the fields with a date part that follow each other in reading order on one
row, each box touching the one before it; a part that repeats starts another date. A date is
filled, printed or left empty as a whole (decision P5-D13). A person's name in FIRST | MIDDLE |
LAST boxes is found from the parts' hint labels (`name_groups`, decision P5-D16).
"""

from collections.abc import Sequence
from typing import Literal

from app.ir.models import BBox, Field
from app.ir.phrases import clean_text

type NamePart = Literal["first", "middle", "last"]

# Neighbouring parts touch, or leave at most this gap (points) between their boxes.
MAX_PART_GAP = 3.0


def side_by_side(a: BBox, b: BBox) -> bool:
    """b starts where a ends, on the same row."""
    if a.page != b.page or abs(b.x0 - a.x1) > MAX_PART_GAP:
        return False
    overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    return overlap >= 0.5 * min(a.height, b.height)


def date_groups(fields: Sequence[Field]) -> list[list[Field]]:
    """The dates written in two or more part boxes, each as its parts in reading order."""
    groups: list[list[Field]] = []
    run: list[Field] = []
    for f in fields:
        if (
            f.date_part is not None
            and run
            and side_by_side(run[-1].bbox, f.bbox)
            and f.date_part not in {p.date_part for p in run}
        ):
            run.append(f)
            continue
        if len(run) > 1:
            groups.append(run)
        run = [f] if f.date_part is not None else []
    if len(run) > 1:
        groups.append(run)
    return groups


# A person's name in FIRST | MIDDLE | LAST boxes (decision P5-D16): the frontend labels each part
# by the hint printed in it (decision P5-D8).
NAME_PART_LABELS: dict[str, NamePart] = {
    "first name": "first", "middle name": "middle", "last name": "last", "surname": "last",
}  # fmt: skip


def name_part(f: Field) -> NamePart | None:
    return NAME_PART_LABELS.get(clean_text(f.label_text or ""))


def name_groups(fields: Sequence[Field]) -> list[list[tuple[Field, NamePart]]]:
    """The names written in two or more part boxes, each as (field, part) in reading order.

    The parts follow each other in reading order (the last part may start the next row); the
    field just before a middle or last part, side by side with it, is the first part even when
    it carries the row's own label ("9.Name of Guardian") instead of the hint."""
    groups: list[list[tuple[Field, NamePart]]] = []
    run: list[tuple[Field, NamePart]] = []
    previous: Field | None = None
    for f in fields:
        part = name_part(f)
        if part is not None and run and part not in {p for _, p in run}:
            run.append((f, part))
        elif (
            part in ("middle", "last")
            and previous is not None
            and name_part(previous) is None
            and side_by_side(previous.bbox, f.bbox)
        ):
            run = [(previous, "first"), (f, part)]
        else:
            if len(run) > 1:
                groups.append(run)
            run = [(f, part)] if part is not None else []
        previous = f
    if len(run) > 1:
        groups.append(run)
    return groups
