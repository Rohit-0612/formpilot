"""Fit pass (SPEC §6.7): the font size at which each value fits its box.

Text is measured as the renderer writes it (no form PDF is opened): Latin text in Helvetica with
PyMuPDF's metrics; Devanagari shaped (HarfBuzz) in MuPDF's built-in Noto Serif Devanagari, laid
out once on a scratch page (decision P5-D5). Start at the default size (capped by the box
height), shrink in 0.5 pt steps down to the minimum; if the value still does not fit, uses
another script, or is Devanagari in a comb row (its conjuncts cannot be split one letter per
box), the result `fits_box` fails and the field needs review. On flat and scanned forms a box with
`max_chars` is a comb row (decision D8) and is measured per character cell; an AcroForm /MaxLen
does not say whether the widget is a comb, so there the whole text is measured. A field the form
asks to write in capitals (`Field.uppercase`) is measured as it will be printed, upper-case.
"""

import html
from functools import lru_cache
from typing import Literal

import pymupdf

from app.ir.models import (
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    SourceKind,
    TraceEvent,
    ValidationResult,
)
from app.passes.context import PassContext
from app.passes.validate import USER_DECIDES

STAGE = "fit"
FIT_VALIDATOR = "fits_box"
FONT = "helv"
STEP = 0.5
PADDING = 2.0  # points kept free on each side of the text
HEIGHT_RATIO = 0.8  # a font size up to this share of the box height
_NO_TEXT_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})


def _width(text: str, size: float) -> float:
    return pymupdf.get_text_length(text, fontname=FONT, fontsize=size)


type Script = Literal["latin", "devanagari"]
_DEVANAGARI = range(0x0900, 0x0980)
_JOINERS = frozenset("\u200c\u200d")  # zero-width (non-)joiner, used in Hindi spelling
MEASURE_SIZE = 10.0


def _latin(ch: str) -> bool:
    """Helvetica in a PDF uses WinAnsi (Latin-1 range); other scripts would print as blanks."""
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def script(text: str) -> Script | None:
    """How the renderer writes the text: Helvetica, or shaped Devanagari (with Latin letters,
    digits and punctuation in between); None if it holds a script neither can show."""
    if all(_latin(ch) for ch in text):
        return "latin"
    if all(_latin(ch) or ord(ch) in _DEVANAGARI or ch in _JOINERS for ch in text):
        return "devanagari"
    return None


def showable(text: str) -> bool:
    return script(text) is not None


def html_paragraph(text: str, size: float) -> str:
    """One unwrapped line, as the renderer lays out shaped text."""
    style = f"margin:0;font-size:{size}pt;line-height:1.2;white-space:nowrap"
    return f'<p style="{style}">{html.escape(text)}</p>'


@lru_cache(maxsize=256)
def _shaped_width_at_measure_size(text: str) -> float:
    with pymupdf.open() as doc:
        page = doc.new_page(width=4000, height=4 * MEASURE_SIZE)
        page.insert_htmlbox(page.rect, html_paragraph(text, MEASURE_SIZE))
        spans = [
            span
            for block in page.get_text("dict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
        ]
    if not spans:
        return 0.0
    return max(s["bbox"][2] for s in spans) - min(s["bbox"][0] for s in spans)


def _shaped_width(text: str, size: float) -> float:
    return _shaped_width_at_measure_size(text) * size / MEASURE_SIZE


def printed(field: Field) -> str | None:
    """The value as the renderer writes it: upper-case where the form asks for capitals."""
    if field.value is None:
        return None
    return field.value.upper() if field.uppercase else field.value


def fit(
    field: Field, value: str, default: float, minimum: float, comb: bool
) -> tuple[float, str | None]:
    """The font size and a failure message (None if the value fits)."""
    box = field.bbox
    size = min(default, max(minimum, (box.y1 - box.y0) * HEIGHT_RATIO))
    kind = script(value)
    if kind is None:
        return size, "The value uses characters the PDF font cannot show; write it by hand."
    if kind == "devanagari" and comb and field.max_chars:
        return size, "Devanagari cannot be written one letter per box; write it by hand."
    if kind == "devanagari":
        room = box.x1 - box.x0 - 2 * PADDING
        while size > minimum and _shaped_width(value, size) > room:
            size = max(minimum, size - STEP)
        if _shaped_width(value, size) > room:
            return size, "The value is too long for the box, even at the smallest font size."
        return size, None
    if comb and field.max_chars:
        cell = (box.x1 - box.x0) / field.max_chars
        widest = max(value, key=lambda ch: _width(ch, 1.0)) if value else "M"
        text, room = widest, cell - 1.0
    else:
        text, room = value, box.x1 - box.x0 - 2 * PADDING
    while size > minimum and _width(text, size) > room:
        size = max(minimum, size - STEP)
    if _width(text, size) > room:
        return size, "The value is too long for the box, even at the smallest font size."
    return size, None


def run(ir: FormIR, ctx: PassContext) -> FormIR:
    trace: list[TraceEvent] = []
    fields = []
    for field in ir.fields:
        if field.no_fill_reason is not None or not field.value or field.kind in _NO_TEXT_KINDS:
            fields.append(field)
            continue
        comb = ir.source_kind is not SourceKind.FILLABLE
        value = printed(field) or ""
        size, message = fit(field, value, ctx.fit_font_size, ctx.fit_min_font_size, comb)
        result = ValidationResult(validator=FIT_VALIDATOR, ok=message is None, message=message)
        kept = [r for r in field.validations if r.validator != FIT_VALIDATOR]
        update: dict[str, object] = {"font_size": size, "validations": [*kept, result]}
        if message is not None and field.status not in USER_DECIDES:
            update["status"] = FieldStatus.NEEDS_REVIEW
        if message is not None:
            trace.append(
                TraceEvent(
                    pass_name=STAGE, field_id=field.id, change="does not fit", at=ctx.clock()
                )
            )
        fields.append(field.model_copy(update=update))
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})
