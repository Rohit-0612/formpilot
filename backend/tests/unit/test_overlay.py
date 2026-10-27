"""Overlay renderer (SPEC §6.9): confirmed values drawn in their boxes, read back from the PDF.

Synthetic fixtures and values only; no model."""

import uuid
from datetime import UTC, datetime

import pymupdf

from app.backends import overlay
from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import BBox, FieldStatus, FormIR
from app.passes import fit, match, understand, validate
from app.passes.context import PassContext
from app.services.review import confirm_all, edit_field
from tests.fixtures import pdfs

NOW = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)
PROFILE = {
    "full_name": "Asha Verma",
    "father_name": "Ravi Verma",
    "date_of_birth": "1998-03-07",
    "phone_mobile": "9000012345",
    "email": "asha.verma@example.com",
    "current_city": "Pune",
    "current_pincode": "411001",
    "pan": "AAAPV1234A",
}
CTX = PassContext(clock=lambda: NOW, profile=PROFILE)


def _filled(name: str) -> tuple[bytes, FormIR]:
    data = pdfs.get(name).data
    with pymupdf.open("pdf", data) as doc:
        ir = flat.run(doc, detect(doc), uuid.uuid4(), NOW)
    return data, fit.run(validate.run(match.run(understand.run(ir, CTX), CTX), CTX), CTX)


def _text_in(pdf: bytes, box: BBox) -> str:
    """The words drawn inside the box (displayed-page coordinates), left to right."""
    with pymupdf.open("pdf", pdf) as doc:
        page = doc[box.page]
        words = page.get_text("words")
        to_displayed = page.rotation_matrix
        inside = []
        for x0, y0, x1, y1, word, *_ in words:
            r = pymupdf.Rect(x0, y0, x1, y1) * to_displayed
            if (
                box.x0 - 1 <= r.x0
                and r.x1 <= box.x1 + 1
                and box.y0 - 2 <= r.y0
                and r.y1 <= box.y1 + 2
            ):
                inside.append((r.x0, word))
    return " ".join(word for _, word in sorted(inside))


def test_confirmed_values_are_drawn_in_their_boxes() -> None:
    original, ir = _filled("flat_persona_form")
    ir, _ = confirm_all(ir, CTX)

    out = overlay.render(original, ir)

    by_label = {f.label_text: f for f in ir.fields}
    assert _text_in(out.pdf, by_label["Full name"].bbox) == "Asha Verma"
    assert _text_in(out.pdf, by_label["City"].bbox) == "Pune"
    assert set(out.drawn) == {f.id for f in ir.fields if f.status is FieldStatus.CONFIRMED}
    assert out.skipped == []


def test_a_comb_row_gets_one_character_per_cell() -> None:
    original, ir = _filled("flat_persona_form")
    ir, _ = confirm_all(ir, CTX)
    pan = next(f for f in ir.fields if f.label_text == "PAN")

    out = overlay.render(original, ir)

    with pymupdf.open("pdf", out.pdf) as doc:
        chars = [
            (c["origin"][0], c["c"])
            for block in doc[0].get_text("rawdict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            for c in span["chars"]
            if c["c"].strip()
            and pan.bbox.y0 <= c["origin"][1] <= pan.bbox.y1
            and c["origin"][0] >= pan.bbox.x0
        ]
    cell = (pan.bbox.x1 - pan.bbox.x0) / 10
    cells = [int((x - pan.bbox.x0) // cell) for x, _ in sorted(chars)]
    assert "".join(c for _, c in sorted(chars)) == "AAAPV1234A"
    assert cells == list(range(10))


def test_only_confirmed_fields_are_rendered() -> None:
    """Invariant 7: filled and suggested values stay off the PDF until the user confirms."""
    original, ir = _filled("flat_persona_form")
    name = next(f for f in ir.fields if f.label_text == "Full name")
    assert name.status is FieldStatus.FILLED

    out = overlay.render(original, ir)

    assert out.drawn == [] and _text_in(out.pdf, name.bbox) == ""
    one, _ = edit_field(ir, name.id, CTX, confirmed=True)
    assert overlay.render(original, one).drawn == [name.id]


def test_capitals_where_the_form_asks_for_them() -> None:
    original, ir = _filled("flat_case_hints")
    name = next(f for f in ir.fields if f.label_text == "Full name")
    ir, _ = edit_field(ir, name.id, CTX, value="Asha Verma", confirmed=True)

    out = overlay.render(original, ir)

    assert _text_in(out.pdf, name.bbox) == "ASHA VERMA"


def test_a_ticked_box_gets_an_x() -> None:
    original, ir = _filled("flat_checkboxes")
    box = next(f for f in ir.fields if f.label_text == "Female")
    ir = ir.model_copy(
        update={
            "fields": [
                f.model_copy(update={"value": "Yes", "status": FieldStatus.CONFIRMED})
                if f.id == box.id
                else f
                for f in ir.fields
            ]
        }
    )

    out = overlay.render(original, ir)

    with pymupdf.open("pdf", out.pdf) as doc, pymupdf.open("pdf", original) as before:
        added = len(doc[0].get_drawings()) - len(before[0].get_drawings())
        inside = [
            d for d in doc[0].get_drawings()
            if pymupdf.Rect(box.bbox.x0, box.bbox.y0, box.bbox.x1, box.bbox.y1).contains(d["rect"])
            and d["width"] and d["width"] > 1
        ]  # fmt: skip
    assert out.drawn == [box.id] and added >= 1 and inside


def test_text_on_a_rotated_page_runs_like_the_forms_own_text() -> None:
    """The value is written on the unrotated page, as the label next to it was."""
    original, ir = _filled("flat_rotated")
    (field,) = ir.fields
    ir, _ = edit_field(ir, field.id, CTX, value="Asha Verma", confirmed=True)

    out = overlay.render(original, ir)

    assert _text_in(out.pdf, field.bbox) == "Asha Verma"


def test_devanagari_is_drawn_shaped_with_an_embedded_font() -> None:
    """P5-D5: MuPDF's Noto Serif Devanagari, shaped (conjuncts), inside the box."""
    original, ir = _filled("flat_persona_form")
    name = next(f for f in ir.fields if f.label_text == "Full name")
    ir, _ = edit_field(ir, name.id, CTX, value="श्रीमती क्षमा द्विवेदी", confirmed=True)

    out = overlay.render(original, ir)

    assert out.drawn == [name.id] and out.skipped == []
    with pymupdf.open("pdf", out.pdf) as doc:
        fonts = {f[3] for f in doc[0].get_fonts(full=True)}
        spans = [
            s["bbox"]
            for b in doc[0].get_text("dict")["blocks"]
            for line in b.get("lines", [])
            for s in line["spans"]
            if "Devanagari" in s["font"]
        ]
    assert "Noto Serif Devanagari Regular" in fonts
    box = name.bbox
    assert spans and all(
        box.x0 <= x0 and x1 <= box.x1 and box.y0 - 3 <= y0 and y1 <= box.y1 + 3
        for x0, y0, x1, y1 in spans
    )


def test_another_script_is_skipped_not_drawn() -> None:
    original, ir = _filled("flat_persona_form")
    name = next(f for f in ir.fields if f.label_text == "Full name")
    ir, _ = edit_field(ir, name.id, CTX, value="ஆஷா வர்மா", confirmed=True)

    out = overlay.render(original, ir)

    assert out.skipped == [name.id] and name.id not in out.drawn
    assert _text_in(out.pdf, name.bbox) == ""


def test_the_original_is_not_changed() -> None:
    original, ir = _filled("flat_persona_form")
    copy = bytes(original)

    overlay.render(original, confirm_all(ir, CTX)[0])

    assert original == copy
