"""The Form IR (SPEC §4): the one contract between frontends, passes and backends.

Coordinates are PDF points with the origin at the top-left of the displayed page (invariant 6).
`pages` replaces SPEC v1.0's `page_sizes` (decision D1, docs/decisions/phase-2.md).

Every model rejects unknown keys, so a stored IR that drifts from this schema fails loudly.
Validation messages never contain field values.
"""

import math
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

import pydantic
from pydantic import AwareDatetime, BaseModel, ConfigDict, model_validator

from app.ir.semantic_types import SemanticType


class _IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceKind(StrEnum):
    FILLABLE = "fillable"  # AcroForm widgets present
    FLAT_TEXT = "flat_text"  # text layer, no widgets
    SCANNED = "scanned"  # image-only pages
    PHOTO = "photo"  # camera image (stretch)


class TextLayer(StrEnum):
    OK = "ok"  # usable text layer
    GARBLED = "garbled"  # text present but extracts as garbage -> OCR (Phase 6)
    NONE = "none"  # < 50 non-space characters and mostly image -> OCR (Phase 6)


class FieldKind(StrEnum):
    TEXT = "text"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    CHOICE = "choice"
    DATE = "date"
    SIGNATURE = "signature"
    UNKNOWN = "unknown"


class ValueSource(StrEnum):
    PROFILE = "profile"
    USER_ANSWER = "user_answer"
    LLM_INFERRED = "llm_inferred"
    USER_EDIT = "user_edit"
    DERIVED = "derived"  # computed in code from the profile or the date (Phase 4, match pass)
    NONE = "none"


class FieldStatus(StrEnum):
    DETECTED = "detected"
    FILLED = "filled"
    NEEDS_INPUT = "needs_input"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"


class BBox(_IRModel):
    page: int = pydantic.Field(ge=0)  # 0-based index into FormIR.pages
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not all(math.isfinite(v) for v in (self.x0, self.y0, self.x1, self.y1)):
            raise ValueError("bbox coordinates must be finite")
        if not (self.x0 < self.x1 and self.y0 < self.y1):
            raise ValueError("bbox must have x0 < x1 and y0 < y1")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


class PageInfo(_IRModel):
    width: float = pydantic.Field(gt=0, allow_inf_nan=False)  # points, displayed page
    height: float = pydantic.Field(gt=0, allow_inf_nan=False)
    text_layer: TextLayer


class Option(_IRModel):
    """One choice of a checkbox, radio group or choice field."""

    value: str  # value written into the PDF (e.g. "/On", an export value)
    label: str | None = None
    bbox: BBox | None = None


class ValidationResult(_IRModel):
    validator: str  # e.g. "pan_format", "fits_box", "min_box_height"
    ok: bool
    message: str | None = None  # human-readable, never contains the value itself


class Field(_IRModel):
    id: str = pydantic.Field(min_length=1, max_length=64)  # stable in a document, e.g. "p0_f012"
    kind: FieldKind
    native_name: str | None  # AcroForm field name, if any
    label_text: str | None  # nearest label text
    context_text: str | None  # section heading / surrounding text
    bbox: BBox
    max_chars: int | None = pydantic.Field(default=None, gt=0)
    options: list[Option] = pydantic.Field(default_factory=list)
    semantic_type: SemanticType = SemanticType.UNKNOWN
    semantic_confidence: float = pydantic.Field(default=0.0, ge=0.0, le=1.0)
    semantic_method: Literal["rule", "llm", "user", "none"] = "none"
    value: str | None = None
    value_source: ValueSource = ValueSource.NONE
    validations: list[ValidationResult] = pydantic.Field(default_factory=list)
    status: FieldStatus = FieldStatus.DETECTED
    # Set for fields FormPilot never fills: not asked, not matched, not rendered (decision P3-D1,
    # docs/decisions/phase-3.md). None for every other field, and in IRs stored before Phase 3.
    no_fill_reason: Literal["office_use", "signature"] | None = None
    # Font size in points chosen by the fit pass (SPEC §6.7); None until the field has a value.
    font_size: float | None = pydantic.Field(default=None, gt=0)


class TraceEvent(_IRModel):
    pass_name: str  # e.g. "frontend.flat", "understand"
    field_id: str | None
    change: str  # what changed; never contains a value
    at: AwareDatetime


class FormIR(_IRModel):
    schema_version: int = 1
    document_id: UUID
    source_kind: SourceKind
    pages: list[PageInfo]  # index in this list == BBox.page
    fields: list[Field] = pydantic.Field(default_factory=list)
    trace: list[TraceEvent] = pydantic.Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [field.id for field in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("field ids must be unique within a document")
        page_count = len(self.pages)
        for field in self.fields:
            boxes = [field.bbox] + [opt.bbox for opt in field.options if opt.bbox is not None]
            if any(box.page >= page_count for box in boxes):
                raise ValueError(f"field {field.id} refers to a page that does not exist")
        return self
