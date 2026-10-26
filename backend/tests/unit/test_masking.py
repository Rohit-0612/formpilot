"""Masking of sensitive values in IRs returned to the client (SPEC §8, decision D2).

All values are synthetic and format-valid only.
"""

import typing
import uuid

import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.api.schemas.ir import MaskedFormIR
from app.config import Settings
from app.ir.models import BBox, Field, FieldKind, FormIR, PageInfo, SourceKind, TextLayer
from app.ir.semantic_types import SENSITIVE_TYPES
from app.ir.semantic_types import SemanticType as T
from app.main import create_app
from app.services.masking import looks_sensitive, mask_ir_data, mask_value

AADHAAR = "2345 6789 0124"
PAN = "ABCDE1234F"
PASSPORT = "K1234567"
VOTER_ID = "ABC1234567"
ACCOUNT = "001234567890"


def _field(i: int, semantic_type: T, value: str | None) -> Field:
    return Field(
        id=f"p0_f{i:03d}",
        kind=FieldKind.TEXT,
        native_name=None,
        label_text=None,
        context_text=None,
        bbox=BBox(page=0, x0=10, y0=10, x1=100, y1=22),
        semantic_type=semantic_type,
        value=value,
    )


def _ir(*fields: tuple[T, str | None]) -> FormIR:
    return FormIR(
        document_id=uuid.uuid4(),
        source_kind=SourceKind.FLAT_TEXT,
        pages=[PageInfo(width=595, height=842, text_layer=TextLayer.OK)],
        fields=[_field(i, t, v) for i, (t, v) in enumerate(fields)],
    )


# --- the mask -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "masked"),
    [
        ("234567890124", "XXXX0124"),
        (AADHAAR, "XXXX0124"),  # separators removed before taking the tail
        ("abcde1234f", "XXXX234F"),
        ("K1234567", "XXXX4567"),  # exactly 8 characters: tail shown
        ("1234567", "XXXX"),  # shorter: fully hidden
        ("", "XXXX"),
    ],
)
def test_mask_value(value: str, masked: str) -> None:
    assert mask_value(value) == masked


def test_mask_has_a_fixed_prefix_so_the_length_is_not_revealed() -> None:
    assert mask_value("123456789") == mask_value("000000000000000006789") == "XXXX6789"


def test_masking_is_idempotent() -> None:
    assert mask_value(mask_value(AADHAAR)) == mask_value(AADHAAR)


# --- which values -------------------------------------------------------------------------


def test_every_sensitive_type_is_masked_whatever_the_value() -> None:
    ir = _ir(*[(t, "plain text") for t in sorted(SENSITIVE_TYPES)])

    masked = MaskedFormIR.model_validate(ir)

    assert [f.value for f in masked.fields] == ["XXXX" + "TEXT"] * len(SENSITIVE_TYPES)
    assert {T.AADHAAR, T.PAN, T.BANK_ACCOUNT_NUMBER, T.PASSPORT_NUMBER, T.VOTER_ID} <= {
        f.semantic_type for f in masked.fields
    }


@pytest.mark.parametrize(
    "value",
    [AADHAAR, "234567890124", PAN, "abcde 1234 f", PASSPORT, VOTER_ID, ACCOUNT, "123456789"],
)
@pytest.mark.parametrize(
    "semantic_type", [T.OTHER, T.UNKNOWN, T.FULL_NAME, T.CURRENT_ADDRESS_LINE1]
)
def test_defence_in_depth_masks_identifier_shaped_values_in_any_field(
    value: str, semantic_type: T
) -> None:
    """An Aadhaar typed into a field understood as `other` is still masked."""
    (field,) = MaskedFormIR.model_validate(_ir((semantic_type, value))).fields

    assert field.value == mask_value(value)
    assert looks_sensitive(value, semantic_type)


@pytest.mark.parametrize(
    ("semantic_type", "value"),
    [
        (T.FULL_NAME, "Asha Verma"),
        (T.CURRENT_PINCODE, "411001"),  # 6 digits: not an identifier
        (T.DATE_OF_BIRTH, "01/02/2003"),
        (T.EMAIL, "asha@example.com"),
        (T.IFSC, "SBIN0001234"),  # public bank data (D2)
        (T.PHONE_MOBILE, "9876543210"),
        (T.PHONE_MOBILE, "+91 98765 43210"),
        (T.PHONE_ALTERNATE, "09876543210"),
        (T.OTHER, None),
    ],
)
def test_other_values_are_left_alone(semantic_type: T, value: str | None) -> None:
    (field,) = MaskedFormIR.model_validate(_ir((semantic_type, value))).fields

    assert field.value == value


@pytest.mark.parametrize(
    "value",
    [
        "9876543210",
        "6000000000",
        "+91 98765 43210",
        "+91-9876543210",
        "098765 43210",
    ],
)
@pytest.mark.parametrize("semantic_type", [T.PHONE_MOBILE, T.PHONE_ALTERNATE])
def test_phone_exception_covers_indian_mobile_numbers_in_phone_fields(
    semantic_type: T, value: str
) -> None:
    (field,) = MaskedFormIR.model_validate(_ir((semantic_type, value))).fields

    assert field.value == value


@pytest.mark.parametrize(
    "value",
    [
        AADHAAR,  # an Aadhaar typed into a phone field
        "5876543210",  # starts with 5: not a mobile number, but account-shaped
        "98765432101",  # 11 digits without a leading 0
        "919876543210",  # 91 without "+": Aadhaar-shaped
        "+1 234567890123",  # another country code
        PAN,
    ],
)
def test_other_values_in_phone_fields_are_still_masked(value: str) -> None:
    (field,) = MaskedFormIR.model_validate(_ir((T.PHONE_MOBILE, value))).fields

    assert field.value == mask_value(value)


@pytest.mark.parametrize("value", ["9876543210", "+91 98765 43210", "+234567890124"])
def test_mobile_shaped_and_plus_prefixed_values_are_masked_outside_phone_fields(
    value: str,
) -> None:
    (field,) = MaskedFormIR.model_validate(_ir((T.OTHER, value))).fields

    assert field.value == mask_value(value)


def test_known_limitations_are_what_they_say() -> None:
    """Recorded in docs/decisions/phase-2.md; this test fails if the behaviour changes."""
    misclassified_account = _ir((T.PHONE_MOBILE, "9876543210"))  # really an account number
    in_free_text = _ir((T.CURRENT_ADDRESS_LINE1, "House 12, Aadhaar 2345 6789 0124"))

    assert MaskedFormIR.model_validate(misclassified_account).fields[0].value == "9876543210"
    assert "2345 6789 0124" in str(MaskedFormIR.model_validate(in_free_text).fields[0].value)


# --- building the client IR ---------------------------------------------------------------


def test_masked_ir_is_built_from_a_model_a_dict_or_stored_json_alike() -> None:
    ir = _ir((T.AADHAAR, AADHAAR), (T.FULL_NAME, "Asha Verma"))

    for source in (ir, ir.model_dump(), ir.model_dump(mode="json")):
        masked = MaskedFormIR.model_validate(source)
        assert [f.value for f in masked.fields] == ["XXXX0124", "Asha Verma"]


def test_masking_never_changes_the_stored_ir() -> None:
    ir = _ir((T.AADHAAR, AADHAAR))
    stored = ir.model_dump(mode="json")

    MaskedFormIR.model_validate(ir)
    mask_ir_data(stored)

    assert ir.fields[0].value == AADHAAR
    assert stored["fields"][0]["value"] == AADHAAR


def test_only_values_are_masked() -> None:
    ir = _ir((T.AADHAAR, AADHAAR))

    masked = MaskedFormIR.model_validate(ir)

    assert masked.model_dump(exclude={"fields"}) == ir.model_dump(exclude={"fields"})
    assert masked.fields[0].model_dump(exclude={"value"}) == ir.fields[0].model_dump(
        exclude={"value"}
    )


# --- the rule: every IR that leaves the API is masked --------------------------------------


def _refs(node: object) -> typing.Iterator[str]:
    """Every component name referenced ($ref) anywhere below an OpenAPI node."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref.rsplit("/", 1)[-1]
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def _reachable(names: typing.Iterable[str], components: dict[str, object]) -> set[str]:
    seen: set[str] = set()
    stack = list(names)
    while stack:
        name = stack.pop()
        if name not in seen:
            seen.add(name)
            stack.extend(_refs(components.get(name, {})))
    return seen


def _ir_routes(openapi: dict[str, typing.Any]) -> dict[str, set[str]]:
    """Path -> IR schemas its responses can contain, directly or nested."""
    components = openapi.get("components", {}).get("schemas", {})
    ir_names = {"FormIR", "MaskedFormIR"}
    found = {}
    for path, operations in openapi["paths"].items():
        responses = [op.get("responses", {}) for op in operations.values()]
        reachable = _reachable(_refs(responses), components) & ir_names
        if reachable:
            found[path] = reachable
    return found


def test_no_route_returns_an_unmasked_form_ir(settings: Settings) -> None:
    """SPEC §8: a Form IR leaves the API only as MaskedFormIR, in any route, at any depth."""
    found = _ir_routes(create_app(settings).openapi())

    assert found["/api/v1/documents/{document_id}/ir"] == {"MaskedFormIR"}
    assert all(names == {"MaskedFormIR"} for names in found.values()), found


def test_the_rule_check_finds_a_nested_plain_ir() -> None:
    class Wrapper(BaseModel):
        irs: list[FormIR] | None

    app = FastAPI()

    @app.get("/leaky", response_model=Wrapper)
    def leaky() -> Wrapper:  # pragma: no cover - never called
        raise NotImplementedError

    assert _ir_routes(app.openapi()) == {"/leaky": {"FormIR"}}
