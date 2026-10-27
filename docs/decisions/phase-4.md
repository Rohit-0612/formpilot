# Phase 4 — Vault, matching, questions, answers, validation, fit: decision record

> Status: **in progress** (milestone M2, branch `phase-4-fill`, from `main` after PR #4). The
> milestone plan was approved by the human on 2026-10-27 with the decisions below.

## What was built

Not yet (in progress).

## Key decisions and alternatives considered

### Human decisions on the M2 plan (2026-10-27)

| Decision | Alternatives | Why |
|---|---|---|
| **P4-D1** Understanding uses Groq `openai/gpt-oss-120b` by default when `GROQ_API_KEY` is set; Ollama `qwen3:8b` is the fallback (no key, or a failed Groq request) | Ollama as the default (SPEC §9 before); Groq only | The human's call. Groq was more accurate on dev (P3-D7: fillable precision 67.7 % vs 60.6 %); requests carry printed form text only, and the privacy guard still applies. The fill-policy tuning runs on the Groq recordings; the qwen rows stay for comparison |
| **P4-D2** Precision-first fill policy, target fill precision ≥ 85 % on dev with coverage reported. If no candidate reaches it, the most precise candidate with coverage ≥ 20 % is chosen and the report says the target was missed | fill every predicted fillable type (60.6 % / 67.7 % precision); a confidence threshold only | A value in the wrong box is worse than an empty box the user fills: on dev, 69 of 88 wrong fillable predictions (qwen) were fields of another person or another date |
| **P4-D3** The three synthetic personas are drafted by Claude Code and not checked by the human | the human checks them (PLAN Phase 4 human task) | The human's call, like P3-D6. Personas are synthetic, with format-valid fake identifiers; validators check them in a test |
| **P4-D4** Acceptance reworded: "with a full persona in the vault, a form asks only for fields the persona lacks or the policy is not confident about". CI checks it on a synthetic fixture form; dev forms are covered by the questions-per-form eval | "a dev form needs only questions for fields the persona lacks" | Dev PDFs are not in the repository, and the fill policy deliberately asks about fields it is not confident about |
| **P4-D5** Values of the sensitive types and the phone types are encrypted field by field (Fernet, the vault key) in stored IR versions; the rest of the IR stays plain with the 24 h expiry | the whole IR plain (24 h expiry only); the whole IR encrypted | The human's call: a database dump must not show identifiers or phone numbers. Field-level keeps the IR queryable and debuggable |

### Milestone plan (approved)

- **Fill policy** (`passes/match.py`, deterministic). A field is filled from the profile only if
  it has no `no_fill_reason`, its type has a profile key or a derived value (full name, age,
  today's date) that the profile can give, and its type is confident under the chosen policy.
  Everything else stays empty and is asked with the form's own label; the predicted type only
  suggests the answer's format. Answers to such label questions are never saved to the profile.
- **Key metric: fill precision**, of the fields the policy fills, the share whose reference type
  is the predicted type. Reported with **fill coverage** (correct fills / reference fillable
  fields), value correctness with the personas, questions per form and the validators' catch
  and false-reject rates. Before any policy: 60.6 % (140/231, qwen) and 67.7 % (151/223, Groq).
- **One tuning session** on dev (Groq recordings), over a fixed candidate list: a confidence
  threshold, rules only, and "a person or date type is filled at most once per form"; a
  change → delta table.
- **Form IR** (additive, `schema_version` stays 1): `Field.font_size`, `ValueSource.DERIVED`.
- **Database** (migration 0003): `audit_events.user_id` and a nullable `document_id` (one of
  the two required) for profile events; job type `answers`.
- **API:** `GET /documents/{id}/questions`, `POST /documents/{id}/answers` → 202 `{job_id}`,
  `GET` / `PUT /profile`.
- **New dependency:** `cryptography` (Fernet, SPEC §7 and §11; PyNaCl was the alternative).
- **Config:** `VAULT_KEY`, `FILL_MIN_CONFIDENCE`, `FIT_FONT_SIZE` (10), `FIT_MIN_FONT_SIZE` (6),
  `GROQ_MODEL`.

## Known limitations

Not yet (in progress).

## Open issues

Not yet (in progress).

## Notes for the next phase

Not yet (in progress).

## In my own words

