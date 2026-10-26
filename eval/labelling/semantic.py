"""Blind semantic-type labelling (Phase 3): a local labelling page, and the merge of its export.

`sheet` writes, under eval/labelling/work/semantic/ (gitignored), an HTML page and one crop per
field: the page around the field's labelled box, outlined in red. It reads only the label files
and the PDFs: no detector output, no LLM, no extracted label text is shown (labels written blind,
SPEC §10). Scope: the text and comb fields of the scored pages (checkboxes are excluded, human
decision 2026-10-26).

`merge` writes the `semantic_type` of each exported field into its label file and nothing else.
It refuses an export whose fields no longer match the label files (id, page, box or kind), and
it does not replace a semantic type already set unless --overwrite is given. The human runs it,
or asks for it, after labelling; label files stay human ground truth (CLAUDE.md §6).
"""

import argparse
import hashlib
import html
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

from app.ir.semantic_types import SEMANTIC_TYPES, SemanticType
from eval.labelling.schema import (
    DATASET_DIR,
    LABELS_DIR,
    REFERENCE_DIR,
    LabelField,
    LabelFile,
    LabelKind,
    SemanticReference,
    dump_label_file,
    dump_reference,
    load_label_file,
)
from eval.labelling.subset import DEV_SUBSET, PageSelection, subset_pages
from eval.labelling.tasks import FROM_SCRATCH, WORK_DIR, labelling_order

EXPORT_SCHEMA = "formpilot-semantic-labels/1"
TEMPLATE = Path(__file__).with_name("semantic_sheet.html")
SHEET_DIR = WORK_DIR / "semantic"
CROP_DPI = 110
# Around the field: room for a label to its left or above it.
MARGIN_LEFT, MARGIN_RIGHT, MARGIN_ABOVE, MARGIN_BELOW = 230.0, 60.0, 45.0, 30.0
BOX_TOLERANCE = 0.01


@dataclass(frozen=True)
class Item:
    form: str
    field: LabelField

    @property
    def key(self) -> str:
        return f"{self.form}/{self.field.id}"


def items(labels_dir: Path, dataset_dir: Path, subset: Mapping[str, PageSelection]) -> list[Item]:
    """The fields to label: text and comb fields of the scored pages, in labelling order."""
    files = {p.stem: p for p in labels_dir.glob("*.json")}
    found: list[Item] = []
    for form in labelling_order(sorted(files), FROM_SCRATCH):
        label_file = load_label_file(files[form])
        with pymupdf.open(dataset_dir / f"{form}.pdf") as doc:
            pages = subset_pages(subset, form, len(doc)) & set(label_file.labelled_pages)
        fields = [f for f in label_file.fields if f.page in pages and f.kind is LabelKind.TEXT]
        fields.sort(key=lambda f: (f.page, round(f.bbox[1]), f.bbox[0]))
        found += [Item(form, f) for f in fields]
    return found


def _crop(page: pymupdf.Page, field: LabelField) -> bytes:
    x0, y0, x1, y1 = field.bbox
    shown = pymupdf.Rect(
        max(0.0, x0 - MARGIN_LEFT),
        max(0.0, y0 - MARGIN_ABOVE),
        min(page.rect.width, x1 + MARGIN_RIGHT),
        min(page.rect.height, y1 + MARGIN_BELOW),
    )
    derotate = page.derotation_matrix  # label boxes are on the displayed page
    annot = page.add_rect_annot(pymupdf.Rect(field.bbox) * derotate)
    annot.set_colors(stroke=(0.9, 0.1, 0.1))
    annot.set_border(width=1.5)
    annot.update()
    try:
        return page.get_pixmap(dpi=CROP_DPI, clip=shown * derotate, annots=True).tobytes("png")
    finally:
        page.delete_annot(annot)


def write_sheet(found: list[Item], dataset_dir: Path, out_dir: Path) -> Path:
    crops = out_dir / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    by_form: dict[str, list[Item]] = {}
    for item in found:
        by_form.setdefault(item.form, []).append(item)
    entries: list[dict[str, Any]] = []
    for form, form_items in by_form.items():
        with pymupdf.open(dataset_dir / f"{form}.pdf") as doc:
            for item in form_items:
                name = f"{form}__{item.field.id}.png"
                (crops / name).write_bytes(_crop(doc[item.field.page], item.field))
                entries.append(
                    {
                        "key": item.key,
                        "form": form,
                        "id": item.field.id,
                        "page": item.field.page,
                        "bbox": list(item.field.bbox),
                        "comb": item.field.comb,
                        "image": f"crops/{name}",
                    }
                )
    types = [
        {"value": t.value, "description": info.description} for t, info in SEMANTIC_TYPES.items()
    ]
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("__ITEMS__", json.dumps(entries)).replace("__TYPES__", json.dumps(types))
    page = page.replace("__SCHEMA__", html.escape(EXPORT_SCHEMA))
    index = out_dir / "index.html"
    index.write_text(page, encoding="utf-8")
    return index


# --- merge ----------------------------------------------------------------------------------------


class MergeError(ValueError):
    pass


def _checked(
    export: dict[str, Any], labels_dir: Path
) -> dict[str, tuple[LabelFile, dict[str, SemanticType]]]:
    """The export's semantic types per form, checked against the label files' boxes."""
    if export.get("schema") != EXPORT_SCHEMA:
        raise MergeError(f"not a semantic-label export (expected schema {EXPORT_SCHEMA})")
    wanted: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in export.get("labels", []):
        wanted.setdefault(entry["form"], {})[entry["id"]] = entry
    checked: dict[str, tuple[LabelFile, dict[str, SemanticType]]] = {}
    for form, entries in sorted(wanted.items()):
        path = labels_dir / f"{form}.json"
        if not path.exists():
            raise MergeError(f"{form}: no label file")
        label_file = load_label_file(path)
        fields = {f.id: f for f in label_file.fields}
        types: dict[str, SemanticType] = {}
        for field_id, entry in entries.items():
            field = fields.get(field_id)
            if field is None:
                raise MergeError(f"{form} {field_id}: no such field in the label file")
            same_box = all(
                abs(a - b) <= BOX_TOLERANCE for a, b in zip(field.bbox, entry["bbox"], strict=True)
            )
            if field.page != entry["page"] or not same_box or field.kind is not LabelKind.TEXT:
                raise MergeError(f"{form} {field_id}: the label file changed since the sheet")
            try:
                types[field_id] = SemanticType(entry["semantic_type"])
            except ValueError:
                raise MergeError(f"{form} {field_id}: unknown semantic type") from None
        checked[form] = (label_file, types)
    return checked


def merge(
    export: dict[str, Any], labels_dir: Path, *, overwrite: bool
) -> dict[str, tuple[int, int]]:
    """Write the exported semantic types into the label files. Returns form -> (set, changed)."""
    updated: dict[str, LabelFile] = {}
    summary: dict[str, tuple[int, int]] = {}
    for form, (label_file, types) in _checked(export, labels_dir).items():
        changed = 0
        new_fields = []
        for field in label_file.fields:
            semantic_type = types.get(field.id)
            if semantic_type is None:
                new_fields.append(field)
                continue
            if field.semantic_type not in (None, semantic_type) and not overwrite:
                raise MergeError(f"{form} {field.id}: already set; use --overwrite to replace it")
            changed += field.semantic_type is not semantic_type
            new_fields.append(field.model_copy(update={"semantic_type": semantic_type}))
        updated[form] = label_file.model_copy(update={"fields": new_fields})
        summary[form] = (len(types), changed)

    for form, label_file in updated.items():  # write only once every form has passed the checks
        LabelFile.model_validate(label_file.model_dump())
        (labels_dir / f"{form}.json").write_text(dump_label_file(label_file), encoding="utf-8")
    return summary


def write_reference(
    export: dict[str, Any],
    labels_dir: Path,
    out_dir: Path,
    *,
    labelled_by: str,
    overwrite: bool = False,
) -> dict[str, int]:
    """Write the export as semantic reference files (decision P3-D6); label files untouched.

    Reference files are frozen once written: an existing one is replaced only with `overwrite`.
    """
    references: dict[str, SemanticReference] = {}
    for form, (_, types) in _checked(export, labels_dir).items():
        if (out_dir / f"{form}.json").exists() and not overwrite:
            raise MergeError(f"{form}: reference labels exist and are frozen")
        sha = hashlib.sha256((labels_dir / f"{form}.json").read_bytes()).hexdigest()
        references[form] = SemanticReference(
            form=form, label_file_sha256=sha, labelled_by=labelled_by, labels=types
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    for form, reference in references.items():
        (out_dir / f"{form}.json").write_text(dump_reference(reference), encoding="utf-8")
    return {form: len(r.labels) for form, r in references.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sheet", help="write the labelling page under eval/labelling/work/")
    merge_cmd = commands.add_parser("merge", help="merge an export into eval/labels/")
    merge_cmd.add_argument("export", type=Path)
    merge_cmd.add_argument("--overwrite", action="store_true")
    ref_cmd = commands.add_parser("reference", help="write reference labels (P3-D6)")
    ref_cmd.add_argument("export", type=Path)
    ref_cmd.add_argument("--by", required=True, help="who labelled, e.g. the model and how")
    ref_cmd.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "sheet":
        found = items(LABELS_DIR, DATASET_DIR / "dev", DEV_SUBSET)
        index = write_sheet(found, DATASET_DIR / "dev", SHEET_DIR)
        print(f"{len(found)} fields; open {index} in a browser")  # noqa: T201 - CLI output
        return 0
    try:
        export = json.loads(args.export.expanduser().read_text(encoding="utf-8"))
        if args.command == "reference":
            counts = write_reference(
                export, LABELS_DIR, REFERENCE_DIR, labelled_by=args.by, overwrite=args.overwrite
            )
            for form, count in counts.items():
                print(f"{form}: {count} reference labels")  # noqa: T201 - CLI output
            return 0
        summary = merge(export, LABELS_DIR, overwrite=args.overwrite)
    except (MergeError, OSError, ValueError, KeyError) as exc:
        print(f"{args.command} refused: {exc}", file=sys.stderr)  # noqa: T201 - CLI output
        return 1
    for form, (count, changed) in summary.items():
        print(f"{form}: {count} semantic types, {changed} changed")  # noqa: T201 - CLI output
    return 0


if __name__ == "__main__":
    sys.exit(main())
