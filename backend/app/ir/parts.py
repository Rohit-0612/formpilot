"""Parts of one value written in neighbouring boxes, shared by the passes and the render checks.

A date in DD | MM | YYYY boxes is several fields, each with `date_part` (decision P5-D8). The
parts of one date are the fields with a date part that follow each other in reading order on one
row, each box touching the one before it; a part that repeats starts another date. A date is
filled, printed or left empty as a whole (decision P5-D13).
"""

from collections.abc import Sequence

from app.ir.models import BBox, Field

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
