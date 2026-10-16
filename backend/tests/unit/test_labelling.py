"""Label Studio tooling (eval/labelling): task export, converter, label file schema.

Everything runs on the synthetic fixtures in tmp folders; no real form and no real label file is
read or written.
"""

import copy
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from pydantic import ValidationError

from app.frontends import flat
from app.frontends.detect import detect
from eval.labelling import convert, tasks
from eval.labelling.schema import LabelField, LabelFile, LabelKind, LabelPage, load_label_file
from tests.conftest import TESTS_DIR
from tests.fixtures import pdfs

VERSION = "flat@test"
REAL_EXPORT = TESTS_DIR / "fixtures" / "labelstudio_export_1.23.2.json"
# Dataset used to produce REAL_EXPORT (Label Studio 1.23.2 in Docker, 2026-10-16): fixture
# name -> PDF stem. Fixtures are byte-deterministic, so the recorded SHA-256 still matches.
REAL_EXPORT_DATASET = {
    "flat_underscores": "21_flat_underscores",
    "flat_boxes": "02_flat_boxes",
    "mixed_mostly_flat": "01_mixed_mostly_flat",
}


def _dataset(folder: Path, fixtures: dict[str, str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for fixture, stem in fixtures.items():
        (folder / f"{stem}.pdf").write_bytes(pdfs.get(fixture).data)
    return folder


def _flat_fields(fixture: str) -> list[Any]:
    with pymupdf.open("pdf", pdfs.get(fixture).data) as doc:
        return list(flat.run(doc, detect(doc), uuid.uuid4(), datetime.now(UTC)).fields)


def _as_export(task_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What Label Studio exports for imported tasks before anyone labels them."""
    exported = copy.deepcopy(task_list)
    for number, task in enumerate(exported, start=1):
        task["id"] = number
        task["annotations"] = []
    return exported


def _accept_predictions(task: dict[str, Any]) -> None:
    """The labeller checks the pre-annotations and submits them unchanged."""
    task["annotations"] = [{"result": task["predictions"][0]["result"], "was_cancelled": False}]


def _rect(x: float, y: float, w: float, h: float, label: str = "text") -> dict[str, Any]:
    return {
        "type": "rectanglelabels",
        "from_name": "kind",
        "to_name": "page",
        "value": {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "rotation": 0,
            "rectanglelabels": [label],
        },
    }


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    return _dataset(
        tmp_path / "dataset",
        {
            "flat_underscores": "21_flat_underscores",
            "flat_comb": "02_flat_comb",
            "flat_checkboxes": "06_flat_checkboxes",
            "mixed_mostly_flat": "01_mixed_mostly_flat",
        },
    )


@pytest.fixture
def exported(dataset: Path, tmp_path: Path) -> list[dict[str, Any]]:
    return tasks.build_tasks(dataset, tmp_path / "files", 72, ("21",), VERSION)


# --- task export --------------------------------------------------------------------------


def test_labelling_order_puts_scratch_first_and_big_forms_last() -> None:
    stems = ["03_b", "25_c", "01_a", "41_e", "02_d", "21_f"]

    assert tasks.labelling_order(stems, ("21", "41")) == [
        "21_f",
        "41_e",
        "02_d",
        "25_c",
        "01_a",
        "03_b",
    ]


def test_one_task_per_ok_page_in_labelling_order(exported: list[dict[str, Any]]) -> None:
    pages = [(t["data"]["form"], t["data"]["page"]) for t in exported]

    # mixed_mostly_flat's third page is garbled: not exported.
    assert pages == [
        ("21_flat_underscores", 0),
        ("02_flat_comb", 0),
        ("06_flat_checkboxes", 0),
        ("01_mixed_mostly_flat", 0),
        ("01_mixed_mostly_flat", 1),
    ]


def test_from_scratch_forms_have_no_predictions(exported: list[dict[str, Any]]) -> None:
    scratch = [t for t in exported if t["data"]["form"].startswith("21_")]

    assert scratch and all("predictions" not in t for t in scratch)
    assert all(t["data"]["prefilled_from"] is None for t in scratch)
    assert all("(from scratch)" in t["data"]["page_label"] for t in scratch)
    others = [t for t in exported if not t["data"]["form"].startswith("21_")]
    assert all(t["data"]["prefilled_from"] == VERSION for t in others)


def test_task_data_and_images(exported: list[dict[str, Any]], tmp_path: Path) -> None:
    task = next(t for t in exported if t["data"]["form"] == "02_flat_comb")
    data = task["data"]

    assert data["image"] == f"{tasks.LOCAL_FILES_PREFIX}/images/02_flat_comb/page-01.png"
    assert data["pdf_sha256"] == convert._pdf_pages(tmp_path / "dataset" / "02_flat_comb.pdf")[0]
    assert (data["page_width_pt"], data["page_height_pt"]) == pdfs.A4
    image = tmp_path / "files" / "images" / "02_flat_comb" / "page-01.png"
    pixmap = pymupdf.Pixmap(str(image))
    result = task["predictions"][0]["result"][0]
    assert (result["original_width"], result["original_height"]) == (pixmap.width, pixmap.height)


def test_predictions_are_the_detector_boxes_in_percent(exported: list[dict[str, Any]]) -> None:
    task = next(t for t in exported if t["data"]["form"] == "02_flat_comb")
    results = task["predictions"][0]["result"]
    fields = _flat_fields("flat_comb")
    width, height = pdfs.A4

    assert [r["id"] for r in results] == [f.id for f in fields]
    for result, field in zip(results, fields, strict=True):
        value = result["value"]
        assert value["x"] * width / 100 == pytest.approx(field.bbox.x0)
        assert value["y"] * height / 100 == pytest.approx(field.bbox.y0)
        assert (value["x"] + value["width"]) * width / 100 == pytest.approx(field.bbox.x1)
        assert (value["y"] + value["height"]) * height / 100 == pytest.approx(field.bbox.y1)
        assert value["rectanglelabels"] == ["comb"]


def test_checkboxes_are_labelled_checkbox(exported: list[dict[str, Any]]) -> None:
    task = next(t for t in exported if t["data"]["form"] == "06_flat_checkboxes")

    labels = {r["value"]["rectanglelabels"][0] for r in task["predictions"][0]["result"]}
    assert labels == {"checkbox"}


def test_main_refuses_to_overwrite_tasks(dataset: Path, tmp_path: Path) -> None:
    out = tmp_path / "files"
    out.mkdir()
    (out / "tasks.json").write_text("[]")

    assert tasks.main(["--dataset", str(dataset), "--out", str(out)]) == 1
    assert (out / "tasks.json").read_text() == "[]"


# --- converter ----------------------------------------------------------------------------


def test_accepted_predictions_round_trip_to_the_detector_boxes(
    exported: list[dict[str, Any]], dataset: Path
) -> None:
    export = _as_export(exported)
    task = next(t for t in export if t["data"]["form"] == "02_flat_comb")
    _accept_predictions(task)

    files = convert.convert_export(export, dataset, "test")

    label = files["02_flat_comb"]
    detector = _flat_fields("flat_comb")
    assert label.labelled_pages == [0]
    assert label.prefilled_from == VERSION
    assert label.verified_by_human is True
    assert [f.id for f in label.fields] == [f"p0_l{i:03d}" for i in range(len(detector))]
    for got, want in zip(label.fields, detector, strict=True):
        assert got.bbox == pytest.approx((want.bbox.x0, want.bbox.y0, want.bbox.x1, want.bbox.y1))
        assert got.kind is LabelKind.TEXT and got.comb is True


def test_partial_labelling_and_skipped_pages(exported: list[dict[str, Any]], dataset: Path) -> None:
    export = _as_export(exported)
    page0, page1 = [t for t in export if t["data"]["form"] == "01_mixed_mostly_flat"]
    _accept_predictions(page1)
    page0["annotations"] = [{"result": [], "was_cancelled": True}]  # skipped

    label = convert.convert_export(export, dataset, "test")["01_mixed_mostly_flat"]

    assert label.labelled_pages == [1]
    assert len(label.pages) == 3  # every page of the PDF, labelled or not
    assert {f.page for f in label.fields} == {1}


def test_empty_annotation_is_a_labelled_page_without_fields(
    exported: list[dict[str, Any]], dataset: Path
) -> None:
    export = _as_export(exported)
    task = next(t for t in export if t["data"]["form"] == "06_flat_checkboxes")
    task["annotations"] = [{"result": [], "was_cancelled": False}]

    label = convert.convert_export(export, dataset, "test")["06_flat_checkboxes"]

    assert label.labelled_pages == [0]
    assert label.fields == []


def test_forms_without_labelled_pages_get_no_file(
    exported: list[dict[str, Any]], dataset: Path
) -> None:
    assert convert.convert_export(_as_export(exported), dataset, "test") == {}


def test_from_scratch_boxes_are_converted_in_reading_order(
    exported: list[dict[str, Any]], dataset: Path
) -> None:
    export = _as_export(exported)
    task = next(t for t in export if t["data"]["form"] == "21_flat_underscores")
    # Drawn bottom row first, then the top row right to left.
    task["annotations"] = [
        {
            "result": [
                _rect(10, 50, 20, 2),
                _rect(60, 10, 20, 2),
                _rect(10, 10, 20, 2, "checkbox"),
            ],
            "was_cancelled": False,
        }
    ]

    label = convert.convert_export(export, dataset, "test")["21_flat_underscores"]

    width, height = pdfs.A4
    assert label.prefilled_from is None
    assert [(f.id, f.kind.value, f.bbox[0]) for f in label.fields] == [
        ("p0_l000", "checkbox", pytest.approx(0.10 * width)),
        ("p0_l001", "text", pytest.approx(0.60 * width)),
        ("p0_l002", "text", pytest.approx(0.10 * width)),
    ]
    assert label.fields[0].bbox[1] == pytest.approx(0.10 * height)


def test_boxes_are_clipped_to_the_page(exported: list[dict[str, Any]], dataset: Path) -> None:
    export = _as_export(exported)
    task = next(t for t in export if t["data"]["form"] == "21_flat_underscores")
    task["annotations"] = [{"result": [_rect(95, -1, 10, 3)], "was_cancelled": False}]

    (field,) = convert.convert_export(export, dataset, "test")["21_flat_underscores"].fields

    assert field.bbox[2] == pytest.approx(pdfs.A4[0])
    assert field.bbox[1] == 0.0


@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda t: t["annotations"].append(copy.deepcopy(t["annotations"][0])), "2 submitted"),
        (lambda t: t["annotations"][0]["result"][0]["value"].update(rotation=12), "rotated"),
        (lambda t: t["annotations"][0]["result"][0]["value"].update(rectanglelabels=[]), "label"),
        (lambda t: t["annotations"][0]["result"][0]["value"].update(width=0.01), "smaller"),
        (lambda t: t["data"].update(pdf_sha256="0" * 64), "not the labelled PDF"),
        (lambda t: t["data"].update(page_width_pt=500), "page size"),
        (lambda t: t.pop("annotations"), "JSON-MIN"),
    ],
)
def test_conversion_errors_say_what_to_fix(
    exported: list[dict[str, Any]], dataset: Path, break_it: Any, message: str
) -> None:
    export = _as_export(exported)
    task = next(t for t in export if t["data"]["form"] == "02_flat_comb")
    _accept_predictions(task)
    break_it(task)

    with pytest.raises(convert.ConversionError, match=message):
        convert.convert_export(export, dataset, "test")


def test_prefilled_from_must_agree_within_a_form(
    exported: list[dict[str, Any]], dataset: Path
) -> None:
    export = _as_export(exported)
    export[-1]["data"]["prefilled_from"] = "flat@other"

    with pytest.raises(convert.ConversionError, match="prefilled_from"):
        convert.convert_export(export, dataset, "test")


def test_write_refuses_to_overwrite_without_flag(
    exported: list[dict[str, Any]], dataset: Path, tmp_path: Path
) -> None:
    export = _as_export(exported)
    _accept_predictions(next(t for t in export if t["data"]["form"] == "02_flat_comb"))
    files = convert.convert_export(export, dataset, "test")
    labels = tmp_path / "labels"

    (path,) = convert.write_label_files(files, labels, overwrite=False)
    with pytest.raises(convert.ConversionError, match="--overwrite"):
        convert.write_label_files(files, labels, overwrite=False)
    convert.write_label_files(files, labels, overwrite=True)

    assert load_label_file(path) == files["02_flat_comb"]


def test_real_label_studio_export(tmp_path: Path) -> None:
    """A JSON export from Label Studio 1.23.2 (synthetic fixtures only), converted end to end."""
    dataset = _dataset(tmp_path / "dataset", {f: s for f, s in REAL_EXPORT_DATASET.items()})

    code = convert.main(
        [str(REAL_EXPORT), "--dataset", str(dataset), "--labels", str(tmp_path / "labels")]
    )

    assert code == 0
    written = sorted(p.name for p in (tmp_path / "labels").glob("*.json"))
    # 01: page 1 skipped, page 2 untouched -> nothing labelled, no file.
    assert written == ["02_flat_boxes.json", "21_flat_underscores.json"]
    boxes = load_label_file(tmp_path / "labels" / "02_flat_boxes.json")
    truth = [f.bbox for f in pdfs.get("flat_boxes").fields]
    assert [f.bbox for f in boxes.fields] == [
        pytest.approx(b, abs=1e-6) for b in sorted(truth, key=lambda b: (b[1], b[0]))
    ]
    scratch = load_label_file(tmp_path / "labels" / "21_flat_underscores.json")
    assert scratch.prefilled_from is None and len(scratch.fields) == 2
    assert json.loads(REAL_EXPORT.read_text())[0]["data"]["prefilled_from"] is None


# --- schema -------------------------------------------------------------------------------


def _label_file(**overrides: Any) -> LabelFile:
    values: dict[str, Any] = {
        "form": "02_flat_boxes",
        "pdf_sha256": "a" * 64,
        "verified_by_human": True,
        "prefilled_from": None,
        "source": "test",
        "labelled_pages": [0],
        "pages": [LabelPage(width=595, height=842), LabelPage(width=595, height=842)],
        "fields": [LabelField(id="p0_l000", page=0, bbox=(10, 10, 100, 22), kind=LabelKind.TEXT)],
    }
    values.update(overrides)
    return LabelFile(**values)


def test_valid_label_file() -> None:
    assert _label_file().fields[0].semantic_type is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"pdf_sha256": "XYZ"},
        {"labelled_pages": [1, 0]},
        {"labelled_pages": [2]},
        {"labelled_pages": []},  # the field's page is then unlabelled
        {"fields": [LabelField(id="p0_l000", page=0, bbox=(10, 10, 700, 22), kind=LabelKind.TEXT)]},
        {
            "fields": [
                LabelField(id="p0_l000", page=0, bbox=(10, 10, 100, 22), kind=LabelKind.TEXT),
                LabelField(id="p0_l000", page=0, bbox=(10, 30, 100, 42), kind=LabelKind.TEXT),
            ]
        },
    ],
)
def test_invalid_label_files(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _label_file(**overrides)


@pytest.mark.parametrize(
    "values",
    [
        {"bbox": (10, 10, 5, 22), "kind": "text"},
        {"bbox": (10, 10, 20, 20), "kind": "checkbox", "comb": True},
        {"bbox": (10, 10, 20, 20), "kind": "radio"},
    ],
)
def test_invalid_label_fields(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        LabelField(id="p0_l000", page=0, **values)
