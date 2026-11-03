# Fill eval — dev, provider `groq:openai/gpt-oss-120b`

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.** Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

- Detector `flat@51463a8`; created 2026-11-01T05:57:03+00:00; tag `m3-forms-after`
- *Fill precision*: of the compared fields the policy fills, the share with the right semantic type. *Coverage*: right fills / compared fields with a fillable reference type. *Value correctness*: filled values equal to the value the reference type gets. *Value precision*: filled values right for the persona as printed, where a repeated row (a table row) has no right profile value and a split date wants its day, month or year (eval/value_truth.py).
- **Chosen policy: LLM confidence >= 0.95, once per form** (target of 85.0 % fill precision **met**; chosen on `asha_verma`).

## Full persona (`asha_verma`)

| Policy | Filled | Fill precision | Coverage | Value correctness | Value precision |
|---|--:|--:|--:|--:|--:|
| every predicted type (no policy) | 188 | 71.8 % (135/188) | 56.0 % (135/241) | 72.3 % | 64.4 % (121/188) |
| LLM confidence >= 0.90 | 165 | 76.4 % (126/165) | 52.3 % (126/241) | 77.0 % | 69.7 % (115/165) |
| LLM confidence >= 0.95 | 154 | 78.6 % (121/154) | 50.2 % (121/241) | 78.6 % | 70.8 % (109/154) |
| LLM confidence >= 0.99 | 115 | 78.3 % (90/115) | 37.3 % (90/241) | 78.3 % | 73.0 % (84/115) |
| rules only | 88 | 76.1 % (67/88) | 27.8 % (67/241) | 76.1 % | 75.0 % (66/88) |
| LLM confidence >= 0.90, once per form | 120 | 84.2 % (101/120) | 41.9 % (101/241) | 85.0 % | 81.7 % (98/120) |
| LLM confidence >= 0.95, once per form **(chosen)** | 111 | 87.4 % (97/111) | 40.2 % (97/241) | 87.4 % | 83.8 % (93/111) |
| LLM confidence >= 0.99, once per form | 79 | 88.6 % (70/79) | 29.0 % (70/241) | 88.6 % | 88.6 % (70/79) |
| rules only, once per form | 64 | 85.9 % (55/64) | 22.8 % (55/241) | 85.9 % | 85.9 % (55/64) |

## Chosen policy, every persona

| Persona | Filled | Fill precision |
|---|--:|--:|
| `asha_verma` | 111 | 87.4 % |
| `meera_iyer` | 83 | 86.7 % |
| `ravi_kumar` | 95 | 89.5 % |

## Questions per form (chosen policy, scored pages)

Fields needing input after filling, and the questions that ask for them.

| Form | `asha_verma`: fields / questions | `empty profile`: fields / questions |
|---|--:|--:|
| 01_sbi_account_opening_form | 203 / 55 | 234 / 68 |
| 02_sbi_kyc_annexure_a | 9 / 5 | 28 / 16 |
| 03_sbi_kyc_annexure_b | 50 / 14 | 59 / 17 |
| 06_union_bank_nomination_form | 22 / 6 | 24 / 8 |
| 21_india_post_pmjjby_claim_form | 40 / 21 | 50 / 25 |
| 23_lic_claim_form_a_3783 | 43 / 20 | 46 / 23 |
| 25_cdlsiet_btech_admission_form | 82 / 16 | 96 / 26 |
| 30_allahabad_univ_enrollment_form | 20 / 10 | 28 / 18 |
| 32_niftem_student_declaration_form | 9 / 2 | 13 / 6 |
| 39_cebs_joining_report | 7 / 2 | 7 / 2 |
| 41_india_post_pli_name_change_form | 15 / 5 | 16 / 6 |
| **Total** | 500 / 156 | 601 / 215 |
