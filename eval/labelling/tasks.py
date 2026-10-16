"""Render dev pages and write Label Studio tasks (one task per page), with pre-annotations.

    make label-tasks        # = python -m eval.labelling.tasks, from the repo root

Writes, under eval/labelling/work/files/ (gitignored):
    images/<form>/page-01.png ...   pages rendered at --dpi
    tasks.json                      Label Studio tasks, in the suggested labelling order

Only pages whose text layer is OK are exported (the others need OCR, Phase 6). Forms listed in
--from-scratch get no pre-annotations (the anchoring check); every other page carries the flat
detector's boxes as Label Studio predictions, which the labeller checks and corrects.
"""

import argparse
import hashlib
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymupdf

from app.frontends import flat
from app.frontends.detect import detect
from app.ir.models import Field, FieldKind, TextLayer
from app.logging import configure_logging, get_logger
from eval.labelling.schema import DATASET_DIR, REPO_ROOT

log = get_logger(__name__)

WORK_DIR = REPO_ROOT / "eval" / "labelling" / "work"
FILES_DIR = WORK_DIR / "files"
# Inside the Label Studio container: LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=/label-studio/files,
# with FILES_DIR mounted at /label-studio/files/formpilot (see README).
LOCAL_FILES_PREFIX = "/data/local-files/?d=formpilot"

# Labelling order (README): from-scratch forms first, then the rest, the two big forms last.
FROM_SCRATCH = ("21", "41")
LAST = ("01", "03")

# RectangleLabels names, as in labeling_config.xml.
FROM_NAME, TO_NAME = "kind", "page"
LABEL_TEXT, LABEL_COMB, LABEL_CHECKBOX = "text", "comb", "checkbox"


def form_number(stem: str) -> str:
    return stem.split("_", 1)[0]


def labelling_order(stems: list[str], from_scratch: tuple[str, ...]) -> list[str]:
    def key(stem: str) -> tuple[int, str]:
        number = form_number(stem)
        group = 0 if number in from_scratch else 2 if number in LAST else 1
        return group, stem

    return sorted(stems, key=key)


def detector_version() -> str:
    """Git commit of the detector; "-dirty" if backend/app has uncommitted changes."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - git from PATH, fixed arguments
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "backend/app"],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    return f"flat@{commit}{'-dirty' if dirty else ''}"


def region_label(field: Field) -> str:
    if field.kind is FieldKind.CHECKBOX:
        return LABEL_CHECKBOX
    return LABEL_COMB if field.max_chars else LABEL_TEXT


def prediction_result(
    field: Field, page_size: tuple[float, float], image_size: tuple[int, int]
) -> dict[str, Any]:
    """One detector box as a Label Studio rectangle (percent of the page, top-left origin)."""
    width_pt, height_pt = page_size
    box = field.bbox
    return {
        "id": field.id,
        "type": "rectanglelabels",
        "from_name": FROM_NAME,
        "to_name": TO_NAME,
        "original_width": image_size[0],
        "original_height": image_size[1],
        "image_rotation": 0,
        "value": {
            "x": 100 * box.x0 / width_pt,
            "y": 100 * box.y0 / height_pt,
            "width": 100 * box.width / width_pt,
            "height": 100 * box.height / height_pt,
            "rotation": 0,
            "rectanglelabels": [region_label(field)],
        },
    }


def form_tasks(
    pdf: Path, files_dir: Path, dpi: int, prefill: bool, version: str
) -> list[dict[str, Any]]:
    data = pdf.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    tasks: list[dict[str, Any]] = []
    with pymupdf.open("pdf", data) as doc:
        detection = detect(doc)
        ir = flat.run(doc, detection, uuid.uuid4(), datetime.now(UTC)) if prefill else None
        image_dir = files_dir / "images" / pdf.stem
        image_dir.mkdir(parents=True, exist_ok=True)
        for index, (page, info) in enumerate(zip(doc, detection.pages, strict=True)):
            if info.text_layer is not TextLayer.OK:
                continue
            image_name = f"page-{index + 1:02d}.png"
            pixmap = page.get_pixmap(dpi=dpi)
            pixmap.save(image_dir / image_name)
            task: dict[str, Any] = {
                "data": {
                    "image": f"{LOCAL_FILES_PREFIX}/images/{pdf.stem}/{image_name}",
                    "form": pdf.stem,
                    "page": index,
                    "page_label": f"#{int(form_number(pdf.stem))} {pdf.stem}: page {index + 1}"
                    f" of {doc.page_count}{'' if prefill else ' (from scratch)'}",
                    "pdf_sha256": sha256,
                    "page_width_pt": info.width,
                    "page_height_pt": info.height,
                    "prefilled_from": version if prefill else None,
                }
            }
            if ir is not None:
                size = (info.width, info.height)
                results = [
                    prediction_result(f, size, (pixmap.width, pixmap.height))
                    for f in ir.fields
                    if f.bbox.page == index
                ]
                task["predictions"] = [{"model_version": version, "result": results}]
            tasks.append(task)
    return tasks


def build_tasks(
    dataset: Path, files_dir: Path, dpi: int, from_scratch: tuple[str, ...], version: str
) -> list[dict[str, Any]]:
    stems = labelling_order([p.stem for p in dataset.glob("*.pdf")], from_scratch)
    tasks: list[dict[str, Any]] = []
    for stem in stems:
        prefill = form_number(stem) not in from_scratch
        form = form_tasks(dataset / f"{stem}.pdf", files_dir, dpi, prefill, version)
        log.info("form_exported", form=stem, pages=len(form), prefilled=prefill)
        tasks += form
    return tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR / "dev")
    parser.add_argument("--out", type=Path, default=FILES_DIR)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument(
        "--from-scratch",
        nargs="*",
        default=list(FROM_SCRATCH),
        help="form numbers exported without pre-annotations (default: 21 41)",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing tasks.json")
    args = parser.parse_args(argv)
    configure_logging("INFO", json=False)

    tasks_file = args.out / "tasks.json"
    if tasks_file.exists() and not args.force:
        log.error(
            "tasks_exist",
            path=str(tasks_file),
            hint="importing them again would duplicate tasks; use --force to rewrite",
        )
        return 1
    version = detector_version()
    tasks = build_tasks(args.dataset, args.out, args.dpi, tuple(args.from_scratch), version)
    args.out.mkdir(parents=True, exist_ok=True)
    tasks_file.write_text(json.dumps(tasks, indent=1) + "\n", encoding="utf-8")
    log.info("tasks_written", path=str(tasks_file), tasks=len(tasks), detector=version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
