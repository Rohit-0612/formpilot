"""Question planning (SPEC §6.4): the fewest questions that cover the fields needing input.

Deterministic. Only fields with status NEEDS_INPUT are asked, in reading order:
- **Typed fields** (the fill policy trusts their type, `match.typed_field_ids`):
  - address, name, bank and education fields of the same group form one group question, with
    one part per type; an address group may also be answered in one free-text line, parsed by
    the LLM (no sensitive or phone type is ever in a free-text group);
  - fields of the same type share one question (one answer fills them all);
  - their answers may be saved to the profile (a sensitive one only with its opt-in).
- **Untyped fields** are asked one by one with the form's own label; the predicted type only
  picks the input (a date input for a date). Their answers are never saved to the profile.
- Checkbox, radio and choice fields become multiple-choice or yes/no questions.

Question ids come from field ids, so they stay stable while the fields are unanswered.
"""

from enum import StrEnum

from pydantic import BaseModel

from app.ir.models import Field, FieldKind, FieldStatus, FormIR
from app.ir.semantic_types import PHONE_TYPES, SEMANTIC_TYPES, SENSITIVE_TYPES
from app.ir.semantic_types import SemanticType as T
from app.passes.match import FillPolicy, typed_field_ids
from app.vault.fields import BY_KEY


class InputKind(StrEnum):
    TEXT = "text"
    DATE = "date"
    CHOICE = "choice"
    YES_NO = "yes_no"


class Choice(BaseModel):
    value: str  # written into the PDF
    label: str


class QuestionPart(BaseModel):
    field_ids: list[str]
    semantic_type: T | None  # None for an untyped (label) question
    label: str
    input: InputKind
    choices: list[Choice] = []
    sensitive: bool = False


class Question(BaseModel):
    id: str
    prompt: str
    group: str | None  # e.g. "current_address"; None for a single question
    parts: list[QuestionPart]
    free_text: bool = False  # the group may be answered in one line (parsed by the LLM)
    can_save: bool = False  # answers may be saved to the profile

    @property
    def field_ids(self) -> list[str]:
        return [i for part in self.parts for i in part.field_ids]


_GROUPS: tuple[tuple[str, str, frozenset[T]], ...] = (
    ("name", "What is your name?", frozenset({T.FIRST_NAME, T.MIDDLE_NAME, T.LAST_NAME})),
    (
        "current_address",
        "What is your current address?",
        frozenset(t for t in T if t.value.startswith("current_")),
    ),
    (
        "permanent_address",
        "What is your permanent address?",
        frozenset(t for t in T if t.value.startswith("permanent_")),
    ),
    (
        "bank",
        "What are your bank details?",
        frozenset({T.BANK_NAME, T.BANK_ACCOUNT_NUMBER, T.IFSC, T.BANK_BRANCH}),
    ),
    (
        "education",
        "What are your education details?",
        frozenset(
            {
                T.INSTITUTION_NAME,
                T.COURSE,
                T.ENROLLMENT_NUMBER,
                T.YEAR_OF_STUDY,
                T.PERCENTAGE_OR_CGPA,
                T.PASSING_YEAR,
            }
        ),
    ),
)
_FREE_TEXT_GROUPS = frozenset({"current_address", "permanent_address"})
_NEVER_FREE_TEXT = SENSITIVE_TYPES | PHONE_TYPES
_DATE_TYPES = frozenset({T.DATE_OF_BIRTH, T.DATE_OF_FILLING})
_OPTION_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO, FieldKind.CHOICE})
_TYPE_ORDER = {t: i for i, t in enumerate(T)}


def _group_of(t: T) -> tuple[str, str] | None:
    for name, prompt, types in _GROUPS:
        if t in types:
            return name, prompt
    return None


def _type_label(t: T) -> str:
    key = SEMANTIC_TYPES[t].profile_key
    if key is not None:
        return BY_KEY[key].label
    return t.value.replace("_", " ").capitalize()


def _in_sentence(label: str) -> str:
    """ "Email address" -> "email address"; acronyms keep their case ("PAN", "IFSC")."""
    if len(label) > 1 and label[1].isupper():
        return label
    return label[:1].lower() + label[1:]


def _form_label(f: Field) -> str:
    return (f.label_text or f.context_text or "this box").strip()


def _input(f: Field, t: T | None) -> tuple[InputKind, list[Choice]]:
    if f.kind in _OPTION_KINDS and len(f.options) > 1:
        return InputKind.CHOICE, [
            Choice(value=o.value, label=o.label or o.value) for o in f.options
        ]
    if f.kind in _OPTION_KINDS:
        return InputKind.YES_NO, []
    if t in _DATE_TYPES:
        return InputKind.DATE, []
    return InputKind.TEXT, []


def _typed_prompt(t: T, f: Field, kind: InputKind) -> str:
    if t is T.DECLARATION_CHECKBOX or kind is InputKind.YES_NO:
        return f"Do you tick this box: “{_form_label(f)}”?"
    if kind is InputKind.CHOICE:
        return f"Which applies to you for “{_form_label(f)}”?"
    if SEMANTIC_TYPES[t].profile_key is not None:
        return f"What is your {_in_sentence(_type_label(t))}?"
    return f"What should go in “{_form_label(f)}”?"


def plan(ir: FormIR, policy: FillPolicy) -> list[Question]:
    # `other` and `unknown` say nothing about what to ask: those fields get label questions.
    typed = typed_field_ids(ir, policy) - {
        f.id for f in ir.fields if f.semantic_type in (T.OTHER, T.UNKNOWN)
    }
    asked = [
        f for f in ir.fields if f.status is FieldStatus.NEEDS_INPUT and f.no_fill_reason is None
    ]
    groups: dict[str, Question] = {}
    by_type: dict[T, QuestionPart] = {}
    questions: list[Question] = []
    for f in asked:
        if f.id not in typed:
            kind, choices = _input(f, f.semantic_type if f.semantic_type in _DATE_TYPES else None)
            prompt = (
                f"Do you tick this box: “{_form_label(f)}”?"
                if kind is InputKind.YES_NO
                else f"The form asks: “{_form_label(f)}”. What should go here?"
            )
            part = QuestionPart(
                field_ids=[f.id], semantic_type=None, label=_form_label(f), input=kind,
                choices=choices,
            )  # fmt: skip
            questions.append(Question(id=f"q_{f.id}", prompt=prompt, group=None, parts=[part]))
            continue
        t = f.semantic_type
        if t in by_type and f.kind not in _OPTION_KINDS:
            by_type[t].field_ids.append(f.id)
            continue
        kind, choices = _input(f, t)
        part = QuestionPart(
            field_ids=[f.id], semantic_type=t, label=_type_label(t), input=kind, choices=choices,
            sensitive=t in SENSITIVE_TYPES,
        )  # fmt: skip
        if kind is InputKind.TEXT or kind is InputKind.DATE:
            by_type[t] = part
        group = _group_of(t)
        if group is None or kind is InputKind.CHOICE:
            can_save = SEMANTIC_TYPES[t].profile_key is not None and kind is not InputKind.YES_NO
            questions.append(
                Question(
                    id=f"q_{f.id}",
                    prompt=_typed_prompt(t, f, kind),
                    group=None,
                    parts=[part],
                    can_save=can_save,
                )
            )
            continue
        name, prompt = group
        if name not in groups:
            groups[name] = Question(
                id=f"q_{name}_{f.id}", prompt=prompt, group=name, parts=[], can_save=True
            )
            questions.append(groups[name])
        groups[name].parts.append(part)
    for question in groups.values():
        question.parts.sort(key=lambda p: _TYPE_ORDER[p.semantic_type])  # type: ignore[index]
        question.free_text = question.group in _FREE_TEXT_GROUPS and not any(
            p.semantic_type in _NEVER_FREE_TEXT for p in question.parts
        )
    return questions
