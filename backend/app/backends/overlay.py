"""Overlay renderer (SPEC §6.9): the confirmed values drawn onto a copy of the original PDF.

Only the fields `review.renderable` returns are drawn (invariant 7: confirmed, with a value,
never a never-fill field). A text value is written as printed (`fit.printed`: upper-case where
the form asks for capitals) in Helvetica at the fit pass's font size, vertically centred in its
box and PADDING from its left edge; a comb row gets one character per cell, centred. Devanagari
is laid out by MuPDF's HTML engine, shaped with HarfBuzz in its built-in Noto Serif Devanagari
(OFL), embedded in the PDF (decision P5-D5). A ticked checkbox or radio gets an "X". A value in
another script, or Devanagari in a comb row, is not drawn: it is returned in
`Rendered.skipped`, never guessed at (the fit pass already asked the user to write it by hand).

IR boxes are top-left points on the displayed page (invariant 6); on a rotated page they are
mapped back to the unrotated page here and the value is written there, in the direction of the
form's own text (the frontend reads the page unrotated too). No value is logged.
"""

from dataclasses import dataclass

import pymupdf

from app.ir.models import Field, FieldKind, FormIR, SourceKind
from app.passes import fit
from app.services.review import renderable

FONT = fit.FONT
PADDING = fit.PADDING
INK = (0.0, 0.0, 0.0)
CAP_RATIO = 0.35  # the baseline sits this share of the font size below the box's middle
TICK_INSET = 0.2  # share of the box kept free around an "X"
TICK_WIDTH = 1.2
_TICK_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    drawn: list[str]  # field ids
    skipped: list[str]  # field ids whose value the font cannot show


def _unrotated(page: pymupdf.Page, field: Field) -> pymupdf.Rect:
    """The field's box on the unrotated page, where PyMuPDF draws and the form's text runs."""
    box = field.bbox
    return (pymupdf.Rect(box.x0, box.y0, box.x1, box.y1) * page.derotation_matrix).normalize()


def _write(page: pymupdf.Page, x: float, baseline: float, text: str, size: float) -> None:
    page.insert_text((x, baseline), text, fontname=FONT, fontsize=size, color=INK)


def _draw_shaped(page: pymupdf.Page, field: Field, value: str) -> bool:
    """Devanagari on one line, its line box centred on the box's middle; False if it would not
    fit at the fit pass's size (nothing is drawn then)."""
    box = _unrotated(page, field)
    size = field.font_size or min(10.0, box.height * fit.HEIGHT_RATIO)
    middle = (box.y0 + box.y1) / 2
    line = pymupdf.Rect(box.x0 + PADDING, middle - 0.75 * size, box.x1, middle + 1.5 * size)
    spare, _ = page.insert_htmlbox(line, fit.html_paragraph(value, size), scale_low=1)
    return spare >= 0


def _draw_text(page: pymupdf.Page, field: Field, value: str, comb: bool) -> None:
    box = _unrotated(page, field)
    size = field.font_size or min(10.0, box.height * fit.HEIGHT_RATIO)
    baseline = (box.y0 + box.y1) / 2 + CAP_RATIO * size
    if comb and field.max_chars:
        cell = box.width / field.max_chars
        for i, ch in enumerate(value[: field.max_chars]):
            width = pymupdf.get_text_length(ch, fontname=FONT, fontsize=size)
            _write(page, box.x0 + i * cell + (cell - width) / 2, baseline, ch, size)
        return
    _write(page, box.x0 + PADDING, baseline, value, size)


def _draw_tick(page: pymupdf.Page, field: Field) -> None:
    box = _unrotated(page, field)
    dx, dy = TICK_INSET * box.width, TICK_INSET * box.height
    x0, y0, x1, y1 = box.x0 + dx, box.y0 + dy, box.x1 - dx, box.y1 - dy
    for a, b in (((x0, y0), (x1, y1)), ((x0, y1), (x1, y0))):
        page.draw_line(a, b, color=INK, width=TICK_WIDTH)


def render(original: bytes, ir: FormIR) -> Rendered:
    """The original PDF with the confirmed values drawn on it."""
    comb = ir.source_kind is not SourceKind.FILLABLE  # as in the fit pass
    drawn: list[str] = []
    skipped: list[str] = []
    with pymupdf.open("pdf", original) as doc:
        for field in renderable(ir):
            page = doc[field.bbox.page]
            if field.kind in _TICK_KINDS:
                _draw_tick(page, field)
                drawn.append(field.id)
                continue
            value = fit.printed(field) or ""
            kind = fit.script(value)
            if kind == "devanagari" and not (comb and field.max_chars):
                (drawn if _draw_shaped(page, field, value) else skipped).append(field.id)
                continue
            if kind != "latin":
                skipped.append(field.id)
                continue
            _draw_text(page, field, value, comb)
            drawn.append(field.id)
        pdf = doc.tobytes(garbage=1, deflate=True)
    return Rendered(pdf, drawn, skipped)
