"""Understanding eval (SPEC §10, PLAN Phase 3): semantic types of the detected fields.

    make eval MODE=hybrid            # replay the recorded model answers (default)
    make eval MODE=hybrid RECORD=1   # ask the model (Ollama) and record its answers
    make eval PROVIDER=groq MODEL=openai/gpt-oss-120b RECORD=1   # Groq; needs GROQ_API_KEY

For every PDF in eval/dataset/<split>/ with a label file in eval/labels/ and semantic reference
labels in eval/labels_semantic/:
- run detect, the flat frontend and the understanding pass (rules, llm or hybrid; SPEC §6.2);
- on each scored page (the labelling subset), match the detected fields to the labelled boxes
  one-to-one by the writing-spot rule (eval/detection.py), and compare the semantic type of each
  matched field that has a reference label.

**The reference labels are written by Claude Code, not by a human** (decision P3-D6): accuracy is
agreement with them, and every report says so.

Reported:
- accuracy on all compared fields, and on the "fillable" ones (reference type neither `other` nor
  `unknown`), because `other` is about half of the dev fields;
- by method (rule, llm, none), per reference type, per form, macro over forms, from scratch vs
  pre-filled;
- the most frequent confusions, never-fill marks, reference fields the detector did not find,
  and failed LLM batches.

Model answers go through a record / replay cache (eval/llm_cache/); a replay that misses the
cache fails the run instead of scoring fields as unknown. Only the dev split is allowed in
Phase 3 (CLAUDE.md §6).
"""

import argparse
import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pymupdf

from app.config import GroqSettings
from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import BBox, FormIR, TextLayer
from app.ir.semantic_types import SemanticType
from app.llm.cache import CachedProvider
from app.llm.groq import GroqProvider
from app.llm.ollama import OllamaProvider
from app.llm.provider import LLMError, LLMProvider, LLMRequest
from app.logging import configure_logging
from app.passes import understand
from app.passes.context import PassContext, UnderstandMode
from eval.detection import Box, _labelled_kind, _predicted_kind, match, writing_spot
from eval.labelling.schema import (
    DATASET_DIR,
    LABELS_DIR,
    REFERENCE_DIR,
    REPO_ROOT,
    load_label_file,
    load_reference,
)
from eval.labelling.subset import DEV_SUBSET, PageSelection, subset_pages
from eval.labelling.tasks import detector_version
from eval.value_truth import NO_ROLE, Role, roles

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
CACHE_DIR = REPO_ROOT / "eval" / "llm_cache" / "understand"
BASELINE = REPO_ROOT / "eval" / "baseline.json"
NOT_FILLABLE = frozenset({SemanticType.OTHER, SemanticType.UNKNOWN})
DISCLOSURE = (
    "Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, "
    "not by a human (decision P3-D6). Accuracy is agreement with them."
)
FIXED_TIME = datetime(2026, 1, 1, tzinfo=UTC)  # trace timestamps only; keeps runs comparable

type CacheMode = Literal["record", "replay", "off"]


class EvalError(Exception):
    pass


@dataclass(frozen=True)
class Compared:
    form: str
    field_id: str  # the label field id
    reference: SemanticType
    predicted: SemanticType
    method: str
    no_fill_reason: str | None
    predicted_id: str = ""  # the detected field's id (Phase 4: the fill eval)
    confidence: float = 0.0  # the semantic confidence (rule 0.95, or the model's own)
    role: Role = NO_ROLE  # Phase 5: a repeated row or a date part (eval/value_truth.py)

    @property
    def correct(self) -> bool:
        return self.reference is self.predicted


@dataclass
class FormResult:
    form: str
    from_scratch: bool
    compared: list[Compared] = field(default_factory=list)
    not_detected: int = 0  # reference fields with no matching detected field
    llm_trouble: list[str] = field(default_factory=list)  # failed or retried batches
    understood: FormIR | None = None  # the scored pages' fields after understanding


class _Counting(LLMProvider):
    """Counts provider errors (a replay miss raises one) so the run can refuse to score them."""

    def __init__(self, inner: LLMProvider) -> None:
        self.inner, self.name, self.model = inner, inner.name, inner.model
        self.errors = 0

    @property
    def is_remote(self) -> bool:
        return self.inner.is_remote

    def _complete(self, request: LLMRequest) -> str:
        try:
            return self.inner.complete_json(request)
        except LLMError:
            self.errors += 1
            raise


def understand_form(ir: FormIR, mode: UnderstandMode, provider: LLMProvider | None) -> FormIR:
    ctx = PassContext(clock=lambda: FIXED_TIME, provider=provider, understand_mode=mode)
    return understand.run(ir, ctx)


def evaluate_form(
    pdf: Path,
    label_path: Path,
    reference_path: Path,
    mode: UnderstandMode,
    provider: LLMProvider | None,
    subset: Mapping[str, PageSelection],
) -> FormResult:
    label = load_label_file(label_path)
    reference = load_reference(reference_path)
    if reference.label_file_sha256 != hashlib.sha256(label_path.read_bytes()).hexdigest():
        raise EvalError(f"{reference_path.name}: written for another version of the label file")
    data = pdf.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    if label.pdf_sha256 != sha256:
        raise EvalError(f"{label_path.name}: labels were made for a different PDF than {pdf.name}")
    with pymupdf.open("pdf", data) as doc:
        detection = detect(doc)
        document_id = uuid.uuid5(uuid.NAMESPACE_URL, f"formpilot-eval:{sha256}")
        ir = flat.run(doc, detection, document_id, FIXED_TIME)
    ok = {i for i, page in enumerate(detection.pages) if page.text_layer is TextLayer.OK}
    pages = set(subset_pages(subset, pdf.stem, len(detection.pages))) & set(label.labelled_pages)
    # Only scored pages are compared; LLM batches are per page, so the rest changes nothing.
    scored = pages & ok
    ir = ir.model_copy(update={"fields": [f for f in ir.fields if f.bbox.page in scored]})
    understood = understand_form(ir, mode, provider)

    result = FormResult(
        form=label.form, from_scratch=label.prefilled_from is None, understood=understood
    )
    role_of = roles(label.fields, reference.labels)
    result.llm_trouble = [
        e.change
        for e in understood.trace
        if e.pass_name == understand.STAGE and e.field_id is None and "LLM" in e.change
    ]
    for page in sorted(scored):
        fields = [f for f in understood.fields if f.bbox.page == page]
        labels = [f for f in label.fields if f.page == page]
        predicted = [Box(f.bbox, _predicted_kind(f.kind, f.max_chars)) for f in fields]
        truth = [
            Box(
                BBox(page=page, x0=f.bbox[0], y0=f.bbox[1], x1=f.bbox[2], y1=f.bbox[3]),
                _labelled_kind(f.kind, f.comb),
            )
            for f in labels
        ]
        matched = {t: p for p, t, _ in match(predicted, truth, writing_spot)}
        for t, label_field in enumerate(labels):
            ref = reference.labels.get(label_field.id)
            if ref is None:
                continue  # checkboxes and fields outside the reference scope
            if t not in matched:
                result.not_detected += 1
                continue
            got = fields[matched[t]]
            result.compared.append(
                Compared(
                    label.form,
                    label_field.id,
                    ref,
                    got.semantic_type,
                    got.semantic_method,
                    got.no_fill_reason,
                    got.id,
                    got.semantic_confidence,
                    role_of.get(label_field.id, NO_ROLE),
                )
            )
    return result


@dataclass
class EvalResult:
    split: str
    mode: str
    detector: str
    provider: str
    created_at: str
    forms: list[FormResult]
    tag: str | None = None

    def compared(self, from_scratch: bool | None = None) -> list[Compared]:
        return [
            c
            for f in self.forms
            if from_scratch is None or f.from_scratch == from_scratch
            for c in f.compared
        ]


def evaluate(
    dataset: Path,
    labels: Path,
    references: Path,
    split: str,
    mode: UnderstandMode,
    provider: LLMProvider | None,
    subset: Mapping[str, PageSelection],
    detector: str,
) -> EvalResult:
    counting = _Counting(provider) if provider is not None else None
    forms = []
    for reference_path in sorted(references.glob("*.json")):
        pdf = dataset / f"{reference_path.stem}.pdf"
        label_path = labels / f"{reference_path.stem}.json"
        if not pdf.exists() or not label_path.exists():
            raise EvalError(f"{reference_path.name}: no PDF or no label file")
        forms.append(evaluate_form(pdf, label_path, reference_path, mode, counting, subset))
    replaying = isinstance(provider, CachedProvider) and provider.mode == "replay"
    if counting is not None and counting.errors and replaying:
        raise EvalError(f"replay: {counting.errors} model requests are not in the cache")
    name = "none" if provider is None else f"{provider.name}:{provider.model}"
    created = datetime.now(UTC).isoformat(timespec="seconds")
    return EvalResult(split, mode, detector, name, created, forms)


# --- metrics ------------------------------------------------------------------------------------


def _accuracy(items: list[Compared]) -> dict[str, float | int | None]:
    correct = sum(c.correct for c in items)
    return {
        "correct": correct,
        "total": len(items),
        "accuracy": correct / len(items) if items else None,
    }


def metrics(result: EvalResult) -> dict[str, object]:
    def block(items: list[Compared]) -> dict[str, object]:
        fillable = [c for c in items if c.reference not in NOT_FILLABLE]
        # Of the fields given a fillable type, how many got the right one: a wrong fillable type
        # puts a profile value in the wrong place (M2 fills only these).
        predicted_fillable = [c for c in items if c.predicted not in NOT_FILLABLE]
        return {
            "all": _accuracy(items),
            "fillable": _accuracy(fillable),
            "fillable_precision": _accuracy(predicted_fillable),
        }

    every = result.compared()
    per_form = {f.form: block(f.compared) for f in result.forms}
    form_values = [
        v["fillable"]["accuracy"]  # type: ignore[index]
        for v in per_form.values()
        if v["fillable"]["accuracy"] is not None  # type: ignore[index]
    ]
    by_type = {}
    for semantic_type in sorted({c.reference for c in every}, key=lambda t: t.value):
        support = [c for c in every if c.reference is semantic_type]
        predicted = [c for c in every if c.predicted is semantic_type]
        by_type[semantic_type.value] = {
            "support": len(support),
            "recall": sum(c.correct for c in support) / len(support),
            "predicted": len(predicted),
            "precision": sum(c.correct for c in predicted) / len(predicted) if predicted else None,
        }
    by_method = {m: _accuracy([c for c in every if c.method == m]) for m in ("rule", "llm", "none")}
    confusions = Counter(
        (c.reference.value, c.predicted.value) for c in every if not c.correct
    ).most_common(15)
    return {
        "overall": block(every),
        "from_scratch": block(result.compared(from_scratch=True)),
        "prefilled": block(result.compared(from_scratch=False)),
        "macro_fillable": sum(form_values) / len(form_values) if form_values else None,
        "by_method": by_method,
        "by_type": by_type,
        "per_form": per_form,
        "confusions": [{"reference": r, "predicted": p, "count": n} for (r, p), n in confusions],
        "predicted_unknown": sum(c.predicted is SemanticType.UNKNOWN for c in every),
        "never_fill": dict(Counter(c.no_fill_reason for c in every if c.no_fill_reason)),
        "not_detected": sum(f.not_detected for f in result.forms),
        "llm_trouble": {f.form: f.llm_trouble for f in result.forms if f.llm_trouble},
    }


def report_json(result: EvalResult) -> dict[str, object]:
    return {
        "kind": "understanding",
        "split": result.split,
        "mode": result.mode,
        "detector": result.detector,
        "provider": result.provider,
        "prompt": understand.PROMPT_FILE.name,
        "created_at": result.created_at,
        "tag": result.tag,
        "reference_labels": DISCLOSURE,
        "metrics": metrics(result),
    }


def _pct(value: object) -> str:
    return "—" if value is None else f"{100 * float(value):.1f} %"  # type: ignore[arg-type]


def _acc(block: Mapping[str, object]) -> str:
    return f"{_pct(block['accuracy'])} ({block['correct']}/{block['total']})"


def report_markdown(result: EvalResult) -> str:
    m = metrics(result)
    overall, scratch, pre = m["overall"], m["from_scratch"], m["prefilled"]  # type: ignore[assignment]
    lines = [
        f"# Understanding eval — {result.split}, mode {result.mode}",
        "",
        f"> **{DISCLOSURE}**",
        "",
        f"- Detector `{result.detector}`; provider `{result.provider}`; prompt "
        f"`{understand.PROMPT_FILE.name}`; created {result.created_at}"
        + (f"; tag `{result.tag}`" if result.tag else ""),
        "- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule)"
        " that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.",
        "",
        "| Scope | Accuracy, all | Accuracy, fillable |",
        "|---|---|---|",
    ]
    for name, block in (("All forms", overall), ("From scratch", scratch), ("Pre-filled", pre)):
        lines.append(f"| {name} | {_acc(block['all'])} | {_acc(block['fillable'])} |")  # type: ignore[index]
    lines += [
        "",
        f"Precision of predicted fillable types: {_acc(overall['fillable_precision'])}.",  # type: ignore[index]
        "",
        f"Macro over forms (fillable): {_pct(m['macro_fillable'])}. Predicted `unknown`: "
        f"{m['predicted_unknown']}. Reference fields not found by the detector: "
        f"{m['not_detected']}.",
        "",
        "## By method",
        "",
        "| Method | Accuracy |",
        "|---|---|",
    ]
    lines += [f"| {k} | {_acc(v)} |" for k, v in m["by_method"].items()]  # type: ignore[union-attr]
    lines += ["", "## Per form", "", "| Form | All | Fillable |", "|---|---|---|"]
    for form, block in m["per_form"].items():  # type: ignore[union-attr]
        lines.append(f"| {form} | {_acc(block['all'])} | {_acc(block['fillable'])} |")
    lines += [
        "",
        "## Per reference type",
        "",
        "| Type | Support | Recall | Predicted | Precision |",
        "|---|--:|--:|--:|--:|",
    ]
    for t, s in m["by_type"].items():  # type: ignore[union-attr]
        lines.append(
            f"| `{t}` | {s['support']} | {_pct(s['recall'])} | {s['predicted']} "
            f"| {_pct(s['precision'])} |"
        )
    lines += [
        "",
        "## Most frequent confusions",
        "",
        "| Reference | Predicted | Count |",
        "|---|---|--:|",
    ]
    lines += [
        f"| `{c['reference']}` | `{c['predicted']}` | {c['count']} |"
        for c in m["confusions"]  # type: ignore[union-attr]
    ]
    lines += ["", f"Never-fill marks on compared fields: {m['never_fill'] or 'none'}."]
    if m["llm_trouble"]:
        lines += ["", "LLM batches that failed or needed a retry:"]
        lines += [f"- {form}: {', '.join(t)}" for form, t in m["llm_trouble"].items()]  # type: ignore[union-attr]
    return "\n".join(lines) + "\n"


def write_reports(result: EvalResult, out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    stamp = result.created_at[:10].replace("-", "")
    commit = result.detector.removeprefix("flat@")
    tag = f"-{result.tag}" if result.tag else ""
    base = out / f"phase3-understanding-{result.split}-{result.mode}{tag}-{stamp}-{commit}"
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report_json(result), indent=2) + "\n", encoding="utf-8")
    md_path.write_text(report_markdown(result), encoding="utf-8")
    return json_path, md_path


def write_baseline(result: EvalResult, report: Path, path: Path) -> None:
    m = metrics(result)
    path.write_text(
        json.dumps(
            {
                "understanding": {
                    "mode": result.mode,
                    "report": report.name,
                    "accuracy": m["overall"]["all"]["accuracy"],  # type: ignore[index]
                    "accuracy_fillable": m["overall"]["fillable"]["accuracy"],  # type: ignore[index]
                    "reference_labels": "Claude-written (P3-D6)",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _provider(name: str, model: str, cache: CacheMode, base_url: str) -> LLMProvider | None:
    if name == "none":
        return None
    inner: LLMProvider
    if name == "groq":
        # GROQ_API_KEY from the environment or .env; a replay sends nothing and needs no key.
        inner = GroqProvider(GroqSettings().groq_api_key, model)
    else:
        inner = OllamaProvider(base_url, model, timeout_seconds=600)
    return inner if cache == "off" else CachedProvider(inner, CACHE_DIR, cache)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Understanding eval (Phase 3).")
    parser.add_argument("--split", choices=["dev"], default="dev")
    parser.add_argument("--mode", choices=["rules", "llm", "hybrid"], default="hybrid")
    parser.add_argument("--provider", choices=["ollama", "groq", "none"], default="ollama")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--cache", choices=["record", "replay", "off"], default="replay")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)

    provider = (
        None
        if args.mode == "rules"
        else _provider(args.provider, args.model, args.cache, args.ollama_url)
    )
    try:
        result = evaluate(
            DATASET_DIR / args.split,
            LABELS_DIR,
            REFERENCE_DIR,
            args.split,
            args.mode,
            provider,
            DEV_SUBSET,
            detector_version(),
        )
    except EvalError as exc:
        print(f"eval refused: {exc}")  # noqa: T201 - CLI output
        return 1
    result.tag = args.tag
    json_path, md_path = write_reports(result, REPORTS_DIR)
    if args.write_baseline:
        write_baseline(result, json_path, BASELINE)
    m = metrics(result)
    print(  # noqa: T201 - CLI output
        f"{args.mode}: accuracy {_acc(m['overall']['all'])}, fillable "  # type: ignore[index]
        f"{_acc(m['overall']['fillable'])}\n{json_path}\n{md_path}"  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
