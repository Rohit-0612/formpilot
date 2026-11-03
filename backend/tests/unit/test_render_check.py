"""Render checks (eval/render_check.py, decision P5-D11) on synthetic pages and IRs.

Characters are placed by hand, so the checks are tested apart from the renderer. No real form,
label or persona is used.
"""

import uuid
from collections.abc import Callable
from itertools import pairwise
from typing import Any

import pymupdf

from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FormIR,
    PageInfo,
    SourceKind,
    TextLayer,
    ValueSource,
)
from app.ir.parts import date_groups
from eval import render_check

DOC_ID = uuid.UUID("5f0c6d1e-0000-4000-8000-000000000042")


def _box(x0: float, y0: float, x1: float, y1: float) -> BBox:
    return BBox(page=0, x0=x0, y0=y0, x1=x1, y1=y1)


def _field(field_id: str, box: BBox, **overrides: Any) -> Field:
    values: dict[str, Any] = {
        "id": field_id,
        "kind": FieldKind.TEXT,
        "native_name": None,
        "label_text": None,
        "context_text": None,
        "bbox": box,
    }
    values.update(overrides)
    return Field(**values)


def _ir(*fields: Field) -> FormIR:
    page = PageInfo(width=595.0, height=842.0, text_layer=TextLayer.OK)
    return FormIR(
        document_id=DOC_ID, source_kind=SourceKind.FLAT_TEXT, pages=[page], fields=list(fields)
    )


def _pdf(draw: Callable[[pymupdf.Page], None] = lambda page: None) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 60), "Application form", fontname="helv", fontsize=12)
    draw(page)
    return doc.tobytes()


def _print(original: bytes, *texts: tuple[float, float, str]) -> bytes:
    """The original with each text written at (x, baseline) in 10 pt Helvetica."""
    with pymupdf.open("pdf", original) as doc:
        for x, baseline, text in texts:
            doc[0].insert_text((x, baseline), text, fontname="helv", fontsize=10)
        return doc.tobytes()


# --- characters ---------------------------------------------------------------------------------


def test_characters_inside_their_box_pass_and_the_forms_own_text_is_ignored() -> None:
    original = _pdf()
    ir = _ir(_field("p0_f000", _box(100, 100, 300, 116)))

    rendered = _print(original, (104, 112, "Asha Verma"))

    assert render_check.check_characters(original, rendered, ir, ["p0_f000"]) == []


def test_a_character_past_the_box_edge_fails_without_naming_it() -> None:
    original = _pdf()
    ir = _ir(_field("p0_f000", _box(100, 100, 130, 116)))

    rendered = _print(original, (104, 112, "Asha Verma"))

    found = render_check.check_characters(original, rendered, ir, ["p0_f000"])
    assert found and {v.check for v in found} == {"characters"}
    assert all("Asha" not in v.detail and "V" not in v.detail for v in found)


def test_a_character_outside_every_printed_box_fails() -> None:
    original = _pdf()
    ir = _ir(_field("p0_f000", _box(100, 100, 300, 116)))

    rendered = _print(original, (104, 200, "X"))

    (violation,) = render_check.check_characters(original, rendered, ir, ["p0_f000"])
    assert violation.field_id is None and violation.page == 1


def _comb(widths: list[float], x0: float = 100) -> Field:
    edges = [x0]
    for width in widths:
        edges.append(edges[-1] + width)
    cells = [_box(a, 100, b, 116) for a, b in pairwise(edges)]
    return _field("p0_f000", _box(x0, 100, edges[-1], 116), max_chars=len(cells), cells=cells)


def test_comb_characters_centred_in_uneven_cells_pass() -> None:
    comb = _comb([14, 20, 14])
    original = _pdf()
    width = pymupdf.get_text_length("0", fontname="helv", fontsize=10)
    texts = [(c.x0 + (c.width - width) / 2, 112, "0") for c in comb.cells]

    rendered = _print(original, *texts)

    assert render_check.check_characters(original, rendered, _ir(comb), ["p0_f000"]) == []


def test_comb_characters_spaced_evenly_over_uneven_cells_fail_on_a_divider() -> None:
    """The M3 renderer's placement on dev form #25: even spacing over cells of uneven width."""
    comb = _comb([14, 14, 30, 14])
    original = _pdf()
    step = comb.bbox.width / 4
    width = pymupdf.get_text_length("0", fontname="helv", fontsize=10)
    texts = [(comb.bbox.x0 + i * step + (step - width) / 2, 112, "0") for i in range(4)]

    rendered = _print(original, *texts)

    found = render_check.check_characters(original, rendered, _ir(comb), ["p0_f000"])
    assert [v.detail for v in found] == ["a character on a comb cell divider"]


def test_two_characters_in_one_comb_cell_fail() -> None:
    comb = _comb([20, 20])
    original = _pdf()

    rendered = _print(original, (101, 112, "1"), (110, 112, "2"))

    found = render_check.check_characters(original, rendered, _ir(comb), ["p0_f000"])
    assert [v.detail for v in found] == ["comb cell 1 holds 2"]


# --- dates --------------------------------------------------------------------------------------


def _date_parts() -> list[Field]:
    return [
        _field("p0_f000", _box(100, 100, 126, 113), date_part="day", max_chars=2),
        _field("p0_f001", _box(126, 100, 152, 113), date_part="month", max_chars=2),
        _field("p0_f002", _box(152, 100, 203, 113), date_part="year", max_chars=4),
    ]


def test_the_parts_of_one_date_are_one_group() -> None:
    parts = _date_parts()
    apart = _field("p0_f003", _box(300, 100, 326, 113), date_part="day", max_chars=2)

    assert [[f.id for f in g] for g in date_groups([*parts, apart])] == [
        ["p0_f000", "p0_f001", "p0_f002"]
    ]


def test_a_date_printed_in_part_fails_and_a_whole_or_empty_one_passes() -> None:
    ir = _ir(*_date_parts())

    (violation,) = render_check.check_dates(ir, ["p0_f000"])
    assert violation.detail == "date printed without month, year"
    assert render_check.check_dates(ir, ["p0_f000", "p0_f001", "p0_f002"]) == []
    assert render_check.check_dates(ir, []) == []


# --- never-fill ---------------------------------------------------------------------------------


def _official_heading(page: pymupdf.Page) -> None:
    text = "(To be filled by the Branch Official)"
    width = pymupdf.get_text_length(text, fontname="helv", fontsize=10)
    page.insert_text(((595 - width) / 2, 300), text, fontname="helv", fontsize=10)


def test_a_field_below_an_official_only_heading_fails_and_one_above_passes() -> None:
    original = _pdf(_official_heading)
    above = _field("p0_f000", _box(100, 200, 300, 214))
    below = _field("p0_f001", _box(100, 400, 300, 414))

    found = render_check.check_never_fill(original, _ir(above, below), ["p0_f000", "p0_f001"])

    assert [(v.field_id, v.detail) for v in found] == [
        ("p0_f001", "below an official-only heading")
    ]


def test_a_field_in_an_office_use_box_fails() -> None:
    def draw(page: pymupdf.Page) -> None:
        page.draw_rect(pymupdf.Rect(80, 380, 400, 460), color=(0, 0, 0), width=0.5)
        page.insert_text((90, 395), "For office use only", fontname="helv", fontsize=9)

    original = _pdf(draw)
    ir = _ir(_field("p0_f000", _box(100, 420, 300, 434)))

    (violation,) = render_check.check_never_fill(original, ir, ["p0_f000"])
    assert violation.detail == "inside an office-use box"


def test_a_printed_never_fill_field_fails() -> None:
    ir = _ir(_field("p0_f000", _box(100, 200, 300, 214), no_fill_reason="signature"))

    (violation,) = render_check.check_never_fill(_pdf(), ir, ["p0_f000"])
    assert violation.detail == "printed (signature)"


# --- ticks --------------------------------------------------------------------------------------


def test_a_tick_counts_only_from_the_users_choice() -> None:
    box = _box(100, 100, 112, 112)
    assumed = _field("p0_f000", box, kind=FieldKind.CHECKBOX, value_source=ValueSource.PROFILE)
    chosen = _field(
        "p0_f001", _box(120, 100, 132, 112), kind=FieldKind.CHECKBOX,
        value_source=ValueSource.USER_ANSWER,
    )  # fmt: skip

    found = render_check.check_ticks(_ir(assumed, chosen), ["p0_f000", "p0_f001"])

    assert [(v.field_id, v.detail) for v in found] == [("p0_f000", "ticked from profile")]
