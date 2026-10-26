# Phase 3 — Field understanding + eval harness: decision record

> Status: **close-out drafted 2026-10-27** (milestone M1, branch `phase-3-understanding`, from
> `main` after the Phase 2 merge). Gate 3 is the human's. The full record is kept under "Key
> decisions and alternatives considered → Detailed record".

## What was built

| Deliverable (PLAN Phase 3) | Where |
|---|---|
| Fields that are never filled (office use, signatures): `Field.no_fill_reason`, the only IR change (P3-D1); AcroForm signature widgets become never-filled text fields | `backend/app/ir/models.py`, `backend/app/frontends/acroform.py`, SPEC §4 |
| LLM layer: interface with a privacy guard (no sensitive or phone value to a remote provider; Ollama cloud models and non-local hosts count as remote), Ollama provider, fake provider, record/replay cache | `backend/app/llm/` |
| Understanding pass: rule matcher on the `semantic_types.py` keywords, then a batched LLM call per page (JSON schema, Pydantic, one retry, `unknown`), never-fill marks, review status | `backend/app/passes/understand.py`, `backend/app/passes/context.py` |
| Versioned prompts | `backend/app/llm/prompts/understand_v1.md` (pre-tuning), `understand_v2.md` (current) |
| The analyze job runs the pass after detection and stores IR version 2, within a deadline | `backend/app/services/analysis.py` |
| Semantic labelling: a blind labelling page, merge for human labels, and Claude-written reference labels (P3-D6) | `eval/labelling/semantic.py`, `eval/labels_semantic/` |
| Understanding eval with rules / llm / hybrid modes and record / replay (`make eval`), reports, baseline | `eval/run_eval.py`, `eval/reports/phase3-*`, `eval/llm_cache/understand/`, `eval/baseline.json` |

**Measured on dev.** Reference labels are **Claude-written, not human** (P3-D6), so accuracy is
agreement with them. Compared: 524 fields (the reference fields the detector found). Fillable:
reference type neither `other` nor `unknown` (241).

| Run | All | Fillable | Fillable, from scratch | Fillable, pre-filled |
|---|---|---|---|---|
| Pre-tuning, rules only | 17.4 % | 33.6 % | 15/30 | 66/211 |
| Pre-tuning, llm only | 57.6 % | 55.2 % | 18/30 | 115/211 |
| Pre-tuning, hybrid | 57.4 % | 57.3 % | 17/30 | 121/211 |
| **Tuned, hybrid (product)** | **64.3 %** | **58.1 %** | 20/30 | 120/211 |

- Tuned hybrid, precision of predicted fillable types: 60.6 % (140/231).
- Replaying the recorded answers reproduces every run exactly without a model.
- Test split: not measured yet (release measurement, Phase 5b, detection only).

**Tests in the close-out run:** see "Open issues" → close-out checks.

## Key decisions and alternatives considered

| Decision | Alternatives | Why this one |
|---|---|---|
| **P3-D1** `no_fill_reason` on `Field`; AcroForm signatures as `text` fields | a new `FieldStatus`; `FieldKind.SIGNATURE` for both frontends (rejected by the human) | Status is the fill workflow, not a reason; the kind describes the entry shape, and the flat detector is scored on signature areas as `text` |
| **P3-D2** no `GroqProvider` yet | build it now | Groq's own pages do not confirm that the free tier needs no card, which was the human's condition |
| **P3-D3** one analyze job: v1 stored first, then understanding with a deadline, then v2 | a separate `understand` job type | That job would need a database migration (job types are a CHECK constraint) the plan did not include; v1 is never lost |
| **P3-D3** at most 20 fields per LLM request | one request per page (SPEC §6.2) | Dense pages (over 100 fields) and a slow local model: shorter answers, no context overflow |
| **P3-D4** rules and prompt frozen before the labels; pre-tuning reports kept | tune while labelling | Honest headline numbers (human rule) |
| **P3-D6** reference labels written by Claude Code, blind, no human audit | a 60-field human audit; a 150-field human sample | The human's choice (no manual work). Disclosed in every report; agreement with a stronger model, not human truth |
| Fillable accuracy reported next to overall accuracy | overall accuracy only | 52 % of the reference fields are `other`, so the overall number flatters |
| Tuning: strict-majority rules, other-person guard, prompt v2 | more keywords; tuning toward labelling conventions (initials as signatures) | Product rules: never fill a profile value into another person's field; fewer wrong fillable predictions (110 → 91) |

### Detailed record

The record as written during the milestone, unchanged except for its heading levels.

#### Plan approved by the human (2026-10-26)

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

#### Decisions

##### P3-D1. Fields that are never filled: `Field.no_fill_reason` (SPEC §4 change)

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

##### P3-D2. Groq is not built yet

Groq's own documentation (console.groq.com, rate-limits page, checked 2026-10-26) does not say
whether the Free tier needs a payment method; third-party pages say it does not, and Groq asks
for one only to upgrade to the Developer tier. The human's condition ("only if its free tier
needs no card or payment") cannot be confirmed from Groq's own pages, so `GroqProvider` is not
built in this pass. It is added only if the human's own sign-up shows no card is asked for.

##### P3-D3. Understanding pass as built (steps 2–4)

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

##### P3-D4. Frozen before the blind labelling (headline-number discipline)

The rule keywords (`backend/app/ir/semantic_types.py`), the matcher
(`backend/app/passes/understand.py`) and the prompt (`backend/app/llm/prompts/understand_v1.md`)
are frozen at commit `c7c7bd9` (2026-10-26, before the human labels). The deadline and the
analyze-job wiring (`8852394`) do not change what the pass decides for a field. The first eval
run after the labelling is the pre-tuning report.

##### P3-D5. Blind labelling tool (step 5)

`make label-semantic` writes a local page (`eval/labelling/work/semantic/`, gitignored) with one
crop per field: the page around the labelled box, outlined in red. It reads only the label files
and the PDFs, so neither detector output nor extracted label text nor a model answer can show.

`make label-semantic-merge` writes only `semantic_type` into the label files. It refuses an
export whose fields no longer match (id, page, box, kind), and it never replaces a type without
`--overwrite`.

Scope: 567 text and comb fields on the scored pages. The labelling conventions are in
`eval/labelling/README.md`.

##### P3-D6. Semantic reference labels written by Claude Code (human decision, 2026-10-26)

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

#### Pre-tuning eval (2026-10-26; kept unchanged as history)

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

#### Tuning (one session, 2026-10-26; dev only)

**Error analysis** on the pre-tuning hybrid run.
- **Signature areas typed `other` (22).**
  - 15 are office boxes on #1 page 4 without label text: the grey "INITIALS" hint is never a label
    (Phase 2 rule 1), and counting initials as signatures is a labelling convention.
  - The rest have their caption *below* the box, which the frontend does not give as the label.

  Neither is fixable in the pass without tuning toward a convention, or without an IR change
  outside this milestone.
- **Other people's fields typed as the user's:** `other` → `full_name` (17), mostly rules typing
  "Name" under nominee / witness / related-person headings, "Maiden Name", "Name in Hindi".
- **Dates:** "Issue / Expiry Date", "Date of Admission" and "dated" typed by rules as the date of
  filling. The model missed the parts of "this __ day of __".
- **Education tables:** `passing_year` (0/8) and `institution_name` (0/3). Their labels are column
  headings far above, often missing.

**Changes, each measured with `make eval MODE=hybrid RECORD=1`** (fillable: reference type
neither `other` nor `unknown`; Δ against the previous row):

| Row | Commit | Change | All | Fillable | Fillable, from scratch | Fillable, pre-filled | Macro (fillable) | Rule-typed (correct) | Predicted fillable (correct) |
|---|---|---|---|---|---|---|---|---|---|
| Pre-tuning | `ee3c22e` | — | 57.4 % (301/524) | 57.3 % (138/241) | 17/30 | 121/211 | 53.7 % | 134 (81) | not computed |
| Change 1 | `fa6c544` | Rules need a strict majority of the label; "No.", "Number" are generic; labels or headings about another person or asking in Hindi are left to the LLM | 60.5 % (+3.1) | 58.1 % (+0.8) | 18/30 (+1) | 122/211 (+1) | 58.4 % (+4.7) | 85 (65): precision 60.4 → 76.5 % | 250 (140): 56.0 % |
| Change 2 | `97a5205` | Prompt v2: classify for the person filling the form; "I / I/We ___" is `full_name`; names in Hindi are `other`; only the signing date and its parts are `date_of_filling`; table cells may carry their column heading | 64.3 % (+3.8) | 58.1 % (±0) | 20/30 (+2) | 120/211 (−2) | 54.5 % (−3.9) | 85 (65) | 231 (140): 60.6 % |

**Kept: both changes.** Prompt v2 leaves the correct fillable fields unchanged (140) but makes 19
fewer wrong fillable predictions (110 → 91). In the product, a wrong prediction means a profile
value written into the wrong box.

Its costs, recorded:
- pre-filled fillable is 2 fields lower than change 1 (1 lower than pre-tuning);
- macro falls 3.9 points: it swings on forms with 2–4 fillable fields, where one field moves a
  form by 25–50 points.

The table example in prompt v2 ("Year", "Name of School / Institute") comes from dev form #25.

**Final (tuned) report:** `…-hybrid-tuned-20261026-97a5205` (a replay of change 2 at its commit).
`eval/baseline.json` moves to it: both of its tracked metrics are higher than pre-tuning (all
57.4 → 64.3 %, fillable 57.3 → 58.1 %), so the CI bar rises. The llm-only mode was not re-run
after tuning; its pre-tuning report stands. The reference labels were not changed during tuning.

**Left for later** (known limitations):
- signature captions below the box;
- office boxes whose only text is a grey hint;
- education tables whose column headings are far from the cell;
- `other` vs `full_name` on claim forms, where the claimant is the nominee.

## Known limitations

- **Accuracy is agreement with Claude-written reference labels** (P3-D6), not with human ground
  truth; no human audited them.
- **Small support.**
  - 241 fillable fields on 11 dev forms; from scratch only 30 (#21, #41).
  - The macro average swings by 25–50 points per field on forms with 2–4 fillable fields.
- **Signature areas with their caption below** are mostly typed `other`: the frontend gives the
  label above or left, never the caption below (an IR or frontend change, after v1).
- **Office boxes whose only text is a grey hint** ("INITIALS") have no label text: hints are
  never labels (Phase 2 rule 1).
- **Education tables:** `passing_year` (0/8) and `institution_name` are rarely found when the
  column heading is far from the cell.
- **Claim forms, where the claimant is the nominee,** are ambiguous to the model: fields labelled
  "nominee" are the user's own there, but another person's on a nomination form.
- **Latency:** not measured yet. On the development laptop under memory pressure, local
  `qwen3:8b` took about 3.6 s per field. The analyze job stops LLM calls at its deadline, and the
  fields left are `unknown` / `NEEDS_REVIEW`.
- **The CI eval gate cannot replay the dev eval yet:** the dev PDFs are not in the repository
  (M4 plan).
- **Ollama only;** Groq is not built (P3-D2).

## Open issues

### Acceptance checks
All four Phase 3 acceptance checks are verified (PLAN.md):
- the rule matcher and LLM-output validation tests;
- dev reports for all three modes;
- replay reproduces the numbers;
- `baseline.json` from the hybrid run.

The gate is the human's.

### For the human
- **Gate 3.**
- **"In my own words" checkpoint** (optional, about 10 minutes):
  1. Why do the rules run before the LLM, and what did the eval show about that?
  2. Why is the model's self-reported confidence not a probability?
  3. Why does the eval report fillable accuracy next to overall accuracy?
- **Groq:** tell Claude Code whether Groq's free sign-up asked for a card; `GroqProvider` is
  added only if it did not.

### Close-out checks (2026-10-27)
Recorded in the close-out commit message (`make lint`, `make test`, `make test-int`; CI on the
branch).

### Status at hand-off (2026-10-27)
- M1 is done; PR #3 (`phase-3-understanding` → `main`) is open and mergeable, waiting for the
  human's Gate 3 and merge.
- The human added a Groq API key to their local `.env` (gitignored, never committed). Whether
  Groq's sign-up asked for a card is not recorded yet; P3-D2's condition still applies.
- **Next steps:**
  1. the human merges PR #3 and ticks Gate 3;
  2. `GroqProvider` (only if the free tier needed no card);
  3. the M2 (Phase 4) plan for approval.

## Notes for the next phase

- **M2 (Phase 4: vault, matching, questions, answers, validation, fit)** starts with one plan
  for approval (milestone gates).
- **Read IR version 2** (the latest) for semantic types:
  - `semantic_method` is `rule`, `llm` or `none`;
  - fields with `no_fill_reason` must never be asked, matched or rendered;
  - `NEEDS_REVIEW` marks low confidence.
- **Answers parsing (SPEC §6.5)** is the first LLM request that carries values. The privacy guard
  is already in `LLMProvider.complete_json`: set `LLMRequest.carries` to the semantic types of
  the values sent.
- **Personas** (`eval/personas/`, three synthetic people) are drafted by Claude Code and checked
  by the human (PLAN Phase 4).
- **Fill correctness and validator evals** can reuse `eval/run_eval.py`'s matching, its
  record/replay cache and its report layout.
- **The understanding cache keys include the prompt:** a new prompt version needs a new
  recording (about an hour on the development laptop).

## In my own words
