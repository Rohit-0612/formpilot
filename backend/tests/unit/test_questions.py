"""Question planning (SPEC §6.4). Synthetic fields only."""

import uuid
from typing import Literal

from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    Option,
    PageInfo,
    SourceKind,
    TextLayer,
)
from app.ir.semantic_types import SemanticType as T
from app.passes.match import FillPolicy
from app.passes.questions import InputKind, plan

POLICY = FillPolicy(min_llm_confidence=0.95)


def _f(
    i: int,
    t: T,
    method: Literal["rule", "llm", "none"] = "rule",
    confidence: float = 0.95,
    **extra: object,
) -> Field:
    return Field(
        id=f"p0_f{i:03d}",
        kind=extra.pop("kind", FieldKind.TEXT),  # type: ignore[arg-type]
        native_name=None,
        label_text=extra.pop("label", f"label {i}"),  # type: ignore[arg-type]
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10 + 20 * i, x1=200, y1=24 + 20 * i),
        semantic_type=t,
        semantic_method=method,
        semantic_confidence=confidence,
        status=extra.pop("status", FieldStatus.NEEDS_INPUT),  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def test_address_fields_become_one_group_question_that_takes_free_text() -> None:
    ir = _ir(
        _f(0, T.CURRENT_CITY),
        _f(1, T.FULL_NAME),
        _f(2, T.CURRENT_ADDRESS_LINE1),
        _f(3, T.CURRENT_PINCODE),
    )

    questions = plan(ir, POLICY)

    assert [q.id for q in questions] == ["q_current_address_p0_f000", "q_p0_f001"]
    address = questions[0]
    assert address.free_text and address.can_save
    assert [p.semantic_type for p in address.parts] == [
        T.CURRENT_ADDRESS_LINE1,
        T.CURRENT_CITY,
        T.CURRENT_PINCODE,
    ]
    assert questions[1].prompt == "What is your full name?"


def test_a_group_with_a_sensitive_type_never_takes_free_text() -> None:
    bank = plan(_ir(_f(0, T.BANK_NAME), _f(1, T.BANK_ACCOUNT_NUMBER), _f(2, T.IFSC)), POLICY)[0]

    assert bank.group == "bank" and not bank.free_text
    assert [p.sensitive for p in bank.parts] == [False, True, False]


def test_fields_of_one_type_share_one_question() -> None:
    questions = plan(_ir(_f(0, T.EMAIL), _f(1, T.PAN), _f(2, T.EMAIL)), POLICY)

    assert len(questions) == 2
    assert questions[0].field_ids == ["p0_f000", "p0_f002"]
    assert questions[1].parts[0].sensitive and questions[1].can_save


def test_untyped_fields_are_asked_with_the_forms_label_and_never_saved() -> None:
    unsure = _f(0, T.FATHER_NAME, "llm", 0.6, label="Name of nominee's father")
    other = _f(1, T.OTHER, "llm", 0.99, label="Relationship with nominee")
    dob = _f(2, T.DATE_OF_BIRTH, "llm", 0.5, label="Nominee's date of birth")

    questions = plan(_ir(unsure, other, dob), POLICY)

    assert [q.prompt for q in questions] == [
        "The form asks: “Name of nominee's father”. What should go here?",
        "The form asks: “Relationship with nominee”. What should go here?",
        "The form asks: “Nominee's date of birth”. What should go here?",
    ]
    assert not any(q.can_save for q in questions)
    assert [q.parts[0].semantic_type for q in questions] == [None, None, None]
    assert questions[2].parts[0].input is InputKind.DATE


def test_a_second_person_field_under_once_per_form_is_a_label_question() -> None:
    policy = FillPolicy(min_llm_confidence=0.95, once_per_form=frozenset({T.FULL_NAME}))

    questions = plan(_ir(_f(0, T.FULL_NAME), _f(1, T.FULL_NAME, label="Witness name")), policy)

    assert [q.prompt for q in questions] == [
        "What is your full name?",
        "The form asks: “Witness name”. What should go here?",
    ]


def test_choices_and_checkboxes() -> None:
    gender = _f(
        0,
        T.GENDER,
        kind=FieldKind.RADIO,
        options=[Option(value="M", label="Male"), Option(value="F", label="Female")],
        label="Gender",
    )
    declaration = _f(1, T.DECLARATION_CHECKBOX, kind=FieldKind.CHECKBOX, label="I agree")

    questions = plan(_ir(gender, declaration), POLICY)

    assert questions[0].parts[0].input is InputKind.CHOICE
    assert [c.label for c in questions[0].parts[0].choices] == ["Male", "Female"]
    assert questions[1].parts[0].input is InputKind.YES_NO
    assert questions[1].prompt == "Do you tick this box: “I agree”?"
    assert not questions[1].can_save


def test_only_fields_needing_input_are_asked() -> None:
    ir = _ir(
        _f(0, T.FULL_NAME, status=FieldStatus.FILLED, value="Asha Verma"),
        _f(1, T.SIGNATURE, status=FieldStatus.SKIPPED, no_fill_reason="signature"),
        _f(2, T.EMAIL),
    )

    assert [q.field_ids for q in plan(ir, POLICY)] == [["p0_f002"]]


def test_fewer_questions_than_fields() -> None:
    types = [T.CURRENT_ADDRESS_LINE1, T.CURRENT_CITY, T.CURRENT_STATE, T.CURRENT_PINCODE]
    ir = _ir(*[_f(i, t) for i, t in enumerate(types)], _f(4, T.EMAIL), _f(5, T.EMAIL))

    assert len(plan(ir, POLICY)) == 2


def test_prompts_keep_acronyms() -> None:
    prompts = [q.prompt for q in plan(_ir(_f(0, T.PAN), _f(1, T.EMAIL), _f(2, T.VOTER_ID)), POLICY)]

    assert prompts == ["What is your PAN?", "What is your email address?", "What is your voter ID?"]
