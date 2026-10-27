"""Match pass (SPEC §6.3): fill fields from the profile, under a precision-first fill policy.

A field is filled only if (decision P4-D2):
- it is not a never-fill field and has no value yet;
- its semantic type is confident under the policy: matched by a rule, or by the LLM with a
  confidence of at least `min_llm_confidence` (None: the LLM's types never fill);
- a type in `once_per_form` has not been filled earlier on the form (reading order): a second
  name or date on a form is often another person's or another date;
- the profile gives a value: stored (`PROFILE`) or computed in code (`DERIVED`: full name from
  its parts, age from the date of birth, today's date).

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


def typed_field_ids(ir: FormIR, policy: FillPolicy) -> set[str]:
    """The fields whose semantic type the policy trusts: confident, and for a once-per-form type
    the first such field in reading order. Only these are filled from, or saved to, the profile;
    the others are asked with the form's own label."""
    seen: set[T] = set()
    typed: set[str] = set()
    for f in ir.fields:
        if f.no_fill_reason is not None or not policy.confident(f):
            continue
        if f.semantic_type in policy.once_per_form:
            if f.semantic_type in seen:
                continue
            seen.add(f.semantic_type)
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
    seen = {f.semantic_type for f in ir.fields if f.id in typed}
    suggested: set[str] = set()
    for f in ir.fields:
        if f.id in typed or f.no_fill_reason is not None or f.semantic_method != "llm":
            continue
        if f.semantic_confidence < floor or f.semantic_type in (T.OTHER, T.UNKNOWN):
            continue
        if f.semantic_type in policy.once_per_form:
            if f.semantic_type in seen:
                continue
            seen.add(f.semantic_type)
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
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})
