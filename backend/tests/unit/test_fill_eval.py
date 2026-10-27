"""Fill eval (eval/fill_eval.py) on the understanding-eval fixture, and its selection rule.

No real form, label, persona or model is used.
"""

import json
from pathlib import Path

from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest
from app.passes.match import FillPolicy
from eval import fill_eval, run_eval
from eval.fill_eval import FillScore, choose
from tests.unit.test_run_eval import FORM, folders  # noqa: F401 - pytest fixture

PERSONA = {
    "email": "asha.verma@example.com",
    "bank_name": "Example Bank",
    "bank_branch": "Camp, Pune",
    "ifsc": "EXAM0001234",
    "full_name": "Asha Verma",
}


def _typed(request: LLMRequest) -> str:
    """The model types every field it is asked about as `other` (the rules type the rest)."""
    fields = json.loads(request.user.split("\n\n")[0])["fields"]
    return json.dumps(
        {"fields": [{"id": f["id"], "semantic_type": "other", "confidence": 0.99} for f in fields]}
    )


def _result(folders: tuple[Path, Path, Path]) -> run_eval.EvalResult:  # noqa: F811
    dataset, labels, references = folders
    return run_eval.evaluate(
        dataset,
        labels,
        references,
        "dev",
        "hybrid",
        FakeProvider(_typed),
        {FORM: "all"},
        "flat@test",
    )


def test_rule_fills_are_scored_by_type_and_value(folders: tuple[Path, Path, Path]) -> None:  # noqa: F811
    result = _result(folders)

    s = fill_eval.score(result, PERSONA, FillPolicy(min_llm_confidence=None))

    # rules type email, bank_name, bank_branch, ifsc (the account box: wrong) -> 4 filled
    assert s == FillScore(filled=4, type_correct=3, value_correct=3, fillable=4, value_right=3)
    assert s.as_dict()["fill_precision"] == 0.75 and s.as_dict()["coverage"] == 0.75
    assert s.as_dict()["value_precision"] == 0.75


def test_a_persona_without_the_value_fills_nothing(folders: tuple[Path, Path, Path]) -> None:  # noqa: F811
    s = fill_eval.score(_result(folders), {"full_name": "A"}, FillPolicy())

    assert s.filled == 0 and s.as_dict()["fill_precision"] is None


def test_choose_takes_the_widest_candidate_meeting_the_target() -> None:
    scores = {
        "a": FillScore(filled=100, type_correct=80, value_correct=80, fillable=200),
        "b": FillScore(filled=60, type_correct=54, value_correct=54, fillable=200),
        "c": FillScore(filled=50, type_correct=48, value_correct=48, fillable=200),
    }

    assert choose(scores) == ("b", True)  # b and c meet 85 %; b covers more


def test_choose_falls_back_to_the_most_precise_wide_enough_candidate() -> None:
    scores = {
        "a": FillScore(filled=100, type_correct=70, value_correct=70, fillable=200),
        "b": FillScore(filled=60, type_correct=48, value_correct=48, fillable=200),
        "c": FillScore(filled=25, type_correct=21, value_correct=21, fillable=200),
    }

    # none reaches 85 %; c (84 %) covers only 10.5 %, so b (80 %) beats a (70 %)
    assert choose(scores) == ("b", False)


def test_candidates_are_fixed_before_the_run() -> None:
    assert len(fill_eval.CANDIDATES) == 9
    assert fill_eval.TARGET_PRECISION == 0.85 and fill_eval.MIN_COVERAGE == 0.20
