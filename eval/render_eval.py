"""Fill-correctness and placement eval on the rendered dev forms (M3 gate, human, 2026-11-06).

    make eval-render   # replays the recorded understanding answers (Groq by default)

Per synthetic persona, every dev form of the subset goes through the product's passes as in
`make render-samples`: match with the product policy, validate, fit, "confirm all" (P5-D7), the
overlay renderer. The text the overlay printed is then read back from the rendered PDF (the
rendered page's characters minus the original page's, eval/render_check.py), each character given
to the printed field whose box holds its centre.

Fill correctness: the read-back text is judged against the persona as the fill eval judges value
precision (eval/fill_eval.py, `value_right`), and an upper-case field (P5-D22) must read back with
no lower-case letter. Per persona:
- of all printed values: printed values right / printed text values. A printed field that is not
  compared (no labelled box with a reference type matched it) counts as not right;
- of the fillable fields: printed values right / compared fields with a fillable reference type
  (the fill eval's coverage denominator).
Each printed field is also judged on the text the renderer was asked to print (`fit.printed`,
the match-level judgement). A field right there but wrong as read back is a printed-text error,
listed with its kind: nothing read back, cut short, spacing, case, different text.

Placement, against the human-labelled box the field was matched to (eval/labels/, the
understanding eval's writing-spot match):
- IoU of the printed field's box with the label box, and containment: the share of the field's
  box inside the label box;
- the share of printed characters inside their field's label box: by the character's centre, and
  whole (the glyph box inside, with the render check's 0.1 pt tolerance). Characters of a field
  that is not compared count as outside.

Read-back spacing: in a comb, an empty cell between characters is a space; elsewhere a gap wider
than SPACE_GAP of the font size. Ticks are not text and are left out (none is printed here: ticks
come only from the user, P5-D12).

Reports (JSON and Markdown) go to eval/reports/ and hold field ids, pages, counts and ratios, never
a value or character. Label boxes are human-labelled; reference types are Claude-written (P3-D6);
personas are Claude-drafted and not checked by a human (P4-D3).
"""

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pymupdf

from app.ir.geometry import intersection_area, iou
from app.ir.models import BBox, Field, FieldKind, SourceKind
from app.logging import configure_logging
from app.passes import fit
from eval import fill_eval, run_eval
from eval.labelling.schema import LABELS_DIR, REPO_ROOT, load_label_file
from eval.render_check import _Char, _holds, _inside, _unrotated, printed_chars
from eval.render_samples import RenderedForm, dev_result, render_forms

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
SPACE_GAP = 0.15  # a gap wider than this share of the font size is a space (Helvetica's is 0.28)
LINE_GAP = 0.5  # characters whose centres differ by more than this share of the size: new line
_TICK_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})
ERROR_KINDS = ("nothing read back", "cut short", "spacing", "case", "different text")


@dataclass(frozen=True)
class PrintedField:
    form: str
    field_id: str
    page: int  # 1-based
    compared: bool  # matched to a labelled box with a reference type
    fillable_reference: bool
    right: bool  # the read-back text is right for the persona
    match_right: bool  # the text the renderer was asked to print is right (the fill eval)
    error: str | None  # how the read-back text differs from that text (ERROR_KINDS)
    iou: float | None
    containment: float | None
    chars: int
    centre_inside: int
    whole_inside: int


# --- read-back ----------------------------------------------------------------------------------


def _cells(page: pymupdf.Page, field: Field) -> list[pymupdf.Rect]:
    """A comb's cells as the overlay renderer uses them: drawn cells, else even steps."""
    if field.cells:
        return [_unrotated(c, page) for c in field.cells]
    box = _unrotated(field.bbox, page)
    step = box.width / (field.max_chars or 1)
    return [
        pymupdf.Rect(box.x0 + i * step, box.y0, box.x0 + (i + 1) * step, box.y1)
        for i in range(field.max_chars or 1)
    ]


def read_back(page: pymupdf.Page, field: Field, chars: Sequence[_Char], comb: bool) -> str:
    """The field's printed text, rebuilt from its characters' positions."""
    if not chars:
        return ""
    if comb and field.max_chars:
        cells = _cells(page, field)
        slots: dict[int, str] = {}
        for ch in chars:
            x = ch.centre[0]
            index = min(range(len(cells)), key=lambda i: abs((cells[i].x0 + cells[i].x1) / 2 - x))
            slots[index] = slots.get(index, "") + ch.c
        return "".join(slots.get(i, " ") for i in range(max(slots) + 1)).strip()
    lines: list[list[_Char]] = []
    for ch in sorted(chars, key=lambda c: c.centre[1]):
        if lines and abs(lines[-1][0].centre[1] - ch.centre[1]) <= LINE_GAP * ch.size:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    texts = []
    for line in lines:
        text, previous = "", None
        for ch in sorted(line, key=lambda c: c.x0):
            if previous is not None and ch.x0 - previous.x1 > SPACE_GAP * ch.size:
                text += " "
            text, previous = text + ch.c, ch
        texts.append(text)
    return " ".join(texts)


def error_kind(read: str, intended: str) -> str | None:
    """How the read-back text differs from the text the renderer was asked to print."""
    if " ".join(read.split()) == " ".join(intended.split()):
        return None
    squashed, meant = "".join(read.split()), "".join(intended.split())
    if not squashed:
        return "nothing read back"
    if squashed == meant:
        return "spacing"
    if squashed.casefold() == meant.casefold():
        return "case"
    if meant.startswith(squashed):
        return "cut short"
    return "different text"


def _right(
    c: run_eval.Compared, got: Field, read: str, profile: Mapping[str, str], today: date
) -> bool:
    if got.uppercase and read != read.upper():
        return False
    return fill_eval.value_right(c, got, profile, today, printed=read)


# --- one form -----------------------------------------------------------------------------------


def _box(page: int, bbox: tuple[float, float, float, float]) -> BBox:
    return BBox(page=page, x0=bbox[0], y0=bbox[1], x1=bbox[2], y1=bbox[3])


def label_boxes(form: str) -> dict[str, BBox]:
    """The human-labelled boxes of a dev form, by label field id."""
    return {f.id: _box(f.page, f.bbox) for f in load_label_file(LABELS_DIR / f"{form}.json").fields}


def evaluate_form(
    item: RenderedForm,
    form: run_eval.FormResult,
    labels: Mapping[str, BBox],
    profile: Mapping[str, str],
    today: date,
) -> list[PrintedField]:
    compared = {c.predicted_id: c for c in form.compared}
    drawn = set(item.rendered.drawn)
    fields = [f for f in item.ir.fields if f.id in drawn and f.kind not in _TICK_KINDS]
    comb = item.ir.source_kind is not SourceKind.FILLABLE  # as in the renderer
    chars = printed_chars(item.original, item.rendered.pdf)
    out: list[PrintedField] = []
    with pymupdf.open("pdf", item.original) as doc:
        boxes = {f.id: _unrotated(f.bbox, doc[f.bbox.page]) for f in fields}
        owned: dict[str, list[_Char]] = {f.id: [] for f in fields}
        for ch in chars:
            owner = next(
                (f for f in fields if f.bbox.page == ch.page and _holds(ch, boxes[f.id])), None
            )
            if owner is not None:
                owned[owner.id].append(ch)
        for f in fields:
            page = doc[f.bbox.page]
            read = read_back(page, f, owned[f.id], comb)
            c = compared.get(f.id)
            label = labels[c.field_id] if c is not None else None
            label_rect = _unrotated(label, page) if label is not None else None
            mine = owned[f.id]
            out.append(
                PrintedField(
                    form=item.form,
                    field_id=f.id,
                    page=f.bbox.page + 1,
                    compared=c is not None,
                    fillable_reference=c is not None and c.reference not in run_eval.NOT_FILLABLE,
                    right=c is not None and _right(c, f, read, profile, today),
                    match_right=c is not None and fill_eval.value_right(c, f, profile, today),
                    error=error_kind(read, fit.printed(f) or ""),
                    iou=None if label is None else round(iou(f.bbox, label), 4),
                    containment=None
                    if label is None
                    else round(
                        intersection_area(f.bbox, label) / (f.bbox.width * f.bbox.height), 4
                    ),
                    chars=len(mine),
                    centre_inside=0
                    if label_rect is None
                    else sum(_holds(ch, label_rect) for ch in mine),
                    whole_inside=0
                    if label_rect is None
                    else sum(_inside(ch, label_rect) for ch in mine),
                )
            )
    return out


# --- scores -------------------------------------------------------------------------------------


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _stats(values: Sequence[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
    }


def summarise(printed: Sequence[PrintedField], fillable: int) -> dict[str, object]:
    """Fill correctness and placement over some printed fields; `fillable` is the number of
    compared fields with a fillable reference type on the same forms."""
    right = sum(p.right for p in printed)
    ious = [p.iou for p in printed if p.iou is not None]
    chars = sum(p.chars for p in printed)
    missed = [p for p in printed if p.match_right and not p.right]
    return {
        "printed": len(printed),
        "compared": sum(p.compared for p in printed),
        "right": right,
        "fillable_reference": fillable,
        "correct_of_printed": _ratio(right, len(printed)),
        "correct_of_fillable": _ratio(right, fillable),
        "match_level_right": sum(p.match_right for p in printed),
        "printed_text_errors": {k: sum(p.error == k for p in printed) for k in ERROR_KINDS},
        "missed_by_match_level": len(missed),
        "iou": _stats(ious)
        | {"share_at_least_0_5": _ratio(sum(v >= 0.5 for v in ious), len(ious))},
        "containment": _stats([p.containment for p in printed if p.containment is not None]),
        "chars": chars,
        "chars_inside_label_by_centre": _ratio(sum(p.centre_inside for p in printed), chars),
        "chars_inside_label_whole": _ratio(sum(p.whole_inside for p in printed), chars),
    }


def report(result: run_eval.EvalResult, tag: str | None, provider: str) -> dict[str, object]:
    personas = fill_eval.load_personas()
    today = run_eval.FIXED_TIME.date()
    forms_by_name = {f.form: f for f in result.forms}
    per_persona: dict[str, object] = {}
    for name, profile in personas.items():
        everything: list[PrintedField] = []
        per_form: dict[str, object] = {}
        fillable_total = fillable_scratch = 0
        for item in render_forms(result, profile):
            form = forms_by_name[item.form]
            printed = evaluate_form(item, form, label_boxes(item.form), profile, today)
            fillable = sum(c.reference not in run_eval.NOT_FILLABLE for c in form.compared)
            fillable_total += fillable
            fillable_scratch += fillable if form.from_scratch else 0
            everything += printed
            per_form[item.form] = summarise(printed, fillable)
        per_persona[name] = {
            "total": summarise(everything, fillable_total),
            # Pre-annotated label boxes start as the detector's own; a high IoU there partly
            # says the human kept them. Forms labelled from scratch have no such start.
            "from_scratch": summarise(
                [p for p in everything if forms_by_name[p.form].from_scratch], fillable_scratch
            ),
            "from_scratch_forms": sorted(f.form for f in result.forms if f.from_scratch),
            "forms": per_form,
            "errors": [
                {
                    "form": p.form,
                    "field_id": p.field_id,
                    "page": p.page,
                    "error": p.error,
                    "right_at_match_level": p.match_right,
                    "right_as_read_back": p.right,
                }
                for p in everything
                if p.error is not None or p.match_right != p.right
            ],
        }
    return {
        "kind": "render-eval",
        "split": "dev",
        "detector": result.detector,
        "provider": provider,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tag": tag,
        "full_persona": fill_eval.FULL_PERSONA,
        "policy": fill_eval.PRODUCT_POLICY,
        "personas": per_persona,
    }


# --- Markdown -----------------------------------------------------------------------------------


def _pct(value: object) -> str:
    return "—" if value is None else f"{100 * float(value):.1f} %"  # type: ignore[arg-type]


def _num(value: object) -> str:
    return "—" if value is None else f"{float(value):.3f}"  # type: ignore[arg-type]


def markdown(data: Mapping[str, object]) -> str:
    personas: dict[str, dict[str, object]] = data["personas"]  # type: ignore[assignment]
    lines = [
        "# Fill correctness and placement, read back from the rendered PDFs — dev",
        "",
        f"- Detector `{data['detector']}`; provider `{data['provider']}` (replay); policy "
        f'"{data["policy"]}" then "confirm all" (P5-D7); created {data["created_at"]}; '
        f"tag `{data['tag']}`",
        "- Printed text is read back from each rendered PDF and judged against the persona as "
        "the fill eval judges value precision. *Correct of printed*: right / printed values (a "
        "printed field with no compared label counts as not right). *Correct of fillable*: right "
        "/ compared fields with a fillable reference type.",
        "- Placement is measured against the human-labelled box each printed field was matched "
        "to. IoU and containment (share of the field's box inside the label box) are per field; "
        "the character shares count printed characters inside the label box.",
        "- Label boxes: human. Reference types: Claude-written (P3-D6). " + fill_eval.PERSONA_NOTE,
        "",
        "## Totals per persona",
        "",
        "| Persona | Printed | Right | Correct of printed | Fillable | Correct of fillable "
        "| Match-level right | Printed-text errors | IoU mean / median | IoU ≥ 0.5 "
        "| Containment mean / median | Chars inside (centre) | Chars inside (whole) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for name, persona in personas.items():
        t: dict[str, object] = persona["total"]  # type: ignore[assignment]
        errors: dict[str, int] = t["printed_text_errors"]  # type: ignore[assignment]
        i: dict[str, object] = t["iou"]  # type: ignore[assignment]
        k: dict[str, object] = t["containment"]  # type: ignore[assignment]
        lines.append(
            f"| {name} | {t['printed']} | {t['right']} | {_pct(t['correct_of_printed'])} | "
            f"{t['fillable_reference']} | {_pct(t['correct_of_fillable'])} | "
            f"{t['match_level_right']} | {sum(errors.values())} | "
            f"{_num(i['mean'])} / {_num(i['median'])} | {_pct(i['share_at_least_0_5'])} | "
            f"{_num(k['mean'])} / {_num(k['median'])} | "
            f"{_pct(t['chars_inside_label_by_centre'])} | {_pct(t['chars_inside_label_whole'])} |"
        )
    lines += [
        "",
        "Most dev label boxes were pre-annotated with the detector's boxes and then checked by "
        "the human, so an IoU near 1 there partly says the human kept the detector's box. On the "
        "forms labelled from scratch ("
        + ", ".join(personas[str(data["full_persona"])]["from_scratch_forms"])  # type: ignore[arg-type,index]
        + "):",
        "",
        "| Persona | Printed | IoU mean / median | IoU ≥ 0.5 | Containment mean "
        "| Chars inside (centre) | Chars inside (whole) |",
        "|---|--:|--:|--:|--:|--:|--:|",
    ]
    for name, persona in personas.items():
        t = persona["from_scratch"]  # type: ignore[assignment]
        i = t["iou"]  # type: ignore[assignment]
        k = t["containment"]  # type: ignore[assignment]
        lines.append(
            f"| {name} | {t['printed']} | {_num(i['mean'])} / {_num(i['median'])} | "
            f"{_pct(i['share_at_least_0_5'])} | {_num(k['mean'])} | "
            f"{_pct(t['chars_inside_label_by_centre'])} | {_pct(t['chars_inside_label_whole'])} |"
        )
    full = str(data["full_persona"])
    forms: dict[str, dict[str, object]] = personas[full]["forms"]  # type: ignore[assignment,index]
    lines += [
        "",
        f"## Per form ({full})",
        "",
        "| Form | Printed | Right | Correct of printed | Fillable | Correct of fillable "
        "| IoU mean | Containment mean | Chars inside (centre) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for name, f in forms.items():
        i = f["iou"]  # type: ignore[assignment]
        k = f["containment"]  # type: ignore[assignment]
        lines.append(
            f"| {name} | {f['printed']} | {f['right']} | {_pct(f['correct_of_printed'])} | "
            f"{f['fillable_reference']} | {_pct(f['correct_of_fillable'])} | "
            f"{_num(i['mean'])} | {_num(k['mean'])} | {_pct(f['chars_inside_label_by_centre'])} |"
        )
    lines += ["", "## Printed-text errors and judgement differences", ""]
    any_error = False
    for name, persona in personas.items():
        for e in persona["errors"]:  # type: ignore[attr-defined]
            any_error = True
            lines.append(
                f"- {name}, {e['form']}, page {e['page']}, `{e['field_id']}`: "
                f"{e['error'] or 'same text'}; right at match level {e['right_at_match_level']}, "
                f"as read back {e['right_as_read_back']}"
            )
    if not any_error:
        lines.append("None: every printed field reads back as the text the renderer was given.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read back the rendered dev forms and score them.")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)
    try:
        result = dev_result(args.provider, args.model)
    except run_eval.EvalError as exc:
        print(f"refused: {exc}")  # noqa: T201 - CLI output
        return 1
    data = report(result, args.tag, f"{args.provider}:{args.model}")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = str(data["created_at"])[:10].replace("-", "")
    commit = str(data["detector"]).removeprefix("flat@")
    tag = f"-{args.tag}" if args.tag else ""
    base = args.out / f"phase5-render-eval-dev{tag}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    personas: dict[str, dict[str, object]] = data["personas"]  # type: ignore[assignment]
    for name, persona in personas.items():
        t: dict[str, object] = persona["total"]  # type: ignore[assignment]
        print(  # noqa: T201 - CLI output
            f"{name}: printed {t['printed']}, correct of printed {_pct(t['correct_of_printed'])}, "
            f"of fillable {_pct(t['correct_of_fillable'])}, errors {t['printed_text_errors']}"
        )
    print(base.with_suffix(".md"))  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
