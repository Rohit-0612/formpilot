import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import pairwise

import pymupdf
import pytest

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.geometry import intersection_area, iou
from app.ir.models import BBox, FieldKind, FieldStatus, FormIR, SourceKind, ValueSource
from app.ir.semantic_types import SemanticType
from tests.fixtures import pdfs
from tests.fixtures.pdfs import ExpectedField

DOC_ID = uuid.UUID("5f0c6d1e-0000-4000-8000-000000000002")
AT = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
FIXTURE_MATCH_IOU = 0.9

# Every fixture the flat frontend applies to (AcroForm fields are widgets: Step 9).
FLAT_FIXTURES = [
    name
    for name in pdfs.NAMES
    if not pdfs.get(name).encrypted and pdfs.get(name).source_kind is not SourceKind.FILLABLE
]


def _run(data: bytes) -> FormIR:
    with pymupdf.open("pdf", data) as doc:
        return flat.run(doc, detect(doc), DOC_ID, AT)


def _run_fixture(name: str) -> FormIR:
    return _run(pdfs.get(name).data)


def _bbox(expected: ExpectedField) -> BBox:
    x0, y0, x1, y1 = expected.bbox
    return BBox(page=expected.page, x0=x0, y0=y0, x1=x1, y1=y1)


def _pdf(draw: Callable[[pymupdf.Page], None], size: tuple[float, float] = pdfs.A4) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    draw(page)
    return doc.tobytes()


def _text(page: pymupdf.Page, x: float, y: float, text: str) -> None:
    page.insert_text((x, y), text, fontname="helv", fontsize=10)


def _line(page: pymupdf.Page, x0: float, y: float, x1: float) -> None:
    page.draw_line((x0, y), (x1, y), color=(0, 0, 0), width=0.5)


# --- against the fixtures' ground truth ---------------------------------------------------


# Labelling rules 1-3 (Step 5): the detector learns them in Step 11. Strict xfail, so the test
# fails loudly once a rule is implemented and the marker must be removed.
STEP_11_RULES = {"flat_wide_cells", "flat_label_inside"}


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            name,
            marks=pytest.mark.xfail(strict=True, reason="labelling rule not implemented (Step 11)"),
        )
        if name in STEP_11_RULES
        else name
        for name in FLAT_FIXTURES
    ],
)
def test_detected_fields_match_ground_truth(name: str) -> None:
    fixture = pdfs.get(name)
    fields = list(_run_fixture(name).fields)

    unmatched = list(fields)
    for expected in fixture.fields:
        target = _bbox(expected)
        best = max(unmatched, key=lambda f: iou(f.bbox, target), default=None)
        assert best is not None and iou(best.bbox, target) >= FIXTURE_MATCH_IOU, (
            f"missed {expected.kind.value} field labelled {expected.label!r} at {expected.bbox}"
        )
        unmatched.remove(best)
        assert best.kind is expected.kind
        if expected.max_chars is not None:
            assert best.max_chars == expected.max_chars
        if expected.label is not None:
            assert best.label_text == expected.label
        if expected.context is not None:
            assert best.context_text == expected.context
    assert unmatched == [], f"extra fields: {[(f.id, f.kind.value, f.bbox) for f in unmatched]}"


@pytest.mark.parametrize("name", FLAT_FIXTURES)
def test_detected_fields_never_overlap(name: str) -> None:
    fields = _run_fixture(name).fields

    for i, a in enumerate(fields):
        for b in fields[i + 1 :]:
            assert intersection_area(a.bbox, b.bbox) == 0.0, (a.id, b.id)


@pytest.mark.parametrize("name", FLAT_FIXTURES)
def test_ids_are_unique_and_in_reading_order(name: str) -> None:
    fields = _run_fixture(name).fields

    assert len({f.id for f in fields}) == len(fields)
    for f in fields:
        assert re.fullmatch(rf"p{f.bbox.page}_f\d{{3}}", f.id)
    for page in {f.bbox.page for f in fields}:
        on_page = [f for f in fields if f.bbox.page == page]
        assert [f.id for f in on_page] == [f"p{page}_f{i:03d}" for i in range(len(on_page))]
        centers = [(f.bbox.y0 + f.bbox.y1) / 2 for f in on_page]
        # Rows go top to bottom (a field is never far above the one before it).
        assert all(b >= a - 6 for a, b in pairwise(centers))


def test_fields_are_detected_only_with_no_values() -> None:
    for field in _run_fixture("flat_underscores").fields:
        assert field.status is FieldStatus.DETECTED
        assert field.value is None
        assert field.value_source is ValueSource.NONE
        assert field.semantic_type is SemanticType.UNKNOWN
        assert field.native_name is None


def test_ir_carries_detection_result() -> None:
    ir = _run_fixture("mixed_mostly_flat")

    assert ir.document_id == DOC_ID
    assert ir.source_kind is SourceKind.FLAT_TEXT
    assert [p.text_layer.value for p in ir.pages] == ["ok", "ok", "garbled"]


# --- pages that need OCR ------------------------------------------------------------------


@pytest.mark.parametrize("name", ["text_layer_garbled_kruti", "text_layer_image_only"])
def test_pages_needing_ocr_get_no_fields_and_a_trace_event(name: str) -> None:
    ir = _run_fixture(name)

    assert ir.fields == []
    events = [e.change for e in ir.trace]
    assert len(events) == 1
    assert "page 0" in events[0] and "needs OCR" in events[0]


def test_underscores_on_a_garbled_page_are_ignored() -> None:
    """The Kruti fixture has an underscore run; its page is garbled, so it is skipped."""
    assert "_" * 30 in pymupdf.open("pdf", pdfs.get("text_layer_garbled_kruti").data)[0].get_text()
    assert _run_fixture("text_layer_garbled_kruti").fields == []


def test_mixed_document_traces_only_the_ocr_page() -> None:
    ir = _run_fixture("mixed_mostly_scanned")

    ocr_events = [e.change for e in ir.trace if e.field_id is None]
    assert [e.split(":")[0] for e in ocr_events] == ["page 1", "page 2"]
    assert {f.bbox.page for f in ir.fields} == {0}


# --- trace and purity ---------------------------------------------------------------------


def test_every_field_has_a_detection_trace_event_without_values() -> None:
    ir = _run_fixture("flat_comb")

    per_field = {e.field_id: e for e in ir.trace if e.field_id is not None}
    assert set(per_field) == {f.id for f in ir.fields}
    assert all(e.pass_name == flat.STAGE and e.at == AT for e in ir.trace)
    assert "comb row (10 cells)" in {e.change.removeprefix("detected ") for e in per_field.values()}


@pytest.mark.parametrize("name", ["flat_boxes", "flat_comb", "mixed_mostly_flat"])
def test_frontend_is_deterministic(name: str) -> None:
    assert _run_fixture(name) == _run_fixture(name)


def test_frontend_does_not_modify_the_document() -> None:
    with pymupdf.open("pdf", pdfs.get("flat_boxes").data) as doc:
        flat.run(doc, detect(doc), DOC_ID, AT)
        assert not doc.is_dirty


# --- edge cases on small in-test pages ----------------------------------------------------


def test_short_dots_stay_with_the_label_text() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Roll No. " + "_" * 20)
        _text(page, 72, 130, "Remarks, e.g. hobbies " + "." * 20)

    labels = [f.label_text for f in _run(_pdf(draw)).fields]

    assert labels == ["Roll No.", "Remarks, e.g. hobbies"]


def test_spaced_underscores_are_one_entry() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Name " + " ".join("_" * 8))

    fields = _run(_pdf(draw)).fields

    assert len(fields) == 1
    assert fields[0].label_text == "Name"


def test_line_drawn_in_pieces_is_one_entry() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Occupation")
        for x in range(150, 450, 50):
            _line(page, x, 101, x + 49)  # 1 pt gaps

    fields = _run(_pdf(draw)).fields

    assert len(fields) == 1
    assert (fields[0].bbox.x0, fields[0].bbox.x1) == (150, 449)


def test_short_lines_and_table_rules_are_not_entries() -> None:
    def draw(page: pymupdf.Page) -> None:
        _line(page, 72, 100, 80)  # 8 pt: a dash, not an entry line
        for y in (200, 220, 240):  # a 2 x 2 table drawn with lines
            _line(page, 72, y, 300)
        for x in (72, 186, 300):
            page.draw_line((x, 200), (x, 240), color=(0, 0, 0), width=0.5)
        _text(page, 76, 214, "Bank")
        _text(page, 76, 234, "Branch")

    fields = _run(_pdf(draw)).fields

    assert [(f.kind, f.label_text) for f in fields] == [
        (FieldKind.TEXT, "Bank"),
        (FieldKind.TEXT, "Branch"),
    ]
    assert all(f.bbox.x0 == 186 for f in fields)  # the empty cells, not the rules


def test_line_inside_a_box_is_dropped_and_traced() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 112, "Email")
        page.draw_rect(pymupdf.Rect(150, 96, 450, 116), color=(0, 0, 0), width=0.5)
        _line(page, 155, 112, 445)  # an underline drawn inside the box

    ir = _run(_pdf(draw))

    assert [(f.bbox.x0, f.bbox.y0, f.bbox.x1, f.bbox.y1) for f in ir.fields] == [
        (150, 96, 450, 116)
    ]
    assert any("dropped drawn line overlapping rectangle" in e.change for e in ir.trace)


def test_dense_writing_lines_are_trimmed_not_dropped() -> None:
    """Lines 8 pt apart: each 12 pt-high box is trimmed to start below the line above."""

    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Address")
        for y in (101, 109, 117):
            _line(page, 150, y, 450)

    fields = sorted(_run(_pdf(draw)).fields, key=lambda f: f.bbox.y1)

    assert [f.bbox.y1 for f in fields] == [101, 109, 117]
    assert [f.bbox.y0 for f in fields] == [101 - pdfs.ROW_HEIGHT, 101, 109]


def test_low_boxes_are_flagged() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 104, "Code")
        page.draw_rect(pymupdf.Rect(150, 100, 300, 104), color=(0, 0, 0), width=0.5)  # 4 pt

    (field,) = _run(_pdf(draw)).fields

    assert [(v.validator, v.ok) for v in field.validations] == [("min_box_height", False)]
    assert field.validations[0].message and "Code" not in field.validations[0].message


def test_frame_around_boxes_is_not_an_entry() -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_rect(pymupdf.Rect(60, 80, 500, 200), color=(0, 0, 0), width=0.5)
        page.draw_rect(pymupdf.Rect(150, 100, 450, 120), color=(0, 0, 0), width=0.5)
        _text(page, 72, 114, "Email")

    fields = _run(_pdf(draw)).fields

    assert [(f.bbox.x0, f.bbox.y0) for f in fields] == [(150, 100)]


def test_segment_merge_keeps_nearby_collinear_segments_apart() -> None:
    """Regression (dev form #3): a divider must not be swallowed by a segment at almost the
    same x far down the page."""
    segments = [
        flat._Segment(154.34, 422.4, 423.0),
        flat._Segment(154.82, 109.9, 122.2),
        flat._Segment(154.34, 429.3, 429.8),
        flat._Segment(155.30, 156.6, 168.9),
    ]

    merged = flat._merge_segments(segments)

    spans = sorted((round(s.start, 1), round(s.end, 1)) for s in merged)
    assert spans == [(109.9, 122.2), (156.6, 168.9), (422.4, 423.0), (429.3, 429.8)]


def test_segment_merge_joins_pieces_in_any_order() -> None:
    segments = [
        flat._Segment(100.0, 60, 90),
        flat._Segment(100.2, 0, 30),
        flat._Segment(99.9, 31, 59),
    ]

    (merged,) = flat._merge_segments(segments)

    assert (merged.start, merged.end) == (0, 90)
    assert merged.pos == pytest.approx(100.033, abs=0.01)


def test_quad_with_rotated_corner_order_is_a_rectangle() -> None:
    """Regression (dev form #3): squares drawn as quads whose corners start at the top right."""
    quad = pymupdf.Quad((38.0, 75.27), (38.0, 62.47), (25.25, 75.27), (25.25, 62.47))

    assert not quad.is_rectangular  # PyMuPDF's own check says no
    assert flat._is_axis_aligned(quad)
    assert not flat._is_axis_aligned(pymupdf.Quad((0, 0), (10, 2), (0, 10), (10, 12)))


def test_checkbox_drawn_as_a_quad_is_detected() -> None:
    def draw(page: pymupdf.Page) -> None:
        shape = page.new_shape()
        shape.draw_quad(pymupdf.Quad((150, 100), (159, 100), (150, 109), (159, 109)))
        shape.finish(color=(0, 0, 0), width=0.5)
        shape.commit()
        _text(page, 163, 108, "Passport")

    fields = _run(_pdf(draw)).fields

    assert [(f.kind, f.label_text) for f in fields] == [(FieldKind.CHECKBOX, "Passport")]


# --- labelling rule 1: grey hints in comb cells (Step 11, fix 2) ----------------------------


@pytest.mark.parametrize(
    ("color", "hint"),
    [
        (0x000000, False),  # black label text
        (0x2A2076, False),  # dark blue label text (dev form #1)
        (0x939598, True),  # grey hints (dev forms #1 and #3)
        (0x999999, True),  # the fixtures' grey
        (0xFFFFFF, False),  # white text on a dark banner
    ],
)
def test_hint_is_grey_text(color: int, hint: bool) -> None:
    assert flat._is_hint(color) is hint


@pytest.mark.parametrize(
    ("hints", "parts"),
    [
        ("....", [(0, 4)]),  # no hints: one part
        ("..STD..", [(0, 7)]),  # one hinted part takes the empty cells on both sides
        ("..AB..CD..", [(0, 5), (5, 10)]),  # two empty cells between parts: 1 + 1
        ("AB...CD", [(0, 4), (4, 7)]),  # three: the odd middle cell goes to the earlier part
        ("ABCD", [(0, 4)]),  # adjacent different letters: one part (a word, not a date)
        ("DDMMYYYY", [(0, 2), (2, 4), (4, 8)]),  # a hinted date: one part per letter (D8)
        (".DDMMYY.", [(0, 3), (3, 5), (5, 8)]),
        ("DMYY", [(0, 4)]),  # a single D or M is not a date group
        ("YYYY", [(0, 4)]),
    ],
)
def test_hinted_parts(hints: str, parts: list[tuple[int, int]]) -> None:
    assert flat._hinted_parts([h if h != "." else "" for h in hints]) == parts


def test_hints_are_not_labels_and_do_not_hide_cells() -> None:
    """A hinted comb row is one entry; its hint letters are not the label of the field below."""

    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 112, "PIN code")
        for i, hint in enumerate("PINXXX"):
            x = 160 + 14 * i
            page.draw_rect(pymupdf.Rect(x, 100, x + 14, 116), color=(0, 0, 0), width=0.5)
            page.insert_text((x + 4, 112), hint, fontname="helv", fontsize=7, color=(0.6,) * 3)
        _line(page, 160, 130, 300)

    fields = _run(_pdf(draw)).fields

    comb, line = fields
    assert (comb.kind, comb.max_chars, comb.label_text) == (FieldKind.TEXT, 6, "PIN code")
    assert line.label_text is None  # not "P I N X X X"


# --- blanks after a colon (Step 11, fix 5) --------------------------------------------------


def test_colon_inside_a_drawn_cell_gets_no_colon_blank() -> None:
    """A label inside a cell is labelling rule 3 (fix 4), never a colon blank."""

    def draw(page: pymupdf.Page) -> None:
        page.draw_rect(pymupdf.Rect(72, 100, 400, 124), color=(0, 0, 0), width=0.5)
        _text(page, 76, 116, "Branch code:")

    with pymupdf.open("pdf", _pdf(draw)) as doc:
        page = doc[0]
        text, drawings = flat._extract_text(page), flat._extract_drawings(page)
        cells = drawings.rects + flat._grid_cells(drawings.horizontal, drawings.vertical)

        assert flat._colon_candidates(text, drawings, cells, []) == []


def test_colon_blank_needs_room() -> None:
    """A colon at the end of the widest line leaves no room: no blank."""

    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "The applicant declares the following:")

    assert _run(_pdf(draw)).fields == []


def test_colon_blank_running_into_a_drawn_entry_is_skipped() -> None:
    """A label whose colon is followed by a drawn comb: the comb is the entry, no sliver."""

    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Account holder name and the full address of the branch here")
        _text(page, 72, 140, "1.Name*:")
        for i in range(10):
            x = 140 + 14 * i
            page.draw_rect(pymupdf.Rect(x, 128, x + 14, 144), color=(0, 0, 0), width=0.5)

    (comb,) = _run(_pdf(draw)).fields

    assert (comb.max_chars, comb.label_text) == (10, "1.Name*")


def test_colon_printed_apart_still_labels_its_blank() -> None:
    def draw(page: pymupdf.Page) -> None:
        _text(page, 72, 100, "Account holder name and the full address of the branch here")
        _text(page, 72, 140, "2. NAME OF THE BANK")
        _text(page, 250, 140, ":")

    (blank,) = _run(_pdf(draw)).fields

    assert blank.label_text == "2. NAME OF THE BANK"
