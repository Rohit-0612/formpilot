"""Questions eval (Phase 5, decisions P5-D1 and P5-D6): suggested values, questions per form before
and after, and how readable the questions are, on dev.

    make eval-questions PROVIDER=groq MODEL=openai/gpt-oss-120b   # replays the recorded answers

Every dev form's scored pages come from the understanding eval's replayed run (eval/run_eval.py),
filled with the chosen fill policy (P4-D2):
- **Suggestions** (full persona), for each floor in FLOORS: how many fields get a suggested value,
  how many of those compared with a reference label have the right type and the right value,
  and the questions they remove (untyped fields asked one by one, to isolate the suggestions).
  The floor in use is SUGGEST_MIN_CONFIDENCE (0.95, P5-D1); the others are for the record only.
- **Questions per form**, before (the M2 plan: no suggestions, one question per untyped field)
  and after (M3: suggestions at the chosen floor, section cards), for the full persona and an
  empty profile: cards (questions shown) and inputs (answer boxes) counted separately.
- **Readability** (full persona, M3 plan): every main text and part label must pass
  `readable_english`; where the texts of untyped fields come from (the model's English
  question, a readable label, or the field's place); the M2 rule (quote the printed label) on
  the same fields; and a sample of the model's questions judged by Claude Code for faithfulness
  to the printed text (eval/readability/, written once and frozen, disclosed in every report).

Reference labels are Claude-written (P3-D6); the personas are Claude-drafted (P4-D3).
"""

import argparse
import json
import random
from collections.abc import Mapping
from pathlib import Path

from app.config import Settings
from app.ir.models import Field, FieldStatus, FormIR
from app.ir.phrases import readable_english
from app.logging import configure_logging
from app.passes import match
from app.passes.context import PassContext
from app.passes.questions import Question, plan
from eval import fill_eval, run_eval
from eval.labelling.schema import DATASET_DIR, LABELS_DIR, REFERENCE_DIR, REPO_ROOT
from eval.labelling.subset import DEV_SUBSET
from eval.labelling.tasks import detector_version

FLOORS = (0.70, 0.85, 0.90, 0.95)
CHOSEN_FLOOR: float = Settings.model_fields["suggest_min_confidence"].default
POLICY = match.policy_for(PassContext(clock=lambda: run_eval.FIXED_TIME))  # the chosen policy
READABILITY_DIR = REPO_ROOT / "eval" / "readability"
SAMPLE_SIZE = 60
SAMPLE_SEED = 20261027
JUDGED_NOTE = (
    "Faithfulness sample: judged by Claude Code (claude-opus-5-5) from the printed label and "
    "heading, not by a human (like P3-D6); judged once and frozen."
)


def _ctx(profile: Mapping[str, str], floor: float | None) -> PassContext:
    return PassContext(
        clock=lambda: run_eval.FIXED_TIME, profile=profile, suggest_min_confidence=floor
    )


def _forms(result: run_eval.EvalResult) -> list[tuple[run_eval.FormResult, FormIR]]:
    return [(f, f.understood) for f in result.forms if f.understood is not None]


def _printed(f: Field) -> str | None:
    return (f.label_text or f.context_text or "").strip() or None


# --- suggestions ---------------------------------------------------------------------------


def suggestions(
    result: run_eval.EvalResult, profile: Mapping[str, str], floor: float
) -> dict[str, object]:
    ctx = _ctx(profile, floor)
    today = ctx.today()
    suggested = compared = right_type = right_value = 0
    per_form: dict[str, dict[str, int]] = {}
    for form, understood in _forms(result):
        before = match.run(understood, _ctx(profile, None))
        after = match.run(understood, ctx)
        by_id = {f.id: f for f in after.fields}
        ids = {f.id for f in after.fields if f.status is FieldStatus.SUGGESTED}
        suggested += len(ids)
        for c in form.compared:
            if c.predicted_id not in ids:
                continue
            compared += 1
            right_type += c.correct
            got = by_id[c.predicted_id]
            as_reference = got.model_copy(update={"semantic_type": c.reference})
            expected = match.resolve(as_reference, profile, today)
            right_value += expected is not None and expected[0] == got.value
        per_form[form.form] = {
            "suggested": len(ids),
            "questions_before": len(plan(before, POLICY, sections=False)),
            "questions_after": len(plan(after, POLICY, sections=False)),
        }
    return {
        "floor": floor,
        "suggested": suggested,
        "compared": compared,
        "right_type": right_type,
        "right_type_rate": right_type / compared if compared else None,
        "right_value": right_value,
        "questions_before": sum(f["questions_before"] for f in per_form.values()),
        "questions_after": sum(f["questions_after"] for f in per_form.values()),
        "per_form": per_form,
    }


# --- questions per form --------------------------------------------------------------------


def _counts(questions: list[Question]) -> dict[str, int]:
    return {"cards": len(questions), "inputs": sum(len(q.parts) for q in questions)}


def questions_per_form(
    result: run_eval.EvalResult, profile: Mapping[str, str]
) -> dict[str, dict[str, dict[str, int]]]:
    out = {}
    for form, understood in _forms(result):
        m2 = match.run(understood, _ctx(profile, None))
        m3 = match.run(understood, _ctx(profile, CHOSEN_FLOOR))
        out[form.form] = {
            "m2": _counts(plan(m2, POLICY, sections=False))
            | {"fields_needing_input": sum(f.status is FieldStatus.NEEDS_INPUT for f in m2.fields)},
            "m3": _counts(plan(m3, POLICY))
            | {"fields_needing_input": sum(f.status is FieldStatus.NEEDS_INPUT for f in m3.fields)},
        }
    return out


# --- readability ---------------------------------------------------------------------------


def _m3(understood: FormIR, profile: Mapping[str, str]) -> tuple[FormIR, list[Question]]:
    filled = match.run(understood, _ctx(profile, CHOSEN_FLOOR))
    return filled, plan(filled, POLICY)


def untyped_parts(
    result: run_eval.EvalResult, profile: Mapping[str, str]
) -> list[tuple[str, Field]]:
    """(form, field) for every untyped part asked in the M3 plan, in form and reading order."""
    out = []
    for form, understood in _forms(result):
        filled, questions = _m3(understood, profile)
        fields = {f.id: f for f in filled.fields}
        for q in questions:
            out += [(form.form, fields[p.field_ids[0]]) for p in q.parts if p.semantic_type is None]
    return out


def readability(result: run_eval.EvalResult, profile: Mapping[str, str]) -> dict[str, object]:
    texts = unreadable = 0
    for _, understood in _forms(result):
        _, questions = _m3(understood, profile)
        for q in questions:
            shown = [q.prompt, *(p.label for p in q.parts)]
            texts += len(shown)
            unreadable += sum(not readable_english(t) for t in shown)
    parts = untyped_parts(result, profile)
    sources = {"model question": 0, "readable label": 0, "place (box N on page P)": 0}
    m2_unreadable = m2_unlabelled = 0
    for _, f in parts:
        printed = _printed(f)
        if f.question_text:
            sources["model question"] += 1
        elif readable_english(printed):
            sources["readable label"] += 1
        else:
            sources["place (box N on page P)"] += 1
        m2_unreadable += printed is not None and not readable_english(printed)
        m2_unlabelled += printed is None
    return {
        "texts_shown": texts,
        "texts_not_readable": unreadable,
        "untyped_parts": len(parts),
        "sources": sources,
        "m2_rule": {"quoted_unreadable": m2_unreadable, "no_label": m2_unlabelled},
    }


def _key(form: str, f: Field) -> str:
    return f"{form}/{f.id}"


def sample(result: run_eval.EvalResult, profile: Mapping[str, str]) -> list[dict[str, str]]:
    """A fixed random sample of the model's questions for untyped fields (seeded)."""
    with_question = [(form, f) for form, f in untyped_parts(result, profile) if f.question_text]
    rng = random.Random(SAMPLE_SEED)  # noqa: S311 - a reproducible sample, not a secret
    chosen = rng.sample(with_question, min(SAMPLE_SIZE, len(with_question)))
    return [
        {
            "key": _key(form, f),
            "label": f.label_text or "",
            "context": f.context_text or "",
            "question": f.question_text or "",
        }
        for form, f in sorted(chosen, key=lambda item: _key(*item))
    ]


def judged(
    current: list[dict[str, str]], directory: Path = READABILITY_DIR
) -> dict[str, object] | None:
    """The frozen judgments for the sample, if written, checked against the current questions."""
    path = directory / "judged-dev.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    items: Mapping[str, Mapping[str, object]] = data["items"]
    now = {item["key"]: item["question"] for item in current}
    stale = sorted(k for k, v in items.items() if now.get(k) != v["question"])
    faithful = sum(bool(v["faithful"]) for v in items.values())
    return {
        "judged_by": data["judged_by"],
        "judged": len(items),
        "faithful": faithful,
        "faithful_rate": faithful / len(items) if items else None,
        "stale": stale,
        "unfaithful": {k: v["note"] for k, v in items.items() if not v["faithful"]},
    }


# --- report --------------------------------------------------------------------------------


def _pct(value: object) -> str:
    return "—" if value is None else f"{100 * float(value):.1f} %"  # type: ignore[arg-type]


def markdown(data: Mapping[str, object]) -> str:
    rows: list[Mapping[str, object]] = data["suggestions"]  # type: ignore[assignment]
    lines = [
        f"# Questions eval — {data['split']}, provider `{data['provider']}`",
        "",
        f"> **{run_eval.DISCLOSURE}** {fill_eval.PERSONA_NOTE}",
        "",
        f"- Detector `{data['detector']}`; created {data['created_at']}"
        + (f"; tag `{data['tag']}`" if data["tag"] else ""),
        f"- Fill policy: the chosen one (P4-D2). Suggestion floor in use: "
        f"**{CHOSEN_FLOOR}** (P5-D1); the other floors are for the record only.",
        "",
        f"## Suggested values (full persona `{fill_eval.FULL_PERSONA}`)",
        "",
        "*Right type*: of the suggested fields compared with a reference label, the share whose "
        "reference type is the predicted type. *Questions*: untyped fields asked one by one, "
        "without and with the suggestions.",
        "",
        "| Floor | Suggested | Compared | Right type | Right value | Questions before → after |",
        "|---|--:|--:|--:|--:|--:|",
    ]
    for r in rows:
        mark = " **(in use)**" if r["floor"] == CHOSEN_FLOOR else ""
        lines.append(
            f"| ≥ {r['floor']}{mark} | {r['suggested']} | {r['compared']} | "
            f"{_pct(r['right_type_rate'])} ({r['right_type']}/{r['compared']}) | "
            f"{r['right_value']} | {r['questions_before']} → {r['questions_after']} |"
        )
    chosen = next(r for r in rows if r["floor"] == CHOSEN_FLOOR)
    per_form: Mapping[str, Mapping[str, int]] = chosen["per_form"]  # type: ignore[assignment]
    lines += ["", f"Questions removed per form at ≥ {CHOSEN_FLOOR}:", ""]
    lines += ["| Form | Suggested | Questions before → after |", "|---|--:|--:|"]
    lines += [
        f"| {form} | {r['suggested']} | {r['questions_before']} → {r['questions_after']} |"
        for form, r in per_form.items()
    ]

    per_profile: Mapping[str, Mapping[str, Mapping[str, Mapping[str, int]]]] = data[
        "questions_per_form"
    ]  # type: ignore[assignment]
    lines += [
        "",
        "## Questions per form, before (M2) and after (M3)",
        "",
        "M2: no suggestions, one question per untyped field. M3: suggestions at the floor in use, "
        "untyped fields under one heading in one card. *Cards*: questions shown; *inputs*: "
        "answer boxes.",
        "",
    ]
    for name, forms in per_profile.items():
        lines += [
            f"### `{name}`",
            "",
            "| Form | Fields needing input M2 → M3 | Cards M2 → M3 | Inputs M2 → M3 |",
            "|---|--:|--:|--:|",
        ]
        total = {s: {"cards": 0, "inputs": 0, "fields_needing_input": 0} for s in ("m2", "m3")}
        for form, r in forms.items():
            for stage in ("m2", "m3"):
                for k in total[stage]:
                    total[stage][k] += r[stage][k]
            lines.append(_qrow(form, r))
        lines += [_qrow("**Total**", total), ""]

    read: Mapping[str, object] = data["readability"]  # type: ignore[assignment]
    sources: Mapping[str, int] = read["sources"]  # type: ignore[assignment]
    m2: Mapping[str, int] = read["m2_rule"]  # type: ignore[assignment]
    lines += [
        "## Readability (full persona, M3 plan)",
        "",
        f"- Texts shown (main texts and part labels): {read['texts_shown']}; **not readable "
        f"English: {read['texts_not_readable']}** (`readable_english`: no Hindi, no other "
        "script, no replacement characters; scrambled English word order is not detected).",
        f"- Untyped fields asked: {read['untyped_parts']}. Their text comes from: "
        + "; ".join(f"{k} {v}" for k, v in sources.items())
        + ".",
        f"- The M2 rule (quote the printed label) on the same fields: "
        f"{m2['quoted_unreadable']} would quote text that is not readable English, "
        f"{m2['no_label']} have no printed label.",
    ]
    judgments: Mapping[str, object] | None = data["faithfulness"]  # type: ignore[assignment]
    if judgments is None:
        lines += ["- Faithfulness sample: not judged yet."]
    else:
        lines += [
            f"- {JUDGED_NOTE} Faithful: **{judgments['faithful']} of {judgments['judged']}** "
            f"({_pct(judgments['faithful_rate'])})"
            + (
                f"; {len(judgments['stale'])} judged questions changed since"
                if judgments["stale"]
                else ""
            )  # type: ignore[arg-type]
            + ".",
        ]
        unfaithful: Mapping[str, str] = judgments["unfaithful"]  # type: ignore[assignment]
        lines += [f"  - `{k}`: {note}" for k, note in unfaithful.items()]
    return "\n".join(lines) + "\n"


def _qrow(form: str, r: Mapping[str, Mapping[str, int]]) -> str:
    m2, m3 = r["m2"], r["m3"]
    return (
        f"| {form} | {m2['fields_needing_input']} → {m3['fields_needing_input']} | "
        f"{m2['cards']} → {m3['cards']} | {m2['inputs']} → {m3['inputs']} |"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Questions eval (Phase 5).")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--tag", default=None)
    parser.add_argument(
        "--write-sample", action="store_true", help="write the faithfulness sample (once)"
    )
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)

    provider = run_eval._provider(args.provider, args.model, "replay", "http://localhost:11434")
    try:
        result = run_eval.evaluate(
            DATASET_DIR / "dev", LABELS_DIR, REFERENCE_DIR, "dev", "hybrid", provider,
            DEV_SUBSET, detector_version(),
        )  # fmt: skip
    except run_eval.EvalError as exc:
        print(f"eval refused: {exc}")  # noqa: T201 - CLI output
        return 1
    personas = fill_eval.load_personas()
    full = personas[fill_eval.FULL_PERSONA]
    current = sample(result, full)
    sample_path = READABILITY_DIR / "sample-dev.json"
    if args.write_sample:
        if sample_path.exists():
            print(f"refused: {sample_path} exists (the sample is frozen)")  # noqa: T201
            return 1
        READABILITY_DIR.mkdir(parents=True, exist_ok=True)
        sample_path.write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n")
    data = {
        "kind": "questions",
        "split": result.split,
        "provider": result.provider,
        "detector": result.detector,
        "created_at": result.created_at,
        "tag": args.tag,
        "reference_labels": run_eval.DISCLOSURE,
        "personas": fill_eval.PERSONA_NOTE,
        "suggest_floor": CHOSEN_FLOOR,
        "suggestions": [suggestions(result, full, floor) for floor in FLOORS],
        "questions_per_form": {
            fill_eval.FULL_PERSONA: questions_per_form(result, full),
            "empty profile": questions_per_form(result, {}),
        },
        "readability": readability(result, full),
        "faithfulness": judged(current),
    }
    stamp = result.created_at[:10].replace("-", "")
    tag = f"-{args.tag}" if args.tag else ""
    commit = result.detector.removeprefix("flat@")
    slug = fill_eval._slug(result.provider)
    base = run_eval.REPORTS_DIR / f"phase5-questions-dev-{slug}{tag}-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    print(base.with_suffix(".md"))  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
