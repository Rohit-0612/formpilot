"""Understanding pass (Phase 3): rule matcher, LLM path with validation and retry, never-fill marks.

LLM calls go to FakeProvider (invariant 5).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.ir.models import (
    BBox,
    Field,
    FieldKind,
    FieldStatus,
    FormIR,
    PageInfo,
    SourceKind,
    TextLayer,
)
from app.ir.semantic_types import SemanticType
from app.llm.fake import FakeProvider
from app.llm.provider import LLMError, LLMRequest
from app.passes import understand
from app.passes.context import PassContext

T = SemanticType
AT = datetime(2026, 10, 26, tzinfo=UTC)
# Synthetic value; it must never reach the LLM or the trace.
FAKE_VALUE = "SYNTHETIC-VALUE-123"


def _field(field_id: str, label: str | None, context: str | None = None, **overrides: Any) -> Field:
    values: dict[str, Any] = {
        "id": field_id,
        "kind": FieldKind.TEXT,
        "native_name": None,
        "label_text": label,
        "context_text": context,
        "bbox": BBox(page=0, x0=10, y0=10, x1=100, y1=20),
    }
    values.update(overrides)
    return Field(**values)


def _ir(*fields: Field, pages: int = 1) -> FormIR:
    return FormIR(
        document_id=uuid.UUID("00000000-0000-4000-8000-000000000030"),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)] * pages,
        fields=list(fields),
    )


def _ctx(provider: FakeProvider | None = None, **overrides: Any) -> PassContext:
    return PassContext(clock=lambda: AT, provider=provider, **overrides)


def _answer(*items: tuple[str, str, float]) -> str:
    return json.dumps(
        {"fields": [{"id": i, "semantic_type": t, "confidence": c} for i, t, c in items]}
    )


def _ids(request: LLMRequest) -> list[str]:
    return [f["id"] for f in json.loads(request.user.split("\n\n")[0])["fields"]]


# --- rules ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "context", "expected"),
    [
        ("Name", None, T.FULL_NAME),
        ("1. Name of the Applicant", None, T.FULL_NAME),
        ("(a) Father\u2019s Name", None, T.FATHER_NAME),
        ("Date of Birth (DD/MM/YYYY)", None, T.DATE_OF_BIRTH),
        ("Mobile No.", None, T.PHONE_MOBILE),
        ("E-mail", None, T.EMAIL),
        ("Account No.", None, T.BANK_ACCOUNT_NUMBER),
        ("IFS Code", None, T.IFSC),
        ("11. AADHAR No.", None, T.AADHAAR),
        ("(Signature of the applicant)", None, T.SIGNATURE),
        ("City", "Permanent Address", T.PERMANENT_CITY),
        ("PIN Code", "Address for correspondence", T.CURRENT_PINCODE),
        ("Permanent Address", None, T.PERMANENT_ADDRESS_LINE1),
    ],
)
def test_rule_matches(label: str, context: str | None, expected: SemanticType) -> None:
    assert understand.rule_match(_field("f", label, context)) is expected


@pytest.mark.parametrize(
    ("label", "context", "why"),
    [
        ("Father's/Husband's Name", None, "two types, words outside the best match"),
        ("City", None, "current or permanent: no hint"),
        ("I hereby declare that the information given above is true", None, "keyword too small"),
        ("Policy No.", None, "no keyword"),
        ("Issue Date", None, "the keyword 'date' is only half the label"),
        ("Name", "2. PARTICULARS OF NOMINEE/S", "about another person"),
        ("Name of witness", None, "about another person"),
        ("Student's name in Hindi", None, "asks in Hindi"),
        ("2. Maiden Name", None, "not the person's current name"),
        (None, None, "no label"),
    ],
)
def test_rule_leaves_it_to_the_llm(label: str | None, context: str | None, why: str) -> None:
    assert understand.rule_match(_field("f", label, context)) is None, why


# --- the pass with an LLM ---------------------------------------------------------------------


def test_rules_first_then_one_llm_request_for_the_rest() -> None:
    provider = FakeProvider([_answer(("p0_f001", "other", 0.9))])
    ir = _ir(_field("p0_f000", "Mobile No."), _field("p0_f001", "Policy No."))

    out = understand.run(ir, _ctx(provider))

    mobile, policy = out.fields
    assert (mobile.semantic_type, mobile.semantic_method, mobile.semantic_confidence) == (
        T.PHONE_MOBILE,
        "rule",
        understand.RULE_CONFIDENCE,
    )
    assert (policy.semantic_type, policy.semantic_method, policy.semantic_confidence) == (
        T.OTHER,
        "llm",
        0.9,
    )
    assert [_ids(r) for r in provider.requests] == [["p0_f001"]]
    assert all(f.status is FieldStatus.DETECTED for f in out.fields)


def test_invalid_answer_is_retried_once_with_the_error() -> None:
    provider = FakeProvider(["not json", _answer(("p0_f000", "other", 0.8))])

    (field,) = understand.run(_ir(_field("p0_f000", "Policy No.")), _ctx(provider)).fields

    assert field.semantic_type is T.OTHER
    assert len(provider.requests) == 2
    assert "previous answer was invalid" in provider.requests[1].user


def test_still_missing_after_the_retry_is_unknown_and_needs_review() -> None:
    provider = FakeProvider([_answer(), _answer(("someone_else", "other", 0.9))])

    out = understand.run(_ir(_field("p0_f000", "Policy No.")), _ctx(provider))

    (field,) = out.fields
    assert (field.semantic_type, field.semantic_method, field.status) == (
        T.UNKNOWN,
        "none",
        FieldStatus.NEEDS_REVIEW,
    )
    assert any("LLM batch retried" in e.change for e in out.trace)


def test_unknown_type_in_the_answer_counts_as_invalid() -> None:
    bad = '{"fields": [{"id": "p0_f000", "semantic_type": "shoe_size", "confidence": 0.9}]}'
    provider = FakeProvider([bad, bad])

    (field,) = understand.run(_ir(_field("p0_f000", "Policy No.")), _ctx(provider)).fields

    assert field.semantic_type is T.UNKNOWN
    assert len(provider.requests) == 2


def test_provider_failure_leaves_fields_unknown_and_is_traced() -> None:
    def fail(_: LLMRequest) -> str:
        raise LLMError("ollama: ConnectError")

    out = understand.run(_ir(_field("p0_f000", "Policy No.")), _ctx(FakeProvider(fail)))

    assert out.fields[0].semantic_type is T.UNKNOWN
    assert [e.change for e in out.trace if e.field_id is None] == ["page 0: LLM batch failed"]


def test_low_confidence_needs_review() -> None:
    provider = FakeProvider([_answer(("p0_f000", "other", 0.5))])

    (field,) = understand.run(_ir(_field("p0_f000", "Policy No.")), _ctx(provider)).fields

    assert field.status is FieldStatus.NEEDS_REVIEW


def test_dense_pages_are_split_into_batches_and_pages_are_separate() -> None:
    def echo(request: LLMRequest) -> str:
        return _answer(*((i, "other", 0.9) for i in _ids(request)))

    provider = FakeProvider(echo)
    page0 = [_field(f"p0_f{i:03d}", "Policy No.") for i in range(understand.LLM_BATCH + 5)]
    page1 = [_field("p1_f000", "Policy No.", bbox=BBox(page=1, x0=10, y0=10, x1=100, y1=20))]

    out = understand.run(_ir(*page0, *page1, pages=2), _ctx(provider))

    assert [len(_ids(r)) for r in provider.requests] == [understand.LLM_BATCH, 5, 1]
    assert all(f.semantic_type is T.OTHER for f in out.fields)


def test_requests_hold_printed_text_only() -> None:
    provider = FakeProvider([_answer(("p0_f000", "other", 0.9))])
    field = _field("p0_f000", "Policy No.", "Nominee details", value=FAKE_VALUE)

    out = understand.run(_ir(field), _ctx(provider))

    (request,) = provider.requests
    assert request.carries == frozenset()
    assert FAKE_VALUE not in request.user
    assert all(FAKE_VALUE not in e.change for e in out.trace)
    sent = json.loads(request.user)["fields"][0]
    assert sent == {
        "id": "p0_f000",
        "kind": "text",
        "label": "Policy No.",
        "context": "Nominee details",
        "options": [],
        "max_chars": None,
    }


# --- modes and no provider --------------------------------------------------------------------


def test_rules_mode_never_calls_the_llm() -> None:
    provider = FakeProvider([])

    out = understand.run(
        _ir(_field("p0_f000", "Policy No.")), _ctx(provider, understand_mode="rules")
    )

    assert provider.requests == []
    assert out.fields[0].semantic_type is T.UNKNOWN


def test_llm_mode_sends_every_field() -> None:
    provider = FakeProvider([_answer(("p0_f000", "phone_mobile", 0.9))])

    out = understand.run(
        _ir(_field("p0_f000", "Mobile No.")), _ctx(provider, understand_mode="llm")
    )

    assert [_ids(r) for r in provider.requests] == [["p0_f000"]]
    assert out.fields[0].semantic_method == "llm"


def test_without_a_provider_the_rules_run_and_it_is_traced() -> None:
    out = understand.run(
        _ir(_field("p0_f000", "Mobile No."), _field("p0_f001", "Policy No.")), _ctx()
    )

    assert [f.semantic_type for f in out.fields] == [T.PHONE_MOBILE, T.UNKNOWN]
    assert "no LLM provider: rules only" in [e.change for e in out.trace]


# --- never filled (P3-D1) ---------------------------------------------------------------------


def test_office_use_fields_are_skipped_whatever_their_type() -> None:
    ir = _ir(
        _field("p0_f000", "Account No.", "FOR OFFICE USE ONLY"),
        _field("p0_f001", "Date", "कार्यालय उपयोग हेतु"),
        _field("p0_f002", "Account No.", "Bank details"),
    )

    out = understand.run(ir, _ctx())

    assert [(f.no_fill_reason, f.status) for f in out.fields] == [
        ("office_use", FieldStatus.SKIPPED),
        ("office_use", FieldStatus.SKIPPED),
        (None, FieldStatus.DETECTED),
    ]
    assert out.fields[0].semantic_type is T.BANK_ACCOUNT_NUMBER  # still classified


def test_signatures_are_never_filled_from_rules_or_the_llm() -> None:
    provider = FakeProvider([_answer(("p0_f001", "signature", 0.9))])
    ir = _ir(_field("p0_f000", "(Signature of the applicant)"), _field("p0_f001", "Thumb mark"))

    out = understand.run(ir, _ctx(provider))

    assert [(f.semantic_type, f.no_fill_reason, f.status) for f in out.fields] == [
        (T.SIGNATURE, "signature", FieldStatus.SKIPPED),
        (T.SIGNATURE, "signature", FieldStatus.SKIPPED),
    ]


def test_fields_already_understood_are_left_alone() -> None:
    """An AcroForm signature widget arrives typed (P3-D1): no rule, no LLM, no new event."""
    provider = FakeProvider([])
    widget = _field(
        "p0_f000",
        "Applicant",
        semantic_type=T.SIGNATURE,
        semantic_confidence=1.0,
        semantic_method="rule",
        no_fill_reason="signature",
        status=FieldStatus.SKIPPED,
    )

    out = understand.run(_ir(widget), _ctx(provider))

    assert out.fields == [widget]
    assert provider.requests == []
    assert out.trace == []


def test_the_pass_is_pure() -> None:
    ir = _ir(_field("p0_f000", "Mobile No."))
    before = ir.model_dump()

    understand.run(ir, _ctx())

    assert ir.model_dump() == before


def test_prompt_lists_every_type_and_the_schema_allows_only_them() -> None:
    prompt = understand._system_prompt()
    enum = understand._schema()["properties"]["fields"]["items"]["properties"]["semantic_type"][
        "enum"
    ]

    assert "{types}" not in prompt
    assert all(f"- {t.value}:" in prompt for t in SemanticType)
    assert set(enum) == {t.value for t in SemanticType}


def test_batches_after_the_deadline_are_skipped_and_traced() -> None:
    """The analyze job's time budget: no LLM call once the deadline has passed."""
    provider = FakeProvider([])
    ctx = _ctx(provider, deadline=AT)  # the clock already reads the deadline

    out = understand.run(_ir(_field("p0_f000", "Mobile No."), _field("p0_f001", "Policy No.")), ctx)

    assert provider.requests == []
    assert [f.semantic_type for f in out.fields] == [T.PHONE_MOBILE, T.UNKNOWN]
    assert "page 0: LLM time budget used up" in [e.change for e in out.trace]
