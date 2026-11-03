# Phase 5 — Review UI and rendering: decision record

> Status: **in progress** (milestone M3, branch `phase-5-review`, from `main` after Gate 4).
> The milestone plan was approved by the human on 2026-10-27 with the decisions below. Gate 5 is
> the human's.

## What was built

To be completed at the end of the milestone.

## Key decisions and alternatives considered

### Human decisions on the M3 plan (2026-10-27)

| Decision | Alternatives | Why |
|---|---|---|
| **P5-D1** Suggested values: a field with a fillable type and a profile value, typed by the LLM with a confidence of at least `SUGGEST_MIN_CONFIDENCE` = **0.95** and below the fill threshold (0.99), is prefilled with status `suggested`: highlighted, unconfirmed, not asked, never in "confirm all", rendered only after an explicit confirm. The suggestions report also lists 0.70, 0.85 and 0.90 from replay, for the record only | a 0.70 floor (more suggestions, about half with the right type on dev); no suggestions | The human's call: fewer suggestions, but more of them right (exploratory replay before the plan: 23 of 36 with the right type at 0.95, 48 of 95 at 0.70). The fill policy (P4-D2) is unchanged |
| **P5-D2** The 10 rendered dev PDFs of the acceptance check are inspected by Claude Code as images (all 10) and spot-checked by the human (3); the work stops for that at the end of the renderer step | the human checks all 10; waived | The human's call |
| **P5-D3** The Playwright happy path runs inside the Compose smoke job | a fourth CI job | CI stays at three jobs, and the test runs against the real stack |
| **P5-D4** "Re-fill from my profile" for documents uploaded before a profile change: after v1 | in M3 | The human's call; uploading again gives the same result |
| **P5-D5** Devanagari rendering: a time-box of half a session to render it with a free embeddable font (Noto Sans Devanagari, OFL) and correct shaping, verified on rendered output. If it does not work cleanly, the review screen and the question both say that such a field will not be printed | no attempt (Helvetica only, the M2 limitation) | The human's addition. **Outcome (time-box met, 2026-10-27):** it works with no new dependency or font file: PyMuPDF 1.28's HTML layout (`insert_htmlbox`) shapes Devanagari with HarfBuzz in MuPDF's built-in Noto Serif Devanagari (OFL) and embeds it; conjuncts (श्री, क्ष, द्वि) were checked on rendered output in MuPDF and in Apple's PDF renderer (Quick Look). The fit pass measures shaped width on a scratch page. Not printed, with "write it by hand": Devanagari in a comb row (conjuncts cannot be split one letter per box) and other scripts. Text copied out of the PDF reads garbled (the font's glyph-to-Unicode map), the print is right |
| **P5-D6** Readable questions (*how* changed by P5-D9): the same batched understanding call also returns a short English question for each field (`question_en` → `Field.question_text`), translated from Hindi and repaired where the text layer is garbled (prompt `understand_v3.md`). The question shows it as the main text with the form's own label in small text below; without it, a clean English label is quoted, else "Box N on page P"; broken text is never the main question | quoting the label (M2); a second LLM call per field; translating in code | On dev with the full persona, 24 of 526 label questions quoted Hindi (often garbled) and 3 had no label. One call keeps the cost; the request still holds printed form text only |

### Decided during the milestone

| Decision | Alternatives | Why |
|---|---|---|
| **P5-D7** (proposed by Claude Code, **awaiting the human's OK**) "Confirm all" confirms every `filled` field whose checks all passed and whose value is not the LLM's: never a suggestion, a field with a warning, or an address part the LLM split from free text (`llm_inferred`) | confirm every filled field | A value the model produced, or one that failed a check, needs a look of its own (invariant 7) |
| **P5-D8** (human, 2026-10-27, after the Sunrise form) Form-layout reading, as general rules: an instruction line is no section heading; entries outside the visible page are dropped; hinted comb parts are labelled by their hints ("FIRST _ NAME" is one part) and a DD / MM / YYYY part gets `Field.date_part`; tables whose header names two or more entry columns, and rows of labelled lines that repeat the same labels, are `table_row` groups (`FormIR.groups`, `Field.group_id`); tick boxes after one label are a `choices` group. **Fill policy change:** a field in a group is never filled or suggested from the profile (a profile holds one value per type; a table row is one instance of many), and is asked row by row (one card per row, never saved); a tick-box row is one choice question | keep the M2 behaviour (one profile value written into every row; a yes/no question per box); a per-row profile (Class X, Class XII…) | On the human's synthetic registration form, the instruction "Please fill in CAPITAL LETTERS only." was the question text of 6 fields, the full date went into a 2-box DD part, and one passing year was filled into several class rows. Dev: detection precision 95.1 % → 95.3 %, recall 92.4 % unchanged (labels v5). Understanding (Groq, `understand_v2`, complete run of 2026-11-01 against the M2 Groq run of P3-D7): accuracy 70.4 % (369/524) → 74.4 % (390/524), fillable accuracy 62.7 % (151/241) → 70.5 % (170/241), precision of predicted fillable types 67.7 % (151/223) → 71.1 % (170/239). Fill, product policy (LLM confidence ≥ 0.99, once per form, full persona): fill precision 86.5 % (64/74) → 88.6 % (70/79), value precision 82.4 % (61/74) → 88.6 % (70/79), coverage 26.6 % → 29.0 %. Two breakdown rows dropped; the human accepted both as known limitations (2026-11-03, below) |
| **P5-D9** (human, 2026-10-27) Prompt `understand_v3` (types and English questions in one call) is dropped; typing stays on `understand_v2`, and a separate **phrase pass** (prompt `phrase_v1.md`) writes the English questions after match, only for the fields asked about the form's own text | accept v3; tune v3 once; measure the run-to-run variance of v2 first | v3 lowered typing on dev: Groq accuracy 70.4 % (369/524) → 69.5 % (364/524), fill precision 86.5 % (64/74) → 84.4 % (65/77), below the 85 % target; qwen3:8b 64.3 % → 60.9 % (319/524), fillable accuracy 58.1 % → 52.3 % (126/241). One failed Groq batch (#21, page 1) was re-asked in record mode. A separate call keeps typing unchanged and asks the model only about the fields that are asked |
| **P5-D10** (human, 2026-11-03) The product keeps `FILL_MIN_CONFIDENCE` = **0.99** (once per form). After the P5-D8 fixes the P4-D2 selection rule picks LLM confidence ≥ **0.95**, once per form (dev, Groq, full persona: fill precision 87.4 % (97/111), coverage 40.2 %); that pick is recorded as a known difference between the eval and the product | move the fill threshold to 0.95 (more coverage, 0.95 meets the 85 % target) | 0.95 is the suggestion floor (P5-D1): with the fill threshold also at 0.95 the suggested band would be empty. At 0.99: fill precision 88.6 % (70/79), coverage 29.0 % |
| **P5-D11** (human, 2026-11-03; changes P5-D2) The human's spot-check of 3 rendered dev PDFs is waived. It is replaced by two checks, each run before and after the render fixes (P5-D12 to P5-D16): (1) a fresh-eyes review by a separate Claude Code agent that has not seen Claude Code's own findings, given the renders and the printed fields per form; its findings are compared with Claude Code's; (2) programmatic render checks (`make render-check`): every printed character inside its field's box or its comb cell, the day / month / year parts of a date printed all or none, nothing printed in a never-fill field or an office-use area, a tick box ticked only from the user's own choice | the human spot-checks 3 (P5-D2) | The human's call, as with P4-D3. Claude Code still inspects all renders as images |

### Milestone plan (approved)

- **Form IR** (additive, `schema_version` stays 1): `FieldStatus.SUGGESTED`, `Field.uppercase`,
  `Field.question_text`.
- **Database:** none.
- **API:** `PATCH /documents/{id}/fields/{field_id}`, `POST /documents/{id}/confirm-all`,
  `POST /documents/{id}/render` → 202 `{job_id}`, `GET /documents/{id}/output`,
  `DELETE /documents/{id}`; the masked IR carries the new fields.
- **New dependency:** `@playwright/test` (web, dev only).
- **Config:** `SUGGEST_MIN_CONFIDENCE` (0.95).
- **Prompt:** `understand_v3.md` (re-recorded on dev with Groq and qwen; if understanding
  accuracy or fill precision drops against the baseline, the work stops and is reported).
  Replaced by the phrase pass (P5-D9).
- **Added after the Sunrise form (human, 2026-10-27):** P5-D8 with the IR additions
  `Field.date_part`, `Field.group_id`, `FormIR.groups` / `FieldGroup`, and `Choice.value` = the
  id of the box to tick in a tick-box row; the phrase pass (P5-D9); the fill eval checks values
  against the personas, not only types (value precision: repeated rows have no right profile
  value, split dates want their day, month or year). Before the fixes (dev, Groq replay, chosen
  policy): fill precision 86.5 % (64/74), value precision 82.4 % (61/74).
- **Added for the render fixes (human, 2026-11-03):** the IR addition `Field.cells` (one box per
  comb cell, so each character is printed in its own cell; P5-D14); `make render-check`
  (P5-D11).
- **Also in the plan:** question grouping by section or person (questions per form before and
  after, inputs and cards counted separately); a free-text address parsing eval with record /
  replay; a UX metric (actions to complete a dev form with the full persona, before and after);
  format hints such as "(Capital letters)" set `Field.uppercase` and the renderer upper-cases the
  value; the hourly expiry job; fill-correctness and placement evals.

## Known limitations

Accepted by the human on 2026-11-03 as known limitations, not regressions (dev, Groq, complete
run of 2026-11-01). The rest is completed at the end of the milestone.

- **Form 06, "Signature with Date" table cells.** After P5-D8, the cells under that column header
  carry it as their label; the model types them `signature`, the frozen reference says `other`
  (form 06, all fields: 100 % (27/27) → 92.6 % (25/27); fillable unchanged at 4/4). Neither type
  is ever filled, so the printed output is unchanged. The reference labels stay unchanged.
- **Rule matches on generic labels.** `ravi_kumar`, product policy: fill precision 92.2 % (59/64)
  → 91.5 % (65/71): 6 more right fills and 1 more wrong one (net +5). All 6 wrong fills come from rules on
  generic labels ("Name", "Age", "Date", "Name of the Bank") that refer to another person or
  thing (a nominee, a bank). After v1 (PLAN.md); no tuning now.
- **Eval pick vs product threshold** (P5-D10): the fill eval's chosen policy is ≥ 0.95, the
  product fills at ≥ 0.99.

## Open issues

- SPEC §9 lists `PATCH /documents/{id}/fields/{field_id}` as "edit value, bbox, or status"; M3
  builds value (edit, clear) and status (confirm, unconfirm). Moving a box is deferred to after
  v1 by PLAN Phase 5 ("Drag/resize of boxes: after v1"); the SPEC row describes the endpoint's
  full scope.
- Commit `8c1b8c5` (office-use fix) says "make test 1081 passed" in its message; the run before
  that commit had **1089** unit tests passing. The message was not amended because the branch
  was already pushed (no history rewrite).
- Commit `58a5b2e` (the last Groq understanding batches) says the batches are from forms 06, 25
  and 32; a replay check shows they are from **form 25 (three batches) and form 32 (one)**. Form
  06's batches were recorded in `51463a8`. Not amended, for the same reason.

## Notes for the next phase

To be completed at the end of the milestone.

## In my own words
