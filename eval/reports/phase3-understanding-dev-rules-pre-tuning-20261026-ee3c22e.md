# Understanding eval — dev, mode rules

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@ee3c22e`; provider `none`; prompt `understand_v1.md`; created 2026-10-26T12:37:17+00:00; tag `pre-tuning`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 17.4 % (91/524) | 33.6 % (81/241) |
| From scratch | 25.4 % (16/63) | 50.0 % (15/30) |
| Pre-filled | 16.3 % (75/461) | 31.3 % (66/211) |

Macro over forms (fillable): 35.1 %. Predicted `unknown`: 390. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | 60.4 % (81/134) |
| llm | — (0/0) |
| none | 2.6 % (10/390) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 12.5 % (21/168) | 28.4 % (21/74) |
| 02_sbi_kyc_annexure_a | 42.4 % (14/33) | 50.0 % (12/24) |
| 03_sbi_kyc_annexure_b | 25.6 % (10/39) | 42.9 % (9/21) |
| 06_union_bank_nomination_form | 0.0 % (0/27) | 0.0 % (0/4) |
| 21_india_post_pmjjby_claim_form | 31.9 % (15/47) | 50.0 % (14/28) |
| 23_lic_claim_form_a_3783 | 18.2 % (8/44) | 23.1 % (3/13) |
| 25_cdlsiet_btech_admission_form | 11.3 % (11/97) | 21.3 % (10/47) |
| 30_allahabad_univ_enrollment_form | 6.9 % (2/29) | 14.3 % (2/14) |
| 32_niftem_student_declaration_form | 50.0 % (8/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 12.5 % (1/8) | 33.3 % (1/3) |
| 41_india_post_pli_name_change_form | 6.2 % (1/16) | 50.0 % (1/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 60.0 % | 3 | 100.0 % |
| `age` | 1 | 100.0 % | 3 | 33.3 % |
| `bank_account_number` | 11 | 90.9 % | 11 | 90.9 % |
| `bank_branch` | 3 | 66.7 % | 4 | 50.0 % |
| `bank_name` | 2 | 100.0 % | 3 | 66.7 % |
| `category` | 2 | 50.0 % | 2 | 50.0 % |
| `course` | 1 | 0.0 % | 0 | — |
| `current_address_line1` | 9 | 22.2 % | 2 | 100.0 % |
| `current_address_line2` | 5 | 0.0 % | 0 | — |
| `current_city` | 4 | 0.0 % | 0 | — |
| `current_country` | 3 | 0.0 % | 0 | — |
| `current_district` | 5 | 20.0 % | 1 | 100.0 % |
| `current_pincode` | 5 | 40.0 % | 2 | 100.0 % |
| `current_state` | 5 | 40.0 % | 2 | 100.0 % |
| `date_of_birth` | 7 | 71.4 % | 7 | 71.4 % |
| `date_of_filling` | 38 | 34.2 % | 22 | 59.1 % |
| `email` | 5 | 80.0 % | 4 | 100.0 % |
| `enrollment_number` | 5 | 60.0 % | 6 | 50.0 % |
| `father_name` | 5 | 0.0 % | 1 | 0.0 % |
| `first_name` | 2 | 0.0 % | 0 | — |
| `full_name` | 21 | 33.3 % | 23 | 30.4 % |
| `gender` | 1 | 0.0 % | 0 | — |
| `guardian_name` | 3 | 33.3 % | 4 | 25.0 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 0.0 % | 0 | — |
| `last_name` | 2 | 0.0 % | 0 | — |
| `marital_status` | 1 | 0.0 % | 0 | — |
| `middle_name` | 2 | 0.0 % | 0 | — |
| `mother_name` | 4 | 0.0 % | 2 | 0.0 % |
| `nationality` | 4 | 0.0 % | 1 | 0.0 % |
| `other` | 272 | 0.0 % | 0 | — |
| `pan` | 2 | 100.0 % | 2 | 100.0 % |
| `passing_year` | 8 | 0.0 % | 0 | — |
| `percentage_or_cgpa` | 5 | 20.0 % | 3 | 33.3 % |
| `permanent_address_line1` | 1 | 0.0 % | 0 | — |
| `phone_alternate` | 3 | 33.3 % | 2 | 50.0 % |
| `phone_mobile` | 8 | 62.5 % | 9 | 55.6 % |
| `place` | 7 | 71.4 % | 6 | 83.3 % |
| `signature` | 40 | 12.5 % | 5 | 100.0 % |
| `spouse_name` | 1 | 100.0 % | 1 | 100.0 % |
| `unknown` | 11 | 90.9 % | 390 | 2.6 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `other` | `unknown` | 228 |
| `signature` | `unknown` | 35 |
| `date_of_filling` | `unknown` | 25 |
| `other` | `full_name` | 14 |
| `full_name` | `unknown` | 14 |
| `other` | `date_of_filling` | 8 |
| `current_address_line1` | `unknown` | 7 |
| `passing_year` | `unknown` | 6 |
| `father_name` | `unknown` | 5 |
| `nationality` | `unknown` | 4 |
| `current_address_line2` | `unknown` | 4 |
| `current_city` | `unknown` | 4 |
| `current_district` | `unknown` | 4 |
| `mother_name` | `unknown` | 4 |
| `percentage_or_cgpa` | `unknown` | 4 |

Never-fill marks on compared fields: {'signature': 5, 'office_use': 40}.
