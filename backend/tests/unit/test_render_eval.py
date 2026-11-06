"""The fill-correctness and placement eval (eval/render_eval.py) on synthetic pages and IRs.

Values are rendered by the real overlay renderer and read back. No real form, label or persona.
"""

import uuid
from typing import Any

import pymupdf
import pytest

from app.backends import overlay
from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    PageInfo,
    SourceKind,
    TextLayer,
    ValueSource,
)
from app.ir.semantic_types import SemanticType
from eval import render_eval, run_eval
from eval.render_samples import RenderedForm

DOC_ID = uuid.UUID("5f0c6d1e-0000-4000-8000-000000000043")
PROFILE = {"full_name": "Asha Verma"}
TODAY = run_eval.FIXED_TIME.date()


def _box(x0: float, y0: float, x1: float, y1: float) -> BBox:
    return BBox(page=0, x0=x0, y0=y0, x1=x1, y1=y1)


def _field(field_id: str, box: BBox, value: str, **overrides: Any) -> Field:
    values: dict[str, Any] = {
        "id": field_id,
        "kind": FieldKind.TEXT,
        "native_name": None,
        "label_text": None,
        "context_text": None,
        "bbox": box,
        "semantic_type": SemanticType.FULL_NAME,
        "value": value,
        "value_source": ValueSource.PROFILE,
        "status": FieldStatus.CONFIRMED,
    }
    values.update(overrides)
    return Field(**values)


def _pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 60), "Application form", fontname="helv", fontsize=12)
    return doc.tobytes()


def _rendered(*fields: Field) -> RenderedForm:
    page = PageInfo(width=595.0, height=842.0, text_layer=TextLayer.OK)
    ir = FormIR(
        document_id=DOC_ID, source_kind=SourceKind.FLAT_TEXT, pages=[page], fields=list(fields)
    )
    original = _pdf()
    return RenderedForm("f", original, ir, overlay.render(original, ir))


def _compared(*predicted_ids: str) -> run_eval.FormResult:
    compared = [
        run_eval.Compared(
            "f", f"p0_l{i:03d}", SemanticType.FULL_NAME, SemanticType.FULL_NAME, "rule", None, pid
        )
        for i, pid in enumerate(predicted_ids)
    ]
    return run_eval.FormResult(form="f", from_scratch=True, compared=compared)


def _evaluate(item: RenderedForm, form: run_eval.FormResult, labels: dict[str, BBox]) -> list:
    return render_eval.evaluate_form(item, form, labels, PROFILE, TODAY)


# --- read-back ----------------------------------------------------------------------------------


def test_a_printed_name_reads_back_with_its_space_and_is_right() -> None:
    item = _rendered(_field("p0_f000", _box(100, 100, 300, 116), "Asha Verma"))
    labels = {"p0_l000": _box(100, 100, 300, 116)}

    (printed,) = _evaluate(item, _compared("p0_f000"), labels)

    assert printed.error is None
    assert printed.right and printed.match_right
    assert (printed.iou, printed.containment) == (1.0, 1.0)
    assert printed.chars == printed.centre_inside == printed.whole_inside == 9  # no space glyph


def test_a_comb_reads_back_cell_by_cell_with_an_empty_cell_as_a_space() -> None:
    comb = _field("p0_f000", _box(100, 100, 260, 116), "Asha Verma", max_chars=10)
    item = _rendered(comb)

    with pymupdf.open("pdf", item.rendered.pdf) as doc:
        chars = render_eval.printed_chars(item.original, item.rendered.pdf)
        text = render_eval.read_back(doc[0], comb, chars, comb=True)

    assert text == "Asha Verma"


def test_a_value_longer_than_its_comb_is_cut_short_and_missed_by_the_match_level() -> None:
    """The renderer writes one character per cell and drops the rest; only the read-back sees it."""
    comb = _field("p0_f000", _box(100, 100, 164, 116), "Asha Verma", max_chars=4)
    item = _rendered(comb)

    (printed,) = _evaluate(item, _compared("p0_f000"), {"p0_l000": comb.bbox})

    assert printed.error == "cut short"
    assert printed.match_right and not printed.right
    summary = render_eval.summarise([printed], fillable=1)
    assert summary["missed_by_match_level"] == 1
    assert summary["printed_text_errors"]["cut short"] == 1  # type: ignore[index]


def test_an_upper_case_field_must_read_back_in_capitals(monkeypatch: pytest.MonkeyPatch) -> None:
    real = overlay._write
    monkeypatch.setattr(
        overlay, "_write", lambda page, x, y, text, size: real(page, x, y, text.lower(), size)
    )
    field = _field("p0_f000", _box(100, 100, 300, 116), "Asha Verma", uppercase=True)

    (printed,) = _evaluate(_rendered(field), _compared("p0_f000"), {"p0_l000": field.bbox})

    assert printed.error == "case"
    assert printed.match_right and not printed.right


@pytest.mark.parametrize(
    ("read", "intended", "kind"),
    [
        ("ASHA", "ASHA", None),
        ("", "ASHA", "nothing read back"),
        ("ASHAVERMA", "ASHA VERMA", "spacing"),
        ("asha", "ASHA", "case"),
        ("ASH", "ASHA", "cut short"),
        ("ASHB", "ASHA", "different text"),
    ],
)
def test_error_kinds(read: str, intended: str, kind: str | None) -> None:
    assert render_eval.error_kind(read, intended) == kind


# --- placement ----------------------------------------------------------------------------------


def test_text_printed_above_a_thin_label_strip_counts_outside_it() -> None:
    """As on a dotted line labelled as a thin strip: the field box is a line taller."""
    field = _field("p0_f000", _box(100, 100, 300, 116), "Asha Verma")
    strip = _box(100, 112, 300, 118)

    (printed,) = _evaluate(_rendered(field), _compared("p0_f000"), {"p0_l000": strip})

    assert printed.right  # the value is right; only its place is measured
    assert printed.iou is not None and printed.iou < 0.5
    assert printed.containment == 0.25
    assert printed.centre_inside == printed.whole_inside == 0


def test_a_field_that_is_not_compared_counts_as_not_right_and_outside() -> None:
    field = _field("p0_f000", _box(100, 100, 300, 116), "Asha Verma")

    (printed,) = _evaluate(_rendered(field), _compared(), {})

    assert not printed.compared and not printed.right
    assert printed.iou is None and printed.centre_inside == 0
    summary = render_eval.summarise([printed], fillable=0)
    assert summary["correct_of_printed"] == 0.0
    assert summary["correct_of_fillable"] is None
    assert summary["chars_inside_label_by_centre"] == 0.0


def test_the_report_holds_no_value() -> None:
    item = _rendered(_field("p0_f000", _box(100, 100, 164, 116), "Asha Verma", max_chars=4))
    printed = _evaluate(item, _compared("p0_f000"), {"p0_l000": item.ir.fields[0].bbox})
    data = {
        "detector": "flat@test", "provider": "fake", "created_at": "now", "tag": None,
        "policy": "p", "full_persona": "x",
        "personas": {"x": {"total": render_eval.summarise(printed, 1),
                           "from_scratch": render_eval.summarise(printed, 1),
                           "from_scratch_forms": ["f"],
                           "forms": {"f": render_eval.summarise(printed, 1)},
                           "errors": [{"form": "f", "field_id": "p0_f000", "page": 1,
                                       "error": "cut short", "right_at_match_level": True,
                                       "right_as_read_back": False}]}},
    }  # fmt: skip

    text = render_eval.markdown(data)

    assert "cut short" in text
    assert "Asha" not in text and "ASHA" not in text
