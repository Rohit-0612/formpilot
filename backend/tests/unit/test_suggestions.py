"""Suggested values (decision P5-D1): prefilled, unconfirmed, not asked; the fill policy is
unchanged. Synthetic data."""

import uuid
from datetime import UTC, datetime
from typing import Literal

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
from app.ir.semantic_types import SemanticType as T
from app.passes import fit, match, validate
from app.passes.context import PassContext
from app.passes.questions import plan

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
PROFILE = {
    "full_name": "Asha Verma",
    "father_name": "Ramesh Verma",
    "mother_name": "Sunita Verma",
    "date_of_birth": "1999-03-05",
    "phone_mobile": "9876543210",
}


def _ctx(floor: float | None = 0.95) -> PassContext:
    return PassContext(clock=lambda: NOW, profile=PROFILE, suggest_min_confidence=floor)


def _f(
    i: int, t: T, confidence: float, method: Literal["rule", "llm"] = "llm", width: float = 190
) -> Field:
    return Field(
        id=f"p0_f{i:03d}", kind=FieldKind.TEXT, native_name=None, label_text=f"label {i}",
        context_text=None, bbox=BBox(page=0, x0=10, y0=10 + 20 * i, x1=10 + width, y1=24 + 20 * i),
        semantic_type=t, semantic_method=method, semantic_confidence=confidence,
    )  # fmt: skip


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def _enrollment_form() -> FormIR:
    """The shape of dev form #30: names typed just under the fill threshold, the date of birth
    at it, and a field asked in Hindi."""
    return _ir(
        _f(0, T.FULL_NAME, 0.98),
        _f(1, T.FATHER_NAME, 0.97),
        _f(2, T.MOTHER_NAME, 0.97),
        _f(3, T.DATE_OF_BIRTH, 0.99),
        _f(4, T.OTHER, 0.95),
    )


def test_names_just_below_the_fill_threshold_are_suggested_with_the_profile_value() -> None:
    out = match.run(_enrollment_form(), _ctx())

    statuses = [f.status for f in out.fields]
    assert statuses == [FieldStatus.SUGGESTED] * 3 + [FieldStatus.FILLED, FieldStatus.NEEDS_INPUT]
    assert [f.value for f in out.fields[:3]] == ["Asha Verma", "Ramesh Verma", "Sunita Verma"]
    assert all(f.value_source is ValueSource.PROFILE for f in out.fields[:3])
    assert [t.change for t in out.trace][:2] == [
        "suggested full_name (profile)",
        "suggested father_name (profile)",
    ]
    assert "Verma" not in out.model_dump_json(include={"trace"})


def test_suggestions_never_change_what_is_filled() -> None:
    form = _enrollment_form()
    with_suggestions = match.run(form, _ctx(0.95))
    without = match.run(form, _ctx(None))

    def filled(ir: FormIR) -> list[str]:
        return [f.id for f in ir.fields if f.status is FieldStatus.FILLED]

    assert filled(with_suggestions) == filled(without) == ["p0_f003"]
    assert not any(f.status is FieldStatus.SUGGESTED for f in without.fields)


def test_below_the_floor_or_rule_typed_or_without_a_profile_value_nothing_is_suggested() -> None:
    form = _ir(
        _f(0, T.FULL_NAME, 0.94),  # below the floor
        _f(1, T.PAN, 0.97),  # no PAN in the profile
        _f(2, T.UNKNOWN, 0.99),
    )

    out = match.run(form, _ctx())

    assert all(f.status is FieldStatus.NEEDS_INPUT and f.value is None for f in out.fields)


def test_once_per_form_counts_filled_fields_and_earlier_suggestions() -> None:
    form = _ir(
        _f(0, T.FATHER_NAME, 0.97),
        _f(1, T.FATHER_NAME, 0.97),  # a second father's name: perhaps another person's
        _f(2, T.FULL_NAME, 0.95, method="rule"),
        _f(3, T.FULL_NAME, 0.98),  # the type is already filled by the rule
    )

    out = match.run(form, PassContext(clock=lambda: NOW, profile=PROFILE,
                                      suggest_min_confidence=0.95))  # fmt: skip

    assert [f.status for f in out.fields] == [
        FieldStatus.SUGGESTED,
        FieldStatus.NEEDS_INPUT,
        FieldStatus.FILLED,
        FieldStatus.NEEDS_INPUT,
    ]


def test_suggested_fields_are_not_asked() -> None:
    ctx = _ctx()
    out = match.run(_enrollment_form(), ctx)

    asked = {i for q in plan(out, match.policy_for(ctx)) for i in q.field_ids}

    assert asked == {"p0_f004"}


def test_a_failed_check_keeps_a_suggestion_suggested() -> None:
    ctx = _ctx()
    narrow = _f(0, T.FULL_NAME, 0.97, width=20)  # "Asha Verma" cannot fit 20 pt

    out = fit.run(validate.run(match.run(_ir(narrow), ctx), ctx), ctx)

    field = out.fields[0]
    assert field.status is FieldStatus.SUGGESTED
    assert [(v.validator, v.ok) for v in field.validations] == [("fits_box", False)]
