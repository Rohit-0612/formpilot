"""Detection eval: the flat detector's boxes against the human labels (SPEC §10, PLAN Phase 2).

    make eval-detect        # = python -m eval.detection --split dev, from the repo root

For every PDF in eval/dataset/<split>/ that has a label file in eval/labels/:
- run detect + the flat frontend (pure functions; no database, no worker);
- per labelled page whose text layer is OK and that is in the labelling subset
  (eval/labelling/subset.py; labelled pages outside it are listed, not scored), match
  predicted and labelled boxes one-to-one, greedily by descending IoU, keeping pairs with
  IoU >= 0.5 (SPEC §10);
- TP = matched pairs, FP = unmatched predictions, FN = unmatched labels;
  precision = TP / (TP + FP), recall = TP / (TP + FN), micro-averaged over pages and forms.

Reported as well: per form; recall by labelled kind and precision by predicted kind (text, comb,
checkbox); kind agreement on matched pairs; the same numbers at IoU >= 0.3 as a diagnostic
(a 9 pt checkbox 2 pt off has IoU ~0.43); from-scratch forms separately from pre-filled ones
(anchoring check); and which pages were not scored and why. Writes a JSON and a Markdown report
to eval/reports/. Only the dev split is allowed in Phase 2 (CLAUDE.md §6).
"""

import argparse
import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pymupdf

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.geometry import MATCH_IOU, iou
from app.ir.models import BBox, FieldKind, TextLayer
from app.logging import configure_logging, get_logger
from eval.labelling.schema import DATASET_DIR, LABELS_DIR, REPO_ROOT, LabelKind, load_label_file
from eval.labelling.subset import DEV_SUBSET, PageSelection, SubsetError, subset_pages
from eval.labelling.tasks import detector_version

log = get_logger(__name__)

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
DIAGNOSTIC_IOU = 0.3
KINDS = ("text", "comb", "checkbox")

DATASET_NOTES = (
    "Known gaps in the test split (docs/reality_check.md, human decision 2026-10-11): the test "
    "split has no Hindi-only form, and no bilingual form with a clean Unicode Hindi text layer. "
    "Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer "
    "to test later; dev stays unchanged. This report uses the dev split only."
)


# --- matching (pure) ----------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    bbox: BBox
    kind: str  # one of KINDS


def match(
    predicted: Sequence[Box], labelled: Sequence[Box], threshold: float
) -> list[tuple[int, int, float]]:
    """One-to-one matches (predicted index, labelled index, IoU), greedy by descending IoU.

    Boxes on different pages never match. Ties are broken by the lower predicted, then the lower
    labelled index, so the result is deterministic.
    """
    pairs = [
        (overlap, p, t)
        for p, pred in enumerate(predicted)
        for t, truth in enumerate(labelled)
        if (overlap := iou(pred.bbox, truth.bbox)) >= threshold
    ]
    pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2]))
    used_p: set[int] = set()
    used_t: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for overlap, p, t in pairs:
        if p in used_p or t in used_t:
            continue
        used_p.add(p)
        used_t.add(t)
        matches.append((p, t, overlap))
    return matches


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    def add(self, other: "Counts") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
        }


def count(predicted: Sequence[Box], labelled: Sequence[Box], threshold: float) -> Counts:
    tp = len(match(predicted, labelled, threshold))
    return Counts(tp=tp, fp=len(predicted) - tp, fn=len(labelled) - tp)


@dataclass
class KindStats:
    """Recall by labelled kind, precision by predicted kind, agreement on matched pairs."""

    labelled: Counter[str] = field(default_factory=Counter)
    labelled_matched: Counter[str] = field(default_factory=Counter)
    predicted: Counter[str] = field(default_factory=Counter)
    predicted_matched: Counter[str] = field(default_factory=Counter)
    agreement: Counter[str] = field(default_factory=Counter)  # "pred->label"

    def add_page(self, predicted: Sequence[Box], labelled: Sequence[Box], threshold: float) -> None:
        self.labelled.update(b.kind for b in labelled)
        self.predicted.update(b.kind for b in predicted)
        for p, t, _ in match(predicted, labelled, threshold):
            self.predicted_matched[predicted[p].kind] += 1
            self.labelled_matched[labelled[t].kind] += 1
            self.agreement[f"{predicted[p].kind}->{labelled[t].kind}"] += 1

    def add(self, other: "KindStats") -> None:
        for name in ("labelled", "labelled_matched", "predicted", "predicted_matched", "agreement"):
            getattr(self, name).update(getattr(other, name))

    def as_dict(self) -> dict[str, object]:
        return {
            "recall_by_labelled_kind": {
                k: _ratio(self.labelled_matched[k], self.labelled[k]) for k in KINDS
            },
            "precision_by_predicted_kind": {
                k: _ratio(self.predicted_matched[k], self.predicted[k]) for k in KINDS
            },
            "matched_pairs_predicted_to_labelled_kind": dict(sorted(self.agreement.items())),
        }


def _ratio(numerator: int, denominator: int) -> dict[str, float | int | None]:
    return {
        "matched": numerator,
        "total": denominator,
        "share": numerator / denominator if denominator else None,
    }


# --- running the detector against the labels ----------------------------------------------


@dataclass
class FormResult:
    form: str
    prefilled_from: str | None
    scored_pages: list[int]  # 0-based
    ocr_pages: list[int]  # labelled, but the text layer is not OK: routed to OCR, not scored
    unlabelled_pages: list[int]  # OK pages in the subset without labels
    outside_subset: list[int] = field(default_factory=list)  # labelled, but not in the subset
    at_match: Counts = field(default_factory=Counts)
    at_diagnostic: Counts = field(default_factory=Counts)
    kinds: KindStats = field(default_factory=KindStats)


def _predicted_kind(kind: FieldKind, max_chars: int | None) -> str:
    if kind is FieldKind.CHECKBOX:
        return "checkbox"
    return "comb" if max_chars else "text"


def _labelled_kind(kind: LabelKind, comb: bool) -> str:
    if kind is LabelKind.CHECKBOX:
        return "checkbox"
    return "comb" if comb else "text"


class EvalError(Exception):
    pass


def evaluate_form(
    pdf: Path, label_path: Path, subset: Mapping[str, PageSelection] | None = None
) -> FormResult:
    """Score one form. Without a subset, every labelled page is in scope."""
    label = load_label_file(label_path)
    data = pdf.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if label.pdf_sha256 != sha256:
        raise EvalError(f"{label_path.name}: labels were made for a different PDF than {pdf.name}")
    document_id = uuid.uuid5(uuid.NAMESPACE_URL, f"formpilot-eval:{sha256}")
    with pymupdf.open("pdf", data) as doc:
        detection = detect(doc)
        ir = flat.run(doc, detection, document_id, datetime.now(UTC))
    if len(label.pages) != len(detection.pages):
        raise EvalError(f"{label_path.name}: page count differs from {pdf.name}")

    ok = {i for i, page in enumerate(detection.pages) if page.text_layer is TextLayer.OK}
    labelled = set(label.labelled_pages)
    if subset is None:
        in_scope: set[int] = set(range(len(detection.pages)))
    else:
        try:
            in_scope = set(subset_pages(subset, pdf.stem, len(detection.pages)))
        except SubsetError as exc:
            raise EvalError(str(exc)) from None
    result = FormResult(
        form=label.form,
        prefilled_from=label.prefilled_from,
        scored_pages=sorted(labelled & ok & in_scope),
        ocr_pages=sorted((labelled & in_scope) - ok),
        unlabelled_pages=sorted((ok & in_scope) - labelled),
        outside_subset=sorted(labelled - in_scope),
    )
    for page in result.scored_pages:
        predicted = [
            Box(f.bbox, _predicted_kind(f.kind, f.max_chars))
            for f in ir.fields
            if f.bbox.page == page
        ]
        truth = [
            Box(
                BBox(page=page, x0=f.bbox[0], y0=f.bbox[1], x1=f.bbox[2], y1=f.bbox[3]),
                _labelled_kind(f.kind, f.comb),
            )
            for f in label.fields
            if f.page == page
        ]
        result.at_match.add(count(predicted, truth, MATCH_IOU))
        result.at_diagnostic.add(count(predicted, truth, DIAGNOSTIC_IOU))
        result.kinds.add_page(predicted, truth, MATCH_IOU)
    return result


@dataclass
class EvalResult:
    split: str
    detector: str
    created_at: str
    forms: list[FormResult]
    forms_without_labels: list[str]
    forms_without_ok_pages: list[str] = field(default_factory=list)  # need OCR, Phase 6
    subset: Mapping[str, PageSelection] | None = None  # None: every labelled page is scored

    def total(self, prefilled: bool | None = None) -> tuple[Counts, Counts, KindStats]:
        at_match, at_diag, kinds = Counts(), Counts(), KindStats()
        for form in self.forms:
            if prefilled is not None and (form.prefilled_from is not None) != prefilled:
                continue
            at_match.add(form.at_match)
            at_diag.add(form.at_diagnostic)
            kinds.add(form.kinds)
        return at_match, at_diag, kinds


def evaluate(
    dataset: Path,
    labels: Path,
    split: str,
    detector: str,
    subset: Mapping[str, PageSelection] | None = None,
) -> EvalResult:
    pdfs = sorted(dataset.glob("*.pdf"))
    stems = {p.stem for p in pdfs}
    orphans = sorted(p.name for p in labels.glob("*.json") if p.stem not in stems)
    if orphans:
        raise EvalError(f"label files without a PDF in {dataset}: {', '.join(orphans)}")
    unknown = sorted(set(subset or {}) - stems)
    if unknown:
        raise EvalError(f"subset names forms without a PDF in {dataset}: {', '.join(unknown)}")
    forms: list[FormResult] = []
    without: list[str] = []
    no_ok_pages: list[str] = []
    for pdf in pdfs:
        label_path = labels / f"{pdf.stem}.json"
        if label_path.exists():
            forms.append(evaluate_form(pdf, label_path, subset))
        elif _has_ok_page(pdf):
            without.append(pdf.stem)
        else:
            no_ok_pages.append(pdf.stem)
    created = datetime.now(UTC).isoformat(timespec="seconds")
    return EvalResult(split, detector, created, forms, without, no_ok_pages, subset)


def _has_ok_page(pdf: Path) -> bool:
    with pymupdf.open(pdf) as doc:
        return any(page.text_layer is TextLayer.OK for page in detect(doc).pages)


# --- reports ------------------------------------------------------------------------------


def report_json(result: EvalResult) -> dict[str, object]:
    def section(prefilled: bool | None) -> dict[str, object]:
        at_match, at_diag, kinds = result.total(prefilled)
        return {
            f"iou_{MATCH_IOU}": at_match.as_dict(),
            f"iou_{DIAGNOSTIC_IOU}": at_diag.as_dict(),
            "kinds": kinds.as_dict(),
        }

    return {
        "eval": "phase2-detection",
        "split": result.split,
        "detector": result.detector,
        "created_at": result.created_at,
        "match_rule": f"one-to-one, greedy by IoU, IoU >= {MATCH_IOU} on the same page",
        "subset_pages_1based": (
            None
            if result.subset is None
            else {form: _selection(pages) for form, pages in sorted(result.subset.items())}
        ),
        "overall": section(None),
        "anchoring_check": {"from_scratch": section(False), "prefilled": section(True)},
        "forms": [
            {
                "form": f.form,
                "prefilled_from": f.prefilled_from,
                "scored_pages": [p + 1 for p in f.scored_pages],
                "ocr_pages_not_scored": [p + 1 for p in f.ocr_pages],
                "unlabelled_pages": [p + 1 for p in f.unlabelled_pages],
                "labelled_outside_subset_not_scored": [p + 1 for p in f.outside_subset],
                f"iou_{MATCH_IOU}": f.at_match.as_dict(),
                f"iou_{DIAGNOSTIC_IOU}": f.at_diagnostic.as_dict(),
                "kinds": f.kinds.as_dict(),
            }
            for f in result.forms
        ],
        "forms_without_labels": result.forms_without_labels,
        "forms_without_ok_pages": result.forms_without_ok_pages,
        "dataset_notes": DATASET_NOTES,
    }


def _selection(pages: PageSelection) -> str | list[int]:
    return pages if isinstance(pages, str) else list(pages)


def _describe(pages: PageSelection) -> str:
    if isinstance(pages, str):
        return "all pages"
    return ("page " if len(pages) == 1 else "pages ") + ", ".join(map(str, pages))


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{100 * value:.1f} %"


def _counts_row(name: str, c: Counts, diag: Counts) -> str:
    return (
        f"| {name} | {_pct(c.precision)} | {_pct(c.recall)} | {c.tp} | {c.fp} | {c.fn} | "
        f"{_pct(diag.precision)} | {_pct(diag.recall)} |"
    )


_COUNTS_HEADER = (
    "| | Precision | Recall | TP | FP | FN | "
    f"Precision @ {DIAGNOSTIC_IOU} | Recall @ {DIAGNOSTIC_IOU} |\n"
    "|---|--:|--:|--:|--:|--:|--:|--:|"
)


def report_markdown(result: EvalResult) -> str:
    at_match, at_diag, kinds = result.total()
    lines = [
        f"# Detection eval — {result.split} split",
        "",
        f"- Detector: `{result.detector}`; run at {result.created_at}.",
        f"- Match: one-to-one, greedy by IoU, IoU ≥ {MATCH_IOU} on the same page (SPEC §10); "
        f"IoU ≥ {DIAGNOSTIC_IOU} shown as a diagnostic.",
        "- Scored: labelled pages whose text layer is OK"
        + (
            "."
            if result.subset is None
            else " and that are in the labelling subset (eval/labelling/subset.py): "
            + "; ".join(
                f"{form} {_describe(pages)}" for form, pages in sorted(result.subset.items())
            )
            + "."
        ),
        "- All numbers below are measured by this run.",
        "",
    ]
    if not result.forms:
        lines += ["**No label files yet: nothing was scored.**", ""]
    else:
        lines += [
            "## Overall",
            "",
            _COUNTS_HEADER,
            _counts_row("all scored pages", at_match, at_diag),
            "",
        ]
        k = kinds.as_dict()
        lines += [
            "## By kind",
            "",
            "| Kind | Recall (labelled boxes found) | Precision (predicted boxes correct) |",
            "|---|--:|--:|",
        ]
        for kind in KINDS:
            r = k["recall_by_labelled_kind"][kind]  # type: ignore[index]
            p = k["precision_by_predicted_kind"][kind]  # type: ignore[index]
            lines.append(
                f"| {kind} | {_pct(r['share'])} ({r['matched']}/{r['total']}) | "
                f"{_pct(p['share'])} ({p['matched']}/{p['total']}) |"
            )
        agreement = k["matched_pairs_predicted_to_labelled_kind"]
        lines += [
            "",
            "Matched pairs, predicted kind → labelled kind: "
            + (", ".join(f"{pair}: {n}" for pair, n in agreement.items()) or "none"),  # type: ignore[union-attr]
            "",
            "## Anchoring check",
            "",
            "Forms labelled from scratch (no pre-filled boxes) against pre-filled forms. If the "
            "detector scores clearly better on the pre-filled forms, pre-annotation may be "
            "biasing the labels.",
            "",
            _COUNTS_HEADER,
        ]
        for name, flag in (("from scratch", False), ("pre-filled", True)):
            m, d, _ = result.total(flag)
            lines.append(_counts_row(name, m, d))
        lines += ["", "## Per form", "", _COUNTS_HEADER.replace("| |", "| Form |", 1)]
        for f in result.forms:
            name = f"{f.form}{' (from scratch)' if f.prefilled_from is None else ''}"
            lines.append(_counts_row(name, f.at_match, f.at_diagnostic))
    lines += ["", "## Not scored", ""]
    rows = []
    for f in result.forms:
        if f.ocr_pages:
            rows.append(f"- {f.form}: labelled pages {_pages(f.ocr_pages)} need OCR (Phase 6)")
        if f.unlabelled_pages:
            rows.append(f"- {f.form}: pages {_pages(f.unlabelled_pages)} not labelled yet")
        if f.outside_subset:
            rows.append(
                f"- {f.form}: labelled pages {_pages(f.outside_subset)} are outside the labelling "
                "subset (not scored)"
            )
    rows += [f"- {stem}: no label file" for stem in result.forms_without_labels]
    rows += [
        f"- {stem}: no page with a usable text layer (needs OCR, Phase 6)"
        for stem in result.forms_without_ok_pages
    ]
    lines += rows or ["- nothing"]
    lines += ["", "## Dataset notes", "", DATASET_NOTES, ""]
    return "\n".join(lines)


def _pages(pages: list[int]) -> str:
    return ", ".join(str(p + 1) for p in pages)


def write_reports(result: EvalResult, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    stamp = result.created_at[:10].replace("-", "")
    commit = result.detector.removeprefix("flat@")
    base = out / f"phase2-detection-{result.split}-{stamp}-{commit}"
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report_json(result), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(report_markdown(result), encoding="utf-8")
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--split", choices=["dev"], default="dev", help="Phase 2: dev only")
    parser.add_argument("--dataset-root", type=Path, default=DATASET_DIR)
    parser.add_argument("--labels", type=Path, default=LABELS_DIR)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)
    configure_logging("INFO", json=False)
    try:
        result = evaluate(
            args.dataset_root / args.split,
            args.labels,
            args.split,
            detector_version(),
            subset=DEV_SUBSET,
        )
    except EvalError as exc:
        log.error("eval_failed", reason=str(exc))
        return 1
    json_path, md_path = write_reports(result, args.out)
    at_match, _, _ = result.total()
    log.info(
        "eval_written",
        markdown=str(md_path),
        json=str(json_path),
        forms=len(result.forms),
        precision=at_match.precision,
        recall=at_match.recall,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
