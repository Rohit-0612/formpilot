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

### P3-D3. Understanding pass as built (steps 2–4)

- **LLM layer** (`backend/app/llm/`): `LLMProvider` with a privacy guard in its one public method
  (a remote provider refuses requests carrying values of the sensitive or phone types); an Ollama
  provider (schema-constrained JSON, temperature 0, thinking off, 8192-token context); a fake
  provider; a record / replay cache keyed by provider, model, prompt, request and schema.
  - An Ollama cloud model or a non-local host counts as remote.
  - Ollama's default 4096-token context could not hold the prompt plus a batch, hence 8192.
- **Rule matcher:** the label's content words against `semantic_types.py`'s keywords (written in
  Phase 2, unchanged). A unique strong match means the longest keyword covers at least half of the
  label and no other type matches words outside it. Format and instruction words ("DD/MM/YYYY",
  "block letters") don't count. Current vs permanent address comes from the heading or label.
- **LLM:** the remaining fields of a page, at most 20 per request. SPEC §6.2 says one request
  per page; the split keeps answers short on dense pages (#1 page 1 has more than 100 fields).
- **In the analyze job:** IR version 1 (detection) is stored and the document is `ready`
  first, then the pass runs and IR version 2 is appended. The pass gets a deadline (job timeout
  minus 30 s); LLM batches after it are skipped and their fields stay unknown. A separate
  `understand` job would need a database migration (job types are a CHECK constraint) that the
  plan did not include.
- **Never filled:** signature fields and fields under an office-use heading get status
  `SKIPPED` with their `no_fill_reason`; confidence below 0.7 gives `NEEDS_REVIEW`.
- **Latency:** not measured yet. A smoke run on #21 (52 fields) took about three minutes on the
  development laptop under memory pressure; the eval will record LLM responses once and replay
  them.

### P3-D4. Frozen before the blind labelling (headline-number discipline)

The rule keywords (`backend/app/ir/semantic_types.py`), the matcher
(`backend/app/passes/understand.py`) and the prompt (`backend/app/llm/prompts/understand_v1.md`)
are frozen at commit `c7c7bd9` (2026-10-26, before the human labels). The deadline and the
analyze-job wiring (`8852394`) do not change what the pass decides for a field. The first eval
run after the labelling is the pre-tuning report.

### P3-D5. Blind labelling tool (step 5)

`make label-semantic` writes a local page (`eval/labelling/work/semantic/`, gitignored) with one
crop per field: the page around the labelled box, outlined in red. It reads only the label files
and the PDFs, so neither detector output nor extracted label text nor a model answer can show.

`make label-semantic-merge` writes only `semantic_type` into the label files. It refuses an
export whose fields no longer match (id, page, box, kind), and it never replaces a type without
`--overwrite`.

Scope: 567 text and comb fields on the scored pages. The labelling conventions are in
`eval/labelling/README.md`.

### P3-D6. Semantic reference labels written by Claude Code (human decision, 2026-10-26)

**Decision.** The human asked Claude Code to do the labelling and everything after it, so that no
manual work is needed, and chose "Claude only, no human audit" over two alternatives:
- Claude labels with a 60-field blind human audit (about 10 minutes);
- the human labels a 150-field sample (15–20 minutes).

How the labels are made:
- Claude Code labels the 567 text and comb fields of the scored dev pages in
  `eval/labels_semantic/`, from the same crops a human would see (the field outlined in red on
  its page), following the conventions in `eval/labelling/README.md`.
- `eval/labels/` (the human's boxes) is not touched.

**Trade-off, stated in every report and in the README.** Semantic accuracy measures agreement
between `qwen3:8b` (through the rules and the prompt) and reference labels written by a
different, much larger model. It is not accuracy against human ground truth.

**Safeguards.**
- **Blind:** the understanding pass is not run on the dev forms before the labels are written,
  and no model answer is looked at.
  - Disclosure: an earlier smoke run on #21 (P3-D3) showed the predicted types of 12 of its 52
    fields.
  - The rules and the prompt were frozen before labelling (P3-D4).
- **Frozen:** once committed, the labels are not changed during tuning. A label that looks wrong
  is listed, not edited.
- **Separate:** stored apart from the human labels, each file with `labelled_by` and the SHA-256 of
  the label file whose boxes it labels.

**How they were written (2026-10-26).**
- From renders of each scored page, every labelled text or comb box outlined and numbered: the
  form only, no model answer. The understanding pass was not run on the dev forms before.
- All 567 fields, in one sitting; files in `eval/labels_semantic/` (11 forms).
- Some conventions were made precise while labelling and applied to every form. They are listed
  in `eval/labelling/README.md` as added during labelling:
  - label for the person filling the form, so other people's data is `other`;
  - names asked in Hindi are `other`;
  - date parts take the date's type;
  - every signing space is `signature`;
  - separator rules are `unknown`.

**Class balance.** 295 of 567 fields (52 %) are `other`: these forms ask much about other people
(nominees, the deceased, witnesses) and for office use. 11 are `unknown`. A model answering
`other` everywhere would reach 52 %, so the eval also reports accuracy on the fields whose type
is neither `other` nor `unknown` (261), and per type.

## Pre-tuning eval (2026-10-26; kept unchanged as history)

`make eval` on the dev split at `ee3c22e`: the rules and prompt as frozen in `c7c7bd9`, the
reference labels of P3-D6, and the model `qwen3:8b` through local Ollama. **Reference labels are
Claude-written, not human** (P3-D6); accuracy is agreement with them.
- **Compared:** 524 fields, the reference fields that the detector found (43 of the 567 were not
  detected).
- **Fillable:** reference type neither `other` nor `unknown` (241 fields).

| Mode | Report | All | Fillable | Fillable, from scratch | Fillable, pre-filled | Macro (fillable) | Predicted `unknown` |
|---|---|---|---|---|---|---|---|
| Rules only | `…-rules-pre-tuning-20261026-ee3c22e` | 17.4 % (91/524) | 33.6 % (81/241) | 50.0 % (15/30) | 31.3 % (66/211) | 35.1 % | 390 |
| Hybrid (product) | `…-hybrid-pre-tuning-20261026-ee3c22e` | 57.4 % (301/524) | 57.3 % (138/241) | 56.7 % (17/30) | 57.3 % (121/211) | 53.7 % | 21 |
| LLM only | `…-llm-pre-tuning-20261026-ee3c22e` | 57.6 % (302/524) | 55.2 % (133/241) | 60.0 % (18/30) | 54.5 % (115/211) | 64.3 % | 43 |

**Hybrid by method:** rules typed 134 fields (60.4 % correct), the LLM 390 (56.4 %). One LLM
batch was retried (#1 page 4); none failed.

**Replay check:** both model modes replayed from `eval/llm_cache/understand/` (83 recorded
answers) with the provider pointed at a dead address. The metrics were identical to the
recorded runs.

`eval/baseline.json` holds the hybrid run.

**Latency:** the hybrid recording took 66 minutes and the llm one 81, on the development laptop
under memory pressure. Not a product latency measurement: not measured yet.

## In my own words

