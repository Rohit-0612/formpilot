"""Semantic types: what a field asks for (SPEC §5). Extend only via a decision record.

Each type has a TypeInfo with:
- description: one line, used in the LLM prompt (Phase 3);
- keywords: normalised (lower-case) label phrases for the rule matcher, English plus common Hindi
  transliterations. Address component keywords ("city", "pincode") are shared by the current_*
  and permanent_* variants on purpose: SPEC §6.2 decides between them from the section context;
- profile_key: the vault key the match pass reads, or None for derived and form-local types;
- sensitive: masked in API responses, saved to the vault only on explicit opt-in (decision D2);
- validators: names of the default validators (implemented in Phase 4).
"""

from dataclasses import dataclass
from enum import StrEnum


class SemanticType(StrEnum):
    # Identity
    FULL_NAME = "full_name"
    FIRST_NAME = "first_name"
    MIDDLE_NAME = "middle_name"
    LAST_NAME = "last_name"
    FATHER_NAME = "father_name"
    MOTHER_NAME = "mother_name"
    GUARDIAN_NAME = "guardian_name"
    SPOUSE_NAME = "spouse_name"
    DATE_OF_BIRTH = "date_of_birth"
    AGE = "age"
    GENDER = "gender"
    NATIONALITY = "nationality"
    CATEGORY = "category"
    MARITAL_STATUS = "marital_status"
    # Contact
    EMAIL = "email"
    PHONE_MOBILE = "phone_mobile"
    PHONE_ALTERNATE = "phone_alternate"
    # Address: current
    CURRENT_ADDRESS_LINE1 = "current_address_line1"
    CURRENT_ADDRESS_LINE2 = "current_address_line2"
    CURRENT_CITY = "current_city"
    CURRENT_DISTRICT = "current_district"
    CURRENT_STATE = "current_state"
    CURRENT_PINCODE = "current_pincode"
    CURRENT_COUNTRY = "current_country"
    # Address: permanent
    PERMANENT_ADDRESS_LINE1 = "permanent_address_line1"
    PERMANENT_ADDRESS_LINE2 = "permanent_address_line2"
    PERMANENT_CITY = "permanent_city"
    PERMANENT_DISTRICT = "permanent_district"
    PERMANENT_STATE = "permanent_state"
    PERMANENT_PINCODE = "permanent_pincode"
    PERMANENT_COUNTRY = "permanent_country"
    # IDs
    PAN = "pan"
    AADHAAR = "aadhaar"
    PASSPORT_NUMBER = "passport_number"
    VOTER_ID = "voter_id"
    # Bank
    BANK_NAME = "bank_name"
    BANK_ACCOUNT_NUMBER = "bank_account_number"
    IFSC = "ifsc"
    BANK_BRANCH = "bank_branch"
    # Education
    INSTITUTION_NAME = "institution_name"
    COURSE = "course"
    ENROLLMENT_NUMBER = "enrollment_number"
    YEAR_OF_STUDY = "year_of_study"
    PERCENTAGE_OR_CGPA = "percentage_or_cgpa"
    PASSING_YEAR = "passing_year"
    # Form-local
    DATE_OF_FILLING = "date_of_filling"
    PLACE = "place"
    SIGNATURE = "signature"
    DECLARATION_CHECKBOX = "declaration_checkbox"
    # Fallbacks
    OTHER = "other"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TypeInfo:
    description: str
    keywords: tuple[str, ...]
    profile_key: str | None
    sensitive: bool = False
    validators: tuple[str, ...] = ()


_PHONE = ("phone_in",)
_PINCODE = ("pincode_format",)

_ADDRESS_LINE1_COMMON = ("address", "address line 1", "house no", "flat no", "street", "pata")
_ADDRESS_LINE2_COMMON = ("address line 2", "locality", "area", "landmark", "village", "post office")
_CITY = ("city", "town", "city/town", "city / town", "shahar", "nagar")
_DISTRICT = ("district", "dist", "zila", "jila")
_STATE = ("state", "rajya")
_PINCODE_KW = ("pincode", "pin code", "pin", "postal code", "zip code")
_COUNTRY = ("country", "desh")


def _address(prefix: str, label: str, heading_keywords: tuple[str, ...]) -> dict[str, TypeInfo]:
    """The seven address types for one variant ("current" or "permanent")."""

    def key(part: str) -> str:
        return f"{prefix}_{part}"

    return {
        SemanticType(key("address_line1")): TypeInfo(
            f"First line of the {label} address (house, flat, street)",
            heading_keywords + _ADDRESS_LINE1_COMMON,
            key("address_line1"),
        ),
        SemanticType(key("address_line2")): TypeInfo(
            f"Second line of the {label} address (locality, area, landmark)",
            _ADDRESS_LINE2_COMMON,
            key("address_line2"),
        ),
        SemanticType(key("city")): TypeInfo(
            f"City or town of the {label} address", _CITY, key("city")
        ),
        SemanticType(key("district")): TypeInfo(
            f"District of the {label} address", _DISTRICT, key("district")
        ),
        SemanticType(key("state")): TypeInfo(f"State of the {label} address", _STATE, key("state")),
        SemanticType(key("pincode")): TypeInfo(
            f"Six-digit Indian PIN code of the {label} address",
            _PINCODE_KW,
            key("pincode"),
            validators=_PINCODE,
        ),
        SemanticType(key("country")): TypeInfo(
            f"Country of the {label} address", _COUNTRY, key("country")
        ),
    }


T = SemanticType

SEMANTIC_TYPES: dict[SemanticType, TypeInfo] = {
    # Identity
    T.FULL_NAME: TypeInfo(
        "The person's full name",
        (
            "name",
            "full name",
            "name in full",
            "applicant name",
            "name of applicant",
            "candidate name",
            "name of the candidate",
            "student name",
            "naam",
            "poora naam",
        ),
        "full_name",
    ),
    T.FIRST_NAME: TypeInfo(
        "Given (first) name", ("first name", "given name", "pehla naam"), "first_name"
    ),
    T.MIDDLE_NAME: TypeInfo("Middle name", ("middle name",), "middle_name"),
    T.LAST_NAME: TypeInfo(
        "Family name / surname", ("last name", "surname", "family name", "upnaam"), "last_name"
    ),
    T.FATHER_NAME: TypeInfo(
        "Father's name",
        ("father's name", "father name", "name of father", "father", "pita ka naam", "pita"),
        "father_name",
    ),
    T.MOTHER_NAME: TypeInfo(
        "Mother's name",
        ("mother's name", "mother name", "name of mother", "mother", "mata ka naam", "mata"),
        "mother_name",
    ),
    T.GUARDIAN_NAME: TypeInfo(
        "Guardian's name",
        ("guardian's name", "guardian name", "name of guardian", "guardian", "abhibhavak"),
        "guardian_name",
    ),
    T.SPOUSE_NAME: TypeInfo(
        "Spouse's (husband's or wife's) name",
        (
            "spouse's name",
            "spouse name",
            "husband's name",
            "wife's name",
            "pati ka naam",
            "patni ka naam",
        ),
        "spouse_name",
    ),
    T.DATE_OF_BIRTH: TypeInfo(
        "Date of birth",
        ("date of birth", "dob", "d.o.b", "birth date", "janm tithi", "janam tithi"),
        "date_of_birth",
        validators=("date", "dob_not_future"),
    ),
    T.AGE: TypeInfo("Age in years (derived from date of birth)", ("age", "aayu", "umar"), None),
    T.GENDER: TypeInfo("Gender", ("gender", "sex", "ling"), "gender"),
    T.NATIONALITY: TypeInfo("Nationality", ("nationality", "rashtriyata"), "nationality"),
    T.CATEGORY: TypeInfo(
        "Reservation category (General, OBC, SC, ST, EWS)",
        ("category", "caste category", "social category", "varg", "shreni"),
        "category",
    ),
    T.MARITAL_STATUS: TypeInfo(
        "Marital status", ("marital status", "vaivahik sthiti"), "marital_status"
    ),
    # Contact
    T.EMAIL: TypeInfo(
        "Email address",
        ("email", "e-mail", "email id", "email address"),
        "email",
        validators=("email_format",),
    ),
    T.PHONE_MOBILE: TypeInfo(
        "Mobile phone number",
        (
            "mobile",
            "mobile no",
            "mobile number",
            "phone",
            "phone no",
            "contact no",
            "contact number",
            "mob",
        ),
        "phone_mobile",
        validators=_PHONE,
    ),
    T.PHONE_ALTERNATE: TypeInfo(
        "Alternate or landline phone number",
        (
            "alternate phone",
            "alternate mobile",
            "alternate number",
            "landline",
            "tel",
            "telephone",
            "phone (residence)",
            "phone (office)",
        ),
        "phone_alternate",
        validators=_PHONE,
    ),
    # Address
    **_address(
        "current",
        "current (correspondence)",
        (
            "present address",
            "current address",
            "correspondence address",
            "address for correspondence",
            "address for communication",
            "mailing address",
            "vartaman pata",
        ),
    ),
    **_address(
        "permanent",
        "permanent",
        ("permanent address", "sthayi pata", "sthai pata"),
    ),
    # IDs (all sensitive, decision D2)
    T.PAN: TypeInfo(
        "Indian Permanent Account Number (PAN), 10 characters",
        ("pan", "pan no", "pan number", "permanent account number"),
        "pan",
        sensitive=True,
        validators=("pan_format",),
    ),
    T.AADHAAR: TypeInfo(
        "Aadhaar number, 12 digits",
        ("aadhaar", "aadhar", "aadhaar no", "aadhaar number", "uid", "uid no", "aadhaar card no"),
        "aadhaar",
        sensitive=True,
        validators=("aadhaar_format", "aadhaar_verhoeff"),
    ),
    T.PASSPORT_NUMBER: TypeInfo(
        "Passport number",
        ("passport no", "passport number", "passport"),
        "passport_number",
        sensitive=True,
    ),
    T.VOTER_ID: TypeInfo(
        "Voter ID (EPIC) number",
        ("voter id", "voter id no", "voter card", "epic no", "election card"),
        "voter_id",
        sensitive=True,
    ),
    # Bank (only the account number is sensitive, decision D2)
    T.BANK_NAME: TypeInfo("Name of the bank", ("bank name", "name of bank", "bank"), "bank_name"),
    T.BANK_ACCOUNT_NUMBER: TypeInfo(
        "Bank account number",
        (
            "account no",
            "account number",
            "a/c no",
            "bank account no",
            "bank account number",
            "khata sankhya",
        ),
        "bank_account_number",
        sensitive=True,
    ),
    T.IFSC: TypeInfo(
        "IFSC code of the bank branch, 11 characters",
        ("ifsc", "ifsc code", "ifs code"),
        "ifsc",
        validators=("ifsc_format",),
    ),
    T.BANK_BRANCH: TypeInfo(
        "Bank branch name", ("branch", "branch name", "bank branch", "shakha"), "bank_branch"
    ),
    # Education
    T.INSTITUTION_NAME: TypeInfo(
        "Name of the school, college or university",
        (
            "institution",
            "name of institution",
            "college",
            "college name",
            "school",
            "school name",
            "university",
            "vidyalaya",
            "mahavidyalaya",
            "vishwavidyalaya",
        ),
        "institution_name",
    ),
    T.COURSE: TypeInfo(
        "Course or programme of study",
        (
            "course",
            "course name",
            "programme",
            "program",
            "branch of study",
            "stream",
            "pathyakram",
        ),
        "course",
    ),
    T.ENROLLMENT_NUMBER: TypeInfo(
        "Enrollment, roll or registration number",
        (
            "enrollment no",
            "enrolment no",
            "enrollment number",
            "roll no",
            "roll number",
            "registration no",
            "registration number",
            "anukramank",
        ),
        "enrollment_number",
    ),
    T.YEAR_OF_STUDY: TypeInfo(
        "Current year or semester of study",
        ("year", "year of study", "semester", "current year", "class"),
        "year_of_study",
    ),
    T.PERCENTAGE_OR_CGPA: TypeInfo(
        "Marks as a percentage or CGPA",
        ("percentage", "% marks", "marks obtained", "cgpa", "sgpa", "grade", "pratishat"),
        "percentage_or_cgpa",
    ),
    T.PASSING_YEAR: TypeInfo(
        "Year of passing an examination",
        ("year of passing", "passing year", "year of pass"),
        "passing_year",
    ),
    # Form-local (not stored in the vault)
    T.DATE_OF_FILLING: TypeInfo(
        "Date the form is filled (today)",
        ("date", "dated", "dinank", "tithi"),
        None,
        validators=("date",),
    ),
    T.PLACE: TypeInfo("Place where the form is signed", ("place", "sthan"), None),
    T.SIGNATURE: TypeInfo(
        "Signature of the applicant",
        ("signature", "signature of applicant", "sign", "hastakshar"),
        None,
    ),
    T.DECLARATION_CHECKBOX: TypeInfo(
        "Checkbox confirming a declaration or consent",
        ("i agree", "i declare", "i hereby declare", "declaration", "i confirm"),
        None,
    ),
    # Fallbacks
    T.OTHER: TypeInfo("Understood, but not one of the types above; always asked", (), None),
    T.UNKNOWN: TypeInfo("Not understood", (), None),
}

SENSITIVE_TYPES: frozenset[SemanticType] = frozenset(
    semantic_type for semantic_type, info in SEMANTIC_TYPES.items() if info.sensitive
)


def type_info(semantic_type: SemanticType) -> TypeInfo:
    return SEMANTIC_TYPES[semantic_type]
