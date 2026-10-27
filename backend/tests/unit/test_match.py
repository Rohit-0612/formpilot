"""Match pass (SPEC §6.3) and the precision-first fill policy (decision P4-D2). Synthetic data."""

import uuid
from datetime import UTC, datetime
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
    ValueSource,
)
from app.ir.semantic_types import SemanticType as T
from app.passes import match
from app.passes.context import PassContext
from app.passes.match import FillPolicy

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
PROFILE = {
    "full_name": "Asha Verma",
    "first_name": "Asha",
    "last_name": "Verma",
    "date_of_birth": "1999-03-05",
    "phone_mobile": "9876543210",
    "gender": "Female",
    "pan": "ABCDE1234F",
}
CTX = PassContext(clock=lambda: NOW, profile=PROFILE)


def _f(
    i: int,
    t: T,
    method: Literal["rule", "llm", "user", "none"] = "rule",
    confidence: float = 0.95,
    **extra: object,
) -> Field:
    return Field(
        id=f"p0_f{i:03d}",
        kind=extra.pop("kind", FieldKind.TEXT),  # type: ignore[arg-type]
        native_name=None,
        label_text=extra.pop("label", None),  # type: ignore[arg-type]
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10 + 20 * i, x1=200, y1=24 + 20 * i),
        semantic_type=t,
        semantic_method=method,
        semantic_confidence=confidence,
        **extra,  # type: ignore[arg-type]
    )


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def test_rule_typed_fields_are_filled_from_the_profile() -> None:
    out = match.run(_ir(_f(0, T.FULL_NAME), _f(1, T.PHONE_MOBILE), _f(2, T.PAN)), CTX)

    assert [f.value for f in out.fields] == ["Asha Verma", "9876543210", "ABCDE1234F"]
    assert all(f.status is FieldStatus.FILLED for f in out.fields)
    assert all(f.value_source is ValueSource.PROFILE for f in out.fields)
    assert out.trace[0].change == "filled full_name (profile)"
    assert "Asha" not in out.model_dump_json(include={"trace"})


def test_llm_types_fill_only_at_or_above_the_confidence_floor() -> None:
    sure = _f(0, T.FULL_NAME, "llm", 0.95)
    unsure = _f(1, T.PHONE_MOBILE, "llm", 0.94)

    out = match.run(_ir(sure, unsure), CTX)

    assert out.fields[0].value == "Asha Verma"
    assert out.fields[1].value is None and out.fields[1].status is FieldStatus.NEEDS_INPUT


def test_rules_only_policy_never_fills_from_llm_types() -> None:
    out = match.run(_ir(_f(0, T.FULL_NAME, "llm", 1.0)), CTX, FillPolicy(min_llm_confidence=None))

    assert out.fields[0].value is None


def test_once_per_form_fills_only_the_first_person_field_of_a_type() -> None:
    policy = FillPolicy(once_per_form=frozenset({T.FULL_NAME}))

    out = match.run(_ir(_f(0, T.FULL_NAME), _f(1, T.FULL_NAME), _f(2, T.PAN)), CTX, policy)

    assert [f.value for f in out.fields] == ["Asha Verma", None, "ABCDE1234F"]


def test_derived_values_age_today_and_full_name_from_parts() -> None:
    ctx = PassContext(
        clock=lambda: NOW, profile={k: PROFILE[k] for k in PROFILE if k != "full_name"}
    )
    fields = [
        _f(0, T.AGE),
        _f(1, T.DATE_OF_FILLING, label="Date (DD-MM-YYYY)"),
        _f(2, T.FULL_NAME),
        _f(3, T.DATE_OF_BIRTH, label="Date of Birth"),
    ]

    out = match.run(_ir(*fields), ctx)

    assert [f.value for f in out.fields] == ["27", "27-10-2026", "Asha Verma", "05/03/1999"]
    assert [f.value_source for f in out.fields] == [
        ValueSource.DERIVED,
        ValueSource.DERIVED,
        ValueSource.DERIVED,
        ValueSource.PROFILE,
    ]


def test_choice_fields_pick_the_matching_option_or_stay_empty() -> None:
    letters = [Option(value="M", label="M"), Option(value="F", label="F")]
    words = [Option(value="1", label="Male"), Option(value="2", label="Female")]
    other = [Option(value="x", label="Transgender")]

    out = match.run(
        _ir(
            _f(0, T.GENDER, kind=FieldKind.RADIO, options=letters),
            _f(1, T.GENDER, kind=FieldKind.CHOICE, options=words),
            _f(2, T.GENDER, kind=FieldKind.CHOICE, options=other),
        ),
        CTX,
    )

    assert [f.value for f in out.fields] == ["F", "2", None]


def test_missing_profile_values_never_fill_and_other_types_are_asked() -> None:
    out = match.run(_ir(_f(0, T.FATHER_NAME), _f(1, T.OTHER), _f(2, T.UNKNOWN, "none", 0)), CTX)

    assert all(f.value is None and f.status is FieldStatus.NEEDS_INPUT for f in out.fields)


def test_never_fill_fields_and_existing_values_are_left_alone() -> None:
    signature = _f(0, T.SIGNATURE, no_fill_reason="signature", status=FieldStatus.SKIPPED)
    answered = _f(1, T.FULL_NAME, value="A. Verma", value_source=ValueSource.USER_ANSWER)

    out = match.run(_ir(signature, answered), CTX)

    assert out.fields == [signature, answered]
