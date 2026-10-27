"""Validator eval (SPEC §10, PLAN Phase 4): catch rate and false-reject rate.

    make eval-validators

- Catch rate: of the synthetic wrong values in eval/invalid_inputs.json, the share a validator
  rejects, typed into a field of their semantic type (a form asking DD/MM/YYYY for dates).
- False-reject rate: of the persona values (eval/personas/), formatted for such a field by the
  match pass as FormPilot would fill them, the share a validator rejects (the target is zero).

No model is involved. The invalid inputs and the personas are synthetic and written by Claude
Code (P4-D3); the misses are listed so the limits of format checks stay visible.
"""

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from app.ir.models import BBox, Field, FieldKind
from app.ir.semantic_types import SEMANTIC_TYPES, SemanticType
from app.logging import configure_logging
from app.passes.match import resolve
from app.validators import validate_field, validator_names
from eval.fill_eval import load_personas
from eval.labelling.schema import REPO_ROOT
from eval.labelling.tasks import detector_version
from eval.run_eval import REPORTS_DIR

INVALID_INPUTS = REPO_ROOT / "eval" / "invalid_inputs.json"
TODAY = date(2026, 10, 27)  # fixed, so the "in the future" vectors stay in the future


def _field(semantic_type: SemanticType) -> Field:
    return Field(
        id="p0_f000",
        kind=FieldKind.TEXT,
        native_name=None,
        label_text="Date (DD/MM/YYYY)" if semantic_type is SemanticType.DATE_OF_BIRTH else None,
        context_text=None,
        bbox=BBox(page=0, x0=0, y0=0, x1=300, y1=14),
        semantic_type=semantic_type,
    )


def rejected(semantic_type: SemanticType, value: str) -> list[str]:
    field = _field(semantic_type).model_copy(update={"value": value})
    return [r.validator for r in validate_field(field, TODAY) if not r.ok]


def evaluate(inputs_path: Path, personas_dir: Path) -> dict[str, object]:
    inputs = json.loads(inputs_path.read_text())["inputs"]
    caught, missed = [], []
    for item in inputs:
        failed = rejected(SemanticType(item["semantic_type"]), item["value"])
        (caught if failed else missed).append({**item, "rejected_by": failed})
    false_rejects, checked = [], 0
    for persona, profile in load_personas(personas_dir).items():
        for t, info in SEMANTIC_TYPES.items():
            key = info.profile_key
            if key is None or key not in profile or not validator_names(_field(t)):
                continue
            value = resolve(_field(t), profile, TODAY)
            if value is None:
                continue
            checked += 1
            failed = rejected(t, value[0])
            if failed:
                false_rejects.append(
                    {"persona": persona, "semantic_type": t.value, "rejected_by": failed}
                )
    return {
        "kind": "validators",
        "detector": detector_version(),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "invalid_inputs": len(inputs),
        "caught": len(caught),
        "catch_rate": len(caught) / len(inputs),
        "missed": [{k: m[k] for k in ("semantic_type", "why")} for m in missed],
        "persona_values_checked": checked,
        "false_rejects": false_rejects,
        "false_reject_rate": len(false_rejects) / checked if checked else None,
    }


def markdown(data: dict[str, object]) -> str:
    lines = [
        "# Validator eval",
        "",
        "> Invalid inputs and personas are synthetic, written by Claude Code (P4-D3). No model.",
        "",
        f"- Detector `{data['detector']}`; created {data['created_at']}",
        f"- **Catch rate: {100 * data['catch_rate']:.1f} % ({data['caught']}/"  # type: ignore[operator]
        f"{data['invalid_inputs']})** of the wrong values in `eval/invalid_inputs.json`.",
        f"- **False-reject rate: {100 * (data['false_reject_rate'] or 0):.1f} % "
        f"({len(data['false_rejects'])}/{data['persona_values_checked']})** of the persona "  # type: ignore[arg-type]
        "values that have a validator, formatted as FormPilot fills them.",
        "",
        "## Not caught (limits of format checks)",
        "",
        "| Type | Why it is wrong |",
        "|---|---|",
    ]
    lines += [f"| `{m['semantic_type']}` | {m['why']} |" for m in data["missed"]]  # type: ignore[attr-defined]
    if data["false_rejects"]:
        lines += ["", "## False rejects", ""]
        lines += [
            f"- `{r['persona']}` `{r['semantic_type']}`: {', '.join(r['rejected_by'])}"
            for r in data["false_rejects"]  # type: ignore[attr-defined]
        ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="Validator eval (Phase 4).").parse_args(argv)
    configure_logging("WARNING", json=False)
    data = evaluate(INVALID_INPUTS, REPO_ROOT / "eval" / "personas")
    stamp = str(data["created_at"])[:10].replace("-", "")
    commit = str(data["detector"]).removeprefix("flat@")
    base = REPORTS_DIR / f"phase4-validators-{stamp}-{commit}"
    base.with_suffix(".json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    print(  # noqa: T201 - CLI output
        f"catch rate {100 * data['catch_rate']:.1f} %, false rejects "  # type: ignore[operator]
        f"{len(data['false_rejects'])}/{data['persona_values_checked']}\n{base.with_suffix('.md')}"  # type: ignore[arg-type]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
