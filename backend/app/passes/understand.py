"""Understanding pass (SPEC §6.2): rules first, the LLM second, then never-fill marks.

1. Rule matcher: the field's label against the keywords of `semantic_types.py`. A unique strong
   match sets the type (method "rule", confidence 0.95). Current vs permanent address comes from
   the section heading or the label.
2. LLM: the fields the rules could not place, batched per page (at most LLM_BATCH per request),
   output constrained to the SemanticType enum and validated with Pydantic; one retry with the
   validation error, then `unknown` (invariant 4). The request holds printed form text only.
3. Never filled (decision P3-D1): signature fields and fields under an office-use heading get a
   `no_fill_reason` and status SKIPPED; fields below the review threshold get NEEDS_REVIEW.

Fields whose semantic method is already set (an AcroForm signature widget) are left alone. With
a deadline in the context, batches due after it are skipped (their fields stay unknown).
Trace events name types and methods, never values.
"""

import json
import re
import unicodedata
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Literal

import pydantic
from pydantic import BaseModel

from app.ir.models import Field, FieldKind, FieldStatus, FormIR, TraceEvent
from app.ir.semantic_types import SEMANTIC_TYPES, SemanticType
from app.llm.provider import LLMError, LLMProvider, LLMRequest
from app.passes.context import PassContext

STAGE = "understand"
RULE_CONFIDENCE = 0.95  # SPEC §6.2
LLM_BATCH = 20  # fields per request: short answers, and dense pages (120 fields) are split
PROMPT_FILE = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "understand_v1.md"

# Words that carry no meaning for matching ("Name of the applicant" ~ "applicant name").
_STOPWORDS = frozenset(
    {"of", "the", "a", "an", "in", "for", "to", "your", "his", "her", "its", "and", "or"}
    | {"with", "is", "as", "on", "at", "by", "please", "if", "any"}
    # format and writing instructions: "(DD/MM/YYYY)", "(in block / capital letters)"
    | {"dd", "mm", "yyyy", "yy", "block", "capital", "letters"}
)
# A leading "1.", "2)", "(a)", "b.", "(iv)": numbering, not part of the label.
_ENUMERATOR = re.compile(r"^\s*\(?(\d{1,3}|[a-z]|[ivx]{1,4})[.)]\s*")
# Office-use headings and labels: the fields under them are never filled (P3-D1).
OFFICE_USE_PHRASES = (
    "for office use",
    "office use only",
    "for official use",
    "for bank use",
    "bank use only",
    "karyalaya upyog",
    "कार्यालय उपयोग",
)
_PERMANENT_HINTS = ("permanent", "sthayi", "sthai", "स्थायी")
_CURRENT_HINTS = (
    "present",
    "current",
    "correspondence",
    "communication",
    "mailing",
    "vartaman",
    "वर्तमान",
)


# --- normalisation ---------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Lower case; letters (any script, with their vowel signs), digits and apostrophes kept."""
    text = unicodedata.normalize("NFC", text.lower()).replace("\u2019", "'").replace("`", "'")
    chars = [ch if ch == "'" or unicodedata.category(ch)[0] in "LNM" else " " for ch in text]
    return " ".join("".join(chars).split())


def tokens(text: str | None) -> tuple[str, ...]:
    """Content words of a label: possessives and leading enumerators ("1.", "(a)") removed."""
    text = (text or "").lower()
    while (match := _ENUMERATOR.match(text)) and match.end() < len(text):
        text = text[match.end() :]
    words = [w.removesuffix("'s").strip("'") for w in _clean(text).split()]
    return tuple(w for w in words if w and w not in _STOPWORDS)


def _contains(haystack: tuple[str, ...], needle: tuple[str, ...]) -> int | None:
    """Start index of `needle` as a contiguous run in `haystack`, or None."""
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i : i + len(needle)] == needle:
            return i
    return None


@cache
def _keywords() -> tuple[tuple[tuple[str, ...], SemanticType], ...]:
    pairs = {
        (tokens(keyword), semantic_type)
        for semantic_type, info in SEMANTIC_TYPES.items()
        for keyword in info.keywords
    }
    return tuple(sorted((k, t) for k, t in pairs if k))


# --- rules -------------------------------------------------------------------------------------


def _has_any(text: str | None, phrases: tuple[str, ...]) -> bool:
    cleaned = _clean(text or "")
    return any(_clean(phrase) in cleaned for phrase in phrases)


def _address_variant(candidates: set[SemanticType], field: Field) -> SemanticType | None:
    """Two address types that share a keyword ("city"): the heading or label decides."""
    parts = {t.value.split("_", 1)[1] for t in candidates}
    prefixes = {t.value.split("_", 1)[0] for t in candidates}
    if len(parts) != 1 or prefixes != {"current", "permanent"}:
        return None
    for text in (field.label_text, field.context_text):
        if _has_any(text, _PERMANENT_HINTS):
            return SemanticType(f"permanent_{parts.pop()}")
        if _has_any(text, _CURRENT_HINTS):
            return SemanticType(f"current_{parts.pop()}")
    return None


def rule_match(field: Field) -> SemanticType | None:
    """The unique strong keyword match of the field's label, or None (then the LLM decides).

    Strong: the longest matching keyword covers at least half of the label's content words, and
    no other type matches words outside it ("Father's/Husband's name" is ambiguous).
    """
    label = tokens(field.label_text)
    if not label:
        return None
    matches: list[tuple[set[int], SemanticType]] = []
    for keyword, semantic_type in _keywords():
        start = _contains(label, keyword)
        if start is not None:
            matches.append((set(range(start, start + len(keyword))), semantic_type))
    if not matches:
        return None
    longest = max(len(span) for span, _ in matches)
    best_spans = [span for span, _ in matches if len(span) == longest]
    if 2 * longest < len(label) or any(span != best_spans[0] for span in best_spans):
        return None
    best = best_spans[0]
    winners = {t for span, t in matches if span == best}
    if any(not span <= best for span, t in matches if t not in winners):
        return None  # another type matches words the best keyword does not cover
    if len(winners) == 1:
        return winners.pop()
    return _address_variant(winners, field)


# --- LLM --------------------------------------------------------------------------------------


class _Classified(BaseModel):
    id: str
    semantic_type: SemanticType
    confidence: float = pydantic.Field(ge=0.0, le=1.0)


class _Answer(BaseModel):
    fields: list[_Classified]


@cache
def _system_prompt() -> str:
    types = "\n".join(
        f"- {t.value}: {info.description}"
        for t, info in SEMANTIC_TYPES.items()
        if t is not SemanticType.UNKNOWN
    )
    types += f"\n- {SemanticType.UNKNOWN.value}: {SEMANTIC_TYPES[SemanticType.UNKNOWN].description}"
    return PROMPT_FILE.read_text().replace("{types}", types)


@cache
def _schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "semantic_type": {
                            "type": "string",
                            "enum": [t.value for t in SemanticType],
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["id", "semantic_type", "confidence"],
                },
            }
        },
        "required": ["fields"],
    }


def _kind(field: Field) -> str:
    return field.kind.value if field.kind is not FieldKind.UNKNOWN else "text"


def _llm_input(fields: list[Field]) -> str:
    return json.dumps(
        {
            "fields": [
                {
                    "id": f.id,
                    "kind": _kind(f),
                    "label": f.label_text,
                    "context": f.context_text,
                    "options": [o.label or o.value for o in f.options],
                    "max_chars": f.max_chars,
                }
                for f in fields
            ]
        },
        ensure_ascii=False,
    )


def _parse(raw: str, wanted: set[str]) -> tuple[dict[str, _Classified], str | None]:
    """The answers for the wanted ids, and a validation error to send back (None if complete)."""
    try:
        answer = _Answer.model_validate_json(raw)
    except pydantic.ValidationError as exc:
        return {}, f"the answer did not match the schema ({exc.error_count()} errors)"
    found = {item.id: item for item in answer.fields if item.id in wanted}
    missing = sorted(wanted - found.keys())
    return found, (f"these ids are missing: {', '.join(missing)}" if missing else None)


def _classify_batch(
    fields: list[Field], provider: LLMProvider
) -> tuple[dict[str, _Classified], Literal["ok", "retried", "failed"]]:
    wanted = {f.id for f in fields}
    request = LLMRequest(system=_system_prompt(), user=_llm_input(fields), schema=_schema())
    try:
        found, error = _parse(provider.complete_json(request), wanted)
        if error is None:
            return found, "ok"
        retry = LLMRequest(
            system=request.system,
            user=f"{request.user}\n\nYour previous answer was invalid: {error}. Answer again "
            "with one entry for every input field.",
            schema=request.schema,
        )
        more, _ = _parse(provider.complete_json(retry), wanted - found.keys())
        return {**found, **more}, "retried"
    except LLMError:
        return {}, "failed"


# --- the pass ------------------------------------------------------------------------------------


def _event(field_id: str | None, change: str, ctx: PassContext) -> TraceEvent:
    return TraceEvent(pass_name=STAGE, field_id=field_id, change=change, at=ctx.clock())


def run(ir: FormIR, ctx: PassContext) -> FormIR:
    fields = {f.id: f for f in ir.fields}
    trace: list[TraceEvent] = []
    todo = [f for f in ir.fields if f.semantic_method == "none"]

    unresolved: list[Field] = []
    for field in todo:
        semantic_type = rule_match(field) if ctx.understand_mode != "llm" else None
        if semantic_type is None:
            unresolved.append(field)
            continue
        fields[field.id] = field.model_copy(
            update={
                "semantic_type": semantic_type,
                "semantic_confidence": RULE_CONFIDENCE,
                "semantic_method": "rule",
            }
        )
        trace.append(_event(field.id, f"semantic_type {semantic_type.value} (rule)", ctx))

    if unresolved and ctx.provider is not None and ctx.understand_mode != "rules":
        by_page: dict[int, list[Field]] = defaultdict(list)
        for field in unresolved:
            by_page[field.bbox.page].append(field)
        for page, page_fields in sorted(by_page.items()):
            for start in range(0, len(page_fields), LLM_BATCH):
                batch = page_fields[start : start + LLM_BATCH]
                if ctx.deadline is not None and ctx.clock() >= ctx.deadline:
                    trace.append(_event(None, f"page {page}: LLM time budget used up", ctx))
                    continue
                found, outcome = _classify_batch(batch, ctx.provider)
                if outcome != "ok":
                    trace.append(_event(None, f"page {page}: LLM batch {outcome}", ctx))
                for field in batch:
                    item = found.get(field.id)
                    if item is None:
                        continue  # stays unknown, confidence 0
                    fields[field.id] = field.model_copy(
                        update={
                            "semantic_type": item.semantic_type,
                            "semantic_confidence": item.confidence,
                            "semantic_method": "llm",
                        }
                    )
                    trace.append(
                        _event(
                            field.id,
                            f"semantic_type {item.semantic_type.value} (llm, "
                            f"confidence {item.confidence:.2f})",
                            ctx,
                        )
                    )
    elif unresolved and ctx.understand_mode != "rules":
        trace.append(_event(None, "no LLM provider: rules only", ctx))

    for field_id, field in fields.items():
        fields[field_id] = _mark(field, ctx, trace)

    return ir.model_copy(
        update={"fields": [fields[f.id] for f in ir.fields], "trace": ir.trace + trace}
    )


def _mark(field: Field, ctx: PassContext, trace: list[TraceEvent]) -> Field:
    """Never-fill reasons (P3-D1) and the review status."""
    reason = field.no_fill_reason
    if reason is None and field.semantic_type is SemanticType.SIGNATURE:
        reason = "signature"
    if reason is None and (
        _has_any(field.context_text, OFFICE_USE_PHRASES)
        or _has_any(field.label_text, OFFICE_USE_PHRASES)
    ):
        reason = "office_use"
    if reason is not None:
        if field.no_fill_reason is None:
            trace.append(_event(field.id, f"no_fill_reason {reason}", ctx))
        return field.model_copy(update={"no_fill_reason": reason, "status": FieldStatus.SKIPPED})
    if field.status is FieldStatus.DETECTED and field.semantic_confidence < ctx.review_threshold:
        return field.model_copy(update={"status": FieldStatus.NEEDS_REVIEW})
    return field
