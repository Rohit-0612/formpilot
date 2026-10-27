"""Validation pass (SPEC §6.6) and fit pass (SPEC §6.7). Values are synthetic."""

import uuid
from datetime import UTC, datetime

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
)
from app.ir.semantic_types import SemanticType as T
from app.passes import fit, validate
from app.passes.context import PassContext

NOW = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)  # already 28 Oct in India
CTX = PassContext(clock=lambda: NOW)


def _field(
    i: int,
    semantic_type: T,
    value: str | None,
    width: float = 200,
    height: float = 14,
    **extra: object,
) -> Field:
    return Field(
        id=f"p0_f{i:03d}",
        kind=extra.pop("kind", FieldKind.TEXT),  # type: ignore[arg-type]
        native_name=None,
        label_text=extra.pop("label", None),  # type: ignore[arg-type]
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10, x1=10 + width, y1=10 + height),
        semantic_type=semantic_type,
        value=value,
        status=FieldStatus.FILLED if value else FieldStatus.NEEDS_INPUT,
        **extra,  # type: ignore[arg-type]
    )


def _ir(*fields: Field, kind: SourceKind = SourceKind.FLAT_TEXT) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=kind,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=list(fields),
    )


def test_context_today_is_the_date_in_india() -> None:
    assert CTX.today().isoformat() == "2026-10-28"


# --- validate -----------------------------------------------------------------------------


def test_failures_need_review_and_the_trace_names_only_the_validator() -> None:
    ir = _ir(_field(0, T.PAN, "ABCDE12345"), _field(1, T.PAN, "ABCDE1234F"), _field(2, T.PAN, None))

    out = validate.run(ir, CTX)

    bad, good, empty = out.fields
    assert bad.status is FieldStatus.NEEDS_REVIEW
    assert [(r.validator, r.ok) for r in bad.validations] == [("pan_format", False)]
    assert good.status is FieldStatus.FILLED and good.validations[0].ok
    assert empty == ir.fields[2]
    assert [e.change for e in out.trace] == ["failed pan_format"]
    assert "ABCDE12345" not in out.model_dump_json(include={"trace"})


def test_validation_keeps_the_fit_result_and_replaces_its_own() -> None:
    old = [
        ValidationResult(validator="pan_format", ok=False, message="old"),
        ValidationResult(validator="fits_box", ok=True),
    ]
    out = validate.run(_ir(_field(0, T.PAN, "ABCDE1234F", validations=old)), CTX)

    assert [(r.validator, r.ok) for r in out.fields[0].validations] == [
        ("pan_format", True),
        ("fits_box", True),
    ]


def test_never_filled_fields_are_not_validated() -> None:
    field = _field(0, T.SIGNATURE, "x", no_fill_reason="signature")

    assert validate.run(_ir(field), CTX).fields[0] == field


def test_dob_in_the_future_uses_the_date_in_india() -> None:
    out = validate.run(_ir(_field(0, T.DATE_OF_BIRTH, "28/10/2026")), CTX)

    assert all(r.ok for r in out.fields[0].validations)  # 28 Oct is today in India


# --- fit ------------------------------------------------------------------------------------


def test_a_short_value_gets_the_default_size() -> None:
    out = fit.run(_ir(_field(0, T.FULL_NAME, "Asha Verma")), CTX)

    assert out.fields[0].font_size == 10.0
    assert out.fields[0].validations[-1] == ValidationResult(validator="fits_box", ok=True)


def test_a_long_value_shrinks_but_not_below_the_minimum() -> None:
    value = "Flat 12, Shanti Apartments, Near City Bus Stand"
    shrunk = fit.run(_ir(_field(0, T.CURRENT_ADDRESS_LINE1, value, width=200)), CTX).fields[0]
    too_long = fit.run(_ir(_field(0, T.CURRENT_ADDRESS_LINE1, value, width=90)), CTX).fields[0]

    assert shrunk.font_size is not None and 6.0 <= shrunk.font_size < 10.0
    assert shrunk.validations[-1].ok
    assert too_long.font_size == 6.0 and not too_long.validations[-1].ok
    assert too_long.status is FieldStatus.NEEDS_REVIEW


def test_a_low_box_caps_the_font_size() -> None:
    assert fit.run(_ir(_field(0, T.CURRENT_CITY, "Pune", height=10)), CTX).fields[0].font_size == 8


def test_comb_rows_are_measured_per_cell_on_flat_forms_only() -> None:
    comb = _field(0, T.CURRENT_PINCODE, "411001", width=60, max_chars=6)  # 10 pt cells

    assert fit.run(_ir(comb), CTX).fields[0].validations[-1].ok
    # the same box as an AcroForm field with /MaxLen 6: the whole text must fit
    whole = fit.run(_ir(comb, kind=SourceKind.FILLABLE), CTX).fields[0]
    assert whole.validations[-1].ok and whole.font_size is not None


def test_devanagari_cannot_be_shown_by_the_pdf_font() -> None:
    out = fit.run(_ir(_field(0, T.FULL_NAME, "आशा वर्मा")), CTX).fields[0]

    assert not out.validations[-1].ok and out.status is FieldStatus.NEEDS_REVIEW


def test_checkboxes_and_empty_fields_are_left_alone() -> None:
    box = _field(0, T.DECLARATION_CHECKBOX, "/On", kind=FieldKind.CHECKBOX)
    empty = _field(1, T.FULL_NAME, None)

    assert fit.run(_ir(box, empty), CTX).fields == [box, empty]
