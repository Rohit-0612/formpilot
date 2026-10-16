"""Render the annotated example images used by eval/labelling/README.md.

    make label-examples     # writes eval/labelling/examples/*.png (gitignored, like the forms)

Each example crops a dev page and draws the boxes a labeller should draw (green). The boxes
were measured once from the page drawings (2026-10-16) and are fixed here, so the images do not
depend on the detector.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.logging import configure_logging, get_logger
from eval.labelling.schema import DATASET_DIR, REPO_ROOT

log = get_logger(__name__)

EXAMPLES_DIR = REPO_ROOT / "eval" / "labelling" / "examples"
GREEN = (0.1, 0.65, 0.2)

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Example:
    name: str
    form: str  # PDF stem in eval/dataset/dev/
    page: int  # 0-based
    clip: Box  # region to render, PDF points
    boxes: tuple[Box, ...]  # what the labeller draws


EXAMPLES = (
    Example(
        "line-entries",
        "25_cdlsiet_btech_admission_form",
        0,
        (25, 115, 560, 162),
        # Dot leaders: from the start to the end of the dots, from the dots up to a little
        # above the label's capital letters.
        ((302.8, 123.0, 543.7, 136.4), (307.3, 142.6, 548.4, 157.0)),
    ),
    Example(
        "rule1-hinted-cells",
        "01_sbi_account_opening_form",
        0,
        (20, 216, 580, 296),
        (
            # Each hinted name row is one comb field (grey hints are not labels).
            (72.0, 223.7, 569.5, 236.4),
            (72.0, 241.6, 569.5, 254.3),
            (72.0, 259.8, 569.5, 272.5),
            # A hinted date row follows D8: DD / MM / YYYY.
            (72.0, 278.2, 97.5, 291.0),
            (97.5, 278.2, 123.0, 291.0),
            (123.0, 278.2, 174.0, 291.0),
        ),
    ),
    Example(
        "rule2-wide-cells",
        "25_cdlsiet_btech_admission_form",
        0,
        (20, 100, 440, 128),
        # Eight wide cells, one character each (DDMMYYYY): one comb field.
        ((120.9, 106.9, 336.0, 123.0),),
    ),
    Example(
        "rule3-label-inside",
        "01_sbi_account_opening_form",
        3,
        (20, 262, 300, 325),
        # Caption printed inside the box: only the empty part above it.
        ((25.3, 267.5, 293.1, 303.6),),
    ),
)


def render(example: Example, dataset: Path, out: Path, dpi: int) -> Path:
    with pymupdf.open(dataset / f"{example.form}.pdf") as doc:
        page = doc[example.page]
        for box in example.boxes:
            rect = pymupdf.Rect(box) * page.derotation_matrix
            page.draw_rect(rect, color=GREEN, fill=GREEN, fill_opacity=0.15, width=1.2)
        target = out / f"{example.name}.png"
        page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(example.clip)).save(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR / "dev")
    parser.add_argument("--out", type=Path, default=EXAMPLES_DIR)
    parser.add_argument("--dpi", type=int, default=144)
    args = parser.parse_args(argv)
    configure_logging("INFO", json=False)
    args.out.mkdir(parents=True, exist_ok=True)
    for example in EXAMPLES:
        log.info("example_written", path=str(render(example, args.dataset, args.out, args.dpi)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
