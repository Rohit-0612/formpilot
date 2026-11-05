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


def _row_result(city_reference: str = "current_city") -> run_eval.EvalResult:
    """A guardian's name in FIRST | MIDDLE | LAST boxes and a city the LLM typed at 0.96."""
    import uuid

    from app.ir.models import BBox, Field, FieldKind, FormIR, PageInfo, SourceKind, TextLayer
    from app.ir.semantic_types import SemanticType as T

    def field(i: int, t: T, label: str, method: str, confidence: float, x: float) -> Field:
        return Field(
            id=f"p0_f{i:03d}", kind=FieldKind.TEXT, native_name=None, label_text=label,
            context_text=None, bbox=BBox(page=0, x0=x, y0=370, x1=x + 150, y1=383),
            semantic_type=t, semantic_method=method, semantic_confidence=confidence,
        )  # fmt: skip

    fields = [
        field(0, T.GUARDIAN_NAME, "9.Name of Guardian", "rule", 0.95, 72),
        field(1, T.MIDDLE_NAME, "MIDDLE NAME", "rule", 0.95, 222),
        field(2, T.LAST_NAME, "LAST NAME", "rule", 0.95, 372),
        field(3, T.CURRENT_CITY, "City", "llm", 0.96, 72).model_copy(
            update={"bbox": BBox(page=0, x0=72, y0=420, x1=222, y1=433)}
        ),
    ]
    ir = FormIR(
        document_id=uuid.uuid4(), source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)], fields=fields,
    )  # fmt: skip
    refs = [T.GUARDIAN_NAME, T.GUARDIAN_NAME, T(city_reference)]
    compared = [
        run_eval.Compared(
            form="f",
            field_id=f"p0_l{i:03d}",
            reference=ref,
            predicted=fields[i].semantic_type,
            method=fields[i].semantic_method,
            no_fill_reason=None,
            predicted_id=fields[i].id,
            confidence=fields[i].semantic_confidence,
        )
        for i, ref in zip((0, 2, 3), refs, strict=True)
    ]
    form = run_eval.FormResult(form="f", from_scratch=False, compared=compared, understood=ir)
    return run_eval.EvalResult("dev", "hybrid", "flat@test", "fake", "2026-11-05", [form])


GUARDIAN = {
    "guardian_name": "Ramesh Verma",
    "current_city": "Pune",
    "current_district": "Haveli",
    "middle_name": "Kumari",
}


def test_a_suggestion_is_not_a_fill() -> None:
    """P5-D17: the split guardian name is suggested; only the old definition counted it."""
    policy = fill_eval.CANDIDATES[fill_eval.PRODUCT_POLICY]

    new = fill_eval.score(_row_result(), GUARDIAN, policy)
    old = fill_eval.score(_row_result(), GUARDIAN, policy, count_suggested=True)

    assert new.filled == 0
    assert (old.filled, old.type_correct, old.value_right) == (2, 1, 0)


def test_suggestions_are_scored_against_the_personas_matching_part() -> None:
    policy = fill_eval.CANDIDATES[fill_eval.PRODUCT_POLICY]

    right = fill_eval.suggestions(_row_result(), GUARDIAN, policy)
    wrong = fill_eval.suggestions(_row_result("current_district"), GUARDIAN, policy)

    # FIRST <- "Ramesh", LAST <- "Verma" (the guardian's, not the applicant's), city <- Pune;
    # the city box where the reference wants the district is a wrong suggestion
    assert right == fill_eval.SuggestionScore(suggested=3, right=3)
    assert wrong.as_dict()["suggestion_precision"] == 2 / 3
