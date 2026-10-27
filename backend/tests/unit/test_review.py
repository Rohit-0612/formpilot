"""Review rules (SPEC §6.8, Phase 5): edit, confirm, unconfirm, confirm all. Synthetic data."""

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
    ValidationResult,
    ValueSource,
)
from app.ir.semantic_types import SemanticType as T
from app.passes.context import PassContext
from app.services.review import (
    FieldNotFoundError,
    NeverFilledError,
    NothingToConfirmError,
    confirm_all,
    edit_field,
    renderable,
)

NOW = datetime(2026, 10, 27, 6, 0, tzinfo=UTC)
CTX = PassContext(clock=lambda: NOW)
FAILED = ValidationResult(validator="pan_format", ok=False, message="Not a PAN.")


def _f(i: int, **extra: Any) -> Field:
    values: dict[str, Any] = {
        "id": f"p0_f{i:03d}", "kind": FieldKind.TEXT, "native_name": None,
        "label_text": f"label {i}", "context_text": None,
        "bbox": BBox(page=0, x0=10, y0=10 + 20 * i, x1=300, y1=26 + 20 * i),
        "semantic_type": T.OTHER, "status": FieldStatus.NEEDS_INPUT,
    }  # fmt: skip
    values.update(extra)
    return Field(**values)


def _ir(*fields: Field) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def _filled(i: int, **extra: Any) -> Field:
    values = {"value": "Asha Verma", "value_source": ValueSource.PROFILE,
              "status": FieldStatus.FILLED} | extra  # fmt: skip
    return _f(i, **values)


def test_an_edit_is_the_users_value_checked_again_and_traced_without_it() -> None:
    ir = _ir(_f(0, semantic_type=T.PAN))

    out, changes = edit_field(ir, "p0_f000", CTX, value="  abcde  1234 ")

    field = out.fields[0]
    assert (field.value, field.value_source) == ("abcde 1234", ValueSource.USER_EDIT)
    assert field.status is FieldStatus.NEEDS_REVIEW  # nine characters: not a PAN
    assert {v.validator for v in field.validations} >= {"pan_format", "fits_box"}
    assert [(c.field_id, c.event) for c in changes] == [("p0_f000", "field_edited")]
    assert "abcde" not in out.model_dump_json(include={"trace"})


def test_clearing_a_value_asks_for_it_again() -> None:
    out, changes = edit_field(_ir(_filled(0)), "p0_f000", CTX, value="  ")

    field = out.fields[0]
    assert (field.value, field.value_source, field.status) == (
        None, ValueSource.NONE, FieldStatus.NEEDS_INPUT,
    )  # fmt: skip
    assert [c.event for c in changes] == ["field_cleared"]


def test_a_suggestion_is_accepted_only_by_a_confirm_and_rejected_by_clearing() -> None:
    suggested = _filled(0, status=FieldStatus.SUGGESTED)

    accepted, changes = edit_field(_ir(suggested), "p0_f000", CTX, confirmed=True)
    assert accepted.fields[0].status is FieldStatus.CONFIRMED
    assert [c.event for c in changes] == ["suggestion_accepted"]

    rejected, changes = edit_field(_ir(suggested), "p0_f000", CTX, value=None)
    assert rejected.fields[0].status is FieldStatus.NEEDS_INPUT
    assert [c.event for c in changes] == ["suggestion_rejected"]


def test_edit_and_confirm_in_one_step_even_with_a_warning() -> None:
    out, changes = edit_field(
        _ir(_f(0, semantic_type=T.PAN)), "p0_f000", CTX, value="ABCDE1234", confirmed=True
    )

    assert out.fields[0].status is FieldStatus.CONFIRMED
    assert any(not v.ok for v in out.fields[0].validations)  # the user confirmed despite it
    assert [c.event for c in changes] == ["field_edited", "field_confirmed"]


def test_unconfirm_returns_to_filled_or_needs_review() -> None:
    clean = _filled(0, status=FieldStatus.CONFIRMED)
    warned = _filled(1, status=FieldStatus.CONFIRMED, validations=[FAILED])

    out, changes = edit_field(_ir(clean, warned), "p0_f000", CTX, confirmed=False)
    out, more = edit_field(out, "p0_f001", CTX, confirmed=False)

    assert [f.status for f in out.fields] == [FieldStatus.FILLED, FieldStatus.NEEDS_REVIEW]
    assert [c.event for c in changes + more] == ["field_unconfirmed"] * 2


def test_confirming_twice_or_unconfirming_an_unconfirmed_field_changes_nothing() -> None:
    _, again = edit_field(_ir(_filled(0, status=FieldStatus.CONFIRMED)), "p0_f000", CTX,
                          confirmed=True)  # fmt: skip
    _, nothing = edit_field(_ir(_filled(0)), "p0_f000", CTX, confirmed=False)

    assert again == [] and nothing == []


def test_a_checkbox_answered_no_can_be_confirmed_but_an_empty_field_cannot() -> None:
    answered_no = _f(0, kind=FieldKind.CHECKBOX, status=FieldStatus.FILLED)

    out, _ = edit_field(_ir(answered_no, _f(1)), "p0_f000", CTX, confirmed=True)

    assert out.fields[0].status is FieldStatus.CONFIRMED
    with pytest.raises(NothingToConfirmError):
        edit_field(out, "p0_f001", CTX, confirmed=True)


def test_never_fill_and_unknown_fields_are_refused() -> None:
    signature = _f(0, status=FieldStatus.SKIPPED, no_fill_reason="signature")

    with pytest.raises(NeverFilledError):
        edit_field(_ir(signature), "p0_f000", CTX, value="x")
    with pytest.raises(FieldNotFoundError):
        edit_field(_ir(signature), "p9_f999", CTX, confirmed=True)


def test_confirm_all_takes_only_clean_filled_values_not_from_the_llm() -> None:
    ir = _ir(
        _filled(0),  # confirmed
        _filled(1, validations=[FAILED], status=FieldStatus.NEEDS_REVIEW),
        _filled(2, status=FieldStatus.SUGGESTED),
        _filled(3, value_source=ValueSource.LLM_INFERRED),  # an address part split by the LLM
        _filled(4, value_source=ValueSource.USER_ANSWER),  # confirmed
        _f(5),  # no value
    )

    out, changes = confirm_all(ir, CTX)

    assert [c.field_id for c in changes] == ["p0_f000", "p0_f004"]
    assert {c.event for c in changes} == {"field_confirmed_in_bulk"}
    assert [f.status for f in out.fields] == [
        FieldStatus.CONFIRMED,
        FieldStatus.NEEDS_REVIEW,
        FieldStatus.SUGGESTED,
        FieldStatus.FILLED,
        FieldStatus.CONFIRMED,
        FieldStatus.NEEDS_INPUT,
    ]


def test_only_confirmed_fields_with_a_value_are_rendered() -> None:
    ir = _ir(
        _filled(0, status=FieldStatus.CONFIRMED),
        _filled(1),
        _filled(2, status=FieldStatus.SUGGESTED),
        _f(3, kind=FieldKind.CHECKBOX, status=FieldStatus.CONFIRMED),  # answered "no"
    )

    assert [f.id for f in renderable(ir)] == ["p0_f000"]
