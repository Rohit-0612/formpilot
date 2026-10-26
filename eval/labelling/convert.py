"""Convert a Label Studio JSON export into label files, eval/labels/<form>.json.

    make label-convert EXPORT=~/Downloads/project-1-at-....json [OVERWRITE=1]

Run by the human labeller (label files are human ground truth, CLAUDE.md §6). Export with
"JSON" (not "JSON-MIN"). Each task is one page:
- a task with one submitted annotation is a labelled page (an empty annotation means "this page
  has no entry areas");
- a task without annotations, or whose annotation was skipped, is not labelled yet;
- more than one submitted annotation for a page is an error (decide which one is right first).

Boxes are converted from percent of the page image to PDF points (top-left origin). The PDF in
eval/dataset/<split>/ must have the SHA-256 recorded in the tasks.
"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pymupdf

from app.logging import configure_logging, get_logger
from eval.labelling.schema import (
    DATASET_DIR,
    LABELS_DIR,
    LabelField,
    LabelFile,
    LabelKind,
    LabelPage,
    dump_label_file,
    load_label_file,
)
from eval.labelling.tasks import FROM_NAME, LABEL_CHECKBOX, LABEL_COMB, LABEL_TEXT

log = get_logger(__name__)

SOURCE_TOOL = "label-studio 1.23.2"
PAGE_SIZE_TOLERANCE = 0.5  # points
MIN_BOX_SIZE = 1.0  # points; smaller rectangles are accidental clicks
DUPLICATE_IOU = 0.5


class ConversionError(Exception):
    """The export cannot be converted as it is; the message says what to fix in Label Studio."""


def _iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def _where(task: dict[str, Any]) -> str:
    data = task.get("data", {})
    return f"task {task.get('id', '?')} ({data.get('form', '?')} page {data.get('page', 0) + 1})"


def _submitted_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    if "annotations" not in task:
        raise ConversionError("this is not a full JSON export: export with 'JSON', not 'JSON-MIN'")
    submitted = [a for a in task["annotations"] if not a.get("was_cancelled")]
    if len(submitted) > 1:
        raise ConversionError(
            f"{_where(task)} has {len(submitted)} submitted annotations; delete all but one"
        )
    return submitted[0] if submitted else None


def _box(
    result: dict[str, Any], page: LabelPage, task: dict[str, Any]
) -> tuple[LabelKind, bool, tuple[float, ...]]:
    value = result["value"]
    if abs(value.get("rotation", 0) or 0) > 0.01:
        raise ConversionError(f"{_where(task)}: a rectangle is rotated; boxes must be upright")
    labels = value.get("rectanglelabels", [])
    if len(labels) != 1 or labels[0] not in (LABEL_TEXT, LABEL_COMB, LABEL_CHECKBOX):
        raise ConversionError(f"{_where(task)}: every rectangle needs exactly one label")
    x0 = max(0.0, value["x"] / 100 * page.width)
    y0 = max(0.0, value["y"] / 100 * page.height)
    x1 = min(page.width, (value["x"] + value["width"]) / 100 * page.width)
    y1 = min(page.height, (value["y"] + value["height"]) / 100 * page.height)
    if x1 - x0 < MIN_BOX_SIZE or y1 - y0 < MIN_BOX_SIZE:
        raise ConversionError(f"{_where(task)}: a rectangle is smaller than 1 pt; delete it")
    label = labels[0]
    kind = LabelKind.CHECKBOX if label == LABEL_CHECKBOX else LabelKind.TEXT
    return kind, label == LABEL_COMB, (x0, y0, x1, y1)


def _reading_order(boxes: list[tuple[float, ...]]) -> list[int]:
    """Indices of boxes top to bottom in rows, left to right within a row."""
    order = sorted(range(len(boxes)), key=lambda i: ((boxes[i][1] + boxes[i][3]) / 2, boxes[i][0]))
    rows: list[list[int]] = []
    for i in order:
        box = boxes[i]
        if rows:
            first = boxes[rows[-1][0]]
            limit = max(3.0, 0.5 * min(first[3] - first[1], box[3] - box[1]))
            if abs((box[1] + box[3]) / 2 - (first[1] + first[3]) / 2) <= limit:
                rows[-1].append(i)
                continue
        rows.append([i])
    return [i for row in rows for i in sorted(row, key=lambda j: boxes[j][0])]


def _pdf_pages(pdf: Path) -> tuple[str, list[LabelPage]]:
    data = pdf.read_bytes()
    with pymupdf.open("pdf", data) as doc:
        pages = [LabelPage(width=p.rect.width, height=p.rect.height) for p in doc]
    return hashlib.sha256(data).hexdigest(), pages


def convert_form(form: str, tasks: list[dict[str, Any]], dataset: Path, source: str) -> LabelFile:
    pdf = dataset / f"{form}.pdf"
    if not pdf.exists():
        raise ConversionError(f"{form}: {pdf} not found; is --dataset the right split?")
    sha256, pages = _pdf_pages(pdf)

    prefilled = {task["data"].get("prefilled_from") for task in tasks}
    if len(prefilled) != 1:
        raise ConversionError(f"{form}: tasks disagree on prefilled_from; re-export the tasks")
    fields: list[LabelField] = []
    labelled: list[int] = []
    for task in sorted(tasks, key=lambda t: t["data"]["page"]):
        data = task["data"]
        if data.get("pdf_sha256") != sha256:
            raise ConversionError(f"{_where(task)}: the PDF in {dataset} is not the labelled PDF")
        index = int(data["page"])
        page = pages[index]
        if (
            abs(page.width - data["page_width_pt"]) > PAGE_SIZE_TOLERANCE
            or abs(page.height - data["page_height_pt"]) > PAGE_SIZE_TOLERANCE
        ):
            raise ConversionError(f"{_where(task)}: page size differs from the PDF")
        annotation = _submitted_annotation(task)
        if annotation is None:
            continue
        if index in labelled:
            raise ConversionError(f"{_where(task)}: the page appears in two tasks")
        labelled.append(index)
        boxes = [
            _box(r, page, task)
            for r in annotation.get("result", [])
            if r.get("type") == "rectanglelabels" and r.get("from_name") == FROM_NAME
        ]
        coords = [b[2] for b in boxes]
        for number, i in enumerate(_reading_order(coords)):
            kind, comb, (x0, y0, x1, y1) = boxes[i]
            fields.append(
                LabelField(
                    id=f"p{index}_l{number:03d}",
                    page=index,
                    bbox=(x0, y0, x1, y1),
                    kind=kind,
                    comb=comb,
                )
            )
        for a in range(len(coords)):
            for b in range(a + 1, len(coords)):
                if _iou(coords[a], coords[b]) >= DUPLICATE_IOU:
                    log.warning("possible_duplicate_boxes", form=form, page=index + 1)

    return LabelFile(
        form=form,
        pdf_sha256=sha256,
        verified_by_human=True,
        prefilled_from=prefilled.pop(),
        source=source,
        labelled_pages=sorted(labelled),
        pages=pages,
        fields=fields,
    )


def convert_export(
    export: list[dict[str, Any]], dataset: Path, source: str
) -> dict[str, LabelFile]:
    if not isinstance(export, list):
        raise ConversionError("expected a JSON list of tasks (Label Studio 'JSON' export)")
    by_form: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in export:
        by_form[task["data"]["form"]].append(task)
    converted = {
        form: convert_form(form, tasks, dataset, source) for form, tasks in by_form.items()
    }
    # A form with no labelled page yet gets no label file (the eval lists it as unlabelled).
    return {form: f for form, f in converted.items() if f.labelled_pages}


def write_label_files(files: dict[str, LabelFile], labels_dir: Path, overwrite: bool) -> list[Path]:
    existing = [
        labels_dir / f"{form}.json" for form in files if (labels_dir / f"{form}.json").exists()
    ]
    if existing and not overwrite:
        names = ", ".join(p.name for p in existing)
        raise ConversionError(f"label files exist ({names}); pass --overwrite to replace them")
    labels_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for form, label_file in sorted(files.items()):
        path = labels_dir / f"{form}.json"
        path.write_text(dump_label_file(label_file), encoding="utf-8")
        load_label_file(path)  # what was written must load back
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("export", type=Path, help="Label Studio JSON export")
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR / "dev")
    parser.add_argument("--labels", type=Path, default=LABELS_DIR)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("INFO", json=False)

    # zsh passes `make label-convert EXPORT=~/...` through with a literal "~".
    export_path: Path = args.export.expanduser()
    try:
        export = json.loads(export_path.read_text(encoding="utf-8"))
        files = convert_export(export, args.dataset, f"{SOURCE_TOOL}, {export_path.name}")
        written = write_label_files(files, args.labels, args.overwrite)
    except ConversionError as exc:
        log.error("conversion_failed", reason=str(exc))
        return 1
    skipped = sorted({task["data"]["form"] for task in export} - set(files))
    if skipped:
        log.info("no_labelled_pages_yet", forms=skipped)
    for path in written:
        label_file = load_label_file(path)
        kinds = defaultdict(int)
        for f in label_file.fields:
            kinds["comb" if f.comb else f.kind.value] += 1
        unlabelled = [
            p + 1 for p in range(len(label_file.pages)) if p not in label_file.labelled_pages
        ]
        log.info(
            "label_file_written",
            file=str(path),
            labelled_pages=[p + 1 for p in label_file.labelled_pages],
            unlabelled_pages=unlabelled,
            prefilled=label_file.prefilled_from is not None,
            **dict(kinds),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
