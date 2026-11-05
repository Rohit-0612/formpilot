# Fill eval — dev, provider `groq:openai/gpt-oss-120b`

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.** Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

- Detector `flat@b24202a`; created 2026-11-05T05:39:59+00:00; tag `m3-render-fixes`
- *Fill precision*: of the compared fields the policy fills, the share with the right semantic type. *Coverage*: right fills / compared fields with a fillable reference type. *Value correctness*: filled values equal to the value the reference type gets. *Value precision*: filled values right for the persona as printed, where a repeated row (a table row) has no right profile value and a split date wants its day, month or year (eval/value_truth.py).
- **Chosen policy: LLM confidence >= 0.90, once per form** (target of 85.0 % fill precision **met**; chosen on `asha_verma`).

## Full persona (`asha_verma`)

| Policy | Filled | Fill precision | Coverage | Value correctness | Value precision |
|---|--:|--:|--:|--:|--:|
| every predicted type (no policy) | 168 | 73.2 % (123/168) | 51.0 % (123/241) | 73.8 % | 64.9 % (109/168) |
| LLM confidence >= 0.90 | 145 | 78.6 % (114/145) | 47.3 % (114/241) | 79.3 % | 71.0 % (103/145) |
| LLM confidence >= 0.95 | 136 | 80.9 % (110/136) | 45.6 % (110/241) | 80.9 % | 72.1 % (98/136) |
| LLM confidence >= 0.99 | 98 | 81.6 % (80/98) | 33.2 % (80/241) | 81.6 % | 75.5 % (74/98) |
| rules only | 73 | 80.8 % (59/73) | 24.5 % (59/241) | 80.8 % | 79.5 % (58/73) |
| LLM confidence >= 0.90, once per form **(chosen)** | 105 | 85.7 % (90/105) | 37.3 % (90/241) | 86.7 % | 82.9 % (87/105) |
| LLM confidence >= 0.95, once per form | 97 | 89.7 % (87/97) | 36.1 % (87/241) | 89.7 % | 85.6 % (83/97) |
| LLM confidence >= 0.99, once per form | 66 | 92.4 % (61/66) | 25.3 % (61/241) | 92.4 % | 92.4 % (61/66) |
| rules only, once per form | 53 | 90.6 % (48/53) | 19.9 % (48/241) | 90.6 % | 90.6 % (48/53) |

## Chosen policy, every persona

| Persona | Filled | Fill precision |
|---|--:|--:|
| `asha_verma` | 105 | 85.7 % |
| `meera_iyer` | 77 | 89.6 % |
| `ravi_kumar` | 94 | 87.2 % |

## Suggestions (floor 0.95, decision P5-D17)

Suggested values are not fills: they are confirmed one by one. A part of a split name is scored against the persona's matching part of that person's name.

| Policy | `asha_verma` | `meera_iyer` | `ravi_kumar` |
|---|--:|--:|--:|
| LLM confidence >= 0.90, once per form | — (0/0) | — (0/0) | — (0/0) |
| LLM confidence >= 0.99, once per form | 64.5 % (20/31) | 69.2 % (18/26) | 70.8 % (17/24) |

## Questions per form (chosen policy, scored pages)

Fields needing input after filling, and the questions that ask for them.

| Form | `asha_verma`: fields / questions | `empty profile`: fields / questions |
|---|--:|--:|
| 01_sbi_account_opening_form | 190 / 49 | 217 / 60 |
| 02_sbi_kyc_annexure_a | 8 / 4 | 26 / 15 |
| 03_sbi_kyc_annexure_b | 47 / 13 | 58 / 15 |
| 06_union_bank_nomination_form | 22 / 6 | 24 / 8 |
| 21_india_post_pmjjby_claim_form | 39 / 20 | 50 / 24 |
| 23_lic_claim_form_a_3783 | 43 / 21 | 46 / 24 |
| 25_cdlsiet_btech_admission_form | 82 / 14 | 96 / 25 |
| 30_allahabad_univ_enrollment_form | 20 / 10 | 28 / 18 |
| 32_niftem_student_declaration_form | 10 / 2 | 13 / 5 |
| 39_cebs_joining_report | 7 / 2 | 7 / 2 |
| 41_india_post_pli_name_change_form | 0 / 0 | 0 / 0 |
| **Total** | 468 / 141 | 565 / 196 |
