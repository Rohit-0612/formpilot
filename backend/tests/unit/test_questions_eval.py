"""Questions eval (eval/questions_eval.py) on the understanding-eval fixture.

No real form, label, persona or model is used. The fixture form flat_boxes has Email, Remarks,
Bank name, Branch and IFSC; the rules type all but Remarks, which the scripted model calls a
full name (wrong: its reference is `other`) at 0.97, below the fill threshold.
"""

import json
from pathlib import Path

from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest
from eval import questions_eval, run_eval
from tests.unit.test_run_eval import FORM, folders  # noqa: F401 - pytest fixture

PERSONA = {"full_name": "Asha Verma", "email": "asha.verma@example.com"}


def _model(request: LLMRequest) -> str:
    fields = json.loads(request.user.split("\n\n")[0])["fields"]
    return json.dumps(
        {
            "fields": [
                {"id": f["id"], "semantic_type": "full_name", "confidence": 0.97,
                 "question_en": "Any remarks?"}
                for f in fields
            ]
        }
    )  # fmt: skip


def _result(folders: tuple[Path, Path, Path]) -> run_eval.EvalResult:  # noqa: F811
    """The eval run, with the model's English question on its fields (as the understanding pass
    stores it, P5-D6), so these tests do not depend on the prompt version."""
    dataset, labels, references = folders
    result = run_eval.evaluate(
        dataset, labels, references, "dev", "hybrid", FakeProvider(_model), {FORM: "all"},
        "flat@test",
    )  # fmt: skip
    for form in result.forms:
        if form.understood is not None:
            fields = [
                f.model_copy(update={"question_text": "Any remarks?"})
                if f.semantic_method == "llm"
                else f
                for f in form.understood.fields
            ]
            form.understood = form.understood.model_copy(update={"fields": fields})
    return result


def test_suggestions_per_floor(folders: tuple[Path, Path, Path]) -> None:  # noqa: F811
    result = _result(folders)

    at_95 = questions_eval.suggestions(result, PERSONA, 0.95)
    at_98 = questions_eval.suggestions(result, PERSONA, 0.98)

    assert (at_95["suggested"], at_95["compared"], at_95["right_type"]) == (1, 1, 0)
    assert at_95["right_type_rate"] == 0.0
    assert at_95["questions_after"] == at_95["questions_before"] - 1  # type: ignore[operator]
    assert at_98["suggested"] == 0 and at_98["right_type_rate"] is None


def test_questions_per_form_before_and_after(folders: tuple[Path, Path, Path]) -> None:  # noqa: F811
    counts = questions_eval.questions_per_form(_result(folders), PERSONA)[FORM]

    assert counts["m3"]["fields_needing_input"] == counts["m2"]["fields_needing_input"] - 1
    assert counts["m3"]["cards"] <= counts["m2"]["cards"]
    assert counts["m2"]["inputs"] >= counts["m2"]["cards"]


def test_readability_counts_sources_and_never_finds_unreadable_text(
    folders: tuple[Path, Path, Path],  # noqa: F811
) -> None:
    read = questions_eval.readability(_result(folders), {})  # empty profile: Remarks is asked

    assert read["texts_not_readable"] == 0
    assert read["sources"]["model question"] == 1  # type: ignore[index]


def test_judgments_are_read_and_stale_ones_reported(
    folders: tuple[Path, Path, Path],  # noqa: F811
    tmp_path: Path,
) -> None:
    current = questions_eval.sample(_result(folders), {})
    assert [item["question"] for item in current] == ["Any remarks?"]
    key = current[0]["key"]
    (tmp_path / "judged-dev.json").write_text(
        json.dumps(
            {
                "judged_by": "test",
                "items": {
                    key: {"question": "Any remarks?", "faithful": True, "note": ""},
                    "other/p0_f001": {"question": "Old?", "faithful": False, "note": "asks X"},
                },
            }
        )
    )

    judged = questions_eval.judged(current, tmp_path)

    assert judged is not None
    assert (judged["judged"], judged["faithful"]) == (2, 1)
    assert judged["stale"] == ["other/p0_f001"]
    assert judged["unfaithful"] == {"other/p0_f001": "asks X"}
    assert questions_eval.judged(current, tmp_path / "missing") is None


def test_the_report_discloses_the_labels_and_the_floor_in_use(
    folders: tuple[Path, Path, Path],  # noqa: F811
) -> None:
    result = _result(folders)
    data = {
        "split": "dev", "provider": result.provider, "detector": "flat@test",
        "created_at": result.created_at, "tag": None,
        "suggestions": [questions_eval.suggestions(result, PERSONA, f)
                        for f in questions_eval.FLOORS],
        "questions_per_form": {"p": questions_eval.questions_per_form(result, PERSONA)},
        "readability": questions_eval.readability(result, PERSONA), "faithfulness": None,
    }  # fmt: skip

    text = questions_eval.markdown(data)

    assert run_eval.DISCLOSURE in text
    assert f"≥ {questions_eval.CHOSEN_FLOOR} **(in use)**" in text
    assert "Faithfulness sample: not judged yet." in text
