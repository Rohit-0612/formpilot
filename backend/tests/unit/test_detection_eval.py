"""Detection eval (eval/detection.py): matching rules, scoring, reports.

Label files here are built from the synthetic fixtures' ground truth in tmp folders; no real
label file is read or written.
"""

import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from app.ir.geometry import iou
from app.ir.models import BBox, FieldKind
from eval import detection
from eval.detection import Box, Counts, Macro, count, macro, match
from eval.labelling.schema import LabelField, LabelFile, LabelKind, LabelPage, dump_label_file
from eval.labelling.subset import ALL, DEV_SUBSET, subset_pages
from tests.fixtures import pdfs

SCRATCH = None  # prefilled_from for from-scratch label files


def _box(x0: float, y0: float, x1: float, y1: float, page: int = 0, kind: str = "text") -> Box:
    return Box(BBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1), kind)


# --- matching -----------------------------------------------------------------------------


def test_perfect_match() -> None:
    boxes = [_box(0, 0, 10, 10), _box(20, 0, 30, 10)]

    assert match(boxes, boxes, 0.5) == [(0, 0, 1.0), (1, 1, 1.0)]
    assert count(boxes, boxes, 0.5) == Counts(tp=2, fp=0, fn=0)


def test_shifted_box_below_threshold_is_a_miss_and_a_false_positive() -> None:
    # Overlap 4 x 10 = 40; union 160 -> IoU 0.25.
    assert count([_box(6, 0, 16, 10)], [_box(0, 0, 10, 10)], 0.5) == Counts(tp=0, fp=1, fn=1)


def test_duplicate_prediction_counts_once() -> None:
    truth = [_box(0, 0, 10, 10)]
    predicted = [_box(0, 0, 10, 10), _box(0, 0, 10, 9)]

    assert count(predicted, truth, 0.5) == Counts(tp=1, fp=1, fn=0)


def test_missed_label() -> None:
    assert count([], [_box(0, 0, 10, 10)], 0.5) == Counts(tp=0, fp=0, fn=1)


def test_boxes_on_different_pages_never_match() -> None:
    assert match([_box(0, 0, 10, 10, page=0)], [_box(0, 0, 10, 10, page=1)], 0.5) == []


def test_greedy_takes_the_best_pair_first() -> None:
    predicted = [_box(0, 0, 10, 10), _box(4, 0, 14, 10)]
    truth = [_box(0, 0, 10, 10), _box(5, 0, 15, 10)]

    pairs = [(p, t) for p, t, _ in match(predicted, truth, 0.5)]

    assert pairs == [(0, 0), (1, 1)]


def test_ties_are_broken_by_index() -> None:
    predicted = [_box(0, 0, 10, 10), _box(0, 0, 10, 10)]
    truth = [_box(0, 0, 10, 10)]

    assert match(predicted, truth, 0.5) == [(0, 0, 1.0)]


def test_small_checkbox_offset_matches_only_at_the_diagnostic_threshold() -> None:
    """A 9 pt checkbox 2 pt off in x and y: IoU = 49 / 113 ~ 0.43."""
    truth = [_box(100, 100, 109, 109, kind="checkbox")]
    predicted = [_box(102, 102, 111, 111, kind="checkbox")]

    assert count(predicted, truth, 0.5).tp == 0
    assert count(predicted, truth, detection.DIAGNOSTIC_IOU).tp == 1


def test_precision_and_recall_are_none_without_boxes() -> None:
    empty = Counts()

    assert (empty.precision, empty.recall) == (None, None)
    assert Counts(tp=3, fp=1, fn=2).precision == 0.75
    assert Counts(tp=3, fp=1, fn=2).recall == 0.6


def test_kind_stats() -> None:
    stats = detection.KindStats()
    predicted = [_box(0, 0, 10, 10, kind="text"), _box(20, 0, 29, 9, kind="checkbox")]
    truth = [_box(0, 0, 10, 10, kind="comb"), _box(40, 0, 49, 9, kind="checkbox")]

    stats.add_page(predicted, truth, 0.5)

    data = stats.as_dict()
    assert data["recall_by_labelled_kind"]["comb"] == {"matched": 1, "total": 1, "share": 1.0}
    assert data["recall_by_labelled_kind"]["checkbox"]["share"] == 0.0
    assert data["precision_by_predicted_kind"]["text"]["share"] == 1.0
    assert data["matched_pairs_predicted_to_labelled_kind"] == {"text->comb": 1}


# --- writing-spot rule (docs/decisions/phase-2.md, fixed before measuring) ---------------

FS = 10.0  # font size of the synthetic label, pt
BASELINE = 100.0


def _line_box(height_factor: float, baseline: float = BASELINE, x0: float = 50, x1: float = 250):
    """A line entry drawn from the writing line up by height_factor x the font size."""
    return BBox(page=0, x0=x0, y0=baseline - height_factor * FS, x1=x1, y1=baseline)


@pytest.mark.parametrize("factor", [0.4, 0.6, 1.0, 1.5, 2.4])
def test_same_writing_line_matches_whatever_the_height(factor: float) -> None:
    detector = _line_box(1.2)
    labeller = _line_box(factor)

    assert detection.writing_spot(detector, labeller) is not None


def test_the_hand_drawn_height_that_iou_misses_is_a_writing_spot_match() -> None:
    detector, labeller = _line_box(1.2), _line_box(0.4)

    assert iou(detector, labeller) < 0.5  # plain IoU calls this a miss
    assert detection.writing_spot(detector, labeller) is not None


@pytest.mark.parametrize("pitch", [1.0, 1.2, 1.5])
@pytest.mark.parametrize("label_factor", [0.6, 1.2])
def test_neighbouring_writing_lines_do_not_match(pitch: float, label_factor: float) -> None:
    """Multi-line entries (one box per line) stay separate, above and below."""
    detector = _line_box(1.2)
    below = _line_box(label_factor, baseline=BASELINE + pitch * FS)
    above = _line_box(label_factor, baseline=BASELINE - pitch * FS)

    assert detection.writing_spot(detector, below) is None
    assert detection.writing_spot(detector, above) is None


def test_horizontal_extent_must_overlap_by_half() -> None:
    detector = _line_box(1.2, x0=0, x1=100)

    assert detection.writing_spot(detector, _line_box(1.2, x0=30, x1=130)) is not None  # 70/130
    assert detection.writing_spot(detector, _line_box(1.2, x0=34, x1=134)) is None  # 66/134


def test_a_comb_row_does_not_match_its_single_cells() -> None:
    comb = BBox(page=0, x0=100, y0=90, x1=260, y1=110)  # 8 cells of 20 pt
    cells = [BBox(page=0, x0=100 + 20 * i, y0=90, x1=120 + 20 * i, y1=110) for i in range(8)]

    assert all(detection.writing_spot(cell, comb) is None for cell in cells)


def test_a_checkbox_2pt_off_in_both_directions_matches_where_plain_iou_does_not() -> None:
    labelled = BBox(page=0, x0=100, y0=100, x1=109, y1=109)
    predicted = BBox(page=0, x0=102, y0=102, x1=111, y1=111)  # plain IoU 49/113 ~ 0.43

    assert iou(predicted, labelled) < 0.5
    assert detection.writing_spot(predicted, labelled) is not None


def test_different_pages_never_match() -> None:
    assert (
        detection.writing_spot(_line_box(1.2), _line_box(1.2).model_copy(update={"page": 1}))
        is None
    )


def test_greedy_prefers_the_same_line_over_a_reachable_neighbour() -> None:
    """A tall labelled box (2x font size) reaches the line above too; the closer centre wins."""
    tall_label = Box(_line_box(2.0), "text")
    same_line = Box(_line_box(1.2), "text")
    line_above = Box(_line_box(1.2, baseline=BASELINE - 1.2 * FS), "text")

    matches = detection.match([line_above, same_line], [tall_label], detection.writing_spot)

    assert [(p, t) for p, t, _ in matches] == [(1, 0)]


def test_known_edge_case_a_label_halfway_between_two_lines_is_a_tie() -> None:
    """docs/decisions/phase-2.md: a 2.4x label over lines 1.2x apart is equally close to both;
    the tie goes to the lower predicted index. Pinned so a change is noticed."""
    tall_label = Box(_line_box(2.4), "text")
    same_line = Box(_line_box(1.2), "text")
    line_above = Box(_line_box(1.2, baseline=BASELINE - 1.2 * FS), "text")

    assert detection.writing_spot(same_line.bbox, tall_label.bbox) == detection.writing_spot(
        line_above.bbox, tall_label.bbox
    )
    matches = detection.match([line_above, same_line], [tall_label], detection.writing_spot)
    assert [(p, t) for p, t, _ in matches] == [(0, 0)]


def test_x_iou() -> None:
    a = BBox(page=0, x0=0, y0=0, x1=10, y1=1)
    assert detection.x_iou(a, BBox(page=0, x0=5, y0=50, x1=15, y1=60)) == pytest.approx(5 / 15)
    assert detection.x_iou(a, BBox(page=0, x0=10, y0=0, x1=20, y1=1)) == 0.0


# --- evaluate() on synthetic fixtures -----------------------------------------------------


def _label_file(
    fixture: str, stem: str, pages: list[int] | None = None, prefilled: str | None = "flat@x"
) -> LabelFile:
    """A label file whose boxes are the fixture's ground truth (labelled pages only)."""
    fx = pdfs.get(fixture)
    labelled = pages if pages is not None else sorted({f.page for f in fx.fields} or {0})
    with pymupdf.open("pdf", fx.data) as doc:
        sizes = [LabelPage(width=p.rect.width, height=p.rect.height) for p in doc]
    fields = [
        LabelField(
            id=f"p{f.page}_l{i:03d}",
            page=f.page,
            bbox=f.bbox,
            kind=LabelKind.CHECKBOX if f.kind is FieldKind.CHECKBOX else LabelKind.TEXT,
            comb=bool(f.max_chars),
        )
        for i, f in enumerate(fx.fields)
        if f.page in labelled
    ]
    return LabelFile(
        form=stem,
        pdf_sha256=hashlib.sha256(fx.data).hexdigest(),
        verified_by_human=True,
        prefilled_from=prefilled,
        source="test",
        labelled_pages=labelled,
        pages=sizes,
        fields=fields,
    )


def _setup(tmp_path: Path, forms: dict[str, tuple[str, LabelFile | None]]) -> tuple[Path, Path]:
    dataset, labels = tmp_path / "dataset" / "dev", tmp_path / "labels"
    dataset.mkdir(parents=True)
    labels.mkdir()
    for stem, (fixture, label) in forms.items():
        (dataset / f"{stem}.pdf").write_bytes(pdfs.get(fixture).data)
        if label is not None:
            (labels / f"{stem}.json").write_text(dump_label_file(label))
    return dataset, labels


def test_perfect_detector_on_a_fixture_scores_one(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path, {"02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes"))}
    )

    result = detection.evaluate(dataset, labels, "dev", "flat@test")

    totals = result.total()
    n = len(pdfs.get("flat_boxes").fields)
    assert totals.spot == totals.iou == Counts(tp=n, fp=0, fn=0)
    assert (totals.spot.precision, totals.spot.recall) == (1.0, 1.0)
    assert totals.kinds.as_dict()["recall_by_labelled_kind"]["text"]["share"] == 1.0


def test_rule_1_fixture_is_found_end_to_end(tmp_path: Path) -> None:
    """Labelling rule 1 (Step 11, fix 2): every hinted part is found under both metrics."""
    label = _label_file("flat_hinted_comb", "21_hinted", prefilled=SCRATCH)
    dataset, labels = _setup(tmp_path, {"21_hinted": ("flat_hinted_comb", label)})

    totals = detection.evaluate(dataset, labels, "dev", "flat@test").total()

    n = len(pdfs.get("flat_hinted_comb").fields)
    assert totals.spot == totals.iou == Counts(tp=n, fp=0, fn=0)


def _with_missed_spot(label: LabelFile) -> LabelFile:
    """The label file plus one labelled spot where the fixture has no entry (bottom of page 0)."""
    missed = LabelField(
        id="p0_l999", page=0, bbox=(72.0, 780.0, 200.0, 792.0), kind=LabelKind.TEXT, comb=False
    )
    return label.model_copy(update={"fields": [*label.fields, missed]})


def test_partial_labels_ocr_pages_and_forms_without_labels(tmp_path: Path) -> None:
    # mixed_mostly_flat: pages 0 and 1 are OK, page 2 is garbled.
    partial = _label_file("mixed_mostly_flat", "01_mixed", pages=[0, 2])
    dataset, labels = _setup(
        tmp_path,
        {"01_mixed": ("mixed_mostly_flat", partial), "06_lines": ("flat_lines", None)},
    )

    result = detection.evaluate(dataset, labels, "dev", "flat@test")

    (form,) = result.forms
    assert form.scored_pages == [0]
    assert form.ocr_pages == [2]
    assert form.unlabelled_pages == [1]
    assert result.forms_without_labels == ["06_lines"]
    assert form.at_match == Counts(tp=2, fp=0, fn=0)  # page 1's predictions are not counted


def test_anchoring_check_separates_scratch_and_prefilled(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path,
        {
            "02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes")),
            "21_hinted": (
                "flat_hinted_comb",
                _with_missed_spot(_label_file("flat_hinted_comb", "21_hinted", prefilled=SCRATCH)),
            ),
        },
    )

    result = detection.evaluate(dataset, labels, "dev", "flat@test")

    scratch = result.total(prefilled=False).spot
    prefilled = result.total(prefilled=True).spot
    assert prefilled.recall == 1.0
    assert scratch.recall is not None and scratch.recall < 1.0
    assert scratch.tp + prefilled.tp == result.total().spot.tp


def test_labels_for_another_pdf_are_rejected(tmp_path: Path) -> None:
    label = _label_file("flat_boxes", "02_boxes").model_copy(update={"pdf_sha256": "0" * 64})
    dataset, labels = _setup(tmp_path, {"02_boxes": ("flat_boxes", label)})

    with pytest.raises(detection.EvalError, match="different PDF"):
        detection.evaluate(dataset, labels, "dev", "flat@test")


def test_label_file_without_pdf_is_rejected(tmp_path: Path) -> None:
    dataset, labels = _setup(tmp_path, {})
    (labels / "99_ghost.json").write_text(dump_label_file(_label_file("flat_boxes", "99_ghost")))

    with pytest.raises(detection.EvalError, match="without a PDF"):
        detection.evaluate(dataset, labels, "dev", "flat@test")


# --- labelling subset ---------------------------------------------------------------------


def test_pages_outside_the_subset_are_listed_and_not_scored(tmp_path: Path) -> None:
    # mixed_mostly_flat: pages 0 and 1 are OK, page 2 is garbled; all three marked labelled.
    label = _label_file("mixed_mostly_flat", "01_mixed", pages=[0, 1, 2])
    dataset, labels = _setup(tmp_path, {"01_mixed": ("mixed_mostly_flat", label)})

    result = detection.evaluate(dataset, labels, "dev", "flat@test", subset={"01_mixed": (1,)})

    (form,) = result.forms
    assert form.scored_pages == [0]
    assert form.outside_subset == [1, 2]
    assert (form.ocr_pages, form.unlabelled_pages) == ([], [])
    assert form.at_match == Counts(tp=2, fp=0, fn=0)  # pages 1 and 2 count for nothing
    markdown = detection.report_markdown(result)
    assert "01_mixed: labelled pages 2, 3 are outside the labelling subset" in markdown
    assert "01_mixed page 1." in markdown
    data = detection.report_json(result)
    assert data["subset_pages_1based"] == {"01_mixed": [1]}
    assert data["forms"][0]["labelled_outside_subset_not_scored"] == [2, 3]  # type: ignore[index]


def test_subset_page_without_labels_is_listed_as_not_labelled(tmp_path: Path) -> None:
    label = _label_file("mixed_mostly_flat", "01_mixed", pages=[0])
    dataset, labels = _setup(tmp_path, {"01_mixed": ("mixed_mostly_flat", label)})

    result = detection.evaluate(dataset, labels, "dev", "flat@test", subset={"01_mixed": ALL})

    (form,) = result.forms
    assert (form.scored_pages, form.unlabelled_pages, form.outside_subset) == ([0], [1], [])


def test_form_missing_from_the_subset_is_not_scored(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path,
        {
            "02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes")),
            "06_lines": ("flat_lines", _label_file("flat_lines", "06_lines")),
        },
    )

    result = detection.evaluate(dataset, labels, "dev", "flat@test", subset={"02_boxes": ALL})

    boxes, lines = result.forms
    assert boxes.scored_pages == [0]
    assert (lines.scored_pages, lines.outside_subset) == ([], [0])
    assert result.total().spot == boxes.at_spot


def test_subset_errors_stop_the_run(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path, {"02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes"))}
    )

    with pytest.raises(detection.EvalError, match=r"outside 1\.\.1"):
        detection.evaluate(dataset, labels, "dev", "flat@test", subset={"02_boxes": (2,)})
    with pytest.raises(detection.EvalError, match="without a PDF"):
        detection.evaluate(dataset, labels, "dev", "flat@test", subset={"99_ghost": ALL})


def test_dev_subset_is_the_human_decision_in_zero_based_pages() -> None:
    """Human, 2026-10-17: #1 pages 1 and 4, #3 page 2, nine forms in full; with labels v5
    (human, 2026-10-22) #1 pages 5, 8 and 9 too, the held-out check of rule 3."""
    assert subset_pages(DEV_SUBSET, "01_sbi_account_opening_form", 9) == {0, 3, 4, 7, 8}
    assert subset_pages(DEV_SUBSET, "03_sbi_kyc_annexure_b", 2) == {1}
    full = {form for form, pages in DEV_SUBSET.items() if pages == ALL}
    assert {form[:2] for form in full} == {"02", "06", "21", "23", "25", "30", "32", "39", "41"}
    assert subset_pages(DEV_SUBSET, "37_aees_joining_report", 1) == frozenset()


# --- reports ------------------------------------------------------------------------------


def test_reports_carry_the_numbers_and_the_dataset_notes(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path,
        {
            "02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes")),
            "21_hinted": (
                "flat_hinted_comb",
                _label_file("flat_hinted_comb", "21_hinted", prefilled=SCRATCH),
            ),
            "06_lines": ("flat_lines", None),
        },
    )
    result = detection.evaluate(dataset, labels, "dev", "flat@abc1234")

    json_path, md_path = detection.write_reports(result, tmp_path / "reports")

    assert json_path.name.startswith("phase2-detection-dev-") and json_path.name.endswith(
        "-abc1234.json"
    )
    data = json.loads(json_path.read_text())
    totals = result.total()
    for key, counts in (("writing_spot", totals.spot), ("iou_0.5", totals.iou)):
        overall = data["overall"][key]
        assert (overall["tp"], overall["fp"], overall["fn"]) == (counts.tp, counts.fp, counts.fn)
    assert data["primary_metric"] == "writing_spot"
    assert set(data["anchoring_check"]) == {"from_scratch", "prefilled"}
    assert data["forms_without_labels"] == ["06_lines"]
    assert data["dataset_notes"] == detection.DATASET_NOTES
    per_form = {f["form"]: f["writing_spot"] for f in data["forms"]}
    expected = macro([Counts(v["tp"], v["fp"], v["fn"]) for v in per_form.values()])
    assert data["overall"]["macro"]["writing_spot"] == expected.as_dict()
    assert data["anchoring_check"]["from_scratch"]["macro"]["writing_spot"]["forms_recall"] == 1
    markdown = md_path.read_text()
    for heading in (
        "## Overall",
        "## Macro average",
        "## By kind (writing spot)",
        "## Anchoring check",
        "## Per form",
        "## Not scored",
    ):
        assert heading in markdown
    assert "no Hindi-only form" in markdown
    assert "06_lines: no label file" in markdown
    assert "21_hinted (from scratch)" in markdown


def test_macro_weights_every_form_equally() -> None:
    big, small = Counts(tp=90, fp=10, fn=0), Counts(tp=1, fp=1, fn=3)

    # Pooled: 91 / 102 and 91 / 94, mostly the big form; macro: the mean of 0.9 and 0.5, of 1.0
    # and 0.25.
    assert macro([big, small]) == Macro(
        precision=0.7, recall=0.625, forms_precision=2, forms_recall=2
    )


def test_macro_leaves_out_undefined_values() -> None:
    no_predictions = Counts(tp=0, fp=0, fn=4)  # recall 0, no precision
    no_labels = Counts(tp=0, fp=2, fn=0)  # precision 0, no recall
    nothing = Counts()  # no scored boxes at all

    result = macro([Counts(tp=3, fp=1, fn=1), no_predictions, no_labels, nothing])

    assert result == Macro(precision=0.375, recall=0.375, forms_precision=2, forms_recall=2)
    assert macro([]) == Macro(precision=None, recall=None, forms_precision=0, forms_recall=0)


def test_report_without_labels_says_nothing_was_scored(tmp_path: Path) -> None:
    dataset, labels = _setup(tmp_path, {"06_lines": ("flat_lines", None)})
    result = detection.evaluate(dataset, labels, "dev", "flat@test")

    markdown = detection.report_markdown(result)

    assert "No label files yet" in markdown
    assert "## Dataset notes" in markdown


def test_cli_allows_only_the_dev_split(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        detection.main(["--split", "test", "--out", str(tmp_path)])


def test_cli_writes_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dataset, labels = _setup(
        tmp_path, {"02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes"))}
    )
    monkeypatch.setattr(detection, "DEV_SUBSET", {"02_boxes": ALL})  # the CLI always applies it

    code = detection.main(
        [
            "--dataset-root",
            str(dataset.parent),
            "--labels",
            str(labels),
            "--out",
            str(tmp_path / "r"),
        ]
    )

    assert code == 0
    (report,) = (tmp_path / "r").glob("phase2-detection-dev-*.json")
    assert json.loads(report.read_text())["subset_pages_1based"] == {"02_boxes": "all"}


def test_tag_names_the_report_files_and_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset, labels = _setup(
        tmp_path, {"02_boxes": ("flat_boxes", _label_file("flat_boxes", "02_boxes"))}
    )
    monkeypatch.setattr(detection, "DEV_SUBSET", {"02_boxes": ALL})
    args = ["--dataset-root", str(dataset.parent), "--labels", str(labels)]

    code = detection.main([*args, "--out", str(tmp_path / "r"), "--tag", "pre-step11-tuning"])

    assert code == 0
    (md,) = (tmp_path / "r").glob("phase2-detection-dev-pre-step11-tuning-*.md")
    assert md.read_text().startswith("# Detection eval — dev split — pre-step11-tuning")
    (js,) = (tmp_path / "r").glob("phase2-detection-dev-pre-step11-tuning-*.json")
    assert json.loads(js.read_text())["tag"] == "pre-step11-tuning"
    with pytest.raises(SystemExit):
        detection.main([*args, "--out", str(tmp_path / "r"), "--tag", "../escape"])


def test_cli_stops_when_the_subset_does_not_match_the_dataset(tmp_path: Path) -> None:
    dataset, labels = _setup(tmp_path, {"02_boxes": ("flat_boxes", None)})

    code = detection.main(
        ["--dataset-root", str(dataset.parent), "--labels", str(labels), "--out", str(tmp_path)]
    )

    assert code == 1  # DEV_SUBSET names forms that this dataset does not have


def test_forms_without_ok_pages_are_listed_as_needing_ocr(tmp_path: Path) -> None:
    dataset, labels = _setup(
        tmp_path,
        {"06_lines": ("flat_lines", None), "38_scan": ("text_layer_image_only", None)},
    )

    result = detection.evaluate(dataset, labels, "dev", "flat@test")

    assert result.forms_without_labels == ["06_lines"]
    assert result.forms_without_ok_pages == ["38_scan"]
    assert "38_scan: no page with a usable text layer" in detection.report_markdown(result)
