"""Question planning (SPEC §6.4): the fewest questions that cover the fields needing input.

Deterministic. Only fields with status NEEDS_INPUT are asked, in reading order:
- **Typed fields** (the fill policy trusts their type, `match.typed_field_ids`):
  - address, name, bank and education fields of the same group form one group question, with
    one part per type; an address group may also be answered in one free-text line, parsed by
    the LLM (no sensitive or phone type is ever in a free-text group);
  - fields of the same type share one question (one answer fills them all);
  - their answers may be saved to the profile (a sensitive one only with its opt-in).
- **Untyped fields** are asked about the form's own text; the predicted type only picks the
  input (a date input for a date). Their answers are never saved to the profile. Untyped fields
  under the same section heading of a page are asked together in one card (`group` "section",
  at most MAX_SECTION_PARTS parts): sections are also how a form groups one person's details.
- Checkbox, radio and choice fields become multiple-choice or yes/no questions.

Readable questions (decision P5-D6): the main text of a question about the form's own text is
the English question from the understanding call (`Field.question_text`); without it, a
readable English label is quoted; otherwise the field is named by its place ("box 3 on page
1"). Hindi or garbled text is never the main text; the form's own text goes in `form_text`
(a card) or `form_label` (a part), shown small below.

Question ids come from field ids, so they stay stable while the fields are unanswered.
"""

from enum import StrEnum

from pydantic import BaseModel

from app.ir.models import Field, FieldKind, FieldStatus, FormIR
from app.ir.phrases import readable_english
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
    label: str  # English: the type's name, or the field's question
    form_label: str | None = None  # the form's own text for the field, if not in `label`
    input: InputKind
    choices: list[Choice] = []
    sensitive: bool = False

    @property
    def key(self) -> str:
        """This part's key in `Answer.parts`: its semantic type, or its field id if untyped."""
        return self.semantic_type.value if self.semantic_type is not None else self.field_ids[0]


class Question(BaseModel):
    id: str
    prompt: str  # English, never Hindi or garbled text (P5-D6)
    form_text: str | None = None  # the form's own text behind the prompt, if not in it
    group: str | None  # e.g. "current_address", "section"; None for a single question
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
MAX_SECTION_PARTS = 8
HEADING_MAX_LENGTH = 80  # a longer "heading" is an instruction, not a section title
SECTION = "section"


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


def _printed(f: Field) -> str | None:
    """The form's own text for the field: its label, else its section heading."""
    text = (f.label_text or f.context_text or "").strip()
    return text or None


def _place(f: Field) -> str:
    """ "box 3 on page 1": the field's number in reading order on its page (ids "p0_f002")."""
    _, _, index = f.id.rpartition("_f")
    number = int(index) + 1 if index.isdigit() else f.id
    return f"box {number} on page {f.bbox.page + 1}"


def _readable(f: Field) -> str | None:
    text = _printed(f)
    return text if readable_english(text) else None


def _english(f: Field) -> str:
    """A part label for the field: the model's question, a readable label, or its place."""
    return f.question_text or _readable(f) or _place(f).capitalize()


def _about(f: Field, kind: InputKind) -> str:
    """The main text of a question about the form's own text (P5-D6)."""
    if f.question_text:
        return f.question_text
    label = _readable(f)
    if kind is InputKind.YES_NO:
        return f"Do you tick this box: “{label}”?" if label else f"Do you tick {_place(f)}?"
    if kind is InputKind.CHOICE:
        return f"Which applies to you for “{label}”?" if label else f"What applies in {_place(f)}?"
    return (
        f"The form asks: “{label}”. What should go here?" if label else f"What goes in {_place(f)}?"
    )


def _not_in(text: str | None, shown: str) -> str | None:
    return text if text and text not in shown else None


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
        return _about(f, InputKind.YES_NO)
    if kind is InputKind.CHOICE:
        return _about(f, InputKind.CHOICE)
    if SEMANTIC_TYPES[t].profile_key is not None:
        return f"What is your {_in_sentence(_type_label(t))}?"
    return _about(f, kind)


def _sections(questions: list[Question], fields: dict[str, Field]) -> list[Question]:
    """Untyped single-field questions under the same heading of a page become one card each
    MAX_SECTION_PARTS parts, in the place of the first one (P5-D6, "section")."""
    members: dict[tuple[int, str], list[Question]] = {}
    for q in questions:
        f = fields[q.field_ids[0]]
        if q.group is None and q.parts[0].semantic_type is None and f.context_text:
            members.setdefault((f.bbox.page, f.context_text.strip()), []).append(q)
    cards: dict[str, Question] = {}  # first member's id -> card
    merged: set[str] = set()
    for (page, heading), group in members.items():
        for start in range(0, len(group), MAX_SECTION_PARTS):
            chunk = group[start : start + MAX_SECTION_PARTS]
            if len(chunk) < 2:
                continue
            title = (
                heading
                if readable_english(heading) and len(heading) <= HEADING_MAX_LENGTH
                else None
            )
            prompt = title or f"{len(chunk)} boxes in one section of page {page + 1}"
            cards[chunk[0].id] = Question(
                id=f"q_sec_{chunk[0].field_ids[0]}",
                prompt=prompt,
                form_text=_not_in(heading, prompt),
                group=SECTION,
                parts=[q.parts[0] for q in chunk],
            )
            merged.update(q.id for q in chunk)
    out = []
    for q in questions:
        if q.id in cards:
            out.append(cards[q.id])
        elif q.id not in merged:
            out.append(q)
    return out


def plan(ir: FormIR, policy: FillPolicy, *, sections: bool = True) -> list[Question]:
    """The questions for the fields needing input; `sections=False` asks untyped fields one by
    one (the M2 plan, kept for the questions-per-form eval)."""
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
            prompt, label = _about(f, kind), _english(f)
            part = QuestionPart(
                field_ids=[f.id], semantic_type=None, label=label,
                form_label=_not_in(_printed(f), label), input=kind, choices=choices,
            )  # fmt: skip
            questions.append(
                Question(
                    id=f"q_{f.id}",
                    prompt=prompt,
                    form_text=_not_in(_printed(f), prompt),
                    group=None,
                    parts=[part],
                )
            )
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
            # "What is your PAN?" needs no form text; a question about the form's text does
            templated = kind in (InputKind.TEXT, InputKind.DATE) and (
                SEMANTIC_TYPES[t].profile_key is not None
            )
            can_save = SEMANTIC_TYPES[t].profile_key is not None and kind is not InputKind.YES_NO
            questions.append(
                Question(
                    id=f"q_{f.id}",
                    prompt=(prompt := _typed_prompt(t, f, kind)),
                    form_text=None if templated else _not_in(_printed(f), prompt),
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
    return _sections(questions, {f.id: f for f in ir.fields}) if sections else questions
