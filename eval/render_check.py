"""Render checks on the rendered dev forms (decision P5-D11), run before and after the render fixes.

    make render-check   # replays the recorded understanding answers (Groq by default)

The dev forms go through the same passes as `make render-samples`; then, per form:
- characters: every character the overlay printed (the rendered page's text minus the original
  page's) lies inside a printed field's box, and in a comb with drawn cells (P5-D14) inside one
  cell, one character per cell;
- dates: the day, month and year parts of one date (`app.ir.parts.date_groups`) are printed all
  or none (P5-D13);
- never-fill: no printed field has a never-fill reason or lies in an office-use area read from
  the original PDF: a small drawn box whose text says "for office use" (P3-D1), or the part of a
  page below a centred line saying it is to be filled by an official, an office, the bank and the
  like (P5-D15);
- ticks: a tick box is ticked only from the user's own answer or edit (P5-D12).

Once per run, a Devanagari smoke test (decision P5-D23): a synthetic page with Devanagari values
rendered by the overlay renderer; a conjunct ("क्ष", "श्र") must be one shaped glyph, a pre-base
vowel sign ("कि") must sit left of its consonant, a post-base one ("की") right of it.

Reports (JSON and Markdown) go to eval/reports/. They hold field ids, pages and counts, never a
printed value or character.
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pymupdf

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
from app.ir.parts import date_groups
from app.ir.phrases import filled_by_others, mentions_office_use
from app.logging import configure_logging
from app.passes import fit
from app.passes.context import PassContext
from eval import run_eval
from eval.labelling.schema import REPO_ROOT
from eval.labelling.tasks import detector_version
from eval.render_samples import RenderedForm, render_dev_forms

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
CHECKS = ("characters", "dates", "never_fill", "ticks")
TOLERANCE = 0.1  # points a printed character may pass a box or cell edge by (rounding)
# Helvetica: capitals and digits reach this share of the font size above the baseline, and
# descenders this share below it.
CAP_HEIGHT = 0.72
DESCENT = 0.21
_DESCENDERS = frozenset("gjpqyQ,;()")
OFFICE_BOX_MAX_PAGE_SHARE = 0.15  # as in the flat frontend: a page frame is not an office box
CENTRED = 0.1  # share of the page width a heading's middle may be off the page's middle
_TICK_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})
_USER_SOURCES = frozenset({ValueSource.USER_ANSWER, ValueSource.USER_EDIT})


@dataclass(frozen=True)
class Violation:
    check: str  # one of CHECKS
    field_id: str | None
    page: int  # 1-based
    detail: str  # never a value


@dataclass(frozen=True)
class _Char:
    page: int  # 0-based
    x0: float
    x1: float
    top: float
    bottom: float  # unrotated page, like PyMuPDF's text extraction
    c: str = ""  # the character, for the read-back eval only (eval/render_eval.py); never reported
    size: float = 0.0  # font size

    @property
    def centre(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.top + self.bottom) / 2


def _chars(page: pymupdf.Page) -> Counter[tuple[str, float, float, float]]:
    found: Counter[tuple[str, float, float, float]] = Counter()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    if ch["c"].strip():
                        x, y = ch["origin"]
                        found[(ch["c"], round(x, 1), round(y, 1), span["size"])] += 1
    return found


def printed_chars(original: bytes, rendered: bytes) -> list[_Char]:
    """The characters on the rendered pages that the original pages do not have."""
    printed: list[_Char] = []
    with pymupdf.open("pdf", original) as before, pymupdf.open("pdf", rendered) as after:
        for page_no, (old, new) in enumerate(zip(before, after, strict=True)):
            added = _chars(new) - _chars(old)
            for (c, x, y, size), count in added.items():
                width = pymupdf.get_text_length(c, fontname="helv", fontsize=size)
                below = DESCENT * size if c in _DESCENDERS else 0.0
                top, bottom = y - CAP_HEIGHT * size, y + below
                printed += [_Char(page_no, x, x + width, top, bottom, c, size)] * count
    return printed


def _unrotated(box: BBox, page: pymupdf.Page) -> pymupdf.Rect:
    return (pymupdf.Rect(box.x0, box.y0, box.x1, box.y1) * page.derotation_matrix).normalize()


def _inside(ch: _Char, rect: pymupdf.Rect) -> bool:
    t = TOLERANCE
    return (
        rect.x0 - t <= ch.x0
        and ch.x1 <= rect.x1 + t
        and rect.y0 - t <= ch.top
        and ch.bottom <= rect.y1 + t
    )


def _holds(ch: _Char, rect: pymupdf.Rect) -> bool:
    x, y = ch.centre
    return rect.x0 <= x <= rect.x1 and rect.y0 <= y <= rect.y1


def check_characters(
    original: bytes, rendered: bytes, ir: FormIR, drawn: Sequence[str]
) -> list[Violation]:
    printed = [f for f in ir.fields if f.id in set(drawn) and f.kind not in _TICK_KINDS]
    violations: list[Violation] = []
    with pymupdf.open("pdf", original) as doc:
        boxes = {f.id: _unrotated(f.bbox, doc[f.bbox.page]) for f in printed}
        cells = {f.id: [_unrotated(c, doc[c.page]) for c in f.cells] for f in printed}
    per_cell: Counter[tuple[str, int]] = Counter()
    for ch in printed_chars(original, rendered):
        owner = next(
            (f for f in printed if f.bbox.page == ch.page and _holds(ch, boxes[f.id])), None
        )
        if owner is None:
            violations.append(
                Violation("characters", None, ch.page + 1, "a character outside every printed box")
            )
            continue
        if not _inside(ch, boxes[owner.id]):
            violations.append(
                Violation("characters", owner.id, ch.page + 1, "a character crosses the box edge")
            )
            continue
        if cells[owner.id]:
            index = next((i for i, c in enumerate(cells[owner.id]) if _holds(ch, c)), None)
            if index is None or not _inside(ch, cells[owner.id][index]):
                violations.append(
                    Violation(
                        "characters", owner.id, ch.page + 1, "a character on a comb cell divider"
                    )
                )
                continue
            per_cell[(owner.id, index)] += 1
    for (field_id, index), count in sorted(per_cell.items()):
        if count > 1:
            page = next(f.bbox.page for f in printed if f.id == field_id)
            violations.append(
                Violation("characters", field_id, page + 1, f"comb cell {index + 1} holds {count}")
            )
    return violations


def check_dates(ir: FormIR, drawn: Sequence[str]) -> list[Violation]:
    violations: list[Violation] = []
    for parts in date_groups(ir.fields):
        shown = [p for p in parts if p.id in set(drawn)]
        if shown and len(shown) < len(parts):
            missing = ", ".join(p.date_part or "" for p in parts if p not in shown)
            violations.append(
                Violation(
                    "dates", parts[0].id, parts[0].bbox.page + 1, f"date printed without {missing}"
                )
            )
    return violations


def _office_boxes(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Small drawn boxes whose own text says "for office use" (unrotated page)."""
    limit = OFFICE_BOX_MAX_PAGE_SHARE * page.rect.width * page.rect.height
    found = []
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1 or rect.height < 1 or rect.width * rect.height > limit:
            continue
        if mentions_office_use(page.get_text("text", clip=rect)):
            found.append(rect)
    return found


def _official_tops(page: pymupdf.Page) -> list[float]:
    """The bottom edge of each centred line saying the part below is for an official
    (unrotated page)."""
    middle = page.mediabox.width / 2 if page.rotation % 180 == 0 else page.mediabox.height / 2
    width = 2 * middle
    tops = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = " ".join(span["text"] for span in line["spans"])
            box = pymupdf.Rect(line["bbox"])
            if filled_by_others(text) and abs((box.x0 + box.x1) / 2 - middle) <= CENTRED * width:
                tops.append(box.y1)
    return tops


def check_never_fill(original: bytes, ir: FormIR, drawn: Sequence[str]) -> list[Violation]:
    violations: list[Violation] = []
    printed = [f for f in ir.fields if f.id in set(drawn)]
    with pymupdf.open("pdf", original) as doc:
        areas = {
            n: (_office_boxes(doc[n]), _official_tops(doc[n]))
            for n in sorted({f.bbox.page for f in printed})
        }
        for f in printed:
            page = doc[f.bbox.page]
            if f.no_fill_reason is not None:
                violations.append(
                    Violation("never_fill", f.id, f.bbox.page + 1, f"printed ({f.no_fill_reason})")
                )
                continue
            rect = _unrotated(f.bbox, page)
            boxes, tops = areas[f.bbox.page]
            if any(b.contains(rect) for b in boxes):
                violations.append(
                    Violation("never_fill", f.id, f.bbox.page + 1, "inside an office-use box")
                )
            elif any(rect.y0 >= top - TOLERANCE for top in tops):
                violations.append(
                    Violation("never_fill", f.id, f.bbox.page + 1, "below an official-only heading")
                )
    return violations


def check_ticks(ir: FormIR, drawn: Sequence[str]) -> list[Violation]:
    return [
        Violation("ticks", f.id, f.bbox.page + 1, f"ticked from {f.value_source.value}")
        for f in ir.fields
        if f.id in set(drawn) and f.kind in _TICK_KINDS and f.value_source not in _USER_SOURCES
    ]


def check_form(
    original: bytes, rendered: bytes, ir: FormIR, drawn: Sequence[str]
) -> list[Violation]:
    return (
        check_characters(original, rendered, ir, drawn)
        + check_dates(ir, drawn)
        + check_never_fill(original, ir, drawn)
        + check_ticks(ir, drawn)
    )


# (value, what correct shaping looks like) for the Devanagari smoke test (P5-D23)
DEVANAGARI_CASES = (
    ("क्ष", "conjunct"),
    ("श्र", "conjunct"),
    ("कि", "pre-base vowel sign"),
    ("की", "post-base vowel sign"),
)


def devanagari_smoke() -> list[str]:
    """Failures of the Devanagari smoke test; empty when every case is shaped right."""
    fields = [
        Field(
            id=f"p0_f{i:03d}",
            kind=FieldKind.TEXT,
            native_name=None,
            label_text="Name",
            context_text=None,
            bbox=BBox(page=0, x0=100, y0=100 + 40 * i, x1=400, y1=126 + 40 * i),
            value=value,
            value_source=ValueSource.USER_ANSWER,
            status=FieldStatus.CONFIRMED,
        )
        for i, (value, _) in enumerate(DEVANAGARI_CASES)
    ]
    ir = FormIR(
        document_id=UUID(int=0), source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)], fields=fields,
    )  # fmt: skip
    blank = pymupdf.open()
    blank.new_page(width=595, height=842)
    out = overlay.render(blank.tobytes(), fit.run(ir, PassContext(clock=lambda: datetime.now(UTC))))
    failures = [f"{f.id}: not drawn" for f in fields if f.id not in out.drawn]
    with pymupdf.open("pdf", out.pdf) as doc:
        glyphs = [
            (ch["c"], ch["bbox"])
            for block in doc[0].get_text("rawdict")["blocks"]
            for line in block.get("lines", [])
            for span in line["spans"]
            for ch in span["chars"]
        ]
    for f, (_, kind) in zip(fields, DEVANAGARI_CASES, strict=True):
        inside = sorted(
            (bbox[0], c) for c, bbox in glyphs if f.bbox.y0 <= (bbox[1] + bbox[3]) / 2 <= f.bbox.y1
        )
        if kind == "conjunct":
            ok = len(inside) == 1
        else:
            order = [c == "क" for _, c in inside]  # True for the consonant, left to right
            ok = order == ([False, True] if kind.startswith("pre") else [True, False])
        if not ok:
            failures.append(f"{f.id}: {kind} not shaped ({len(inside)} glyphs)")
    return failures


def report(forms: Sequence[RenderedForm], tag: str | None, provider: str) -> dict[str, object]:
    per_form: dict[str, object] = {}
    for item in forms:
        found = check_form(item.original, item.rendered.pdf, item.ir, item.rendered.drawn)
        per_form[item.form] = {
            "printed": len(item.rendered.drawn),
            "failures": {check: sum(v.check == check for v in found) for check in CHECKS},
            "violations": [asdict(v) for v in found],
        }
    return {
        "kind": "render-check",
        "split": "dev",
        "detector": detector_version(),
        "provider": provider,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tag": tag,
        "checks": list(CHECKS),
        "forms": per_form,
        "devanagari_smoke": devanagari_smoke(),
    }


def markdown(data: dict[str, object]) -> str:
    forms: dict[str, dict[str, object]] = data["forms"]  # type: ignore[assignment]
    lines = [
        "# Render checks — dev",
        "",
        f"- Detector `{data['detector']}`; provider `{data['provider']}` (replay); created "
        f"{data['created_at']}; tag `{data['tag']}`",
        "- Checks (decision P5-D11): *characters* inside their box or comb cell; *dates* printed "
        "all or none; *never_fill*: nothing printed in a never-fill field or an office-use area; "
        "*ticks* only from the user's own choice. Counts are failures.",
        "",
        "| Form | Printed | " + " | ".join(CHECKS) + " |",
        "|---|--:|" + "--:|" * len(CHECKS),
    ]
    totals: Counter[str] = Counter()
    for name, form in forms.items():
        failures: dict[str, int] = form["failures"]  # type: ignore[assignment]
        totals.update(failures)
        counts = " | ".join(str(failures[c]) for c in CHECKS)
        lines.append(f"| {name} | {form['printed']} | {counts} |")
    lines.append("| **Total** | | " + " | ".join(f"**{totals[c]}**" for c in CHECKS) + " |")
    smoke: list[str] = data.get("devanagari_smoke", [])  # type: ignore[assignment]
    cases = ", ".join(f"{v} ({k})" for v, k in DEVANAGARI_CASES)
    lines += [
        "",
        f"Devanagari smoke test (P5-D23; {cases}): "
        + ("passed." if not smoke else "**failed**: " + "; ".join(smoke)),
    ]
    lines += ["", "## Failures", ""]
    any_failure = False
    for name, form in forms.items():
        for v in form["violations"]:  # type: ignore[attr-defined]
            any_failure = True
            field = v["field_id"] or "—"
            lines.append(f"- {name}, page {v['page']}, `{field}`: {v['check']}: {v['detail']}")
    if not any_failure:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the rendered dev forms (P5-D11).")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)
    try:
        forms = render_dev_forms(args.provider, args.model)
    except run_eval.EvalError as exc:
        print(f"refused: {exc}")  # noqa: T201 - CLI output
        return 1
    data = report(forms, args.tag, f"{args.provider}:{args.model}")
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = str(data["created_at"])[:10].replace("-", "")
    commit = str(data["detector"]).removeprefix("flat@")
    tag = f"-{args.tag}" if args.tag else ""
    base = args.out / f"phase5-render-check-dev{tag}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    forms_data: dict[str, dict[str, object]] = data["forms"]  # type: ignore[assignment]
    for name, form in forms_data.items():
        print(f"{name}: {form['printed']} printed, failures {form['failures']}")  # noqa: T201
    smoke_failures: list[str] = data["devanagari_smoke"]  # type: ignore[assignment]
    print(f"devanagari smoke: {smoke_failures or 'passed'}")  # noqa: T201 - CLI output
    print(base.with_suffix(".md"))  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
