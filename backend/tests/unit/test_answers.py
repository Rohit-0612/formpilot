"""Answer parsing (SPEC §6.5) and profile saves. Synthetic values; the LLM is a FakeProvider."""

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

import pytest

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
    ValueSource,
)
from app.ir.semantic_types import SemanticType as T
from app.llm.fake import FakeProvider
from app.llm.provider import LLMRequest, PrivacyError
from app.passes import answers
from app.passes.answers import Answer, profile_changes
from app.passes.context import PassContext
from app.passes.match import FillPolicy
from app.passes.questions import plan
from app.services.masking import contains_identifier

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
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
        status=FieldStatus.NEEDS_INPUT,
        **extra,  # type: ignore[arg-type]
    )


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def _run(ir: FormIR, given: list[Answer], provider: object = None) -> FormIR:
    ctx = PassContext(clock=lambda: NOW, provider=provider)  # type: ignore[arg-type]
    return answers.run(ir, ctx, given, plan(ir, POLICY))


def test_typed_answers_are_normalised_and_formatted_for_each_field() -> None:
    ir = _ir(
        _f(0, T.DATE_OF_BIRTH, label="Date of birth (DD-MM-YYYY)"),
        _f(1, T.PAN),
        _f(2, T.PHONE_MOBILE),
        _f(3, T.PHONE_MOBILE),  # same question
    )
    questions = plan(ir, POLICY)

    out = _run(
        ir,
        [
            Answer(question_id=questions[0].id, value="5 March 1999"),
            Answer(question_id=questions[1].id, value="abcde 1234 f"),
            Answer(question_id=questions[2].id, value="+91 90000 12345"),
        ],
    )

    assert [f.value for f in out.fields] == ["05-03-1999", "ABCDE1234F", "9000012345", "9000012345"]
    assert all(f.status is FieldStatus.FILLED for f in out.fields)
    assert all(f.value_source is ValueSource.USER_ANSWER for f in out.fields)
    assert "ABCDE" not in out.model_dump_json(include={"trace"})


def test_an_invalid_typed_answer_is_kept_as_typed_for_the_validator() -> None:
    ir = _ir(_f(0, T.PAN))

    out = _run(ir, [Answer(question_id=plan(ir, POLICY)[0].id, value="ABCDE12345")])

    assert out.fields[0].value == "ABCDE12345" and out.fields[0].status is FieldStatus.FILLED


def test_group_parts_and_label_questions() -> None:
    ir = _ir(
        _f(0, T.CURRENT_CITY),
        _f(1, T.CURRENT_PINCODE),
        _f(2, T.OTHER, label="Nominee date of birth", method="llm", confidence=0.4),
    )
    group, label = plan(ir, POLICY)

    out = _run(
        ir,
        [
            Answer(
                question_id=group.id, parts={"current_city": " Pune ", "current_pincode": "411 001"}
            ),
            Answer(question_id=label.id, value="some text  here"),
        ],
    )

    assert [f.value for f in out.fields] == ["Pune", "411001", "some text here"]


def test_free_text_address_is_split_by_the_llm_with_its_types_declared() -> None:
    ir = _ir(_f(0, T.CURRENT_ADDRESS_LINE1), _f(1, T.CURRENT_CITY), _f(2, T.CURRENT_PINCODE))
    [group] = plan(ir, POLICY)

    def split(request: LLMRequest) -> str:
        assert json.loads(request.user)["parts"] == [
            "current_address_line1",
            "current_city",
            "current_pincode",
        ]
        assert request.carries == {T.CURRENT_ADDRESS_LINE1, T.CURRENT_CITY, T.CURRENT_PINCODE}
        return json.dumps(
            {"current_address_line1": "Flat 12, Example Residency", "current_city": "Pune",
             "current_pincode": "411001"}
        )  # fmt: skip

    provider = FakeProvider(split, remote=True)
    out = _run(
        ir,
        [Answer(question_id=group.id, free_text="Flat 12, Example Residency, Pune 411001")],
        provider,
    )

    assert [f.value for f in out.fields] == ["Flat 12, Example Residency", "Pune", "411001"]
    assert all(f.value_source is ValueSource.LLM_INFERRED for f in out.fields)
    assert len(provider.requests) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Flat 12, Pune 411001, phone 90000 12345",
        "House 7 Pune 411001 Aadhaar 2345 6789 0124",
        "PAN ABCDE1234F, Pune",
    ],
)
def test_free_text_with_an_identifier_or_phone_is_never_sent(text: str) -> None:
    ir = _ir(_f(0, T.CURRENT_ADDRESS_LINE1), _f(1, T.CURRENT_CITY))
    provider = FakeProvider([], remote=True)

    out = _run(ir, [Answer(question_id=plan(ir, POLICY)[0].id, free_text=text)], provider)

    assert provider.requests == []
    assert all(f.value is None for f in out.fields)
    assert "identifier" in out.trace[-1].change and text not in out.trace[-1].change


def test_identifier_detection_leaves_plain_addresses_alone() -> None:
    assert not contains_identifier("Flat 12, Example Residency, Sample Nagar, Pune 411001")
    assert contains_identifier("call +91-9000012345")


def test_free_text_is_refused_where_a_group_holds_a_sensitive_type() -> None:
    ir = _ir(_f(0, T.BANK_NAME), _f(1, T.BANK_ACCOUNT_NUMBER))
    provider = FakeProvider([], remote=True)

    out = _run(ir, [Answer(question_id=plan(ir, POLICY)[0].id, free_text="Example Bank")], provider)

    assert provider.requests == [] and all(f.value is None for f in out.fields)


def test_the_privacy_guard_would_refuse_a_sensitive_type_anyway() -> None:
    with pytest.raises(PrivacyError):
        types = [T.CURRENT_CITY, T.PHONE_MOBILE]
        answers.split_free_text("x", types, FakeProvider([], remote=True))


def test_unreadable_llm_output_is_retried_once_then_reported() -> None:
    ir = _ir(_f(0, T.CURRENT_ADDRESS_LINE1), _f(1, T.CURRENT_CITY))
    provider = FakeProvider(["not json", '{"wrong": 1}'], remote=True)

    out = _run(ir, [Answer(question_id=plan(ir, POLICY)[0].id, free_text="Pune")], provider)

    assert len(provider.requests) == 2
    assert all(f.value is None for f in out.fields)
    assert out.trace[-1].change.endswith("free text not understood; answer the parts")


def test_yes_no_and_unknown_questions() -> None:
    box = _f(0, T.DECLARATION_CHECKBOX, kind=FieldKind.CHECKBOX, options=[Option(value="/On")])
    flat_box = _f(1, T.OTHER, kind=FieldKind.CHECKBOX, method="none", confidence=0)
    q1, q2 = plan(_ir(box, flat_box), POLICY)

    out = _run(
        _ir(box, flat_box),
        [
            Answer(question_id=q1.id, value="yes"),
            Answer(question_id=q2.id, value="no"),
            Answer(question_id="q_gone", value="x"),
        ],
    )

    assert [f.value for f in out.fields] == ["/On", None]
    assert all(f.status is FieldStatus.FILLED for f in out.fields)
    assert any(e.change.startswith("q_gone:") for e in out.trace)


def test_profile_changes_need_the_save_tick_and_a_sensitive_opt_in() -> None:
    ir = _ir(_f(0, T.EMAIL), _f(1, T.PAN), _f(2, T.AADHAAR), _f(3, T.OTHER, method="none"))
    email, pan, aadhaar, label = plan(ir, POLICY)

    changes = profile_changes(
        [
            Answer(question_id=email.id, value="asha@example.com", save_to_profile=True),
            Answer(question_id=pan.id, value="ABCDE1234F", save_to_profile=True),
            Answer(
                question_id=aadhaar.id,
                value="2345 6789 0124",
                save_to_profile=True,
                sensitive_opt_in=["aadhaar"],
            ),
            Answer(question_id=label.id, value="x", save_to_profile=True),
        ],
        [email, pan, aadhaar, label],
        NOW.date(),
    )

    assert changes.values == {"email": "asha@example.com", "aadhaar": "234567890124"}
    assert changes.opt_in == {"aadhaar": True}
