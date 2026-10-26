# Understanding eval — dev, mode hybrid

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@fa6c544`; provider `ollama:qwen3:8b`; prompt `understand_v1.md`; created 2026-10-26T16:03:51+00:00; tag `tuning-1-rules`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 60.5 % (317/524) | 58.1 % (140/241) |
| From scratch | 68.3 % (43/63) | 60.0 % (18/30) |
| Pre-filled | 59.4 % (274/461) | 57.8 % (122/211) |

Macro over forms (fillable): 58.4 %. Predicted `unknown`: 17. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | 76.5 % (65/85) |
| llm | 57.4 % (252/439) |
| none | — (0/0) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 60.1 % (101/168) | 48.6 % (36/74) |
| 02_sbi_kyc_annexure_a | 87.9 % (29/33) | 91.7 % (22/24) |
| 03_sbi_kyc_annexure_b | 66.7 % (26/39) | 66.7 % (14/21) |
| 06_union_bank_nomination_form | 51.9 % (14/27) | 75.0 % (3/4) |
| 21_india_post_pmjjby_claim_form | 61.7 % (29/47) | 60.7 % (17/28) |
| 23_lic_claim_form_a_3783 | 54.5 % (24/44) | 38.5 % (5/13) |
| 25_cdlsiet_btech_admission_form | 52.6 % (51/97) | 55.3 % (26/47) |
| 30_allahabad_univ_enrollment_form | 37.9 % (11/29) | 50.0 % (7/14) |
| 32_niftem_student_declaration_form | 75.0 % (12/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 75.0 % (6/8) | 33.3 % (1/3) |
| 41_india_post_pli_name_change_form | 87.5 % (14/16) | 50.0 % (1/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 100.0 % | 6 | 83.3 % |
| `age` | 1 | 100.0 % | 6 | 16.7 % |
| `bank_account_number` | 11 | 81.8 % | 11 | 81.8 % |
| `bank_branch` | 3 | 66.7 % | 2 | 100.0 % |
| `bank_name` | 2 | 100.0 % | 4 | 50.0 % |
| `category` | 2 | 100.0 % | 8 | 25.0 % |
| `course` | 1 | 0.0 % | 3 | 0.0 % |
| `current_address_line1` | 9 | 77.8 % | 15 | 46.7 % |
| `current_address_line2` | 5 | 40.0 % | 3 | 66.7 % |
| `current_city` | 4 | 100.0 % | 7 | 57.1 % |
| `current_country` | 3 | 100.0 % | 4 | 75.0 % |
| `current_district` | 5 | 80.0 % | 6 | 66.7 % |
| `current_pincode` | 5 | 100.0 % | 6 | 83.3 % |
| `current_state` | 5 | 100.0 % | 7 | 71.4 % |
| `date_of_birth` | 7 | 71.4 % | 9 | 55.6 % |
| `date_of_filling` | 38 | 44.7 % | 30 | 56.7 % |
| `email` | 5 | 100.0 % | 5 | 100.0 % |
| `enrollment_number` | 5 | 60.0 % | 11 | 27.3 % |
| `father_name` | 5 | 60.0 % | 8 | 37.5 % |
| `first_name` | 2 | 0.0 % | 2 | 0.0 % |
| `full_name` | 21 | 47.6 % | 26 | 38.5 % |
| `gender` | 1 | 100.0 % | 1 | 100.0 % |
| `guardian_name` | 3 | 33.3 % | 2 | 50.0 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 33.3 % | 1 | 100.0 % |
| `last_name` | 2 | 0.0 % | 0 | — |
| `marital_status` | 1 | 100.0 % | 2 | 50.0 % |
| `middle_name` | 2 | 0.0 % | 0 | — |
| `mother_name` | 4 | 50.0 % | 4 | 50.0 % |
| `nationality` | 4 | 50.0 % | 3 | 66.7 % |
| `other` | 272 | 64.0 % | 257 | 67.7 % |
| `pan` | 2 | 100.0 % | 2 | 100.0 % |
| `passing_year` | 8 | 0.0 % | 0 | — |
| `percentage_or_cgpa` | 5 | 60.0 % | 9 | 33.3 % |
| `permanent_address_line1` | 1 | 0.0 % | 0 | — |
| `phone_alternate` | 3 | 66.7 % | 4 | 50.0 % |
| `phone_mobile` | 8 | 87.5 % | 10 | 70.0 % |
| `place` | 7 | 71.4 % | 6 | 83.3 % |
| `signature` | 40 | 40.0 % | 18 | 88.9 % |
| `spouse_name` | 1 | 100.0 % | 2 | 50.0 % |
| `unknown` | 11 | 27.3 % | 17 | 17.6 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `signature` | `other` | 21 |
| `date_of_filling` | `other` | 17 |
| `other` | `full_name` | 12 |
| `other` | `date_of_filling` | 12 |
| `full_name` | `other` | 9 |
| `other` | `enrollment_number` | 8 |
| `other` | `unknown` | 7 |
| `other` | `current_address_line1` | 6 |
| `unknown` | `other` | 6 |
| `passing_year` | `other` | 6 |
| `other` | `category` | 6 |
| `other` | `age` | 5 |
| `other` | `father_name` | 4 |
| `other` | `date_of_birth` | 4 |
| `other` | `percentage_or_cgpa` | 4 |

Never-fill marks on compared fields: {'signature': 18, 'office_use': 40}.

LLM batches that failed or needed a retry:
- 01_sbi_account_opening_form: page 3: LLM batch retried
