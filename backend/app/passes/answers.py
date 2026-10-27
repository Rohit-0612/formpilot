"""Answer parsing (SPEC §6.5): the user's answers to the planned questions, into field values.

- Structured answers (a part's text, a date, a choice, yes / no) are parsed in code: a typed
  part is normalised for its semantic type and formatted for each field (the match pass's
  `resolve`, so dates follow the form's format); a value that does not normalise is kept as
  typed and the validate pass flags it.
- A free-text answer to an address group is split by the LLM (prompt `answers_v1.md`, JSON
  schema, Pydantic, one retry) and then handled like typed parts (value source LLM_INFERRED).
  The request declares the types it carries (address types only; the privacy guard refuses
  sensitive and phone types), and text that contains an identifier or a phone number is never
  sent: the user is asked to answer the parts one by one instead.
- Answers to untyped (label) questions are written as typed, a date reformatted to the form's
  format. They are never saved to the profile.

Problems (an unknown question, a missing value, an unreadable free text) are recorded in the
trace without values; those fields stay NEEDS_INPUT and are asked again.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

import pydantic
from pydantic import BaseModel

from app.ir.models import Field, FieldStatus, FormIR, TraceEvent, ValueSource
from app.ir.semantic_types import SEMANTIC_TYPES
from app.ir.semantic_types import SemanticType as T
from app.llm.provider import LLMError, LLMProvider, LLMRequest, PrivacyError
from app.passes.context import PassContext
from app.passes.match import resolve
from app.passes.questions import InputKind, Question, QuestionPart
from app.services.masking import contains_identifier
from app.validators.dates import date_format_for, format_date, parse_date
from app.validators.normalize import InvalidValueError, normalize

STAGE = "answers"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "answers_v1.md"
YES, NO = "yes", "no"
_FLAT_CHECKBOX_ON = "Yes"  # a flat checkbox has no export value; the renderer draws an X


class Answer(BaseModel):
    question_id: str
    value: str | None = None  # a single-part question
    parts: dict[str, str] = {}  # a group question: semantic type -> text
    free_text: str | None = None  # a free-text group, split by the LLM
    save_to_profile: bool = False
    sensitive_opt_in: list[str] = []  # profile keys whose sensitive value may be saved


@dataclass
class ProfileChanges:
    values: dict[str, str] = field(default_factory=dict)  # profile key -> canonical value
    opt_in: dict[str, bool] = field(default_factory=dict)


_TYPE_VALUES = frozenset(t.value for t in T)


# --- LLM free text ---------------------------------------------------------------------------


@cache
def _system_prompt() -> str:
    return PROMPT_FILE.read_text()


def _schema(types: Sequence[T]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {t.value: {"anyOf": [{"type": "string"}, {"type": "null"}]} for t in types},
        "required": [t.value for t in types],
    }


def _split(text: str, types: Sequence[T], provider: LLMProvider) -> dict[T, str] | None:
    request = LLMRequest(
        system=_system_prompt(),
        user=json.dumps({"text": text, "parts": [t.value for t in types]}, ensure_ascii=False),
        schema=_schema(types),
        carries=frozenset(types),
    )
    for attempt in range(2):
        try:
            raw = provider.complete_json(request)
            parsed = pydantic.TypeAdapter(dict[str, str | None]).validate_json(raw)
        except PrivacyError:
            raise  # a bug, not a model failure: never retried or hidden
        except (LLMError, pydantic.ValidationError):
            if attempt == 0:
                request = LLMRequest(
                    system=request.system,
                    user=request.user + "\n\nYour previous answer was invalid. Answer again with "
                    "a JSON object holding exactly the keys in parts.",
                    schema=request.schema,
                    carries=request.carries,
                )
            continue
        wanted = {t.value: t for t in types}
        return {wanted[k]: v.strip() for k, v in parsed.items() if k in wanted and v and v.strip()}
    return None


# --- applying values ------------------------------------------------------------------------


def _canonical(t: T, raw: str, today: date) -> str | None:
    try:
        return normalize(t, raw, today)
    except InvalidValueError:
        return None


def _typed_value(f: Field, t: T, raw: str, today: date) -> str:
    """The value for one field of a typed part: normalised and formatted, else as typed."""
    canonical = _canonical(t, raw, today)
    key = SEMANTIC_TYPES[t].profile_key
    if canonical is not None and key is not None:
        resolved = resolve(f.model_copy(update={"semantic_type": t}), {key: canonical}, today)
        if resolved is not None:
            return resolved[0]
    if canonical is not None and t is T.DATE_OF_FILLING:
        return format_date(date.fromisoformat(canonical), date_format_for(f))
    return " ".join(raw.split())


def _label_value(f: Field, part: QuestionPart, raw: str) -> str:
    text = " ".join(raw.split())
    if part.input is InputKind.DATE:
        parsed = parse_date(text)
        if parsed is not None:
            return format_date(parsed, date_format_for(f))
    return text


def _yes_no_value(f: Field, raw: str) -> str | None:
    if raw.strip().casefold() != YES:
        return None
    return f.options[0].value if f.options else _FLAT_CHECKBOX_ON


def run(
    ir: FormIR, ctx: PassContext, answers: Sequence[Answer], questions: Sequence[Question]
) -> FormIR:
    today = ctx.today()
    by_id = {q.id: q for q in questions}
    ir_fields = {f.id: f for f in ir.fields}
    values: dict[str, tuple[str | None, ValueSource]] = {}
    trace: list[TraceEvent] = []

    def problem(question_id: str, change: str) -> None:
        event = TraceEvent(
            pass_name=STAGE, field_id=None, change=f"{question_id}: {change}", at=ctx.clock()
        )
        trace.append(event)

    for answer in answers:
        question = by_id.get(answer.question_id)
        if question is None:
            problem(answer.question_id, "no such question (already answered?)")
            continue
        texts: dict[T | None, str] = {}
        source = ValueSource.USER_ANSWER
        if answer.free_text is not None and answer.free_text.strip():
            types = [p.semantic_type for p in question.parts if p.semantic_type is not None]
            if not question.free_text:
                problem(question.id, "this question cannot be answered in one line")
                continue
            if contains_identifier(answer.free_text):
                problem(question.id, "free text holds an identifier or phone; answer the parts")
                continue
            if ctx.provider is None:
                problem(question.id, "no model to read free text; answer the parts")
                continue
            split = _split(answer.free_text, types, ctx.provider)
            if split is None:
                problem(question.id, "free text not understood; answer the parts")
                continue
            texts.update(split)
            source = ValueSource.LLM_INFERRED
        elif len(question.parts) == 1 and answer.value is not None:
            texts[question.parts[0].semantic_type] = answer.value
        else:
            texts.update({T(k): v for k, v in answer.parts.items() if k in _TYPE_VALUES})
        answered = False
        for part in question.parts:
            raw = texts.get(part.semantic_type)
            if raw is None or not raw.strip():
                continue
            answered = True
            for field_id in part.field_ids:
                f = ir_fields[field_id]
                if part.input is InputKind.YES_NO:
                    values[field_id] = (_yes_no_value(f, raw), source)
                elif part.semantic_type is None:
                    values[field_id] = (_label_value(f, part, raw), source)
                else:
                    values[field_id] = (_typed_value(f, part.semantic_type, raw, today), source)
        if not answered:
            problem(question.id, "no value given")

    fields = []
    for f in ir.fields:
        if f.id not in values:
            fields.append(f)
            continue
        value, source = values[f.id]
        fields.append(
            f.model_copy(
                update={
                    "value": value,
                    "value_source": source,
                    "status": FieldStatus.FILLED,
                    "validations": [],
                }
            )
        )
        trace.append(
            TraceEvent(
                pass_name=STAGE,
                field_id=f.id,
                change=f"answered ({source.value})"
                if value is not None
                else "answered: left empty",
                at=ctx.clock(),
            )
        )
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})


def profile_changes(
    answers: Sequence[Answer], questions: Sequence[Question], today: date
) -> ProfileChanges:
    """What to save to the profile: typed parts of savable questions the user chose to save,
    sensitive ones only with their opt-in. Values that do not normalise are not saved."""
    by_id = {q.id: q for q in questions}
    changes = ProfileChanges()
    for answer in answers:
        question = by_id.get(answer.question_id)
        if question is None or not question.can_save or not answer.save_to_profile:
            continue
        texts: Mapping[str, str] = (
            {question.parts[0].semantic_type.value: answer.value}  # type: ignore[union-attr]
            if len(question.parts) == 1 and answer.value is not None
            else answer.parts
        )
        for part in question.parts:
            t = part.semantic_type
            key = SEMANTIC_TYPES[t].profile_key if t is not None else None
            raw = texts.get(t.value) if t is not None else None
            if key is None or raw is None:
                continue
            canonical = _canonical(t, raw, today)  # type: ignore[arg-type]
            if canonical is None:
                continue
            if part.sensitive:
                if key not in answer.sensitive_opt_in:
                    continue
                changes.opt_in[key] = True
            changes.values[key] = canonical
    return changes
