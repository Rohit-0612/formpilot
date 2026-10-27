"""The profile's keys (one per semantic type with a profile key, SPEC §5), with a label and a
group for the profile page and the question templates."""

from dataclasses import dataclass

from app.ir.semantic_types import SEMANTIC_TYPES, SemanticType


@dataclass(frozen=True)
class ProfileField:
    key: str
    label: str
    group: str
    sensitive: bool
    semantic_type: SemanticType


_LABELS = {
    "pan": "PAN",
    "aadhaar": "Aadhaar number",
    "ifsc": "IFSC",
    "date_of_birth": "Date of birth",
    "phone_mobile": "Mobile number",
    "phone_alternate": "Alternate phone number",
    "percentage_or_cgpa": "Percentage or CGPA",
    "voter_id": "Voter ID",
    "email": "Email address",
    "father_name": "Father's name",
    "mother_name": "Mother's name",
    "guardian_name": "Guardian's name",
    "spouse_name": "Spouse's name",
    "current_pincode": "PIN code",
    "permanent_pincode": "PIN code",
}

_GROUPS = (
    ("current_", "Current address"),
    ("permanent_", "Permanent address"),
    ("bank_", "Bank"),
    ("ifsc", "Bank"),
)
_IDENTITY_IDS = {"pan", "aadhaar", "passport_number", "voter_id"}
_EDUCATION = {
    "institution_name",
    "course",
    "enrollment_number",
    "year_of_study",
    "percentage_or_cgpa",
    "passing_year",
}
_CONTACT = {"email", "phone_mobile", "phone_alternate"}


def _label(key: str) -> str:
    if key in _LABELS:
        return _LABELS[key]
    for prefix, _ in _GROUPS[:2]:
        if key.startswith(prefix):
            key = key.removeprefix(prefix)
    return key.replace("_", " ").capitalize().replace("line1", "line 1").replace("line2", "line 2")


def _group(key: str) -> str:
    for prefix, group in _GROUPS:
        if key.startswith(prefix):
            return group
    if key in _IDENTITY_IDS:
        return "ID numbers"
    if key in _EDUCATION:
        return "Education"
    if key in _CONTACT:
        return "Contact"
    return "Personal"


PROFILE_FIELDS: tuple[ProfileField, ...] = tuple(
    ProfileField(
        info.profile_key, _label(info.profile_key), _group(info.profile_key), info.sensitive, t
    )
    for t, info in SEMANTIC_TYPES.items()
    if info.profile_key is not None
)
BY_KEY: dict[str, ProfileField] = {f.key: f for f in PROFILE_FIELDS}
