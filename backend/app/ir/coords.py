"""Coordinate conversions at the edges of the pipeline (architecture invariant 6).

Inside the IR, boxes are PDF points with the origin at the top-left of the *displayed* page, i.e.
the CropBox after applying /Rotate (SPEC §4).

Outside the IR there are two other systems:
- PDF user space: origin at the bottom-left, y grows upwards, and the visible area is the CropBox,
  whose origin need not be (0, 0). /Rotate turns the page clockwise for display.
- Page images: pixels at a known DPI, origin top-left (the viewer and the labelling tool).

Note: PyMuPDF already reports words and drawings top-left, but on the *unrotated* page;
`page.rotation_matrix` maps them to the displayed page (checked 2026-10-11, see
docs/decisions/phase-2.md).
"""

from dataclasses import dataclass

from app.ir.models import BBox

POINTS_PER_INCH = 72.0

Rect = tuple[float, float, float, float]  # (x0, y0, x1, y1)


@dataclass(frozen=True)
class PageGeometry:
    """Where a page's visible area sits in PDF user space, and how it is rotated."""

    crop_box: Rect  # PDF user space, bottom-left origin
    rotation: int = 0  # /Rotate: 0, 90, 180 or 270, clockwise

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.crop_box
        if not (x0 < x1 and y0 < y1):
            raise ValueError("crop box must have x0 < x1 and y0 < y1")
        if self.rotation not in (0, 90, 180, 270):
            raise ValueError("rotation must be 0, 90, 180 or 270")

    @property
    def unrotated_size(self) -> tuple[float, float]:
        x0, y0, x1, y1 = self.crop_box
        return x1 - x0, y1 - y0

    @property
    def displayed_size(self) -> tuple[float, float]:
        """(width, height) in points of the page as displayed."""
        width, height = self.unrotated_size
        return (height, width) if self.rotation in (90, 270) else (width, height)


def pdf_point_to_ir(x: float, y: float, geometry: PageGeometry) -> tuple[float, float]:
    """PDF user space (bottom-left origin) -> displayed page, top-left origin."""
    cx0, _, _, cy1 = geometry.crop_box
    width, height = geometry.unrotated_size
    # Unrotated page, top-left origin.
    u, v = x - cx0, cy1 - y
    match geometry.rotation:
        case 0:
            return u, v
        case 90:
            return height - v, u
        case 180:
            return width - u, height - v
        case _:  # 270
            return v, width - u


def ir_point_to_pdf(x: float, y: float, geometry: PageGeometry) -> tuple[float, float]:
    """Displayed page, top-left origin -> PDF user space (bottom-left origin)."""
    cx0, _, _, cy1 = geometry.crop_box
    width, height = geometry.unrotated_size
    match geometry.rotation:
        case 0:
            u, v = x, y
        case 90:
            u, v = y, height - x
        case 180:
            u, v = width - x, height - y
        case _:  # 270
            u, v = width - y, x
    return u + cx0, cy1 - v


def _normalised(ax: float, ay: float, bx: float, by: float) -> Rect:
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def pdf_rect_to_bbox(rect: Rect, geometry: PageGeometry, page: int) -> BBox:
    """A rectangle in PDF user space (e.g. a widget's /Rect) -> an IR box."""
    x0, y0, x1, y1 = rect
    ax, ay = pdf_point_to_ir(x0, y0, geometry)
    bx, by = pdf_point_to_ir(x1, y1, geometry)
    nx0, ny0, nx1, ny1 = _normalised(ax, ay, bx, by)
    return BBox(page=page, x0=nx0, y0=ny0, x1=nx1, y1=ny1)


def bbox_to_pdf_rect(bbox: BBox, geometry: PageGeometry) -> Rect:
    """An IR box -> a rectangle in PDF user space, normalised so x0 < x1 and y0 < y1."""
    ax, ay = ir_point_to_pdf(bbox.x0, bbox.y0, geometry)
    bx, by = ir_point_to_pdf(bbox.x1, bbox.y1, geometry)
    return _normalised(ax, ay, bx, by)


def points_to_pixels(value: float, dpi: float) -> float:
    return value * dpi / POINTS_PER_INCH


def pixels_to_points(value: float, dpi: float) -> float:
    return value * POINTS_PER_INCH / dpi


def bbox_to_pixels(bbox: BBox, dpi: float) -> Rect:
    """An IR box -> pixel rectangle on a page image rendered at dpi (both top-left origin)."""
    return (
        points_to_pixels(bbox.x0, dpi),
        points_to_pixels(bbox.y0, dpi),
        points_to_pixels(bbox.x1, dpi),
        points_to_pixels(bbox.y1, dpi),
    )


def bbox_from_pixels(rect: Rect, dpi: float, page: int) -> BBox:
    """A pixel rectangle on a page image rendered at dpi -> an IR box."""
    x0, y0, x1, y1 = (pixels_to_points(value, dpi) for value in rect)
    return BBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1)
