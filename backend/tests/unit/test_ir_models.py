import math
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

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
    TraceEvent,
    ValidationResult,
    ValueSource,
)
from app.ir.semantic_types import SemanticType

DOC_ID = uuid.UUID("5f0c6d1e-0000-4000-8000-000000000001")
AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
# Synthetic, format-valid-looking value; must never appear in validation messages.
FAKE_PAN = "ABCDE1234F"


def _bbox(page: int = 0, x0: float = 10, y0: float = 20, x1: float = 110, y1: float = 40) -> BBox:
    return BBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1)


def _field(field_id: str = "p0_f000", **overrides: Any) -> Field:
    values: dict[str, Any] = {
        "id": field_id,
        "kind": FieldKind.TEXT,
        "native_name": None,
        "label_text": "Name",
        "context_text": "Personal details",
        "bbox": _bbox(),
    }
    values.update(overrides)
    return Field(**values)


def _ir(**overrides: Any) -> FormIR:
    values: dict[str, Any] = {
        "document_id": DOC_ID,
        "source_kind": SourceKind.FLAT_TEXT,
        "pages": [
            PageInfo(width=595.0, height=842.0, text_layer=TextLayer.OK),
            PageInfo(width=595.0, height=842.0, text_layer=TextLayer.GARBLED),
        ],
        "fields": [_field()],
    }
    values.update(overrides)
    return FormIR(**values)


def _full_ir() -> FormIR:
    """An IR that uses every model and most optional attributes."""
    checkbox = _field(
        "p1_f001",
        kind=FieldKind.CHECKBOX,
        bbox=_bbox(page=1, x0=50, y0=60, x1=59, y1=69),
        options=[Option(value="/On", label="Yes", bbox=_bbox(page=1, x0=50, y0=60, x1=59, y1=69))],
    )
    pan = _field(
        "p0_f002",
        max_chars=10,
        semantic_type=SemanticType.PAN,
        semantic_confidence=0.95,
        semantic_method="rule",
        value=FAKE_PAN,
        value_source=ValueSource.PROFILE,
        validations=[ValidationResult(validator="pan_format", ok=True)],
        status=FieldStatus.FILLED,
    )
    trace = [TraceEvent(pass_name="frontend.flat", field_id="p0_f000", change="detected", at=AT)]
    return _ir(fields=[_field(), checkbox, pan], trace=trace)


# --- round trip and JSON shape ------------------------------------------------------------


def test_json_round_trip_is_lossless() -> None:
    ir = _full_ir()

    restored = FormIR.model_validate_json(ir.model_dump_json())

    assert restored == ir


def test_json_uses_pages_with_text_layer_and_plain_enum_strings() -> None:
    data = _full_ir().model_dump(mode="json")

    assert "page_sizes" not in data
    assert data["pages"][1] == {"width": 595.0, "height": 842.0, "text_layer": "garbled"}
    assert data["source_kind"] == "flat_text"
    assert data["fields"][1]["kind"] == "checkbox"
    assert data["fields"][2]["semantic_type"] == "pan"
    assert data["schema_version"] == 1


def test_field_defaults() -> None:
    field = _field()

    assert field.semantic_type is SemanticType.UNKNOWN
    assert field.semantic_method == "none"
    assert field.semantic_confidence == 0.0
    assert field.status is FieldStatus.DETECTED
    assert field.value is None
    assert field.value_source is ValueSource.NONE
    assert field.options == []
    assert field.validations == []
    assert field.no_fill_reason is None
    assert field.uppercase is False
    assert field.question_text is None


def test_native_label_and_context_are_required_but_nullable() -> None:
    """SPEC §4 declares them without defaults: a frontend must state them explicitly."""
    with pytest.raises(ValidationError):
        Field(id="p0_f000", kind=FieldKind.TEXT, bbox=_bbox())  # type: ignore[call-arg]


# --- BBox --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "coords",
    [
        {"x0": 10, "y0": 20, "x1": 10, "y1": 40},  # zero width
        {"x0": 10, "y0": 20, "x1": 110, "y1": 20},  # zero height
        {"x0": 110, "y0": 20, "x1": 10, "y1": 40},  # x flipped
        {"x0": 10, "y0": 40, "x1": 110, "y1": 20},  # y flipped
        {"x0": math.nan, "y0": 20, "x1": 110, "y1": 40},
        {"x0": 10, "y0": 20, "x1": math.inf, "y1": 40},
    ],
)
def test_bbox_rejects_malformed_coordinates(coords: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        BBox(page=0, **coords)


def test_bbox_rejects_negative_page() -> None:
    with pytest.raises(ValidationError):
        _bbox(page=-1)


def test_bbox_width_and_height() -> None:
    box = _bbox(x0=10, y0=20, x1=110, y1=45)

    assert (box.width, box.height) == (100, 25)


# --- PageInfo and other field constraints -------------------------------------------------


@pytest.mark.parametrize("size", [{"width": 0, "height": 842}, {"width": 595, "height": -1}])
def test_page_size_must_be_positive(size: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        PageInfo(text_layer=TextLayer.OK, **size)


def test_text_layer_values() -> None:
    assert {layer.value for layer in TextLayer} == {"ok", "garbled", "none"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"semantic_confidence": 1.01},
        {"semantic_confidence": -0.1},
        {"max_chars": 0},
        {"semantic_method": "guess"},
        {"semantic_type": "shoe_size"},
        {"no_fill_reason": "too_hard"},
        {"id": ""},
        {"question_text": ""},
        {"question_text": "x" * 201},
        {"status": "maybe"},
    ],
)
def test_field_rejects_invalid_values(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _field(**overrides)


@pytest.mark.parametrize("reason", ["office_use", "signature"])
def test_no_fill_reason_round_trips(reason: str) -> None:
    ir = _ir(fields=[_field(no_fill_reason=reason)])

    assert FormIR.model_validate_json(ir.model_dump_json()).fields[0].no_fill_reason == reason


def test_ir_stored_before_no_fill_reason_still_loads() -> None:
    """P3-D1 keeps schema_version 1: a stored IR without the attribute loads with None."""
    data = _full_ir().model_dump(mode="json")
    for field in data["fields"]:
        del field["no_fill_reason"]

    restored = FormIR.model_validate(data)

    assert restored.schema_version == 1
    assert all(field.no_fill_reason is None for field in restored.fields)


def test_phase_5_additions_round_trip() -> None:
    field = _field(
        status=FieldStatus.SUGGESTED, uppercase=True, question_text="What is your father's name?"
    )
    restored = FormIR.model_validate_json(_ir(fields=[field]).model_dump_json()).fields[0]

    assert restored.status is FieldStatus.SUGGESTED
    assert restored.uppercase is True
    assert restored.question_text == "What is your father's name?"


def test_ir_stored_before_phase_5_still_loads() -> None:
    """The Phase 5 additions keep schema_version 1: older stored IRs load with the defaults."""
    data = _full_ir().model_dump(mode="json")
    for field in data["fields"]:
        del field["uppercase"], field["question_text"]

    restored = FormIR.model_validate(data)

    assert all(not f.uppercase and f.question_text is None for f in restored.fields)


def test_trace_event_requires_timezone() -> None:
    with pytest.raises(ValidationError):
        TraceEvent(pass_name="p", field_id=None, change="c", at=datetime(2026, 10, 11, 12, 0))


# --- unknown keys -------------------------------------------------------------------------


def test_unknown_keys_are_rejected() -> None:
    data = _full_ir().model_dump(mode="json")
    data["page_sizes"] = [[595.0, 842.0]]

    with pytest.raises(ValidationError):
        FormIR.model_validate(data)


def test_unknown_keys_in_nested_models_are_rejected() -> None:
    data = _full_ir().model_dump(mode="json")
    data["fields"][0]["bbox"]["rotation"] = 90

    with pytest.raises(ValidationError):
        FormIR.model_validate(data)


# --- document-level consistency -----------------------------------------------------------


def test_duplicate_field_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _ir(fields=[_field("p0_f000"), _field("p0_f000")])


def test_field_on_missing_page_is_rejected() -> None:
    with pytest.raises(ValidationError, match="page that does not exist"):
        _ir(fields=[_field(bbox=_bbox(page=2))])


def test_option_on_missing_page_is_rejected() -> None:
    option = Option(value="/On", bbox=_bbox(page=5))

    with pytest.raises(ValidationError, match="page that does not exist"):
        _ir(fields=[_field(kind=FieldKind.CHECKBOX, options=[option])])


def test_ir_without_fields_is_valid() -> None:
    """A scanned document has pages but no fields until OCR exists (Phase 6)."""
    ir = _ir(source_kind=SourceKind.SCANNED, fields=[])

    assert ir.fields == []


def test_consistency_messages_never_contain_values() -> None:
    duplicate = [_field("p0_f000", value=FAKE_PAN), _field("p0_f000", value=FAKE_PAN)]

    with pytest.raises(ValidationError) as excinfo:
        _ir(fields=duplicate)

    assert all(FAKE_PAN not in error["msg"] for error in excinfo.value.errors())
