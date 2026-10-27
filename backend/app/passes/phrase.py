"""Phrase pass (decisions P5-D6, P5-D9): an English question for every field that is asked about
the form's own text.

Runs after match, so it knows which fields are asked: those needing input that are not asked by
a typed question ("What is your PAN?" needs no model). A row of tick boxes is phrased once, as a
choice between its boxes (the question goes on its first box); a cell of a table row is phrased
with its row ("What was your percentage in Class XII?").

The fields go to the LLM in batches (at most BATCH per request) with printed form text only:
label, context, the row of a table, the options and the input kind; never a value. The answer is
validated with Pydantic (one retry with the error, invariant 4); a question that is not readable
English or is too long is dropped, and the questions pass falls back to the form's label. With
a deadline in the context, batches due after it are skipped. Typing is not touched: the prompt
was split from the understanding prompt because asking for both lowered the typing accuracy
(P5-D9).
"""

import json
from functools import cache
from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel

from app.ir.models import Field, FieldKind, FieldStatus, FormIR, TraceEvent
from app.ir.phrases import readable_english
from app.ir.semantic_types import SemanticType as T
from app.llm.provider import LLMError, LLMProvider, LLMRequest
from app.passes.context import PassContext
from app.passes.match import policy_for, typed_field_ids

STAGE = "phrase"
BATCH = 25
QUESTION_MAX_LENGTH = 200  # Field.question_text
PROMPT_FILE = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "phrase_v1.md"
_OPTION_KINDS = frozenset({FieldKind.CHECKBOX, FieldKind.RADIO, FieldKind.CHOICE})
_DATE_TYPES = frozenset({T.DATE_OF_BIRTH, T.DATE_OF_FILLING})

type Kind = Literal["text", "date", "choice", "tick"]


class _Phrased(BaseModel):
    id: str
    question: str


class _Answer(BaseModel):
    questions: list[_Phrased]


@cache
def _system_prompt() -> str:
    return PROMPT_FILE.read_text()


@cache
def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "question": {"type": "string"}},
                    "required": ["id", "question"],
                },
            }
        },
        "required": ["questions"],
    }


def _kind(f: Field) -> Kind:
    if f.kind in _OPTION_KINDS:
        return "choice" if len(f.options) > 1 else "tick"
    return "date" if f.semantic_type in _DATE_TYPES else "text"


def items(ir: FormIR, ctx: PassContext) -> list[dict[str, object]]:
    """What the model is told about each field to phrase (printed text only, never a value)."""
    typed = typed_field_ids(ir, policy_for(ctx)) - {
        f.id for f in ir.fields if f.semantic_type in (T.OTHER, T.UNKNOWN)
    }
    groups = {g.id: g for g in ir.groups}
    asked = [
        f for f in ir.fields if f.status is FieldStatus.NEEDS_INPUT and f.no_fill_reason is None
    ]
    out: list[dict[str, object]] = []
    seen: set[str] = set()
    for f in asked:
        group = groups.get(f.group_id) if f.group_id is not None else None
        if group is not None and group.kind == "choices":
            if group.id in seen:
                continue
            seen.add(group.id)
            members = [m for m in asked if m.group_id == group.id]
            out.append(
                {
                    "id": f.id, "kind": "choice", "label": group.label,
                    "context": f.context_text, "row": None,
                    "options": [m.label_text or "" for m in members],
                }
            )  # fmt: skip
            continue
        if f.id in typed:
            continue
        out.append(
            {
                "id": f.id, "kind": _kind(f), "label": f.label_text, "context": f.context_text,
                "row": group.label if group is not None else None,
                "options": [o.label or o.value for o in f.options],
            }
        )  # fmt: skip
    return out


def _question(text: str) -> str | None:
    text = " ".join(text.split())
    return text if readable_english(text) and len(text) <= QUESTION_MAX_LENGTH else None


def _parse(raw: str, wanted: set[str]) -> tuple[dict[str, str], str | None]:
    """The usable questions for the wanted ids, and an error to send back (None if complete)."""
    try:
        answer = _Answer.model_validate_json(raw)
    except pydantic.ValidationError as exc:
        return {}, f"the answer did not match the schema ({exc.error_count()} errors)"
    found = {
        item.id: question
        for item in answer.questions
        if item.id in wanted and (question := _question(item.question)) is not None
    }
    missing = sorted(wanted - found.keys())
    if missing:
        return found, f"these ids have no English question: {', '.join(missing)}"
    return found, None


def _phrase_batch(
    batch: list[dict[str, object]], provider: LLMProvider
) -> tuple[dict[str, str], Literal["ok", "retried", "failed"]]:
    wanted = {str(item["id"]) for item in batch}
    user = json.dumps({"fields": batch}, ensure_ascii=False)
    request = LLMRequest(system=_system_prompt(), user=user, schema=_schema())
    try:
        found, error = _parse(provider.complete_json(request), wanted)
        if error is None:
            return found, "ok"
        retry = LLMRequest(
            system=request.system,
            user=f"{request.user}\n\nYour previous answer was invalid: {error}. Answer again "
            "with one short English question for every input field.",
            schema=request.schema,
        )
        more, _ = _parse(provider.complete_json(retry), wanted - found.keys())
        return {**found, **more}, "retried"
    except LLMError:
        return {}, "failed"


def _event(field_id: str | None, change: str, ctx: PassContext) -> TraceEvent:
    return TraceEvent(pass_name=STAGE, field_id=field_id, change=change, at=ctx.clock())


def run(ir: FormIR, ctx: PassContext) -> FormIR:
    todo = items(ir, ctx)
    if not todo:
        return ir
    if ctx.provider is None:
        return ir.model_copy(update={"trace": [*ir.trace, _event(None, "no LLM provider", ctx)]})
    trace: list[TraceEvent] = []
    questions: dict[str, str] = {}
    for start in range(0, len(todo), BATCH):
        if ctx.deadline is not None and ctx.clock() >= ctx.deadline:
            trace.append(_event(None, "LLM time budget used up", ctx))
            break
        found, outcome = _phrase_batch(todo[start : start + BATCH], ctx.provider)
        if outcome != "ok":
            trace.append(_event(None, f"batch {start // BATCH}: LLM {outcome}", ctx))
        questions.update(found)
    fields = []
    for f in ir.fields:
        if f.id in questions:
            f = f.model_copy(update={"question_text": questions[f.id]})
            trace.append(_event(f.id, "question_text (llm)", ctx))
        fields.append(f)
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace})
