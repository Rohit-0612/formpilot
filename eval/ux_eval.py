"""UX metric (M3 gate, human decision 2026-11-06): actions to complete one form, on dev.

    make eval-ux   # replays the recorded understanding answers (Groq by default)

Every dev form's scored pages come from the understanding eval's replayed run (eval/run_eval.py)
and go through the product's passes with the full persona: match with the product policy,
validate, fit. Then the actions a user needs to reach a filled PDF are counted:
- one per question card, answered or skipped, however many inputs it has (the inputs typed are
  counted apart);
- one per suggested value, confirmed one by one (P5-D7);
- one per value from the profile that "confirm all" does not take (a check failed or the fit
  pass flagged it): the user fixes or confirms it;
- one "confirm all", if there is anything to confirm in bulk;
- one render-and-download.
Assumptions: the user answers each card by its parts (not as one line of free text parsed by the
LLM, whose values "confirm all" would leave out), and every answer passes its checks.

After: the product as it is now (M3: suggestions at SUGGEST_MIN_CONFIDENCE, section and person
cards, confirm all). Before: recomputed from today's pipeline with the M3 features turned off: no
suggestions, the M2 question plan (`plan(..., sections=False)`: untyped fields asked one by one),
and no confirm all, so every value to print is confirmed one by one (the profile's values and
every answered field). It is not a historical M2 measurement.

Reports (JSON and Markdown) go to eval/reports/ and hold counts only. The persona is
Claude-drafted and not checked by a human (P4-D3).
"""

import argparse
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from app.ir.models import FieldStatus, FormIR
from app.logging import configure_logging
from app.passes import fit, match, validate
from app.passes.questions import CHOICES, Question, plan
from app.services.review import bulk_confirmable
from eval import fill_eval, run_eval
from eval.labelling.schema import REPO_ROOT
from eval.questions_eval import CHOSEN_FLOOR, POLICY, _ctx
from eval.render_samples import dev_result

REPORTS_DIR = REPO_ROOT / "eval" / "reports"
ACTIONS = ("cards", "suggestions", "review", "confirm_all", "render")
BEFORE_NOTE = (
    "Before: recomputed from today's pipeline with the M3 features turned off (no suggestions, "
    "the M2 question plan, no confirm all), not a historical M2 measurement."
)


def _filled(understood: FormIR, profile: Mapping[str, str], floor: float | None) -> FormIR:
    ctx = _ctx(profile, floor)
    return fit.run(validate.run(match.run(understood, ctx), ctx), ctx)


def _to_review(ir: FormIR) -> int:
    """Profile values that "confirm all" leaves to the user."""
    return sum(
        f.value is not None
        and f.no_fill_reason is None
        and f.status in (FieldStatus.FILLED, FieldStatus.NEEDS_REVIEW)
        and not bulk_confirmable(f)
        for f in ir.fields
    )


def _answered(questions: list[Question]) -> int:
    """Fields the answers fill: one tick per choice card, every field of the others."""
    return sum(1 if q.group == CHOICES else len(q.field_ids) for q in questions)


def after(understood: FormIR, profile: Mapping[str, str]) -> dict[str, int]:
    ir = _filled(understood, profile, CHOSEN_FLOOR)
    questions = plan(ir, POLICY)
    in_bulk = sum(bulk_confirmable(f) for f in ir.fields) + _answered(questions)
    counts = {
        "cards": len(questions),
        "suggestions": sum(f.status is FieldStatus.SUGGESTED for f in ir.fields),
        "review": _to_review(ir),
        "confirm_all": int(in_bulk > 0),
        "render": 1,
    }
    return counts | {
        "actions": sum(counts.values()),
        "inputs": sum(len(q.parts) for q in questions),
    }


def before(understood: FormIR, profile: Mapping[str, str]) -> dict[str, int]:
    ir = _filled(understood, profile, None)
    questions = plan(ir, POLICY, sections=False)
    one_by_one = sum(bulk_confirmable(f) for f in ir.fields) + _answered(questions)
    counts = {
        "cards": len(questions),
        "suggestions": 0,
        "review": _to_review(ir),
        "confirm_all": 0,
        "render": 1,
    }
    return counts | {
        "confirm_one_by_one": one_by_one,
        "actions": sum(counts.values()) + one_by_one,
        "inputs": sum(len(q.parts) for q in questions),
    }


def report(result: run_eval.EvalResult, tag: str | None, provider: str) -> dict[str, object]:
    profile = fill_eval.load_personas()[fill_eval.FULL_PERSONA]
    forms = {
        form.form: {
            "before": before(form.understood, profile),
            "after": after(form.understood, profile),
        }
        for form in result.forms
        if form.understood is not None
    }
    keys = ("actions", "inputs", "confirm_one_by_one", *ACTIONS)
    total = {
        side: {k: sum(f[side].get(k, 0) for f in forms.values()) for k in keys}
        for side in ("before", "after")
    }
    return {
        "kind": "ux-actions",
        "split": "dev",
        "detector": result.detector,
        "provider": provider,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tag": tag,
        "persona": fill_eval.FULL_PERSONA,
        "suggest_min_confidence": CHOSEN_FLOOR,
        "policy": fill_eval.PRODUCT_POLICY,
        "before_note": BEFORE_NOTE,
        "forms": forms,
        "total": total,
    }


def markdown(data: Mapping[str, object]) -> str:
    forms: dict[str, dict[str, dict[str, int]]] = data["forms"]  # type: ignore[assignment]
    total: dict[str, dict[str, int]] = data["total"]  # type: ignore[assignment]
    lines = [
        "# Actions to complete one form — dev",
        "",
        f"- Detector `{data['detector']}`; provider `{data['provider']}` (replay); persona "
        f'`{data["persona"]}`; policy "{data["policy"]}", suggestions from '
        f"{data['suggest_min_confidence']}; created {data['created_at']}; tag `{data['tag']}`",
        "- Actions: one per question card (answered or skipped), one per suggestion confirmed, one "
        "per profile value that confirm all leaves to the user, one confirm all, one "
        "render-and-download; before, one confirm per value to print instead of confirm all. "
        "Inputs: answer boxes typed. Cards are assumed answered by their parts, each answer "
        "passing its checks.",
        f"- **{data['before_note']}**",
        "- " + fill_eval.PERSONA_NOTE,
        "",
        "| Form | Actions before | Actions after | Cards before / after | Inputs before / after "
        "| Confirms one by one (before) | Suggestions (after) | Review | Confirm all (after) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|--:|",
    ]
    rows = [*forms.items(), ("**Total**", total)]
    for name, f in rows:
        b, a = f["before"], f["after"]
        lines.append(
            f"| {name} | {b['actions']} | {a['actions']} | {b['cards']} / {a['cards']} | "
            f"{b['inputs']} / {a['inputs']} | {b['confirm_one_by_one']} | {a['suggestions']} | "
            f"{b['review']} / {a['review']} | {a['confirm_all']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count the actions to complete each dev form.")
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
    base = args.out / f"phase5-ux-actions-dev{tag}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    total: dict[str, dict[str, int]] = data["total"]  # type: ignore[assignment]
    print(  # noqa: T201 - CLI output
        f"actions before {total['before']['actions']}, after {total['after']['actions']}"
    )
    print(base.with_suffix(".md"))  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
