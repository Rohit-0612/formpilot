"""The UX metric (eval/ux_eval.py): actions to complete one form, now and with the M3 features
turned off. Synthetic fields and values only."""

from app.ir.models import FormIR
from app.ir.semantic_types import SemanticType as T
from app.passes.questions import CHOICES, InputKind, Question, QuestionPart
from eval import ux_eval
from tests.unit.test_suggestions import PROFILE, _f, _ir


def _form() -> FormIR:
    return _ir(
        _f(0, T.FULL_NAME, 0.98),  # suggested now; asked before
        _f(1, T.FATHER_NAME, 0.97),  # suggested now; asked before
        _f(2, T.DATE_OF_BIRTH, 0.99),  # filled from the profile
        _f(3, T.OTHER, 0.95),  # asked: a label question
        _f(4, T.PHONE_MOBILE, 0.95, "rule", width=20),  # filled, but too long for its box
    )


def test_actions_now_count_cards_suggestions_review_confirm_all_and_render() -> None:
    assert ux_eval.after(_form(), PROFILE) == {
        "cards": 1, "suggestions": 2, "review": 1, "confirm_all": 1, "render": 1,
        "actions": 6, "inputs": 1,
    }  # fmt: skip


def test_actions_before_ask_the_suggestions_and_confirm_every_value_one_by_one() -> None:
    """Before: the two names are asked; the date, the label answer and the two names are each
    confirmed by hand (4); the phone that needs review is counted once, as now."""
    assert ux_eval.before(_form(), PROFILE) == {
        "cards": 3, "suggestions": 0, "review": 1, "confirm_all": 0, "render": 1,
        "confirm_one_by_one": 4, "actions": 9, "inputs": 3,
    }  # fmt: skip


def _question(group: str | None, *field_ids: str) -> Question:
    part = QuestionPart(
        field_ids=list(field_ids), semantic_type=None, label="Which one?", input=InputKind.CHOICE
    )
    return Question(id="q", prompt="Which one?", group=group, parts=[part])


def test_a_choice_card_fills_one_box_and_other_cards_fill_all_their_fields() -> None:
    choice = _question(CHOICES, "p0_f000", "p0_f001", "p0_f002")
    row = _question("table_row", "p0_f003", "p0_f004")

    assert ux_eval._answered([choice, row]) == 1 + 2


def test_the_report_says_the_before_figure_is_recomputed() -> None:
    counts = {"before": ux_eval.before(_form(), PROFILE), "after": ux_eval.after(_form(), PROFILE)}
    data = {
        "detector": "flat@test", "provider": "fake", "persona": "p", "policy": "x",
        "suggest_min_confidence": 0.95, "created_at": "now", "tag": None,
        "before_note": ux_eval.BEFORE_NOTE, "forms": {"f": counts}, "total": counts,
    }  # fmt: skip

    text = ux_eval.markdown(data)

    assert "not a historical M2 measurement" in text
    assert "| f | 9 | 6 |" in text
    assert "Verma" not in text
