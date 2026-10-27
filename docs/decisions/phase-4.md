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

### Fill-policy tuning session: fixed before the run (P4-D2)

Written and committed before the first fill eval run, so the choice cannot follow the numbers.
- **Data:** dev split, Groq `openai/gpt-oss-120b` recordings (P4-D1), hybrid mode, replayed;
  the qwen3:8b recordings are scored the same way for comparison only.
- **Personas** (`eval/personas/`, P4-D3): `asha_verma` (every profile field; the policy is chosen
  on this one), `ravi_kumar` and `meera_iyer` (partial).
- **Candidates** (`eval/fill_eval.py`, `CANDIDATES`): no policy (every predicted type); LLM
  confidence ≥ 0.90, ≥ 0.95, ≥ 0.99; rules only; and each of the last four with "a person or date
  type at most once per form".
- **Rule:** the highest coverage among candidates with fill precision ≥ 85 % (ties: higher
  precision); if none reaches 85 %, the highest fill precision among candidates with coverage
  ≥ 20 % (ties: higher coverage), and the report says the target was missed.
- One session: if no candidate is good enough, the result is reported as it is; no new
  candidates are added after the run.

### Fill-policy tuning session: result (2026-10-27)

Reports: `eval/reports/phase4-fill-dev-groq-openai-gpt-oss-120b-tuning-20261027-b315f23.md`
and `…-ollama-qwen3-8b-comparison-…`. Full persona (`asha_verma`), dev, 241 compared fields with
a fillable reference type. Reference labels Claude-written (P3-D6), personas not checked by a
human (P4-D3).

| Candidate | Groq: fill precision | Groq: coverage | qwen3:8b: fill precision | qwen3:8b: coverage |
|---|--:|--:|--:|--:|
| No policy (every predicted type) | 64.8 % (127/196) | 52.7 % | 57.6 % (117/203) | 48.5 % |
| LLM ≥ 0.90 | 68.1 % (111/163) | 46.1 % | 57.9 % (117/202) | 48.5 % |
| LLM ≥ 0.95 | 75.6 % (102/135) | 42.3 % | 70.1 % (89/127) | 36.9 % |
| LLM ≥ 0.99 | 79.8 % (79/99) | 32.8 % | 68.3 % (82/120) | 34.0 % |
| Rules only | 74.0 % (54/73) | 22.4 % | 74.0 % (54/73) | 22.4 % |
| LLM ≥ 0.90, once per form | 70.0 % (91/130) | 37.8 % | 63.1 % (99/157) | 41.1 % |
| LLM ≥ 0.95, once per form | 79.0 % (83/105) | 34.4 % | 76.0 % (73/96) | 30.3 % |
| **LLM ≥ 0.99, once per form (chosen)** | **86.5 % (64/74)** | **26.6 %** | 74.2 % (66/89) | 27.4 % |
| Rules only, once per form | 81.4 % (48/59) | 19.9 % | 81.4 % (48/59) | 19.9 % |

- **Chosen by the rule:** LLM confidence ≥ 0.99 and person or date types at most once per form.
  **Target met on Groq** (86.5 % ≥ 85 %); it is now the product default (`FILL_MIN_CONFIDENCE`
  0.99, `FILL_ONCE_PER_FORM` true). Value correctness under it: 86.5 %. The other personas:
  `ravi_kumar` 92.2 % (64 filled), `meera_iyer` 84.6 % (52 filled).
- **qwen3:8b (the fallback) does not reach the target** with any candidate; under the chosen
  policy it fills at 74.2 %. On the Ollama fallback, fills are less precise (known limitation).
- "No policy" here (64.8 %) is below the understanding eval's fillable precision (67.7 %,
  151/223) because only fields the persona can fill count: never-fill fields, types without a
  profile value (`place`, `signature`) and unmatched options are not filled.
- The baseline (`eval/baseline.json`, `fill`) holds the chosen policy's Groq numbers.

## Known limitations

Not yet (in progress).

## Open issues

Not yet (in progress).

## Notes for the next phase

Not yet (in progress).

## In my own words

