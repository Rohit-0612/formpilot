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
| **P5-D7** (proposed by Claude Code; **approved by the human on 2026-11-05**) "Confirm all" confirms only `filled` fields (typed by a rule or by the LLM at confidence ≥ 0.99) whose checks all passed and whose value is not the LLM's: never a suggestion or a split name part (`suggested`), a field with a warning, or an address part the LLM split from free text (`llm_inferred`) | confirm every filled field | A value the model produced, or one that failed a check, needs a look of its own (invariant 7) |
| **P5-D8** (human, 2026-10-27, after the Sunrise form) Form-layout reading, as general rules: an instruction line is no section heading; entries outside the visible page are dropped; hinted comb parts are labelled by their hints ("FIRST _ NAME" is one part) and a DD / MM / YYYY part gets `Field.date_part`; tables whose header names two or more entry columns, and rows of labelled lines that repeat the same labels, are `table_row` groups (`FormIR.groups`, `Field.group_id`); tick boxes after one label are a `choices` group. **Fill policy change:** a field in a group is never filled or suggested from the profile (a profile holds one value per type; a table row is one instance of many), and is asked row by row (one card per row, never saved); a tick-box row is one choice question | keep the M2 behaviour (one profile value written into every row; a yes/no question per box); a per-row profile (Class X, Class XII…) | On the human's synthetic registration form, the instruction "Please fill in CAPITAL LETTERS only." was the question text of 6 fields, the full date went into a 2-box DD part, and one passing year was filled into several class rows. Dev: detection precision 95.1 % → 95.3 %, recall 92.4 % unchanged (labels v5). Understanding (Groq, `understand_v2`, complete run of 2026-11-01 against the M2 Groq run of P3-D7): accuracy 70.4 % (369/524) → 74.4 % (390/524), fillable accuracy 62.7 % (151/241) → 70.5 % (170/241), precision of predicted fillable types 67.7 % (151/223) → 71.1 % (170/239). Fill, product policy (LLM confidence ≥ 0.99, once per form, full persona): fill precision 86.5 % (64/74) → 88.6 % (70/79), value precision 82.4 % (61/74) → 88.6 % (70/79), coverage 26.6 % → 29.0 %. Two breakdown rows dropped; the human accepted both as known limitations (2026-11-03, below) |
| **P5-D9** (human, 2026-10-27) Prompt `understand_v3` (types and English questions in one call) is dropped; typing stays on `understand_v2`, and a separate **phrase pass** (prompt `phrase_v1.md`) writes the English questions after match, only for the fields asked about the form's own text | accept v3; tune v3 once; measure the run-to-run variance of v2 first | v3 lowered typing on dev: Groq accuracy 70.4 % (369/524) → 69.5 % (364/524), fill precision 86.5 % (64/74) → 84.4 % (65/77), below the 85 % target; qwen3:8b 64.3 % → 60.9 % (319/524), fillable accuracy 58.1 % → 52.3 % (126/241). One failed Groq batch (#21, page 1) was re-asked in record mode. A separate call keeps typing unchanged and asks the model only about the fields that are asked |
| **P5-D10** (human, 2026-11-03) The product keeps `FILL_MIN_CONFIDENCE` = **0.99** (once per form). After the P5-D8 fixes the P4-D2 selection rule picks LLM confidence ≥ **0.95**, once per form (dev, Groq, full persona: fill precision 87.4 % (97/111), coverage 40.2 %); that pick is recorded as a known difference between the eval and the product | move the fill threshold to 0.95 (more coverage, 0.95 meets the 85 % target) | 0.95 is the suggestion floor (P5-D1): with the fill threshold also at 0.95 the suggested band would be empty. At 0.99: fill precision 88.6 % (70/79), coverage 29.0 % |
| **P5-D11** (human, 2026-11-03; changes P5-D2) The human's spot-check of 3 rendered dev PDFs is waived. It is replaced by two checks, each run before and after the render fixes (P5-D12 to P5-D16): (1) a fresh-eyes review by a separate Claude Code agent that has not seen Claude Code's own findings, given the renders and the printed fields per form; its findings are compared with Claude Code's; (2) programmatic render checks (`make render-check`): every printed character inside its field's box or its comb cell, the day / month / year parts of a date printed all or none, nothing printed in a never-fill field or an office-use area, a tick box ticked only from the user's own choice | the human spot-checks 3 (P5-D2) | The human's call, as with P4-D3. Claude Code still inspects all renders as images |
| **P5-D12** (human, 2026-11-03) A tick box or radio never keeps a type that holds a value (a passport number, a name: such a type becomes `other`), and a tick is never set from the profile: it comes only from the user's own answer to a choice question | tick a box whose type the profile has a value for (M3 before) | Dev form #03: "A- PASSPORT" was ticked because the profile has a passport number; the user picks the document. An AcroForm radio group is now asked too; a dropdown is still filled |
| **P5-D13** (human, 2026-11-03) The day, month and year parts of one date (`app.ir.parts.date_groups`) are filled all or none; if one part is only a suggestion, so are the others | fill each part on its own | Dev form #03, section F: only the DD part was typed as a date and printed |
| **P5-D14** (human, 2026-11-03; IR addition `Field.cells` approved the same day) A comb row keeps its cells as drawn; each character is centred in its own cell and measured against it | equal cells over the comb's box (M3 before); a known limitation with a review note | Dev form #25's Aadhaar cells differ in width: two digits sat on the dividers. Done inside the half-session time-box |
| **P5-D15** (human, 2026-11-03) Below a centred line saying the part is to be filled by an official, an office, the bank, BPM/SPM, a postmaster or an authority (and not by the applicant too), every field on the page is `office_use`; so is a field whose own label or heading says so | mark only "for office use" text (P3-D1) | Dev form #41 is an acknowledgement slip the post office fills in. Dev: 17 fields newly office-use, all on #41 |
| **P5-D16** (human, 2026-11-03) A whole name (guardian's, father's, mother's, spouse's, the applicant's) in FIRST / MIDDLE / LAST boxes is split into the parts as suggestions, confirmed one by one, never the whole name in one part: two words are first and last, three fill a row with three parts, anything else is asked | the whole name in the first part (M3 before) | Dev form #01's guardian row. Since P5-D19 that row is conditional and asked, so no dev field is split now |
| **P5-D17** (human, 2026-11-05) The fill eval counts only values with status `filled` as fills; a suggestion is not a fill (P5-D1). New metric: suggestion precision, with the product's floor (0.95), each part of a split name against the persona's matching part of that person's name, any other suggestion against the value its reference type gets | count every profile value whatever its status (before) | At `14e5bc3` the old definition counted the two split guardian parts as fills (asha 77 filled, 69 right type, 68 right value; new definition 75 / 68 / 68). Old and new give the same numbers at `c955d10` and now (table below) |
| **P5-D18** (human, 2026-11-05) Fields below a tear-off slip's title ("ACKNOWLEDGEMENT …", "RECEIPT", a short line) to the page's end, and fields below a line of its own saying "(For office use only)" up to the next section heading (bold or large, near the note) are `office_use`. Office-use phrases match through ligatures a text layer extracts as other letters ("oĦce") | only fields inside a drawn office-use box (P3-D1) | Fresh-eyes review: dates and account numbers printed in bank slips and in #01's CIF block. Dev: 63 fields newly office-use, all in office areas (#01 page 1 CIF block, page 4 "FOR OFFICE USE/ATTESTATION", page 5 "ACKNOWLEDGEMENT DA-1"; #02 and #03 office blocks and acknowledgements) |
| **P5-D19** (human, 2026-11-05; IR addition `Field.condition` approved the same day) A short line stating a condition ("in case of", "if applicable", "where applicable", "only if", "if yes", at most 8 words) sets `Field.condition` on the fields of its row from its start on, and a note in parentheses under a row's label ("(In Case Of Minor*)") also on the row above. Such a field is never filled or suggested from the profile: it is asked | prefill and let the user clear it | Dev form #01: the guardian's name "(In Case Of Minor*)" was prefilled for an adult. Dev: 12 fields get a condition, all conditional on the form |
| **P5-D20** (human, 2026-11-05) Numbers an institution gives for this application are never filled or suggested from the profile: the `enrollment_number` type and any label naming an enrolment, roll, registration, application, membership or admission number | fill the profile's number | Dev form #25: a 2014 enrolment number from another institute printed on a 2026-27 admission |
| **P5-D21** (human, 2026-11-05) A nationality-typed field whose label asks for a country gets the country of the stored nationality from a fixed table ("Indian" → "India"); a nationality not in the table is asked | print the nationality | Dev form #25: "Country of Citizenship: Indian" |
| **P5-D22** (human, 2026-11-05) A case hint ("BLOCK letters", "Capital letters") in a form-level instruction area, the first page's header (its top quarter) or a block under an "Instructions" heading, applies to every text field of the form; any other instruction applies from its line to the next section heading; a field's own label hint stays its own | a page instruction covers its page only (M3 before) | Fresh-eyes review: #03's page 2 address in mixed case though page 1's header says "Please fill up in BLOCK letters only". Dev: 255 text fields become upper-case, none loses it, all on #01 (pages 2, 4-9) and #03 (page 2); fill numbers unchanged |
| **P5-D23** (human, 2026-11-05) P5-D5's time-box is met; a Devanagari smoke test runs in every `make render-check`: on a synthetic page the overlay renderer must draw "क्ष" and "श्र" as one shaped glyph each, "कि" with its vowel sign left of the consonant and "की" with it right | a further time-box | Passed on 2026-11-05; a unit test shows the check fails on unshaped text. Had it failed, the review screen would show the "won't print" note for Devanagari values |
| **P5-D24** (human, 2026-11-05) #01's FATCA annexure account number stays a known limitation: the annexure is conditional (tax residence outside India) but prints no condition line, so P5-D19 cannot see it. The section-subject layer (M4) handles it | a rule for FATCA annexures | A general rule needs each section's subject and condition: planned for M4 |
| **P5-D25** (human, 2026-11-05) #21 page 1's IFSC is accepted: it sits in section 16, the nominee's bank account, and this claim form is completed by the claimant, who is the nominee and the applicant; the IFSC is the applicant's own bank's. The account number and bank name beside it are asked (the LLM typed those labels `other`) | record a known limitation | The value is right for the section |
| **P5-D26** (human, 2026-11-06, additions to the approved gate plan) The 24 h expiry: an hourly arq cron sweep (minute 0) and one sweep each time the worker starts, after the stale jobs are failed, because a free-tier host can sleep through cron runs. A document past `expires_at` is deleted with its stored files, IR versions, jobs and audit events (cascade), as the user's own delete; one with a queued or running job waits for the next sweep. Until it is swept, every route of the document and its jobs answers **410** "This form expired: FormPilot deletes forms 24 hours after upload. Upload it again."; `DELETE` still works; other users still get 404. Each expiry leaves one `document_expired` audit event on the owner (actor `system`, no document id, file name or value), so the events count expiries; logs hold counts only | hourly cron only; a counts column on `audit_events` (a schema change); sweep in the API process too | No schema change: the existing columns hold a per-owner event with nothing identifying. The start-up sweep runs in the worker, which owns the jobs; see Open issues for the API side |
| **P5-D27** (Claude Code, within the approved gate plan, 2026-11-06) `make eval-render`: per persona, the dev forms are rendered as by `render-samples` and the printed text is read back from the PDF. *Fill correctness*: read-back values right for the persona (as the fill eval's value precision; an upper-case field must read back in capitals) out of all printed values, and out of the compared fields with a fillable reference type. *Printed-text errors*: right as `fit.printed`, wrong as read back. *Placement* against the human label boxes: IoU, containment, share of printed characters inside the label box (by centre and whole glyph), also on the forms labelled from scratch alone | score `fit.printed` only (the match level); IoU only | Only the read-back sees what the PDF shows. 9 of the 11 dev label files were pre-annotated with the detector's boxes, so their IoU partly measures that start; the from-scratch forms are reported apart |
| **P5-D28** (Claude Code, within the approved gate plan, 2026-11-06) `make eval-ux`: actions to complete one dev form with the full persona: one per question card (answered or skipped), one per suggestion, one per profile value confirm all leaves to the user, one confirm all, one render-and-download; inputs typed apart. *Before* is recomputed from today's pipeline with the M3 features turned off: no suggestions, the M2 question plan kept in code (`plan(..., sections=False)`: typed fields grouped as in M2, untyped fields one by one), no confirm all (every value to print confirmed one by one). It is not a historical M2 measurement | one question per field for *before*, as the plan's wording said | The M2 plan in code is what M2 asked; one question per field would overstate the *before* count. Cards and inputs equal the questions eval's M2 and M3 counts on every dev form |

### Dev numbers before and after the render fixes (P5-D12 to P5-D21)

Groq `openai/gpt-oss-120b` replayed, `understand_v2`; `c955d10` is the last commit before the
render fixes, `b24202a` the last fix. Reports: `eval/reports/*-m3-forms-after-20261101-51463a8*`
and `*-m3-render-fixes-20261105-b24202a*`.

| Understanding (dev) | c955d10 | b24202a |
|---|--:|--:|
| Groq, all fields | 74.4 % (390/524) | 74.4 % (390/524) |
| Groq, fillable accuracy | 70.5 % (170/241) | 70.5 % (170/241) |
| qwen3:8b, live, all / fillable | 66.4 % / 64.7 % (`4f143bd`) | 66.4 % (348/524) / 64.7 % (156/241) |

Fill, product policy (LLM confidence ≥ 0.99, once per form), under the definition before P5-D17
(a profile value counts as a fill whatever its status) and after it (only status `filled`):

| Persona | Definition | c955d10: filled, fill precision, coverage, value precision | b24202a |
|---|---|---|---|
| `asha_verma` | old | 79, 88.6 % (70/79), 29.0 %, 88.6 % (70/79) | 66, 92.4 % (61/66), 25.3 %, 92.4 % (61/66) |
| `asha_verma` | new | 79, 88.6 %, 29.0 %, 88.6 % | 66, 92.4 %, 25.3 %, 92.4 % |
| `meera_iyer` | old | 56, 87.5 % (49/56), 20.3 %, 87.5 % (49/56) | 47, 93.6 % (44/47), 18.3 %, 93.6 % (44/47) |
| `meera_iyer` | new | 56, 87.5 %, 20.3 %, 87.5 % | 47, 93.6 %, 18.3 %, 93.6 % |
| `ravi_kumar` | old | 71, 91.5 % (65/71), 27.0 %, 91.5 % (65/71) | 63, 93.7 % (59/63), 24.5 %, 93.7 % (59/63) |
| `ravi_kumar` | new | 71, 91.5 %, 27.0 %, 91.5 % | 63, 93.7 %, 24.5 %, 93.7 % |

The two definitions agree at both commits: the eval context has no suggestion floor, and since
P5-D19 the guardian row is conditional, so no split name is suggested on dev. They differed at
`14e5bc3` (asha 77 / 69 / 68 old, 75 / 68 / 68 new). A per-field diff explains every changed fill
(asha: 8 office-use P5-D15/D18, 3 institution numbers P5-D20, 1 condition P5-D19, 1 date part
P5-D13; meera 4 / 3 / 1 / 1; ravi 7 office-use, 1 date part); fill precision and value precision
rose for every persona, the coverage drop comes from those fields only (human: expected).
Suggestion precision (P5-D17, floor 0.95, product policy): asha 64.5 % (20/31), meera 69.2 %
(18/26), ravi 70.8 % (17/24). The P4-D2 rule now picks ≥ 0.90, once per form: 85.7 % (90/105),
coverage 37.3 %.

Render checks (`make render-check`, P5-D11): before (`bfacffa`) 5 failures (#03 a part-printed
date and a tick from the profile, #25 two comb digits on dividers, #41 two fields below an
official-only heading); after (`b24202a`) none on the 11 forms. Fresh-eyes review by a separate
agent: 35 problems before (12 high), 13 after (6 high): the generic-label fills (nominee name and
age, #21 address, #32 guardian name), #21's certificate date, the existing account's number,
and the low-severity notes in Known limitations; new after: #03's address in mixed case although
page 1 asks for BLOCK letters (the case hint is per page), #01's FATCA account number (a
conditional annexure without a condition line), #21 page 1's IFSC alone in its table.

### M3 gate measurements (2026-11-06, dev, Groq replayed)

Fill correctness and placement, read back from the rendered PDFs (`eval/reports/phase5-render-eval-dev-20261106-31d7722`; product policy, then confirm all):

| Persona | Printed | Right | Correct of printed | Correct of fillable | Printed-text errors | IoU mean / median | IoU ≥ 0.5 | Containment mean | Chars inside label (centre / whole) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| asha_verma | 64 | 59 | 92.2 % | 24.5 % (59/241) | 0 | 0.857 / 1.000 | 85.9 % | 0.869 | 92.7 % / 80.4 % |
| meera_iyer | 46 | 43 | 93.5 % | 17.8 % (43/241) | 0 | 0.887 / 1.000 | 87.0 % | 0.891 | 90.0 % / 86.7 % |
| ravi_kumar | 61 | 57 | 93.4 % | 23.6 % (57/241) | 0 | 0.855 / 1.000 | 85.2 % | 0.862 | 92.2 % / 75.7 % |

Every printed field reads back as the text the renderer was given, so the read-back and the
match-level judgement agree on every field. A check with a deliberately broken renderer (last
character dropped; lower case) found 64 and 31 errors, so the read-back does see them. On the two
forms labelled from scratch (21, 41; only 21 prints) IoU mean is 0.441 / 0.404 / 0.441.

Actions to complete one form (`eval/reports/phase5-ux-actions-dev-20261106-4ceb39c`; full
persona; *before* recomputed with the M3 features turned off, not a historical M2 measurement):
**949 before, 200 after** on the 11 dev forms. Cards 414 → 145, inputs typed 456 → 425, 521
one-by-one confirms → 10 confirm-alls and 31 suggestions, 3 reviews both ways.

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
- **Eval pick vs product threshold** (P5-D10): the fill eval's chosen policy is ≥ 0.95 at
  `c955d10` and ≥ 0.90, once per form after the render fixes (85.7 %, 90/105); the product fills
  at ≥ 0.99.
- **Form 41, the official's slip Date** (human, 2026-11-05). The frozen reference labels the post
  office's acknowledgement date `date_of_filling`; P5-D15 makes the slip office-use, so the fill
  eval loses one right fill per persona. It is not an applicant fill; the labels stay unchanged,
  as for form 06.

Accepted by the human on 2026-11-05, no fix in M3 (from the fresh-eyes review of P5-D11):

- **Form 21's post-office certificate DATE** ("We hereby certify …", signed by the Post Office
  official) is printed: the block has no "to be filled by" line, no office-use phrase and no slip
  title.
- **An existing account's number and branch on an account-opening form** (#01's DA-1 and FATCA
  account numbers): the profile's account is not the account being opened. Part of the generic-
  label entry in PLAN.md's After v1 list.
- **#01's FATCA annexure account number** (P5-D24): a conditional annexure without a condition
  line; for the M4 section-subject layer.
- **Form 23's "Telephone No." gets the alternate number** (typed `phone_alternate` by rule), not
  the mobile.
- **Values slightly above their line** (form 21's Branch and IFSC): text is centred in the
  detected box, whose bottom is the drawn line.
- **01/01/2026 in the renders** is the eval's fixed clock (`run_eval.FIXED_TIME`), so runs are
  reproducible; the product prints the day of filling.

Found by the M3 gate evals (2026-11-06), for the human to accept or schedule:

- **Printed text a line above a dotted-line strip** (form 21, labelled from scratch): the human
  boxes are thin strips on the writing line; the detected box starts a line higher and text is
  centred in it, so 0 % of the glyphs lie wholly inside the strip (64.7 % by centre). Related to
  "Values slightly above their line" above.
- **First characters left of the human box** (form 30): the detected box starts at the colon,
  the human box where the line starts; 1 or 2 characters per field fall outside it.

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

- **A value longer than its comb is cut short without a warning** (found 2026-11-06 while
  building `eval-render`). The fit pass and the overlay renderer both pair characters with cells
  by `zip(..., strict=False)`: a 10-character value in a 4-cell comb passes the fit check, stays
  `filled`, is taken by confirm all, and only 4 characters print. Not seen on dev (0 "cut short"
  in the read-back); a unit test in `test_render_eval.py` shows the read-back catches it.
  Proposed fix, awaiting the human's decision: the fit pass flags a comb value with more
  characters than cells ("The value has more characters than the boxes"), so it needs review.
- **Start-up sweep and the API** (P5-D26): the sweep runs when the worker starts, not when the
  API starts. Between sweeps the API refuses expired documents (410), so no expired form is
  served either way. If the M4 platform runs the API without an always-on worker, decide then
  whether the API's start also sweeps.

## Resume point (2026-11-06)

- **Done in M3:** IR additions (suggestions, uppercase, question text, date parts, groups, comb
  cells, conditions); case hints, suggestions, readable questions (phrase pass), grouping;
  questions, address and fill evals; review routes and audit; overlay renderer with Devanagari
  (P5-D5, smoke test P5-D23), render job and download; `render-samples` and `render-check`;
  render fixes P5-D12 to P5-D25. Gate items 1-3 of the approved plan (2026-11-06): the expiry
  sweep and the 410 (P5-D26, `2212921`, `62f6b3e`), `make eval-render` (P5-D27, `31d7722`,
  report `be97cbc`), `make eval-ux` (P5-D28, `4ceb39c`, report `7778f65`). Numbers: "M3 gate
  measurements" above.
- **Stopped for the human (2026-11-06):** the eval-render and UX numbers; the comb overflow
  (Open issues, fix proposed); the two placement limitations; P5-D28's *before* definition.
- **Next, after the human's approval:** item 4, the review screen (side panel, suggested band,
  confirm all per P5-D7); item 5, the Playwright happy path in the Compose smoke job, with two
  privacy assertions (no unmasked sensitive value in the review page's DOM; no unconfirmed
  suggestion in the downloaded PDF) and review-screen screenshots saved as CI artifacts, not
  committed; item 6, the close-out (this record, gate checklist, "In my own words", PR).

## Notes for the next phase

To be completed at the end of the milestone.

## In my own words
