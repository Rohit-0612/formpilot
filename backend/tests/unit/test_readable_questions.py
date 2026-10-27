"""Readable questions (decision P5-D6) and section cards (Phase 5). Synthetic fields only."""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    PageInfo,
    SourceKind,
    TextLayer,
    ValueSource,
)
from app.ir.phrases import readable_english
from app.ir.semantic_types import SemanticType as T
from app.passes import answers
from app.passes.answers import Answer
from app.passes.context import PassContext
from app.passes.match import FillPolicy
from app.passes.questions import MAX_SECTION_PARTS, SECTION, InputKind, plan

POLICY = FillPolicy(min_llm_confidence=0.99)
NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
GARBLED = "प्रार्ी का नाम ( वहन्दी में )"  # dev form #30's text layer


def _f(i: int, label: str | None, context: str | None = None, **extra: Any) -> Field:
    return Field(
        id=f"p0_f{i:03d}", kind=extra.pop("kind", FieldKind.TEXT), native_name=None,
        label_text=label, context_text=context,
        bbox=BBox(page=0, x0=10, y0=10 + 20 * i, x1=200, y1=24 + 20 * i),
        semantic_type=extra.pop("t", T.OTHER), semantic_method=extra.pop("semantic_method", "llm"),
        semantic_confidence=0.9,
        status=FieldStatus.NEEDS_INPUT, **extra,
    )  # fmt: skip


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def test_the_models_english_question_is_the_main_text_and_the_label_goes_below() -> None:
    field = _f(2, GARBLED, question_text="What is your name, written in Hindi?")

    (question,) = plan(_ir(field), POLICY)

    assert question.prompt == "What is your name, written in Hindi?"
    assert question.form_text == GARBLED
    assert question.parts[0].label == "What is your name, written in Hindi?"
    assert question.parts[0].form_label == GARBLED


def test_without_an_english_question_a_garbled_label_is_never_the_main_text() -> None:
    garbled = _f(4, GARBLED)
    checkbox = _f(5, "विकलांग", kind=FieldKind.CHECKBOX)
    unlabelled = _f(6, None)

    questions = plan(_ir(garbled, checkbox, unlabelled), POLICY)

    assert [q.prompt for q in questions] == [
        "What goes in box 5 on page 1?",
        "Do you tick box 6 on page 1?",
        "What goes in box 7 on page 1?",
    ]
    assert [q.form_text for q in questions] == [GARBLED, "विकलांग", None]
    assert all(readable_english(q.prompt) for q in questions)


def test_a_readable_english_label_is_still_quoted() -> None:
    (question,) = plan(_ir(_f(0, "Policy No.")), POLICY)

    assert question.prompt == "The form asks: “Policy No.”. What should go here?"
    assert question.form_text is None and question.parts[0].form_label is None


def test_fields_under_one_heading_become_one_section_card() -> None:
    heading = "Details of the Nominee"
    fields = [
        _f(0, "Name", heading),
        _f(1, "Relationship", heading),
        _f(2, "Date of birth", heading, t=T.DATE_OF_BIRTH),
        _f(3, "Policy No.", "Policy details"),  # alone under its heading: a single question
        _f(4, None, t=T.EMAIL, semantic_method="rule"),  # typed: never in a card
    ]

    questions = plan(_ir(*fields), POLICY)

    assert [(q.id, q.group) for q in questions] == [
        ("q_sec_p0_f000", SECTION),
        ("q_p0_f003", None),
        ("q_p0_f004", None),
    ]
    card = questions[0]
    assert card.prompt == heading and card.form_text is None
    assert [p.field_ids for p in card.parts] == [["p0_f000"], ["p0_f001"], ["p0_f002"]]
    assert card.parts[2].input is InputKind.DATE
    assert not card.can_save and not card.free_text


def test_a_garbled_heading_is_not_the_cards_title_and_cards_are_capped() -> None:
    fields = [_f(i, f"Item {i}", "(कायाथलय उपयोग हेतु)") for i in range(MAX_SECTION_PARTS + 1)]

    questions = plan(_ir(*fields), POLICY)

    assert [len(q.parts) for q in questions] == [MAX_SECTION_PARTS, 1]
    assert questions[0].prompt == f"{MAX_SECTION_PARTS} boxes in one section of page 1"
    assert questions[0].form_text == "(कायाथलय उपयोग हेतु)"
    assert questions[1].group is None


def test_a_section_card_is_answered_part_by_part_with_field_ids() -> None:
    heading = "Details of the Nominee"
    ir = _ir(_f(0, "Name", heading), _f(1, "Relationship", heading), _f(2, "Age", heading))
    (card,) = plan(ir, POLICY)

    out = answers.run(
        ir,
        PassContext(clock=lambda: NOW),
        [Answer(question_id=card.id, parts={"p0_f000": "Ravi Kumar", "p0_f002": "34"})],
        [card],
    )

    assert [f.value for f in out.fields] == ["Ravi Kumar", None, "34"]
    assert out.fields[0].value_source is ValueSource.USER_ANSWER
    assert [f.status for f in out.fields] == [
        FieldStatus.FILLED,
        FieldStatus.NEEDS_INPUT,
        FieldStatus.FILLED,
    ]
