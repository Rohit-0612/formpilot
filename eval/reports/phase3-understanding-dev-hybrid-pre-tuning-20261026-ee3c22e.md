# Understanding eval — dev, mode hybrid

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@ee3c22e`; provider `ollama:qwen3:8b`; prompt `understand_v1.md`; created 2026-10-26T13:43:16+00:00; tag `pre-tuning`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 57.4 % (301/524) | 57.3 % (138/241) |
| From scratch | 66.7 % (42/63) | 56.7 % (17/30) |
| Pre-filled | 56.2 % (259/461) | 57.3 % (121/211) |

Macro over forms (fillable): 53.7 %. Predicted `unknown`: 21. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | 60.4 % (81/134) |
| llm | 56.4 % (220/390) |
| none | — (0/0) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 53.6 % (90/168) | 50.0 % (37/74) |
| 02_sbi_kyc_annexure_a | 87.9 % (29/33) | 91.7 % (22/24) |
| 03_sbi_kyc_annexure_b | 66.7 % (26/39) | 66.7 % (14/21) |
| 06_union_bank_nomination_form | 33.3 % (9/27) | 25.0 % (1/4) |
| 21_india_post_pmjjby_claim_form | 59.6 % (28/47) | 57.1 % (16/28) |
| 23_lic_claim_form_a_3783 | 54.5 % (24/44) | 38.5 % (5/13) |
| 25_cdlsiet_btech_admission_form | 53.6 % (52/97) | 55.3 % (26/47) |
| 30_allahabad_univ_enrollment_form | 37.9 % (11/29) | 50.0 % (7/14) |
| 32_niftem_student_declaration_form | 75.0 % (12/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 75.0 % (6/8) | 33.3 % (1/3) |
| 41_india_post_pli_name_change_form | 87.5 % (14/16) | 50.0 % (1/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 100.0 % | 6 | 83.3 % |
| `age` | 1 | 100.0 % | 4 | 25.0 % |
| `bank_account_number` | 11 | 90.9 % | 11 | 90.9 % |
| `bank_branch` | 3 | 66.7 % | 4 | 50.0 % |
| `bank_name` | 2 | 100.0 % | 4 | 50.0 % |
| `category` | 2 | 100.0 % | 10 | 20.0 % |
| `course` | 1 | 0.0 % | 1 | 0.0 % |
| `current_address_line1` | 9 | 66.7 % | 15 | 40.0 % |
| `current_address_line2` | 5 | 60.0 % | 7 | 42.9 % |
| `current_city` | 4 | 100.0 % | 8 | 50.0 % |
| `current_country` | 3 | 100.0 % | 4 | 75.0 % |
| `current_district` | 5 | 80.0 % | 6 | 66.7 % |
| `current_pincode` | 5 | 100.0 % | 7 | 71.4 % |
| `current_state` | 5 | 80.0 % | 5 | 80.0 % |
| `date_of_birth` | 7 | 71.4 % | 9 | 55.6 % |
| `date_of_filling` | 38 | 44.7 % | 32 | 53.1 % |
| `email` | 5 | 100.0 % | 6 | 83.3 % |
| `enrollment_number` | 5 | 80.0 % | 13 | 30.8 % |
| `father_name` | 5 | 60.0 % | 7 | 42.9 % |
| `first_name` | 2 | 0.0 % | 0 | — |
| `full_name` | 21 | 42.9 % | 30 | 30.0 % |
| `gender` | 1 | 100.0 % | 1 | 100.0 % |
| `guardian_name` | 3 | 33.3 % | 7 | 14.3 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 0.0 % | 0 | — |
| `last_name` | 2 | 0.0 % | 0 | — |
| `marital_status` | 1 | 100.0 % | 2 | 50.0 % |
| `middle_name` | 2 | 0.0 % | 0 | — |
| `mother_name` | 4 | 50.0 % | 5 | 40.0 % |
| `nationality` | 4 | 25.0 % | 2 | 50.0 % |
| `other` | 272 | 58.8 % | 239 | 66.9 % |
| `pan` | 2 | 100.0 % | 3 | 66.7 % |
| `passing_year` | 8 | 0.0 % | 0 | — |
| `percentage_or_cgpa` | 5 | 60.0 % | 9 | 33.3 % |
| `permanent_address_line1` | 1 | 0.0 % | 1 | 0.0 % |
| `phone_alternate` | 3 | 66.7 % | 3 | 66.7 % |
| `phone_mobile` | 8 | 87.5 % | 12 | 58.3 % |
| `place` | 7 | 71.4 % | 6 | 83.3 % |
| `signature` | 40 | 40.0 % | 18 | 88.9 % |
| `spouse_name` | 1 | 100.0 % | 1 | 100.0 % |
| `unknown` | 11 | 27.3 % | 21 | 14.3 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `signature` | `other` | 22 |
| `other` | `full_name` | 17 |
| `date_of_filling` | `other` | 17 |
| `other` | `date_of_filling` | 13 |
| `other` | `unknown` | 9 |
| `full_name` | `other` | 9 |
| `other` | `current_address_line1` | 8 |
| `other` | `category` | 8 |
| `other` | `enrollment_number` | 7 |
| `unknown` | `other` | 6 |
| `other` | `father_name` | 4 |
| `other` | `guardian_name` | 4 |
| `other` | `phone_mobile` | 4 |
| `other` | `date_of_birth` | 4 |
| `other` | `percentage_or_cgpa` | 4 |

Never-fill marks on compared fields: {'signature': 18, 'office_use': 40}.

LLM batches that failed or needed a retry:
- 01_sbi_account_opening_form: page 3: LLM batch retried
