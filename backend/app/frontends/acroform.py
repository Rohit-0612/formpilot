"""AcroForm frontend: form widgets -> FormIR fields (SPEC §6.1; secondary path, Step 9).

Phase 0 found no fillable form among the 20 collected, so this path is kept minimal and tested
on synthetic fixtures only (docs/decisions/phase-2.md, Step 9):
- text widgets -> TEXT, `max_chars` from /MaxLen;
- checkboxes -> CHECKBOX with one option, the on-state (e.g. "Agreed");
- a radio group -> one RADIO field per page: options are the buttons' on-states with their boxes
  and the text to their right; the field box is the union of the buttons;
- combo and list boxes -> CHOICE, options from /Opt (export value, display text);
- signature widgets -> TEXT, like flat signature boxes, with `semantic_type` signature (known from
  the widget type) and `no_fill_reason` "signature": detected, never filled (decision P3-D1);
- push buttons and unknown widget types are skipped with a trace event.

Labels: the tooltip (/TU); without one, the text the flat frontend would take (left, else
above; tick boxes right first), only on pages whose text layer is OK. Context: the nearest
heading above (flat logic). Boxes: widget rects are on the unrotated page, mapped to the
displayed page like the flat frontend's. Values a form carries (/V) are never copied: values
come from the user. Reads the document only.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import pymupdf

from app.frontends import flat
from app.frontends.detect import Detection
from app.ir.models import BBox, Field, FieldKind, FormIR, Option, TextLayer, TraceEvent
from app.ir.semantic_types import SemanticType

STAGE = "frontend.acroform"

# A signature widget's type says what it is: no rule or LLM is needed (decision P3-D1).
_SIGNATURE = {
    "semantic_type": SemanticType.SIGNATURE,
    "semantic_confidence": 1.0,
    "semantic_method": "rule",
    "no_fill_reason": "signature",
}

_KINDS = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: FieldKind.TEXT,
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: FieldKind.CHECKBOX,
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: FieldKind.RADIO,
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: FieldKind.CHOICE,
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: FieldKind.CHOICE,
}


@dataclass
class _Spec:
    """One IR field before ids are assigned (ids follow reading order)."""

    kind: FieldKind
    native_name: str | None
    bbox: BBox
    label: str | None
    context: str | None
    max_chars: int | None = None
    options: list[Option] = field(default_factory=list)
    widget_type: str = ""
    signature: bool = False


def _union(boxes: list[BBox]) -> BBox:
    return BBox(
        page=boxes[0].page,
        x0=min(b.x0 for b in boxes),
        y0=min(b.y0 for b in boxes),
        x1=max(b.x1 for b in boxes),
        y1=max(b.y1 for b in boxes),
    )


def _rect(widget: pymupdf.Widget) -> flat.Rect:
    r = widget.rect
    return (r.x0, r.y0, r.x1, r.y1)


def _choice_options(widget: pymupdf.Widget) -> list[Option]:
    options = []
    for choice in widget.choice_values or []:
        if isinstance(choice, list | tuple):
            value, label = choice[0], choice[1]
            options.append(Option(value=str(value), label=str(label)))
        else:
            options.append(Option(value=str(choice)))
    return options


def _page_specs(page: pymupdf.Page, page_no: int, text_ok: bool) -> tuple[list[_Spec], list[str]]:
    widgets = list(page.widgets())
    text = flat.page_text(page) if text_ok else None
    rects = [_rect(w) for w in widgets]

    def label(widget: pymupdf.Widget, rect: flat.Rect, kind: FieldKind) -> str | None:
        tooltip = (widget.field_label or "").strip()
        if tooltip:
            return tooltip
        if text is None:
            return None
        return flat.label_for(rect, kind, text, [r for r in rects if r != rect])

    def context(rect: flat.Rect) -> str | None:
        return flat.context_for(rect, text) if text is not None else None

    specs: list[_Spec] = []
    skipped: list[str] = []
    # Radio buttons of one group share the group's field name (inherited from the parent).
    radio_groups: dict[str | int, list[pymupdf.Widget]] = defaultdict(list)
    for widget, rect in zip(widgets, rects, strict=True):
        signature = widget.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE
        kind = FieldKind.TEXT if signature else _KINDS.get(widget.field_type)
        if kind is None:
            skipped.append(f"page {page_no}: skipped a {widget.field_type_string} widget")
            continue
        if kind is FieldKind.RADIO:
            radio_groups[widget.field_name or widget.xref].append(widget)
            continue
        options: list[Option] = []
        bbox = flat.displayed(rect, page, page_no)
        if kind is FieldKind.CHECKBOX:
            options = [Option(value=str(widget.on_state()), bbox=bbox)]
        elif kind is FieldKind.CHOICE:
            options = _choice_options(widget)
        specs.append(
            _Spec(
                kind=kind,
                native_name=widget.field_name,
                bbox=bbox,
                label=label(widget, rect, kind),
                context=context(rect),
                max_chars=(widget.text_maxlen or None)
                if kind is FieldKind.TEXT and not signature
                else None,
                options=options,
                widget_type=widget.field_type_string,
                signature=signature,
            )
        )

    for buttons in radio_groups.values():
        button_rects = [_rect(b) for b in buttons]
        others = [r for r in rects if r not in button_rects]
        options = [
            Option(
                value=str(button.on_state()),
                label=flat.label_right_of(rect, text, [r for r in rects if r != rect])
                if text is not None
                else None,
                bbox=flat.displayed(rect, page, page_no),
            )
            for button, rect in zip(buttons, button_rects, strict=True)
        ]
        group_rect = (
            min(r[0] for r in button_rects),
            min(r[1] for r in button_rects),
            max(r[2] for r in button_rects),
            max(r[3] for r in button_rects),
        )
        tooltip = (buttons[0].field_label or "").strip()
        # The group's own label is the question ("Gender"), left of or above the buttons; the
        # text right of each button is that option's label.
        group_label = tooltip or (
            flat.label_for(group_rect, FieldKind.TEXT, text, others) if text is not None else None
        )
        specs.append(
            _Spec(
                kind=FieldKind.RADIO,
                native_name=buttons[0].field_name,
                bbox=_union([o.bbox for o in options if o.bbox is not None]),
                label=group_label,
                context=context(group_rect),
                options=options,
                widget_type="RadioButton",
            )
        )
    return specs, skipped


def run(doc: pymupdf.Document, detection: Detection, document_id: UUID, at: datetime) -> FormIR:
    """Build a FormIR from the widgets of every page. Reads the document only."""
    fields: list[Field] = []
    trace: list[TraceEvent] = []
    for page_no, (page, info) in enumerate(zip(doc, detection.pages, strict=True)):
        specs, skipped = _page_specs(page, page_no, info.text_layer is TextLayer.OK)
        for index, (bbox, spec) in enumerate(flat.reading_order([(s.bbox, s) for s in specs])):
            field_id = f"p{page_no}_f{index:03d}"
            fields.append(
                Field(
                    id=field_id,
                    kind=spec.kind,
                    native_name=spec.native_name,
                    label_text=spec.label,
                    context_text=spec.context,
                    bbox=bbox,
                    max_chars=spec.max_chars,
                    options=spec.options,
                    **_SIGNATURE if spec.signature else {},
                )
            )
            trace.append(
                TraceEvent(
                    pass_name=STAGE,
                    field_id=field_id,
                    change=f"detected {spec.widget_type} widget",
                    at=at,
                )
            )
        trace += [
            TraceEvent(pass_name=STAGE, field_id=None, change=note, at=at) for note in skipped
        ]
    return FormIR(
        document_id=document_id,
        source_kind=detection.source_kind,
        pages=detection.pages,
        fields=fields,
        trace=trace,
    )
