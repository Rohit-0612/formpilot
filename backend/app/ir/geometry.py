"""Geometry on IR boxes, shared by the frontends and the detection eval."""

from app.ir.models import BBox

# SPEC §10: a predicted box matches a labelled box at IoU >= 0.5 on the same page.
MATCH_IOU = 0.5


def intersection_area(a: BBox, b: BBox) -> float:
    if a.page != b.page:
        return 0.0
    width = min(a.x1, b.x1) - max(a.x0, b.x0)
    height = min(a.y1, b.y1) - max(a.y0, b.y0)
    return width * height if width > 0 and height > 0 else 0.0


def iou(a: BBox, b: BBox) -> float:
    """Intersection over union; 0.0 for boxes on different pages."""
    overlap = intersection_area(a, b)
    if overlap == 0.0:
        return 0.0
    union = a.width * a.height + b.width * b.height - overlap
    return overlap / union
