"""Match pass (SPEC §6.3): fill fields from the profile, under a precision-first fill policy.

A field is filled only if (decision P4-D2):
- it is not a never-fill field and has no value yet;
- it is no tick box or radio (decision P5-D12): a tick comes only from the user's own answer to a
  choice question, never from the profile having a value;
- it asks for no number an institution gives for this application (decision P5-D20): the
  `enrollment_number` type, or a label naming an enrolment, roll, registration, application,
  membership or admission number is always asked;
- its semantic type is confident under the policy: matched by a rule, or by the LLM with a
  confidence of at least `min_llm_confidence` (None: the LLM's types never fill);
- a type in `once_per_form` has not been filled earlier on the form (reading order): a second
  name or date on a form is often another person's or another date; the day, month and year
  boxes of one date (`date_part`) count once each;
- it is in no group (decision P5-D8): a row of a table with several rows is one instance of
  many (a profile holds one value per type), and a row of tick boxes is asked as one choice;
- for a date in DD | MM | YYYY boxes (`app.ir.parts.date_groups`), every part gets a value
  (decision P5-D13): otherwise none is filled and the date is asked; and if one part is only a
  suggestion, so are the others (a date is confirmed and printed whole);
- for a name in FIRST | MIDDLE | LAST boxes (`app.ir.parts.name_groups`) whose parts include a
  trusted whole-name type (the guardian's, father's, mother's, spouse's or the applicant's own
  name), the name is split into the parts as suggestions, each confirmed on its own, never the
  whole name in one part (decision P5-D16): two words are first and last name, three words fill
  a row with all three parts; any other split is unclear and the parts are asked. Values the row's
  other parts got for their own types are removed;
- the profile gives a value: stored (`PROFILE`) or computed in code (`DERIVED`: full name from
  its parts, age from the date of birth, today's date, the country of a nationality for a field
  that asks for a country, decision P5-D21: "Country of Citizenship" gets "India", not
  "Indian"; a nationality missing from `COUNTRY_OF` is asked).

Suggested values (decision P5-D1): a field the policy does not trust, typed by the LLM with a
confidence of at least `suggest_min_confidence`, gets the profile value with status SUGGESTED:
prefilled but unconfirmed, not asked, rendered only after the user confirms it. The once-per-form
rule applies to suggestions as well, after the filled fields. Suggestions never change which
fields are filled.

Every other field without a value gets status NEEDS_INPUT and is asked (questions pass). The
trace names the type and the source, never the value.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from app.ir.models import Field, FieldKind, FieldStatus, FormIR, Option, TraceEvent, ValueSource
from app.ir.parts import NamePart, date_groups, name_groups
from app.ir.phrases import clean_text, names_institution_number
from app.ir.semantic_types import SEMANTIC_TYPES
from app.ir.semantic_types import SemanticType as T
from app.passes.context import PassContext
from app.validators.dates import date_format_for, format_date

STAGE = "match"

PERSON_AND_DATE_TYPES: frozenset[T] = frozenset(
    {
        T.FULL_NAME, T.FIRST_NAME, T.MIDDLE_NAME, T.LAST_NAME, T.FATHER_NAME, T.MOTHER_NAME,
        T.GUARDIAN_NAME, T.SPOUSE_NAME, T.DATE_OF_BIRTH, T.AGE, T.GENDER, T.DATE_OF_FILLING,
    }
)  # fmt: skip
_OPTION_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO, FieldKind.CHOICE})
TICK_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO})


@dataclass(frozen=True)
class FillPolicy:
    min_llm_confidence: float | None = 0.99
    once_per_form: frozenset[T] = field(default_factory=frozenset)

    def confident(self, f: Field) -> bool:
        if f.semantic_method == "rule" or f.semantic_method == "user":
            return True
        if f.semantic_method == "llm" and self.min_llm_confidence is not None:
            return f.semantic_confidence >= self.min_llm_confidence
        return False


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _age(born: date, today: date) -> int:
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _choose_option(options: list[Option], value: str) -> str | None:
    """The option whose label or value is the profile value (case-insensitive), or the one it
    abbreviates ("M" for "Male"); None if no single option matches."""
    wanted = value.strip().casefold()
    exact = [o for o in options if wanted in {(o.label or "").casefold(), o.value.casefold()}]
    if len(exact) == 1:
        return exact[0].value
    letters = [o for o in options if (o.label or o.value).strip().casefold() == wanted[:1]]
    return letters[0].value if len(letters) == 1 and len(wanted) > 1 else None


# The country of a nationality (P5-D21); a country name maps to itself.
COUNTRY_OF: dict[str, str] = {
    "indian": "India", "nepali": "Nepal", "nepalese": "Nepal", "bhutanese": "Bhutan",
    "bangladeshi": "Bangladesh", "sri lankan": "Sri Lanka", "american": "United States",
    "british": "United Kingdom", "canadian": "Canada", "australian": "Australia",
}  # fmt: skip


def _asks_country(f: Field) -> bool:
    return "country" in clean_text(f.label_text or "").split()


def country_of(nationality: str) -> str | None:
    key = clean_text(nationality)
    known = {clean_text(c): c for c in COUNTRY_OF.values()}
    return COUNTRY_OF.get(key) or known.get(key)


def resolve(f: Field, profile: Mapping[str, str], today: date) -> tuple[str, ValueSource] | None:
    """The value for the field's type from the profile, formatted for this field, or None."""
    t = f.semantic_type
    if t is T.DATE_OF_FILLING:
        return format_date(today, date_format_for(f)), ValueSource.DERIVED
    if t is T.AGE:
        born = _iso(profile.get("date_of_birth", ""))
        return (str(_age(born, today)), ValueSource.DERIVED) if born else None
    key = SEMANTIC_TYPES[t].profile_key
    stored = profile.get(key) if key else None
    if stored is None and t is T.FULL_NAME:
        parts = [profile.get(k) for k in ("first_name", "middle_name", "last_name")]
        if parts[0] and parts[2]:
            return " ".join(p for p in parts if p), ValueSource.DERIVED
        return None
    if stored is None:
        return None
    if t is T.NATIONALITY and _asks_country(f):
        country = country_of(stored)
        return (country, ValueSource.DERIVED) if country else None
    if t is T.DATE_OF_BIRTH:
        born = _iso(stored)
        return (format_date(born, date_format_for(f)), ValueSource.PROFILE) if born else None
    if f.kind in _OPTION_KINDS and f.options:
        chosen = _choose_option(f.options, stored)
        return (chosen, ValueSource.PROFILE) if chosen else None
    return stored, ValueSource.PROFILE


def policy_for(ctx: PassContext) -> FillPolicy:
    return FillPolicy(
        min_llm_confidence=ctx.fill_min_confidence,
        once_per_form=PERSON_AND_DATE_TYPES if ctx.fill_once_per_form else frozenset(),
    )


def _once_key(f: Field) -> tuple[T, str | None]:
    return f.semantic_type, f.date_part


INSTITUTION_SCOPED: frozenset[T] = frozenset({T.ENROLLMENT_NUMBER})


def _profile_fillable(f: Field) -> bool:
    """Neither a never-fill field, nor in a group (P5-D8), nor a tick box (P5-D12), nor a number
    an institution gives (P5-D20)."""
    if f.no_fill_reason is not None or f.group_id is not None or f.kind in TICK_KINDS:
        return False
    return f.semantic_type not in INSTITUTION_SCOPED and not names_institution_number(f.label_text)


def typed_field_ids(ir: FormIR, policy: FillPolicy) -> set[str]:
    """The fields whose semantic type the policy trusts: confident, in no group, and for a
    once-per-form type the first such field (or date part) in reading order. Only these are
    filled from, or saved to, the profile; the others are asked with the form's own label."""
    seen: set[tuple[T, str | None]] = set()
    typed: set[str] = set()
    for f in ir.fields:
        if not _profile_fillable(f) or not policy.confident(f):
            continue
        if f.semantic_type in policy.once_per_form:
            if _once_key(f) in seen:
                continue
            seen.add(_once_key(f))
        typed.add(f.id)
    return typed


def suggested_field_ids(
    ir: FormIR, policy: FillPolicy, floor: float | None, typed: set[str] | None = None
) -> set[str]:
    """The fields that get a suggested value if the profile has one (P5-D1): typed by the LLM
    with a confidence of at least `floor` but not trusted by the policy; a once-per-form type
    only if no trusted field and no earlier suggestion on the form has it. None: no suggestions."""
    if floor is None:
        return set()
    typed = typed_field_ids(ir, policy) if typed is None else typed
    seen = {_once_key(f) for f in ir.fields if f.id in typed}
    suggested: set[str] = set()
    for f in ir.fields:
        if f.id in typed or not _profile_fillable(f) or f.semantic_method != "llm":
            continue
        if f.semantic_confidence < floor or f.semantic_type in (T.OTHER, T.UNKNOWN):
            continue
        if f.semantic_type in policy.once_per_form:
            if _once_key(f) in seen:
                continue
            seen.add(_once_key(f))
        suggested.add(f.id)
    return suggested


def run(ir: FormIR, ctx: PassContext, policy: FillPolicy | None = None) -> FormIR:
    policy = policy or policy_for(ctx)
    today = ctx.today()
    typed = typed_field_ids(ir, policy)
    suggested = suggested_field_ids(ir, policy, ctx.suggest_min_confidence, typed)
    trace: list[TraceEvent] = []
    fields: list[Field] = []
    for f in ir.fields:
        if f.no_fill_reason is not None or f.value is not None:
            fields.append(f)
            continue
        found = resolve(f, ctx.profile, today) if f.id in typed | suggested else None
        if found is None:
            fields.append(f.model_copy(update={"status": FieldStatus.NEEDS_INPUT}))
            continue
        value, source = found
        status = FieldStatus.FILLED if f.id in typed else FieldStatus.SUGGESTED
        update = {"value": value, "value_source": source, "status": status}
        fields.append(f.model_copy(update=update))
        verb = "filled" if status is FieldStatus.FILLED else "suggested"
        trace.append(
            TraceEvent(
                pass_name=STAGE,
                field_id=f.id,
                change=f"{verb} {f.semantic_type.value} ({source.value})",
                at=ctx.clock(),
            )
        )
    set_here = {f.id for f in ir.fields if f.value is None}
    fields = _whole_dates(fields, set_here, trace, ctx)
    fields = _split_names(fields, set_here, typed | suggested, trace, ctx)
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})


def _whole_dates(
    fields: list[Field], set_here: set[str], trace: list[TraceEvent], ctx: PassContext
) -> list[Field]:
    """P5-D13: a date's parts are filled all or none, and confirmed together."""
    by_id = {f.id: f for f in fields}
    for parts in date_groups(fields):
        mine = [p for p in parts if p.id in set_here and p.value is not None]
        if not mine:
            continue
        if any(p.value is None for p in parts):
            for p in mine:
                by_id[p.id] = p.model_copy(
                    update={
                        "value": None,
                        "value_source": ValueSource.NONE,
                        "status": FieldStatus.NEEDS_INPUT,
                    }
                )
                change = "not filled: the date's other parts have no value"
                trace.append(
                    TraceEvent(pass_name=STAGE, field_id=p.id, change=change, at=ctx.clock())
                )
        elif any(p.status is FieldStatus.SUGGESTED for p in mine):
            for p in mine:
                if p.status is FieldStatus.FILLED:
                    by_id[p.id] = p.model_copy(update={"status": FieldStatus.SUGGESTED})
                    change = "suggested: a part of the same date is a suggestion"
                    trace.append(
                        TraceEvent(pass_name=STAGE, field_id=p.id, change=change, at=ctx.clock())
                    )
    return [by_id[f.id] for f in fields]


WHOLE_NAME_TYPES = frozenset(
    {T.FULL_NAME, T.FATHER_NAME, T.MOTHER_NAME, T.GUARDIAN_NAME, T.SPOUSE_NAME}
)
_PART_KEYS: dict[NamePart, str] = {
    "first": "first_name",
    "middle": "middle_name",
    "last": "last_name",
}


def split_name(value: str, parts: set[NamePart]) -> dict[NamePart, str] | None:
    """The name over the parts a row has, or None when the split is unclear (P5-D16)."""
    words = value.split()
    if len(words) == 2 and {"first", "last"} <= parts:
        return {"first": words[0], "last": words[1]}
    if len(words) == 3 and parts == {"first", "middle", "last"}:
        return {"first": words[0], "middle": words[1], "last": words[2]}
    return None


def _whole_name_parts(
    person: T, profile: Mapping[str, str], parts: set[NamePart]
) -> dict[NamePart, str] | None:
    if person is T.FULL_NAME and profile.get("first_name") and profile.get("last_name"):
        stored = {p: profile[k] for p, k in _PART_KEYS.items() if profile.get(k)}
        return stored if set(stored) <= parts else None  # a middle name with no box: unclear
    key = SEMANTIC_TYPES[person].profile_key
    value = profile.get(key) if key else None
    return split_name(value, parts) if value else None


def _split_names(
    fields: list[Field],
    set_here: set[str],
    trusted: set[str],
    trace: list[TraceEvent],
    ctx: PassContext,
) -> list[Field]:
    """P5-D16: a whole name split over its FIRST | MIDDLE | LAST boxes, as suggestions."""
    by_id = {f.id: f for f in fields}
    for row in name_groups(fields):
        if any(f.id not in set_here for f, _ in row):
            continue  # a part already had a value (the user's): left alone
        persons = {f.semantic_type for f, _ in row if f.semantic_type in WHOLE_NAME_TYPES}
        persons &= {f.semantic_type for f, _ in row if f.id in trusted}
        if len(persons) != 1:
            continue  # parts typed one by one (the applicant's own row), or two people
        (person,) = persons
        split = _whole_name_parts(person, ctx.profile, {p for _, p in row})
        for f, part in row:
            value = split.get(part) if split else None
            if value is not None:
                update = {
                    "value": value,
                    "value_source": ValueSource.DERIVED,
                    "status": FieldStatus.SUGGESTED,
                }
                change = f"suggested the {part} part of {person.value} (split)"
            else:
                update = {
                    "value": None,
                    "value_source": ValueSource.NONE,
                    "status": FieldStatus.NEEDS_INPUT,
                }
                change = f"not filled: {part} part of {person.value}, " + (
                    "no such word" if split else "the split is unclear"
                )
            by_id[f.id] = f.model_copy(update=update)
            trace.append(TraceEvent(pass_name=STAGE, field_id=f.id, change=change, at=ctx.clock()))
    return [by_id[f.id] for f in fields]
