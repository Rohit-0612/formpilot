import pytest

from app.ir.semantic_types import SEMANTIC_TYPES, SENSITIVE_TYPES, SemanticType, type_info

ADDRESS_PARTS = (
    "address_line1",
    "address_line2",
    "city",
    "district",
    "state",
    "pincode",
    "country",
)

# SPEC §5, written out by hand: adding or removing a type needs a decision record.
SPEC_TYPES = {
    # Identity
    "full_name", "first_name", "middle_name", "last_name", "father_name", "mother_name",
    "guardian_name", "spouse_name", "date_of_birth", "age", "gender", "nationality", "category",
    "marital_status",
    # Contact
    "email", "phone_mobile", "phone_alternate",
    # Address
    *(f"{prefix}_{part}" for prefix in ("current", "permanent") for part in ADDRESS_PARTS),
    # IDs
    "pan", "aadhaar", "passport_number", "voter_id",
    # Bank
    "bank_name", "bank_account_number", "ifsc", "bank_branch",
    # Education
    "institution_name", "course", "enrollment_number", "year_of_study", "percentage_or_cgpa",
    "passing_year",
    # Form-local
    "date_of_filling", "place", "signature", "declaration_checkbox",
    # Fallbacks
    "other", "unknown",
}  # fmt: skip

# Decision D2 (docs/decisions/phase-2.md): CLAUDE.md §3 plus voter_id.
EXPECTED_SENSITIVE = {"aadhaar", "pan", "bank_account_number", "passport_number", "voter_id"}

# Derived in code, form-local, or fallbacks: never read from the vault.
NO_PROFILE_KEY = {
    "age",
    "date_of_filling",
    "place",
    "signature",
    "declaration_checkbox",
    "other",
    "unknown",
}


def test_enum_matches_spec_section_5() -> None:
    assert {member.value for member in SemanticType} == SPEC_TYPES


def test_every_type_has_info() -> None:
    assert set(SEMANTIC_TYPES) == set(SemanticType)


def test_sensitive_set_matches_decision_d2() -> None:
    assert {member.value for member in SENSITIVE_TYPES} == EXPECTED_SENSITIVE


@pytest.mark.parametrize("semantic_type", list(SemanticType))
def test_type_info_is_complete(semantic_type: SemanticType) -> None:
    info = type_info(semantic_type)

    assert info.description.strip()
    if semantic_type not in (SemanticType.OTHER, SemanticType.UNKNOWN):
        assert info.keywords, "the rule matcher needs at least one keyword"
    for keyword in info.keywords:
        assert keyword == keyword.strip().lower(), "keywords are normalised (lower-case, trimmed)"
        assert keyword
    assert len(info.keywords) == len(set(info.keywords)), "duplicate keyword"


@pytest.mark.parametrize("semantic_type", list(SemanticType))
def test_profile_key(semantic_type: SemanticType) -> None:
    info = type_info(semantic_type)

    if semantic_type.value in NO_PROFILE_KEY:
        assert info.profile_key is None
    else:
        assert info.profile_key == semantic_type.value


@pytest.mark.parametrize("prefix", ["current", "permanent"])
def test_address_variants_are_complete(prefix: str) -> None:
    for part in ADDRESS_PARTS:
        assert SemanticType(f"{prefix}_{part}") in SEMANTIC_TYPES


def test_address_variants_differ_only_by_heading_keywords() -> None:
    """Components share keywords; current vs permanent is decided from context (SPEC §6.2)."""
    current = type_info(SemanticType.CURRENT_CITY).keywords
    permanent = type_info(SemanticType.PERMANENT_CITY).keywords
    assert current == permanent

    current_line1 = set(type_info(SemanticType.CURRENT_ADDRESS_LINE1).keywords)
    permanent_line1 = set(type_info(SemanticType.PERMANENT_ADDRESS_LINE1).keywords)
    assert "permanent address" in permanent_line1 - current_line1
    assert "present address" in current_line1 - permanent_line1


def test_validators_named_for_types_with_format_rules() -> None:
    """SPEC §6.6 rules attach to these types (implemented in Phase 4)."""
    assert type_info(SemanticType.PAN).validators == ("pan_format",)
    assert "aadhaar_verhoeff" in type_info(SemanticType.AADHAAR).validators
    assert type_info(SemanticType.IFSC).validators == ("ifsc_format",)
    assert type_info(SemanticType.CURRENT_PINCODE).validators == ("pincode_format",)
    assert type_info(SemanticType.PERMANENT_PINCODE).validators == ("pincode_format",)
    assert type_info(SemanticType.PHONE_MOBILE).validators == ("phone_in",)
    assert "dob_not_future" in type_info(SemanticType.DATE_OF_BIRTH).validators
