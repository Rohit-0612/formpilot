# Phase 3 — Field understanding + eval harness: decision record

> Status: **in progress** (milestone M1, started 2026-10-26 on branch `phase-3-understanding`,
> from `main` after the Phase 2 merge). The close-out sections are filled in at the end of the
> milestone.

## Plan approved by the human (2026-10-26)

The M1 plan was approved once, with three changes by the human (milestone gates, CLAUDE.md §1):

1. **Signatures:** no new Field kind (below, P3-D1).
2. **Headline-number discipline:**
   - The rule keywords and the `understand_v1` prompt are written from SPEC and
     `semantic_types.py` **before** the human labels semantic types, and are not revised while
     they label.
   - The first eval run after labelling (rules, llm, hybrid) is committed as the
     **pre-tuning report** and stays unchanged as history.
   - After that, at most one session of tuning; every change goes in a table (change → delta).
   - The README reports both pre-tuning and tuned numbers, marked as dev.
3. **Branch:** M1 starts from `main` after the Phase 2 PR is merged.

**Planned stops:** after step 5 (the blind labelling tool), for the human's labelling, and at
the end of the milestone.

**Other parts of the approved plan:**
- `httpx` moves from the dev group to the runtime dependencies (HTTP calls to the LLM provider).
- Ollama is the default provider.
- Semantic types are labelled for text and comb fields only (567 on the scored dev pages);
  checkboxes are excluded.

## Decisions

### P3-D1. Fields that are never filled: `Field.no_fill_reason` (SPEC §4 change)

**Problem.** Office-use fields ("For office use", "For bank use only") and signature areas are
boxed like any other field (Phase 2 labelling rules), but FormPilot must never fill them: not
asked, not matched, not rendered. The flat frontend boxes signature areas as `text`, while the
AcroForm frontend skipped signature widgets (Phase 2, Step 9).

**Decision** (human, 2026-10-26):
- **The only IR change:** an optional `Field.no_fill_reason: Literal["office_use", "signature"]
  | None = None`.
  - `schema_version` stays 1: an IR stored before Phase 3 has no such key and loads with
    `None` (tested).
  - Later passes (match, questions, render) skip any field whose `no_fill_reason` is set.
- **No new Field kind.**
  - AcroForm signature widgets become fields of the kind flat signature boxes use (`text`),
    with `semantic_type = signature` and `no_fill_reason = "signature"`.
  - The widget type alone says it is a signature, so the frontend sets this directly
    (`semantic_method = "rule"`, confidence 1.0) and the understanding pass leaves it alone.
  - (`FieldKind.SIGNATURE` exists in the enum from SPEC v1.0 but no frontend emits it.)
- **Flat signature areas and office-use fields** are marked by the understanding pass (rules).

**Alternatives considered.**
- A new `FieldStatus` such as `NOT_FILLABLE`: status describes the fill workflow (detected,
  needs input, confirmed), and a never-filled field would still need a reason for the review UI.
- `FieldKind.SIGNATURE` for both frontends: rejected by the human. The kind describes the entry
  shape, and the flat detector is scored on signature areas as `text`.

### P3-D2. Groq is not built yet

Groq's own documentation (console.groq.com, rate-limits page, checked 2026-10-26) does not say
whether the Free tier needs a payment method; third-party pages say it does not, and Groq asks
for one only to upgrade to the Developer tier. The human's condition ("only if its free tier
needs no card or payment") cannot be confirmed from Groq's own pages, so `GroqProvider` is not
built in this pass. It is added only if the human's own sign-up shows no card is asked for.

## In my own words

