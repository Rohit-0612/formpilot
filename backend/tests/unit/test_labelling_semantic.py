"""Blind semantic labelling tool (eval/labelling/semantic.py) on synthetic fixtures in tmp folders.

No real form and no real label file is read or written.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from app.ir.semantic_types import SemanticType
from eval.labelling import semantic
from eval.labelling.schema import (
    LabelField,
    LabelFile,
    LabelKind,
    LabelPage,
    dump_label_file,
    load_label_file,
)
from tests.fixtures import pdfs

FORM = "02_flat_boxes"
SHA = "0" * 64


def _label_file(*fields: LabelField, pages: int = 1) -> LabelFile:
    return LabelFile(
        form=FORM,
        pdf_sha256=SHA,
        verified_by_human=True,
        prefilled_from=None,
        source="test",
        labelled_pages=list(range(pages)),
        pages=[LabelPage(width=595, height=842)] * pages,
        fields=list(fields),
    )


def _field(field_id: str, y: float, kind: LabelKind = LabelKind.TEXT, **extra: Any) -> LabelField:
    return LabelField(id=field_id, page=0, bbox=(100, y, 300, y + 15), kind=kind, **extra)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    dataset, labels = tmp_path / "dataset", tmp_path / "labels"
    dataset.mkdir()
    labels.mkdir()
    (dataset / f"{FORM}.pdf").write_bytes(pdfs.get("flat_boxes").data)
    fields = (
        _field("p0_l002", 300),
        _field("p0_l000", 100),
        _field("p0_l001", 200, LabelKind.CHECKBOX),
        _field("p0_l003", 400, comb=True, max_chars=10),
    )
    (labels / f"{FORM}.json").write_text(dump_label_file(_label_file(*fields)))
    return dataset, labels


def _export(*labels: dict[str, Any]) -> dict[str, Any]:
    return {"schema": semantic.EXPORT_SCHEMA, "labels": list(labels)}


def _entry(field_id: str, y: float, semantic_type: str) -> dict[str, Any]:
    return {
        "form": FORM,
        "id": field_id,
        "page": 0,
        "bbox": [100, y, 300, y + 15],
        "semantic_type": semantic_type,
    }


# --- the sheet ---------------------------------------------------------------------------------


def test_text_and_comb_fields_of_scored_pages_in_reading_order(folders: tuple[Path, Path]) -> None:
    dataset, labels = folders

    found = semantic.items(labels, dataset, {FORM: "all"})

    assert [i.field.id for i in found] == ["p0_l000", "p0_l002", "p0_l003"]  # no checkbox
    assert semantic.items(labels, dataset, {}) == []  # outside the subset: nothing


def test_sheet_is_blind_and_self_contained(folders: tuple[Path, Path], tmp_path: Path) -> None:
    dataset, labels = folders
    found = semantic.items(labels, dataset, {FORM: "all"})

    index = semantic.write_sheet(found, dataset, tmp_path / "sheet")

    page = index.read_text()
    items = json.loads(page.split("const ITEMS = ", 1)[1].split(";\n", 1)[0])
    # Only where the box is: no detector output, no label text, no prediction.
    assert {frozenset(item) for item in items} == {
        frozenset({"key", "form", "id", "page", "bbox", "comb", "image"})
    }
    assert all(
        (tmp_path / "sheet" / item["image"]).read_bytes().startswith(b"\x89PNG") for item in items
    )
    assert "<script src" not in page and "http" not in page.split("<script>", 1)[1]
    assert all(f'"value": "{t.value}"' in page for t in SemanticType)


# --- the merge -----------------------------------------------------------------------------------


def test_merge_writes_only_the_semantic_types(folders: tuple[Path, Path]) -> None:
    _, labels = folders
    before = load_label_file(labels / f"{FORM}.json")

    summary = semantic.merge(
        _export(_entry("p0_l000", 100, "full_name"), _entry("p0_l003", 400, "pan")),
        labels,
        overwrite=False,
    )

    after = load_label_file(labels / f"{FORM}.json")
    assert summary == {FORM: (2, 2)}
    assert {f.id: f.semantic_type for f in after.fields} == {
        "p0_l002": None,
        "p0_l000": SemanticType.FULL_NAME,
        "p0_l001": None,
        "p0_l003": SemanticType.PAN,
    }
    strip = lambda lf: [f.model_copy(update={"semantic_type": None}) for f in lf.fields]  # noqa: E731
    assert strip(after) == strip(before)
    assert after.model_copy(update={"fields": []}) == before.model_copy(update={"fields": []})


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        (_entry("p0_l000", 101, "full_name"), "changed since the sheet"),
        (_entry("p0_l999", 100, "full_name"), "no such field"),
        (_entry("p0_l000", 100, "shoe_size"), "unknown semantic type"),
        ({**_entry("p0_l001", 200, "gender")}, "changed since the sheet"),  # a checkbox
    ],
)
def test_merge_refuses_and_writes_nothing(
    folders: tuple[Path, Path], entry: dict[str, Any], message: str
) -> None:
    _, labels = folders
    before = (labels / f"{FORM}.json").read_text()

    with pytest.raises(semantic.MergeError, match=message):
        semantic.merge(_export(_entry("p0_l002", 300, "email"), entry), labels, overwrite=False)

    assert (labels / f"{FORM}.json").read_text() == before


def test_merge_does_not_replace_a_type_without_overwrite(folders: tuple[Path, Path]) -> None:
    _, labels = folders
    semantic.merge(_export(_entry("p0_l000", 100, "full_name")), labels, overwrite=False)

    with pytest.raises(semantic.MergeError, match="already set"):
        semantic.merge(_export(_entry("p0_l000", 100, "first_name")), labels, overwrite=False)
    assert semantic.merge(
        _export(_entry("p0_l000", 100, "full_name")), labels, overwrite=False
    ) == {FORM: (1, 0)}
    semantic.merge(_export(_entry("p0_l000", 100, "first_name")), labels, overwrite=True)

    fields = {f.id: f for f in load_label_file(labels / f"{FORM}.json").fields}
    assert fields["p0_l000"].semantic_type is SemanticType.FIRST_NAME


def test_merge_refuses_other_exports(folders: tuple[Path, Path]) -> None:
    with pytest.raises(semantic.MergeError, match="not a semantic-label export"):
        semantic.merge({"labels": []}, folders[1], overwrite=False)
