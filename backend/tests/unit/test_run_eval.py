"""Understanding eval (eval/run_eval.py) on a synthetic fixture with a fake model.

No real form, label or model is used: the label and reference files are written into tmp folders.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.llm.cache import CachedProvider
from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest
from eval import run_eval
from eval.labelling.schema import (
    LabelField,
    LabelFile,
    LabelKind,
    LabelPage,
    SemanticReference,
    dump_label_file,
    dump_reference,
)
from tests.fixtures import pdfs

FORM = "02_flat_boxes"
# flat_boxes as detected (Email, Remarks, Bank name, Branch, IFSC), plus one box it cannot find.
BOXES = [
    (160, 116, 450, 134),
    (72, 178, 520, 238),
    (200, 320, 450, 340),
    (200, 340, 450, 360),
    (200, 360, 450, 380),
    (72, 600, 300, 620),
]
REFERENCE = ["email", "other", "bank_name", "bank_branch", "bank_account_number", "full_name"]


def _other_for_everything(request: LLMRequest) -> str:
    ids = [f["id"] for f in json.loads(request.user.split("\n\n")[0])["fields"]]
    return json.dumps(
        {"fields": [{"id": i, "semantic_type": "other", "confidence": 0.9} for i in ids]}
    )


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path, Path]:
    dataset, labels, references = tmp_path / "dataset", tmp_path / "labels", tmp_path / "ref"
    for folder in (dataset, labels, references):
        folder.mkdir()
    data = pdfs.get("flat_boxes").data
    (dataset / f"{FORM}.pdf").write_bytes(data)
    fields = [
        LabelField(id=f"p0_l{i:03d}", page=0, bbox=box, kind=LabelKind.TEXT)
        for i, box in enumerate(BOXES)
    ]
    label_file = LabelFile(
        form=FORM,
        pdf_sha256=hashlib.sha256(data).hexdigest(),
        verified_by_human=True,
        prefilled_from="flat@test",
        source="test",
        labelled_pages=[0],
        pages=[LabelPage(width=595, height=842)],
        fields=fields,
    )
    (labels / f"{FORM}.json").write_text(dump_label_file(label_file))
    reference = SemanticReference(
        form=FORM,
        label_file_sha256=hashlib.sha256((labels / f"{FORM}.json").read_bytes()).hexdigest(),
        labelled_by="test",
        labels={f.id: t for f, t in zip(fields, REFERENCE, strict=True)},
    )
    (references / f"{FORM}.json").write_text(dump_reference(reference))
    return dataset, labels, references


def _run(folders: tuple[Path, Path, Path], mode: str, provider: object) -> run_eval.EvalResult:
    dataset, labels, references = folders
    return run_eval.evaluate(
        dataset,
        labels,
        references,
        "dev",
        mode,
        provider,
        {FORM: "all"},
        "flat@test",  # type: ignore[arg-type]
    )


def test_hybrid_scores_matched_fields_against_the_reference(
    folders: tuple[Path, Path, Path],
) -> None:
    provider = FakeProvider(_other_for_everything)

    m = run_eval.metrics(_run(folders, "hybrid", provider))

    assert m["overall"]["all"] == {"correct": 4, "total": 5, "accuracy": 0.8}  # type: ignore[index]
    assert m["overall"]["fillable"] == {"correct": 3, "total": 4, "accuracy": 0.75}  # type: ignore[index]
    assert m["not_detected"] == 1
    assert m["by_method"]["llm"] == {"correct": 1, "total": 1, "accuracy": 1.0}  # type: ignore[index]
    assert m["confusions"] == [
        {"reference": "bank_account_number", "predicted": "ifsc", "count": 1}
    ]
    assert m["prefilled"]["all"]["total"] == 5 and m["from_scratch"]["all"]["total"] == 0  # type: ignore[index]


def test_rules_mode_never_asks_the_model(folders: tuple[Path, Path, Path]) -> None:
    m = run_eval.metrics(_run(folders, "rules", None))

    assert m["overall"]["all"]["correct"] == 3  # type: ignore[index]
    assert m["predicted_unknown"] == 1


def test_replay_that_misses_the_cache_refuses_to_score(
    folders: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    replay = CachedProvider(FakeProvider([]), tmp_path / "cache", "replay")

    with pytest.raises(run_eval.EvalError, match="not in the cache"):
        _run(folders, "hybrid", replay)


def test_record_then_replay_gives_the_same_numbers(
    folders: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    cache = tmp_path / "cache"
    recorded = _run(
        folders, "hybrid", CachedProvider(FakeProvider(_other_for_everything), cache, "record")
    )
    silent = FakeProvider([])  # replay must never ask the model
    replayed = _run(folders, "hybrid", CachedProvider(silent, cache, "replay"))

    assert run_eval.metrics(replayed) == run_eval.metrics(recorded)
    assert silent.requests == []


def test_reference_for_another_label_file_version_is_refused(
    folders: tuple[Path, Path, Path],
) -> None:
    _, labels, _ = folders
    (labels / f"{FORM}.json").write_text((labels / f"{FORM}.json").read_text() + "\n")

    with pytest.raises(run_eval.EvalError, match="another version of the label file"):
        _run(folders, "rules", None)


def test_reports_say_the_reference_labels_are_claude_written(
    folders: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    result = _run(folders, "hybrid", FakeProvider(_other_for_everything))
    result.tag = "unit"

    json_path, md_path = run_eval.write_reports(result, tmp_path / "reports")

    assert json_path.name.startswith("phase3-understanding-dev-hybrid-unit-")
    assert json.loads(json_path.read_text())["reference_labels"] == run_eval.DISCLOSURE
    assert run_eval.DISCLOSURE in md_path.read_text()
    assert "| All forms | 80.0 % (4/5) | 75.0 % (3/4) |" in md_path.read_text()
