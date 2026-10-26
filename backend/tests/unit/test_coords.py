"""Coordinate conversions, checked by hand-computed cases, round trips, and against PyMuPDF."""

import random

import pymupdf
import pytest

from app.ir.coords import (
    PageGeometry,
    Rect,
    bbox_from_pixels,
    bbox_to_pdf_rect,
    bbox_to_pixels,
    ir_point_to_pdf,
    pdf_point_to_ir,
    pdf_rect_to_bbox,
)
from app.ir.models import BBox

ROTATIONS = (0, 90, 180, 270)
# A CropBox whose origin is not (0, 0), inside a MediaBox that is offset too.
MEDIA_BOX = (10.0, 20.0, 410.0, 620.0)
CROP_BOX = (20.0, 40.0, 400.0, 600.0)  # 380 x 560 points
LETTER = (0.0, 0.0, 612.0, 792.0)


# --- hand-computed cases ------------------------------------------------------------------


def test_letter_page_corners_flip_vertically() -> None:
    geometry = PageGeometry(LETTER)

    assert pdf_point_to_ir(0, 0, geometry) == (0, 792)  # bottom-left -> bottom-left
    assert pdf_point_to_ir(0, 792, geometry) == (0, 0)  # top-left -> origin
    assert pdf_point_to_ir(612, 792, geometry) == (612, 0)


def test_bottom_left_rect_to_top_left_bbox() -> None:
    # A 100 x 20 pt box whose bottom edge is 700 pt above the page bottom.
    bbox = pdf_rect_to_bbox((72, 700, 172, 720), PageGeometry(LETTER), page=3)

    assert bbox == BBox(page=3, x0=72, y0=72, x1=172, y1=92)


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        # Values reported by PyMuPDF 1.28.2 (drawing rect * page.rotation_matrix), 2026-10-11.
        (0, (30, 480, 60, 500)),
        (90, (60, 30, 80, 60)),
        (180, (320, 60, 350, 80)),
        (270, (480, 320, 500, 350)),
    ],
)
def test_offset_crop_box_and_rotation(rotation: int, expected: Rect) -> None:
    rect_in_user_space = (50.0, 100.0, 80.0, 120.0)

    bbox = pdf_rect_to_bbox(rect_in_user_space, PageGeometry(CROP_BOX, rotation), page=0)

    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == expected


@pytest.mark.parametrize(("rotation", "size"), [(0, (380, 560)), (90, (560, 380))])
def test_displayed_size_swaps_on_quarter_turns(rotation: int, size: tuple[float, float]) -> None:
    assert PageGeometry(CROP_BOX, rotation).displayed_size == size


@pytest.mark.parametrize(
    ("crop_box", "rotation"),
    [((0, 0, 0, 792), 0), ((0, 792, 612, 0), 0), (LETTER, 45), (LETTER, -90)],
)
def test_invalid_geometry_is_rejected(crop_box: Rect, rotation: int) -> None:
    with pytest.raises(ValueError):
        PageGeometry(crop_box, rotation)


# --- round trips (deterministic pseudo-random points) -------------------------------------


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_point_round_trip(rotation: int) -> None:
    geometry = PageGeometry(CROP_BOX, rotation)
    rng = random.Random(rotation)

    for _ in range(200):
        x, y = rng.uniform(20, 400), rng.uniform(40, 600)
        back = ir_point_to_pdf(*pdf_point_to_ir(x, y, geometry), geometry)
        assert back == pytest.approx((x, y))


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_rect_round_trip(rotation: int) -> None:
    geometry = PageGeometry(CROP_BOX, rotation)
    rng = random.Random(1000 + rotation)

    for _ in range(200):
        x0, y0 = rng.uniform(20, 300), rng.uniform(40, 500)
        rect = (x0, y0, x0 + rng.uniform(1, 90), y0 + rng.uniform(1, 90))
        bbox = pdf_rect_to_bbox(rect, geometry, page=0)
        assert bbox_to_pdf_rect(bbox, geometry) == pytest.approx(rect)


@pytest.mark.parametrize("rotation", ROTATIONS)
def test_ir_boxes_stay_inside_the_displayed_page(rotation: int) -> None:
    geometry = PageGeometry(CROP_BOX, rotation)
    width, height = geometry.displayed_size

    bbox = pdf_rect_to_bbox(CROP_BOX, geometry, page=0)

    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == pytest.approx((0, 0, width, height))


# --- against PyMuPDF ----------------------------------------------------------------------


def _pdf_with_rect(rect: Rect, rotation: int) -> bytes:
    """One page with MEDIA_BOX/CROP_BOX/rotation and a stroked rect drawn in PDF user space."""
    x0, y0, x1, y1 = rect
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(1, 1, 2, 2))  # creates a content stream we then replace
    content = f"0 0 0 RG 0.5 w {x0} {y0} {x1 - x0} {y1 - y0} re S".encode()
    doc.update_stream(page.get_contents()[0], content)
    doc.xref_set_key(page.xref, "MediaBox", "[{} {} {} {}]".format(*MEDIA_BOX))
    doc.xref_set_key(page.xref, "CropBox", "[{} {} {} {}]".format(*CROP_BOX))
    doc.xref_set_key(page.xref, "Rotate", str(rotation))
    return doc.tobytes()


@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("rect", [(50, 100, 80, 120), (21, 41, 399, 599), (200, 300, 201, 450)])
def test_matches_pymupdf_displayed_coordinates(rotation: int, rect: Rect) -> None:
    with pymupdf.open("pdf", _pdf_with_rect(rect, rotation)) as doc:
        page = doc[0]
        (drawing,) = page.get_drawings()
        expected = drawing["rect"] * page.rotation_matrix
        displayed = (page.rect.width, page.rect.height)

    geometry = PageGeometry(CROP_BOX, rotation)
    bbox = pdf_rect_to_bbox(rect, geometry, page=0)

    assert geometry.displayed_size == pytest.approx(displayed)
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == pytest.approx(tuple(expected), abs=1e-3)


# --- pixels <-> points --------------------------------------------------------------------


def test_pixels_at_72_dpi_equal_points() -> None:
    bbox = BBox(page=0, x0=10, y0=20, x1=30, y1=40)

    assert bbox_to_pixels(bbox, dpi=72) == (10, 20, 30, 40)


def test_pixels_scale_with_dpi() -> None:
    bbox = BBox(page=1, x0=72, y0=36, x1=144, y1=72)

    assert bbox_to_pixels(bbox, dpi=144) == (144, 72, 288, 144)
    assert bbox_from_pixels((144, 72, 288, 144), dpi=144, page=1) == bbox


@pytest.mark.parametrize("dpi", [72, 96, 110, 144, 300])
def test_pixel_round_trip(dpi: int) -> None:
    rng = random.Random(dpi)
    for _ in range(100):
        x0, y0 = rng.uniform(0, 500), rng.uniform(0, 700)
        bbox = BBox(page=0, x0=x0, y0=y0, x1=x0 + rng.uniform(1, 90), y1=y0 + rng.uniform(1, 90))
        back = bbox_from_pixels(bbox_to_pixels(bbox, dpi), dpi, page=0)
        assert (back.x0, back.y0, back.x1, back.y1) == pytest.approx(
            (bbox.x0, bbox.y0, bbox.x1, bbox.y1)
        )
