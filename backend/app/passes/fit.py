"""Fit pass (SPEC §6.7): the font size at which each value fits its box.

Text is measured with the renderer's font (Helvetica, PyMuPDF's metrics; no PDF is opened). Start
at the default size (capped by the box height), shrink in 0.5 pt steps down to the minimum; if
the value still does not fit, or uses characters Helvetica cannot show (e.g. Devanagari), the
result `fits_box` fails and the field needs review. On flat and scanned forms a box with
`max_chars` is a comb row (decision D8) and is measured per character cell; an AcroForm /MaxLen
does not say whether the widget is a comb, so there the whole text is measured. A field the form
asks to write in capitals (`Field.uppercase`) is measured as it will be printed, upper-case.
"""

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

STAGE = "fit"
FIT_VALIDATOR = "fits_box"
FONT = "helv"
STEP = 0.5
PADDING = 2.0  # points kept free on each side of the text
HEIGHT_RATIO = 0.8  # a font size up to this share of the box height
_NO_TEXT_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})


def _width(text: str, size: float) -> float:
    return pymupdf.get_text_length(text, fontname=FONT, fontsize=size)


def _showable(text: str) -> bool:
    """Helvetica in a PDF uses WinAnsi (Latin-1 range); other scripts would print as blanks."""
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


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
    if not _showable(value):
        return size, "The value uses characters the PDF font cannot show; write it by hand."
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
        if message is not None:
            update["status"] = FieldStatus.NEEDS_REVIEW
            trace.append(
                TraceEvent(
                    pass_name=STAGE, field_id=field.id, change="does not fit", at=ctx.clock()
                )
            )
        fields.append(field.model_copy(update=update))
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})
