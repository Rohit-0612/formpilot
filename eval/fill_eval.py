"""Fill eval (SPEC §10, PLAN Phase 4): how precisely the fill policy fills dev forms from a profile.

    make eval-fill PROVIDER=groq MODEL=openai/gpt-oss-120b   # replays the recorded answers

For every dev form, the understanding eval's matched fields (eval/run_eval.py, replayed from
eval/llm_cache/understand/) go through the match pass with each synthetic persona's profile and
each candidate fill policy. Per policy and persona:
- fill precision (the key metric, decision P4-D2): of the compared fields the policy fills, the
  share whose predicted semantic type is the reference type;
- fill coverage: those correct fills / the compared fields with a fillable reference type;
- value correctness: of the filled fields, the share whose value is the value the reference type
  would get from the same persona (formatting and derived values included);
- value precision (Phase 5): of the filled fields, the share whose value as printed is right for
  the persona, where the reference layout says what is right: no profile value in a repeated row
  (a table row), the day, month or year in a part of a split date (eval/value_truth.py).

The policy is chosen on the full persona by a rule fixed before the run (decision P4-D2,
docs/decisions/phase-4.md): the highest coverage among candidates with fill precision >= 85 %;
if none reaches it, the highest fill precision among candidates with coverage >= 20 %, and the
report says the target was missed. Reference labels are Claude-written (P3-D6); the personas are
Claude-drafted and not checked by a human (P4-D3).
"""

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.ir.models import Field, FieldStatus, ValueSource
from app.ir.semantic_types import SemanticType
from app.logging import configure_logging
from app.passes import fit, match
from app.passes.context import PassContext
from app.passes.match import PERSON_AND_DATE_TYPES, FillPolicy
from app.passes.questions import plan
from eval import run_eval
from eval.labelling.schema import DATASET_DIR, LABELS_DIR, REFERENCE_DIR, REPO_ROOT
from eval.labelling.subset import DEV_SUBSET
from eval.labelling.tasks import detector_version
from eval.value_truth import part_right, same_text

PERSONAS_DIR = REPO_ROOT / "eval" / "personas"
FULL_PERSONA = "asha_verma"
TARGET_PRECISION = 0.85
MIN_COVERAGE = 0.20
PERSONA_NOTE = "Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3)."

_ONCE = PERSON_AND_DATE_TYPES
CANDIDATES: dict[str, FillPolicy] = {
    "every predicted type (no policy)": FillPolicy(min_llm_confidence=0.0),
    "LLM confidence >= 0.90": FillPolicy(min_llm_confidence=0.90),
    "LLM confidence >= 0.95": FillPolicy(min_llm_confidence=0.95),
    "LLM confidence >= 0.99": FillPolicy(min_llm_confidence=0.99),
    "rules only": FillPolicy(min_llm_confidence=None),
    "LLM confidence >= 0.90, once per form": FillPolicy(0.90, _ONCE),
    "LLM confidence >= 0.95, once per form": FillPolicy(0.95, _ONCE),
    "LLM confidence >= 0.99, once per form": FillPolicy(0.99, _ONCE),
    "rules only, once per form": FillPolicy(None, _ONCE),
}
_FILLED_SOURCES = frozenset({ValueSource.PROFILE, ValueSource.DERIVED})


@dataclass(frozen=True)
class FillScore:
    filled: int
    type_correct: int
    value_correct: int
    fillable: int
    value_right: int = 0

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "filled": self.filled,
            "type_correct": self.type_correct,
            "value_correct": self.value_correct,
            "fillable_reference": self.fillable,
            "fill_precision": self.type_correct / self.filled if self.filled else None,
            "coverage": self.type_correct / self.fillable if self.fillable else None,
            "value_correctness": self.value_correct / self.filled if self.filled else None,
            "value_right": self.value_right,
            "value_precision": self.value_right / self.filled if self.filled else None,
        }


def load_personas(directory: Path = PERSONAS_DIR) -> dict[str, dict[str, str]]:
    return {
        path.stem: json.loads(path.read_text())["profile"]
        for path in sorted(directory.glob("*.json"))
    }


def value_right(c: run_eval.Compared, got: Field, profile: Mapping[str, str], today: date) -> bool:
    """The filled value, as printed, is right for the persona (eval/value_truth.py)."""
    printed = fit.printed(got)
    if printed is None or c.role.repeated:
        return False
    if c.role.part is not None:
        born = today if c.reference is SemanticType.DATE_OF_FILLING else None
        if born is None:
            try:
                born = date.fromisoformat(profile.get("date_of_birth", ""))
            except ValueError:
                return False
        return part_right(printed, born, c.role.part)
    as_reference = got.model_copy(update={"semantic_type": c.reference})
    expected = match.resolve(as_reference, profile, today)
    return expected is not None and same_text(printed, expected[0])


def score(result: run_eval.EvalResult, profile: Mapping[str, str], policy: FillPolicy) -> FillScore:
    ctx = PassContext(clock=lambda: run_eval.FIXED_TIME, profile=profile)
    today = ctx.today()
    filled = type_correct = value_correct = fillable = right = 0
    for form in result.forms:
        if form.understood is None:
            continue
        by_id = {f.id: f for f in match.run(form.understood, ctx, policy).fields}
        for c in form.compared:
            fillable += c.reference not in run_eval.NOT_FILLABLE
            got = by_id[c.predicted_id]
            if got.value is None or got.value_source not in _FILLED_SOURCES:
                continue
            filled += 1
            type_correct += c.correct
            as_reference = got.model_copy(update={"semantic_type": c.reference})
            expected = match.resolve(as_reference, profile, today)
            value_correct += expected is not None and expected[0] == got.value
            right += value_right(c, got, profile, today)
    return FillScore(filled, type_correct, value_correct, fillable, right)


def questions_per_form(
    result: run_eval.EvalResult, profile: Mapping[str, str], policy: FillPolicy
) -> dict[str, dict[str, int]]:
    """Per form (scored pages): fields needing input after filling, and the questions asked."""
    ctx = PassContext(clock=lambda: run_eval.FIXED_TIME, profile=profile)
    out = {}
    for form in result.forms:
        if form.understood is None:
            continue
        filled = match.run(form.understood, ctx, policy)
        out[form.form] = {
            "fields_needing_input": sum(f.status is FieldStatus.NEEDS_INPUT for f in filled.fields),
            "questions": len(plan(filled, policy)),
        }
    return out


def choose(scores: Mapping[str, FillScore]) -> tuple[str, bool]:
    """The chosen candidate and whether it meets the precision target (rule in the docstring)."""

    def precision(s: FillScore) -> float:
        return s.type_correct / s.filled if s.filled else 0.0

    def coverage(s: FillScore) -> float:
        return s.type_correct / s.fillable if s.fillable else 0.0

    meeting = [n for n, s in scores.items() if precision(s) >= TARGET_PRECISION]
    if meeting:
        return max(meeting, key=lambda n: (coverage(scores[n]), precision(scores[n]))), True
    wide = [n for n, s in scores.items() if coverage(s) >= MIN_COVERAGE]
    pool = wide or list(scores)
    return max(pool, key=lambda n: (precision(scores[n]), coverage(scores[n]))), False


def _pct(value: object) -> str:
    return "—" if value is None else f"{100 * float(value):.1f} %"  # type: ignore[arg-type]


def report(
    result: run_eval.EvalResult,
    table: Mapping[str, Mapping[str, FillScore]],
    chosen: str,
    met: bool,
    tag: str | None,
    questions: Mapping[str, Mapping[str, Mapping[str, int]]] | None = None,
) -> dict[str, object]:
    return {
        "kind": "fill",
        "split": result.split,
        "provider": result.provider,
        "detector": result.detector,
        "created_at": result.created_at,
        "tag": tag,
        "reference_labels": run_eval.DISCLOSURE,
        "personas": PERSONA_NOTE,
        "rule": {
            "target_precision": TARGET_PRECISION,
            "min_coverage": MIN_COVERAGE,
            "chosen_on": FULL_PERSONA,
        },
        "chosen": chosen,
        "target_met": met,
        "candidates": {
            name: {persona: s.as_dict() for persona, s in by_persona.items()}
            for name, by_persona in table.items()
        },
        "questions_per_form": questions or {},
    }


def markdown(data: Mapping[str, object]) -> str:
    candidates: Mapping[str, Mapping[str, Mapping[str, object]]] = data["candidates"]  # type: ignore[assignment]
    personas = list(next(iter(candidates.values())))
    verdict = (
        f"target of {_pct(TARGET_PRECISION)} fill precision **met**"
        if data["target_met"]
        else f"**target of {_pct(TARGET_PRECISION)} fill precision missed**: chosen as the most "
        f"precise candidate with coverage of at least {_pct(MIN_COVERAGE)}"
    )
    lines = [
        f"# Fill eval — {data['split']}, provider `{data['provider']}`",
        "",
        f"> **{run_eval.DISCLOSURE}** {PERSONA_NOTE}",
        "",
        f"- Detector `{data['detector']}`; created {data['created_at']}"
        + (f"; tag `{data['tag']}`" if data["tag"] else ""),
        "- *Fill precision*: of the compared fields the policy fills, the share with the right "
        "semantic type. *Coverage*: right fills / compared fields with a fillable reference "
        "type. *Value correctness*: filled values equal to the value the reference type gets. "
        "*Value precision*: filled values right for the persona as printed, where a repeated "
        "row (a table row) has no right profile value and a split date wants its day, month or "
        "year (eval/value_truth.py).",
        f"- **Chosen policy: {data['chosen']}** ({verdict}; chosen on `{FULL_PERSONA}`).",
        "",
        f"## Full persona (`{FULL_PERSONA}`)",
        "",
        "| Policy | Filled | Fill precision | Coverage | Value correctness | Value precision |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for name, by_persona in candidates.items():
        s = by_persona[FULL_PERSONA]
        mark = " **(chosen)**" if name == data["chosen"] else ""
        lines.append(
            f"| {name}{mark} | {s['filled']} | {_pct(s['fill_precision'])} "
            f"({s['type_correct']}/{s['filled']}) | {_pct(s['coverage'])} "
            f"({s['type_correct']}/{s['fillable_reference']}) | {_pct(s['value_correctness'])} "
            f"| {_pct(s['value_precision'])} ({s['value_right']}/{s['filled']}) |"
        )
    lines += ["", "## Chosen policy, every persona", "", "| Persona | Filled | Fill precision |"]
    lines += ["|---|--:|--:|"] + [
        f"| `{p}` | {candidates[data['chosen']][p]['filled']} "  # type: ignore[index]
        f"| {_pct(candidates[data['chosen']][p]['fill_precision'])} |"  # type: ignore[index]
        for p in personas
    ]
    per_profile: Mapping[str, Mapping[str, Mapping[str, int]]] = data["questions_per_form"]  # type: ignore[assignment]
    if per_profile:
        names = list(per_profile)
        lines += [
            "",
            "## Questions per form (chosen policy, scored pages)",
            "",
            "Fields needing input after filling, and the questions that ask for them.",
            "",
            "| Form | " + " | ".join(f"`{n}`: fields / questions" for n in names) + " |",
            "|---|" + "--:|" * len(names),
        ]
        forms = list(next(iter(per_profile.values())))
        for form in [*forms, "total"]:
            cells = []
            for n in names:
                rows = per_profile[n]
                if form == "total":
                    f = sum(r["fields_needing_input"] for r in rows.values())
                    q = sum(r["questions"] for r in rows.values())
                else:
                    f, q = rows[form]["fields_needing_input"], rows[form]["questions"]
                cells.append(f"{f} / {q}")
            name = "**Total**" if form == "total" else form
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _slug(provider: str) -> str:
    return provider.replace("/", "-").replace(":", "-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fill eval (Phase 4).")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)

    provider = run_eval._provider(args.provider, args.model, "replay", "http://localhost:11434")
    try:
        result = run_eval.evaluate(
            DATASET_DIR / "dev",
            LABELS_DIR,
            REFERENCE_DIR,
            "dev",
            "hybrid",
            provider,
            DEV_SUBSET,
            detector_version(),
        )
    except run_eval.EvalError as exc:
        print(f"eval refused: {exc}")  # noqa: T201 - CLI output
        return 1
    personas = load_personas()
    table = {
        name: {persona: score(result, profile, policy) for persona, profile in personas.items()}
        for name, policy in CANDIDATES.items()
    }
    chosen, met = choose({name: by[FULL_PERSONA] for name, by in table.items()})
    profiles = {FULL_PERSONA: personas[FULL_PERSONA], "empty profile": {}}
    questions = {
        name: questions_per_form(result, profile, CANDIDATES[chosen])
        for name, profile in profiles.items()
    }
    data = report(result, table, chosen, met, args.tag, questions)
    stamp = result.created_at[:10].replace("-", "")
    tag = f"-{args.tag}" if args.tag else ""
    commit = result.detector.removeprefix("flat@")
    base = run_eval.REPORTS_DIR / f"phase4-fill-dev-{_slug(result.provider)}{tag}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    if args.write_baseline:
        baseline = json.loads(run_eval.BASELINE.read_text())
        full = table[chosen][FULL_PERSONA].as_dict()
        baseline["fill"] = {
            "provider": result.provider,
            "policy": chosen,
            "report": base.with_suffix(".json").name,
            "fill_precision": full["fill_precision"],
            "coverage": full["coverage"],
            "value_precision": full["value_precision"],
            "target_met": met,
        }
        run_eval.BASELINE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    full = table[chosen][FULL_PERSONA].as_dict()
    print(  # noqa: T201 - CLI output
        f"chosen: {chosen} (target met: {met}); fill precision {_pct(full['fill_precision'])}, "
        f"coverage {_pct(full['coverage'])}, value precision {_pct(full['value_precision'])}"
        f"\n{base.with_suffix('.md')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
