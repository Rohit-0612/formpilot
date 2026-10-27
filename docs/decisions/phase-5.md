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
| **P5-D5** Devanagari rendering: a time-box of half a session to render it with a free embeddable font (Noto Sans Devanagari, OFL) and correct shaping, verified on rendered output. If it does not work cleanly, the review screen and the question both say that such a field will not be printed | no attempt (Helvetica only, the M2 limitation) | The human's addition. Outcome: to be recorded |
| **P5-D6** Readable questions: the same batched understanding call also returns a short English question for each field (`question_en` → `Field.question_text`), translated from Hindi and repaired where the text layer is garbled (prompt `understand_v3.md`). The question shows it as the main text with the form's own label in small text below; without it, a clean English label is quoted, else "Box N on page P"; broken text is never the main question | quoting the label (M2); a second LLM call per field; translating in code | On dev with the full persona, 24 of 526 label questions quoted Hindi (often garbled) and 3 had no label. One call keeps the cost; the request still holds printed form text only |

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
- **Also in the plan:** question grouping by section or person (questions per form before and
  after, inputs and cards counted separately); a free-text address parsing eval with record /
  replay; a UX metric (actions to complete a dev form with the full persona, before and after);
  format hints such as "(Capital letters)" set `Field.uppercase` and the renderer upper-cases the
  value; the hourly expiry job; fill-correctness and placement evals.

## Known limitations

To be completed at the end of the milestone.

## Open issues

- Commit `8c1b8c5` (office-use fix) says "make test 1081 passed" in its message; the run before
  that commit had **1089** unit tests passing. The message was not amended because the branch
  was already pushed (no history rewrite).

## Notes for the next phase

To be completed at the end of the milestone.

## In my own words
