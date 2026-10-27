# Understanding eval — dev, mode hybrid

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@4f143bd`; provider `ollama:qwen3:8b`; prompt `understand_v2.md`; created 2026-10-27T18:20:16+00:00; tag `qwen-m3-forms`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 66.4 % (348/524) | 64.7 % (156/241) |
| From scratch | 74.6 % (47/63) | 66.7 % (20/30) |
| Pre-filled | 65.3 % (301/461) | 64.5 % (136/211) |

Precision of predicted fillable types: 61.9 % (156/252).

Macro over forms (fillable): 56.8 %. Predicted `unknown`: 9. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | 76.9 % (83/108) |
| llm | 63.7 % (265/416) |
| none | — (0/0) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 67.3 % (113/168) | 63.5 % (47/74) |
| 02_sbi_kyc_annexure_a | 90.9 % (30/33) | 91.7 % (22/24) |
| 03_sbi_kyc_annexure_b | 66.7 % (26/39) | 66.7 % (14/21) |
| 06_union_bank_nomination_form | 66.7 % (18/27) | 25.0 % (1/4) |
| 21_india_post_pmjjby_claim_form | 70.2 % (33/47) | 67.9 % (19/28) |
| 23_lic_claim_form_a_3783 | 61.4 % (27/44) | 30.8 % (4/13) |
| 25_cdlsiet_btech_admission_form | 58.8 % (57/97) | 66.0 % (31/47) |
| 30_allahabad_univ_enrollment_form | 41.4 % (12/29) | 57.1 % (8/14) |
| 32_niftem_student_declaration_form | 75.0 % (12/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 75.0 % (6/8) | 33.3 % (1/3) |
| 41_india_post_pli_name_change_form | 87.5 % (14/16) | 50.0 % (1/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 100.0 % | 6 | 83.3 % |
| `age` | 1 | 100.0 % | 4 | 25.0 % |
| `bank_account_number` | 11 | 63.6 % | 8 | 87.5 % |
| `bank_branch` | 3 | 66.7 % | 2 | 100.0 % |
| `bank_name` | 2 | 100.0 % | 4 | 50.0 % |
| `category` | 2 | 100.0 % | 8 | 25.0 % |
| `course` | 1 | 0.0 % | 1 | 0.0 % |
| `current_address_line1` | 9 | 55.6 % | 11 | 45.5 % |
| `current_address_line2` | 5 | 40.0 % | 5 | 40.0 % |
| `current_city` | 4 | 75.0 % | 5 | 60.0 % |
| `current_country` | 3 | 100.0 % | 3 | 100.0 % |
| `current_district` | 5 | 60.0 % | 4 | 75.0 % |
| `current_pincode` | 5 | 80.0 % | 4 | 100.0 % |
| `current_state` | 5 | 80.0 % | 6 | 66.7 % |
| `date_of_birth` | 7 | 100.0 % | 11 | 63.6 % |
| `date_of_filling` | 38 | 68.4 % | 41 | 63.4 % |
| `email` | 5 | 100.0 % | 5 | 100.0 % |
| `enrollment_number` | 5 | 80.0 % | 14 | 28.6 % |
| `father_name` | 5 | 60.0 % | 4 | 75.0 % |
| `first_name` | 2 | 100.0 % | 4 | 50.0 % |
| `full_name` | 21 | 52.4 % | 22 | 50.0 % |
| `gender` | 1 | 100.0 % | 1 | 100.0 % |
| `guardian_name` | 3 | 33.3 % | 2 | 50.0 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 100.0 % | 3 | 100.0 % |
| `last_name` | 2 | 100.0 % | 5 | 40.0 % |
| `marital_status` | 1 | 100.0 % | 2 | 50.0 % |
| `middle_name` | 2 | 100.0 % | 5 | 40.0 % |
| `mother_name` | 4 | 50.0 % | 2 | 100.0 % |
| `nationality` | 4 | 50.0 % | 3 | 66.7 % |
| `other` | 272 | 69.5 % | 263 | 71.9 % |
| `pan` | 2 | 100.0 % | 2 | 100.0 % |
| `passing_year` | 8 | 37.5 % | 3 | 100.0 % |
| `percentage_or_cgpa` | 5 | 40.0 % | 8 | 25.0 % |
| `permanent_address_line1` | 1 | 0.0 % | 0 | — |
| `phone_alternate` | 3 | 66.7 % | 4 | 50.0 % |
| `phone_mobile` | 8 | 87.5 % | 10 | 70.0 % |
| `place` | 7 | 71.4 % | 5 | 100.0 % |
| `signature` | 40 | 42.5 % | 20 | 85.0 % |
| `spouse_name` | 1 | 100.0 % | 1 | 100.0 % |
| `unknown` | 11 | 27.3 % | 9 | 33.3 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `signature` | `other` | 20 |
| `other` | `date_of_filling` | 13 |
| `other` | `full_name` | 11 |
| `other` | `enrollment_number` | 10 |
| `date_of_filling` | `other` | 9 |
| `full_name` | `other` | 8 |
| `unknown` | `other` | 7 |
| `other` | `category` | 6 |
| `other` | `percentage_or_cgpa` | 5 |
| `passing_year` | `other` | 5 |
| `other` | `date_of_birth` | 4 |
| `other` | `current_address_line1` | 4 |
| `bank_account_number` | `other` | 4 |
| `current_address_line1` | `other` | 4 |
| `other` | `age` | 3 |

Never-fill marks on compared fields: {'signature': 20, 'office_use': 41}.

LLM batches that failed or needed a retry:
- 06_union_bank_nomination_form: page 1: LLM batch retried
