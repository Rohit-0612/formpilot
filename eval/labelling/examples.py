"""Render the annotated example images for eval/labelling/README.md.

    make label-images       # synthetic fixtures -> eval/labelling/images/*.png (committed)
    make label-examples     # dev-form crops -> eval/labelling/examples/*.png (gitignored)

Green = a box the labeller draws; red dashed = an area that gets no box. The README uses the
synthetic images: crops of the dev forms are never committed (like the forms themselves). The
synthetic boxes are the fixtures' ground truth (backend/tests/fixtures/pdfs.py); the dev boxes
were measured once from the page drawings (2026-10-16) and are fixed here.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.logging import configure_logging, get_logger
from eval.labelling.schema import DATASET_DIR, REPO_ROOT
from tests.fixtures import pdfs

log = get_logger(__name__)

IMAGES_DIR = REPO_ROOT / "eval" / "labelling" / "images"
EXAMPLES_DIR = REPO_ROOT / "eval" / "labelling" / "examples"
GREEN = (0.1, 0.65, 0.2)
RED = (0.85, 0.1, 0.1)

Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class Example:
    name: str
    clip: Box  # region to render, PDF points
    boxes: tuple[Box, ...]  # what the labeller draws
    no_box: tuple[Box, ...] = ()  # areas that get no box


def _truth(fixture: str) -> tuple[Box, ...]:
    return tuple(field.bbox for field in pdfs.get(fixture).fields)


# (fixture, example) pairs rendered from the synthetic fixtures.
SYNTHETIC: tuple[tuple[str, Example], ...] = (
    ("flat_dot_leaders", Example("line-entries", (60, 75, 360, 190), _truth("flat_dot_leaders"))),
    ("flat_comb", Example("comb-rows", (60, 110, 400, 262), _truth("flat_comb"))),
    ("flat_multiline", Example("multi-line", (60, 100, 520, 300), _truth("flat_multiline"))),
    (
        "flat_hinted_comb",
        Example("rule1-hinted-cells", (60, 110, 520, 222), _truth("flat_hinted_comb")),
    ),
    (
        "flat_wide_cells",
        Example("rule2-wide-cells", (60, 110, 400, 184), _truth("flat_wide_cells")),
    ),
    (
        "flat_label_inside",
        Example(
            "rule3-label-inside",
            (60, 100, 530, 310),
            _truth("flat_label_inside"),
            (pdfs.PHOTO_BOX, pdfs.THUMB_BOX),
        ),
    ),
)

# (form stem, 0-based page, example) on the dev forms: local only.
DEV: tuple[tuple[str, int, Example], ...] = (
    (
        "25_cdlsiet_btech_admission_form",
        0,
        Example(
            "line-entries",
            (25, 115, 560, 162),
            ((302.8, 123.0, 543.7, 136.4), (307.3, 142.6, 548.4, 157.0)),
        ),
    ),
    (
        "01_sbi_account_opening_form",
        0,
        Example(
            "rule1-hinted-cells",
            (20, 216, 580, 296),
            (
                # One box per hinted part, split halfway through the empty cells between hints.
                (72.0, 223.7, 352.6, 236.4),
                (352.6, 223.7, 569.5, 236.4),
                (72.0, 241.6, 569.5, 254.3),
                (72.0, 259.8, 250.6, 272.5),
                (250.6, 259.8, 403.7, 272.5),
                (403.7, 259.8, 569.5, 272.5),
                # Hinted date row as D8: DD / MM / YYYY.
                (72.0, 278.2, 97.5, 291.0),
                (97.5, 278.2, 123.0, 291.0),
                (123.0, 278.2, 174.0, 291.0),
            ),
        ),
    ),
    (
        "25_cdlsiet_btech_admission_form",
        0,
        Example("rule2-wide-cells", (20, 100, 440, 128), ((120.9, 106.9, 336.0, 123.0),)),
    ),
    (
        "01_sbi_account_opening_form",
        3,
        Example("rule3-label-inside", (20, 262, 300, 325), ((25.3, 267.5, 293.1, 303.6),)),
    ),
)


def render_page(page: pymupdf.Page, example: Example, out: Path, dpi: int) -> Path:
    for box in example.boxes:
        rect = pymupdf.Rect(box) * page.derotation_matrix
        page.draw_rect(rect, color=GREEN, fill=GREEN, fill_opacity=0.15, width=1.2)
    for box in example.no_box:
        rect = pymupdf.Rect(box) * page.derotation_matrix
        page.draw_rect(rect, color=RED, width=1.2, dashes="[4 3] 0")
    target = out / f"{example.name}.png"
    page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(example.clip)).save(target)
    return target


def render_synthetic(out: Path, dpi: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for fixture, example in SYNTHETIC:
        with pymupdf.open("pdf", pdfs.get(fixture).data) as doc:
            written.append(render_page(doc[0], example, out, dpi))
    return written


def render_dev(dataset: Path, out: Path, dpi: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for form, page, example in DEV:
        with pymupdf.open(dataset / f"{form}.pdf") as doc:
            written.append(render_page(doc[page], example, out, dpi))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--synthetic", action="store_true", help="render the committed images from the fixtures"
    )
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR / "dev")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dpi", type=int, default=144)
    args = parser.parse_args(argv)
    configure_logging("INFO", json=False)
    if args.synthetic:
        written = render_synthetic(args.out or IMAGES_DIR, args.dpi)
    else:
        written = render_dev(args.dataset, args.out or EXAMPLES_DIR, args.dpi)
    for path in written:
        log.info("example_written", path=str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
