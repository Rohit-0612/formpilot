import pytest

from app.ir.geometry import MATCH_IOU, intersection_area, iou
from app.ir.models import BBox
from tests.fixtures.pdfs import FONT_SIZE, ROW_HEIGHT


def _box(x0: float, y0: float, x1: float, y1: float, page: int = 0) -> BBox:
    return BBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1)


# --- basics -------------------------------------------------------------------------------


def test_identical_boxes() -> None:
    assert iou(_box(0, 0, 10, 10), _box(0, 0, 10, 10)) == 1.0


def test_disjoint_and_touching_boxes() -> None:
    assert iou(_box(0, 0, 10, 10), _box(20, 0, 30, 10)) == 0.0
    assert iou(_box(0, 0, 10, 10), _box(10, 0, 20, 10)) == 0.0  # shared edge, no area


def test_different_pages_never_overlap() -> None:
    assert iou(_box(0, 0, 10, 10, page=0), _box(0, 0, 10, 10, page=1)) == 0.0


def test_partial_overlap() -> None:
    # Overlap 5 x 10 = 50; union 100 + 100 - 50 = 150.
    assert intersection_area(_box(0, 0, 10, 10), _box(5, 0, 15, 10)) == 50
    assert iou(_box(0, 0, 10, 10), _box(5, 0, 15, 10)) == pytest.approx(1 / 3)


def test_containment() -> None:
    assert iou(_box(0, 0, 10, 10), _box(2, 2, 7, 7)) == pytest.approx(25 / 100)


def test_symmetric() -> None:
    a, b = _box(0, 0, 10, 10), _box(3, 4, 18, 9)
    assert iou(a, b) == iou(b, a)


# --- the line-entry convention tolerates how a human draws the box ------------------------
# Convention: from the writing line up by ROW_HEIGHT = 1.2 x the label's font size.
# Labeller instruction: from the start to the end of the line, and from the line up to a
# little above the label's capital letters. These heights must still match.

WRITING_LINE = 400.0
LINE_X0, LINE_X1 = 150.0, 450.0


def _line_entry(height: float, x0: float = LINE_X0, x1: float = LINE_X1) -> BBox:
    return _box(x0, WRITING_LINE - height, x1, WRITING_LINE)


def test_convention_box_is_one_point_two_font_heights() -> None:
    assert pytest.approx(1.2 * FONT_SIZE) == ROW_HEIGHT


@pytest.mark.parametrize("factor", [1.0, 1.5])
def test_human_box_of_one_to_one_and_a_half_font_heights_matches(factor: float) -> None:
    convention = _line_entry(ROW_HEIGHT)
    human = _line_entry(factor * FONT_SIZE)

    assert iou(human, convention) >= MATCH_IOU


def test_human_box_with_small_horizontal_slack_still_matches() -> None:
    convention = _line_entry(ROW_HEIGHT)
    # 1.0x font height, starting 3 pt early and ending 5 pt short.
    human = _line_entry(FONT_SIZE, x0=LINE_X0 - 3, x1=LINE_X1 - 5)

    assert iou(human, convention) >= MATCH_IOU


@pytest.mark.parametrize(
    ("factor", "matches"), [(0.6, True), (0.55, False), (2.4, True), (2.5, False)]
)
def test_tolerance_window_is_0_6_to_2_4_font_heights(factor: float, matches: bool) -> None:
    """With the x-span right, any height from 0.6x to 2.4x the font size still matches."""
    result = iou(_line_entry(factor * FONT_SIZE), _line_entry(ROW_HEIGHT))

    assert (result >= MATCH_IOU - 1e-9) is matches
