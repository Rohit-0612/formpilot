"""Rendered dev forms for the Phase 5 acceptance check (decision P5-D2): the human opens them in
a normal PDF reader and checks that the values are right and in place.

    make render-samples   # replays the recorded understanding answers (Groq by default)

For every dev form of the subset: detection, understanding (replayed), match with the full
persona under the product's fill policy, validate, fit, "confirm all" (P5-D7), overlay render.
The PDFs go to eval/renders/ (git-ignored, like every dev PDF); a list of what was printed per
form (field ids and counts, never values) is printed.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.backends import overlay
from app.ir.models import FormIR
from app.logging import configure_logging
from app.passes import fit, match, validate
from app.passes.context import PassContext
from app.services.review import confirm_all
from eval import fill_eval, run_eval
from eval.labelling.schema import DATASET_DIR, LABELS_DIR, REFERENCE_DIR, REPO_ROOT
from eval.labelling.subset import DEV_SUBSET
from eval.labelling.tasks import detector_version

OUT_DIR = REPO_ROOT / "eval" / "renders"


@dataclass(frozen=True)
class RenderedForm:
    form: str
    original: bytes
    ir: FormIR  # after match, validate, fit and "confirm all"
    rendered: overlay.Rendered


def render_dev_forms(provider_name: str, model: str) -> list[RenderedForm]:
    """The dev forms of the subset through the product's passes, rendered (replay only)."""
    provider = run_eval._provider(provider_name, model, "replay", "http://localhost:11434")
    result = run_eval.evaluate(
        DATASET_DIR / "dev", LABELS_DIR, REFERENCE_DIR, "dev", "hybrid", provider,
        DEV_SUBSET, detector_version(),
    )  # fmt: skip
    profile = fill_eval.load_personas()[fill_eval.FULL_PERSONA]
    ctx = PassContext(clock=lambda: run_eval.FIXED_TIME, profile=profile)
    forms: list[RenderedForm] = []
    for form in result.forms:
        if form.understood is None:
            continue
        ir = fit.run(validate.run(match.run(form.understood, ctx), ctx), ctx)
        ir, _ = confirm_all(ir, ctx)
        original = (DATASET_DIR / "dev" / f"{form.form}.pdf").read_bytes()
        forms.append(RenderedForm(form.form, original, ir, overlay.render(original, ir)))
    return forms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the dev forms with the full persona.")
    parser.add_argument("--provider", choices=["ollama", "groq"], default="groq")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    configure_logging("WARNING", json=False)

    try:
        forms = render_dev_forms(args.provider, args.model)
    except run_eval.EvalError as exc:
        print(f"refused: {exc}")  # noqa: T201 - CLI output
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for item in forms:
        out = item.rendered
        path = args.out / f"{item.form}-filled.pdf"
        path.write_bytes(out.pdf)
        with pymupdf.open("pdf", out.pdf) as doc:
            pages = sorted({f.bbox.page + 1 for f in item.ir.fields if f.id in out.drawn})
            print(  # noqa: T201 - CLI output
                f"{item.form}: {len(out.drawn)} printed, {len(out.skipped)} not printable, "
                f"pages {pages} of {doc.page_count} -> {path.relative_to(REPO_ROOT)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
