# Understanding eval — dev, mode llm

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@ee3c22e`; provider `ollama:qwen3:8b`; prompt `understand_v1.md`; created 2026-10-26T15:04:47+00:00; tag `pre-tuning`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 57.6 % (302/524) | 55.2 % (133/241) |
| From scratch | 66.7 % (42/63) | 60.0 % (18/30) |
| Pre-filled | 56.4 % (260/461) | 54.5 % (115/211) |

Macro over forms (fillable): 64.3 %. Predicted `unknown`: 43. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | — (0/0) |
| llm | 57.6 % (302/524) |
| none | — (0/0) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 55.4 % (93/168) | 45.9 % (34/74) |
| 02_sbi_kyc_annexure_a | 87.9 % (29/33) | 91.7 % (22/24) |
| 03_sbi_kyc_annexure_b | 56.4 % (22/39) | 57.1 % (12/21) |
| 06_union_bank_nomination_form | 51.9 % (14/27) | 75.0 % (3/4) |
| 21_india_post_pmjjby_claim_form | 59.6 % (28/47) | 57.1 % (16/28) |
| 23_lic_claim_form_a_3783 | 47.7 % (21/44) | 46.2 % (6/13) |
| 25_cdlsiet_btech_admission_form | 52.6 % (51/97) | 44.7 % (21/47) |
| 30_allahabad_univ_enrollment_form | 37.9 % (11/29) | 50.0 % (7/14) |
| 32_niftem_student_declaration_form | 75.0 % (12/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 87.5 % (7/8) | 66.7 % (2/3) |
| 41_india_post_pli_name_change_form | 87.5 % (14/16) | 100.0 % (2/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 100.0 % | 7 | 71.4 % |
| `age` | 1 | 100.0 % | 5 | 20.0 % |
| `bank_account_number` | 11 | 63.6 % | 8 | 87.5 % |
| `bank_branch` | 3 | 66.7 % | 2 | 100.0 % |
| `bank_name` | 2 | 100.0 % | 4 | 50.0 % |
| `category` | 2 | 100.0 % | 8 | 25.0 % |
| `course` | 1 | 0.0 % | 1 | 0.0 % |
| `current_address_line1` | 9 | 77.8 % | 14 | 50.0 % |
| `current_address_line2` | 5 | 40.0 % | 4 | 50.0 % |
| `current_city` | 4 | 100.0 % | 8 | 50.0 % |
| `current_country` | 3 | 100.0 % | 4 | 75.0 % |
| `current_district` | 5 | 80.0 % | 6 | 66.7 % |
| `current_pincode` | 5 | 100.0 % | 7 | 71.4 % |
| `current_state` | 5 | 100.0 % | 6 | 83.3 % |
| `date_of_birth` | 7 | 71.4 % | 9 | 55.6 % |
| `date_of_filling` | 38 | 42.1 % | 31 | 51.6 % |
| `email` | 5 | 100.0 % | 6 | 83.3 % |
| `enrollment_number` | 5 | 60.0 % | 9 | 33.3 % |
| `father_name` | 5 | 40.0 % | 5 | 40.0 % |
| `first_name` | 2 | 0.0 % | 3 | 0.0 % |
| `full_name` | 21 | 42.9 % | 24 | 37.5 % |
| `gender` | 1 | 100.0 % | 1 | 100.0 % |
| `guardian_name` | 3 | 33.3 % | 3 | 33.3 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 33.3 % | 1 | 100.0 % |
| `last_name` | 2 | 0.0 % | 0 | — |
| `marital_status` | 1 | 100.0 % | 2 | 50.0 % |
| `middle_name` | 2 | 0.0 % | 0 | — |
| `mother_name` | 4 | 50.0 % | 4 | 50.0 % |
| `nationality` | 4 | 50.0 % | 4 | 50.0 % |
| `other` | 272 | 60.7 % | 239 | 69.0 % |
| `pan` | 2 | 100.0 % | 3 | 66.7 % |
| `passing_year` | 8 | 0.0 % | 0 | — |
| `percentage_or_cgpa` | 5 | 60.0 % | 11 | 27.3 % |
| `permanent_address_line1` | 1 | 0.0 % | 0 | — |
| `phone_alternate` | 3 | 33.3 % | 2 | 50.0 % |
| `phone_mobile` | 8 | 87.5 % | 11 | 63.6 % |
| `place` | 7 | 57.1 % | 5 | 80.0 % |
| `signature` | 40 | 40.0 % | 19 | 84.2 % |
| `spouse_name` | 1 | 100.0 % | 1 | 100.0 % |
| `unknown` | 11 | 36.4 % | 43 | 9.3 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `signature` | `other` | 17 |
| `other` | `unknown` | 17 |
| `other` | `date_of_filling` | 14 |
| `date_of_filling` | `unknown` | 13 |
| `full_name` | `other` | 11 |
| `other` | `full_name` | 11 |
| `date_of_filling` | `other` | 8 |
| `signature` | `unknown` | 7 |
| `other` | `current_address_line1` | 6 |
| `other` | `enrollment_number` | 6 |
| `passing_year` | `other` | 6 |
| `other` | `category` | 6 |
| `unknown` | `other` | 5 |
| `other` | `percentage_or_cgpa` | 5 |
| `other` | `date_of_birth` | 4 |

Never-fill marks on compared fields: {'signature': 19, 'office_use': 40}.
