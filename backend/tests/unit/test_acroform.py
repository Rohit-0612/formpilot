"""AcroForm frontend (Step 9) on synthetic fixtures, and the Gate 2 coordinate check."""

import dataclasses
import uuid
from datetime import UTC, datetime

import pymupdf
import pytest

from app.frontends import acroform
from app.frontends.detect import detect
from app.ir.coords import PageGeometry, pdf_rect_to_bbox
from app.ir.models import BBox, FieldKind, FormIR, TextLayer
from app.ir.semantic_types import SemanticType
from tests.fixtures import pdfs

DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000009")
AT = datetime(2026, 10, 19, tzinfo=UTC)
FILLABLE = ["fillable_basic", "fillable_rotated"]


def _run(name: str, text_layer: TextLayer | None = None) -> FormIR:
    with pymupdf.open("pdf", pdfs.get(name).data) as doc:
        detection = detect(doc)
        if text_layer is not None:
            pages = [p.model_copy(update={"text_layer": text_layer}) for p in detection.pages]
            detection = dataclasses.replace(detection, pages=pages)
        return acroform.run(doc, detection, DOCUMENT_ID, AT)


def _box(bbox: BBox | None) -> tuple[float, ...] | None:
    return None if bbox is None else (bbox.x0, bbox.y0, bbox.x1, bbox.y1)


def _approx(box: tuple[float, ...] | None) -> object:
    return None if box is None else pytest.approx(box, abs=0.01)


@pytest.mark.parametrize("name", FILLABLE)
def test_fields_match_the_fixture_ground_truth(name: str) -> None:
    fixture = pdfs.get(name)

    ir = _run(name)

    assert ir.source_kind is fixture.source_kind
    assert len(ir.fields) == len(fixture.fields)
    for got, want in zip(ir.fields, fixture.fields, strict=True):  # reading order
        assert got.bbox.page == want.page
        assert got.kind is want.kind
        assert _box(got.bbox) == _approx(want.bbox), want.native_name
        assert got.native_name == want.native_name
        assert got.label_text == want.label
        assert got.max_chars == want.max_chars
        assert [(o.value, o.label, _box(o.bbox)) for o in got.options] == [
            (o.value, o.label, _approx(o.bbox)) for o in want.options
        ]


def test_values_the_form_carries_are_not_copied() -> None:
    """The combo box has /V (UP); values come from the user, never from the form."""
    assert all(field.value is None for field in _run("fillable_basic").fields)


def test_ids_trace_and_skipped_widgets() -> None:
    ir = _run("fillable_rotated")

    assert [f.id for f in ir.fields] == ["p0_f000"]
    changes = [(event.field_id, event.change) for event in ir.trace]
    assert changes == [
        ("p0_f000", "detected Text widget"),
        (None, "page 0: skipped a Button widget"),
    ]
    assert {event.pass_name for event in ir.trace} == {acroform.STAGE}


def test_without_a_usable_text_layer_only_tooltips_label_fields() -> None:
    by_name = {f.native_name: f for f in _run("fillable_basic", TextLayer.GARBLED).fields}

    assert by_name["full_name"].label_text == "Full name of the applicant"  # tooltip
    assert by_name["mobile_no"].label_text is None  # would come from the page text
    assert all(o.label is None for o in by_name["gender"].options)
    assert all(f.context_text is None for f in by_name.values())


def test_run_reads_the_document_only() -> None:
    data = pdfs.get("fillable_basic").data
    with pymupdf.open("pdf", data) as doc:
        first = acroform.run(doc, detect(doc), DOCUMENT_ID, AT)
        second = acroform.run(doc, detect(doc), DOCUMENT_ID, AT)
        assert doc.tobytes(no_new_id=True, deflate=True) == pymupdf.open("pdf", data).tobytes(
            no_new_id=True, deflate=True
        )
    assert first == second


# --- Gate 2: coordinate conversion bottom-left <-> top-left ----------------------------------


def _numbers(raw: tuple[str, str]) -> list[float]:
    kind, value = raw
    assert kind == "array", raw
    return [float(v) for v in value.strip("[]").split()]


def _geometry(doc: pymupdf.Document, page: pymupdf.Page) -> PageGeometry:
    """From the raw page objects, independent of PyMuPDF's own transforms."""
    crop = doc.xref_get_key(page.xref, "CropBox")
    box = crop if crop[0] != "null" else doc.xref_get_key(page.xref, "MediaBox")
    rotate = doc.xref_get_key(page.xref, "Rotate")
    rotation = int(rotate[1]) if rotate[0] == "int" else 0
    x0, y0, x1, y1 = _numbers(box)
    return PageGeometry(crop_box=(x0, y0, x1, y1), rotation=rotation)


@pytest.mark.parametrize("name", FILLABLE)
def test_raw_pdf_rects_converted_with_coords_equal_the_ir_boxes(name: str) -> None:
    """Each widget's /Rect (PDF user space, bottom-left origin), converted by app/ir/coords.py,
    is the IR box (top-left origin of the displayed page): offset CropBox and /Rotate 90."""
    ir = _run(name)
    ir_boxes = {(f.native_name, None): f.bbox for f in ir.fields} | {
        (f.native_name, o.value): o.bbox for f in ir.fields for o in f.options if o.bbox
    }
    checked = 0
    with pymupdf.open("pdf", pdfs.get(name).data) as doc:
        page = doc[0]
        geometry = _geometry(doc, page)
        for widget in page.widgets():
            if widget.field_type == pymupdf.PDF_WIDGET_TYPE_BUTTON:
                continue  # skipped by the frontend
            x0, y0, x1, y1 = _numbers(doc.xref_get_key(widget.xref, "Rect"))
            converted = pdf_rect_to_bbox((x0, y0, x1, y1), geometry, page=0)
            is_radio = widget.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON
            key = (widget.field_name, widget.on_state() if is_radio else None)
            assert _box(ir_boxes[key]) == _approx(_box(converted)), key
            checked += 1
    # Every widget but the push button: 6 in fillable_basic (two of them radio buttons).
    assert checked == {"fillable_basic": 6, "fillable_rotated": 1}[name]


def test_signature_widget_is_a_text_field_that_is_never_filled() -> None:
    """P3-D1: like a flat signature box, a TEXT field; its widget type makes it a signature."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 690), "Signature of the applicant", fontname="helv", fontsize=10)
    for name, field_type, rect in (
        ("name", pymupdf.PDF_WIDGET_TYPE_TEXT, (72, 100, 272, 118)),
        ("sign", pymupdf.PDF_WIDGET_TYPE_SIGNATURE, (72, 700, 272, 740)),
    ):
        widget = pymupdf.Widget()
        widget.field_name, widget.field_type, widget.rect = name, field_type, pymupdf.Rect(rect)
        page.add_widget(widget)
    with pymupdf.open("pdf", doc.tobytes()) as reopened:
        ir = acroform.run(reopened, detect(reopened), DOCUMENT_ID, AT)

    by_name = {f.native_name: f for f in ir.fields}
    sign = by_name["sign"]
    assert (sign.kind, sign.semantic_type, sign.no_fill_reason) == (
        FieldKind.TEXT,
        SemanticType.SIGNATURE,
        "signature",
    )
    assert (sign.semantic_method, sign.semantic_confidence, sign.max_chars) == ("rule", 1.0, None)
    assert by_name["name"].no_fill_reason is None
    assert by_name["name"].semantic_method == "none"
    assert (sign.id, "detected Signature widget") in [(e.field_id, e.change) for e in ir.trace]
