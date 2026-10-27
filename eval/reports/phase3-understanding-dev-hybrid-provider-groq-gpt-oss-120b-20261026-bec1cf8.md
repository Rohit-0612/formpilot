# Understanding eval — dev, mode hybrid

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.**

- Detector `flat@bec1cf8`; provider `groq:openai/gpt-oss-120b`; prompt `understand_v2.md`; created 2026-10-26T20:24:54+00:00; tag `provider-groq-gpt-oss-120b`
- Compared: the detected fields matched to a labelled text or comb box (writing-spot rule) that has a reference type. *Fillable*: reference type neither `other` nor `unknown`.

| Scope | Accuracy, all | Accuracy, fillable |
|---|---|---|
| All forms | 70.4 % (369/524) | 62.7 % (151/241) |
| From scratch | 63.5 % (40/63) | 46.7 % (14/30) |
| Pre-filled | 71.4 % (329/461) | 64.9 % (137/211) |

Precision of predicted fillable types: 67.7 % (151/223).

Macro over forms (fillable): 64.6 %. Predicted `unknown`: 28. Reference fields not found by the detector: 43.

## By method

| Method | Accuracy |
|---|---|
| rule | 76.5 % (65/85) |
| llm | 69.2 % (304/439) |
| none | — (0/0) |

## Per form

| Form | All | Fillable |
|---|---|---|
| 01_sbi_account_opening_form | 65.5 % (110/168) | 58.1 % (43/74) |
| 02_sbi_kyc_annexure_a | 93.9 % (31/33) | 95.8 % (23/24) |
| 03_sbi_kyc_annexure_b | 79.5 % (31/39) | 71.4 % (15/21) |
| 06_union_bank_nomination_form | 100.0 % (27/27) | 100.0 % (4/4) |
| 21_india_post_pmjjby_claim_form | 57.4 % (27/47) | 46.4 % (13/28) |
| 23_lic_claim_form_a_3783 | 81.8 % (36/44) | 76.9 % (10/13) |
| 25_cdlsiet_btech_admission_form | 60.8 % (59/97) | 55.3 % (26/47) |
| 30_allahabad_univ_enrollment_form | 58.6 % (17/29) | 50.0 % (7/14) |
| 32_niftem_student_declaration_form | 75.0 % (12/16) | 72.7 % (8/11) |
| 39_cebs_joining_report | 75.0 % (6/8) | 33.3 % (1/3) |
| 41_india_post_pli_name_change_form | 81.2 % (13/16) | 50.0 % (1/2) |

## Per reference type

| Type | Support | Recall | Predicted | Precision |
|---|--:|--:|--:|--:|
| `aadhaar` | 5 | 60.0 % | 4 | 75.0 % |
| `age` | 1 | 100.0 % | 3 | 33.3 % |
| `bank_account_number` | 11 | 72.7 % | 10 | 80.0 % |
| `bank_branch` | 3 | 66.7 % | 4 | 50.0 % |
| `bank_name` | 2 | 50.0 % | 4 | 25.0 % |
| `category` | 2 | 100.0 % | 6 | 33.3 % |
| `course` | 1 | 0.0 % | 1 | 0.0 % |
| `current_address_line1` | 9 | 66.7 % | 10 | 60.0 % |
| `current_address_line2` | 5 | 40.0 % | 5 | 40.0 % |
| `current_city` | 4 | 75.0 % | 5 | 60.0 % |
| `current_country` | 3 | 66.7 % | 3 | 66.7 % |
| `current_district` | 5 | 60.0 % | 4 | 75.0 % |
| `current_pincode` | 5 | 80.0 % | 5 | 80.0 % |
| `current_state` | 5 | 80.0 % | 5 | 80.0 % |
| `date_of_birth` | 7 | 71.4 % | 5 | 100.0 % |
| `date_of_filling` | 38 | 76.3 % | 33 | 87.9 % |
| `email` | 5 | 100.0 % | 6 | 83.3 % |
| `enrollment_number` | 5 | 60.0 % | 8 | 37.5 % |
| `father_name` | 5 | 60.0 % | 3 | 100.0 % |
| `first_name` | 2 | 0.0 % | 0 | — |
| `full_name` | 21 | 81.0 % | 28 | 60.7 % |
| `gender` | 1 | 100.0 % | 2 | 50.0 % |
| `guardian_name` | 3 | 33.3 % | 1 | 100.0 % |
| `ifsc` | 2 | 100.0 % | 2 | 100.0 % |
| `institution_name` | 3 | 33.3 % | 2 | 50.0 % |
| `last_name` | 2 | 0.0 % | 1 | 0.0 % |
| `marital_status` | 1 | 100.0 % | 1 | 100.0 % |
| `middle_name` | 2 | 0.0 % | 0 | — |
| `mother_name` | 4 | 50.0 % | 2 | 100.0 % |
| `nationality` | 4 | 100.0 % | 4 | 100.0 % |
| `other` | 272 | 79.4 % | 273 | 79.1 % |
| `pan` | 2 | 100.0 % | 2 | 100.0 % |
| `passing_year` | 8 | 12.5 % | 9 | 11.1 % |
| `percentage_or_cgpa` | 5 | 40.0 % | 4 | 50.0 % |
| `permanent_address_line1` | 1 | 0.0 % | 1 | 0.0 % |
| `phone_alternate` | 3 | 66.7 % | 3 | 66.7 % |
| `phone_mobile` | 8 | 75.0 % | 8 | 75.0 % |
| `place` | 7 | 85.7 % | 7 | 85.7 % |
| `signature` | 40 | 40.0 % | 17 | 94.1 % |
| `spouse_name` | 1 | 100.0 % | 1 | 100.0 % |
| `unknown` | 11 | 18.2 % | 28 | 7.1 % |

## Most frequent confusions

| Reference | Predicted | Count |
|---|---|--:|
| `signature` | `other` | 14 |
| `other` | `full_name` | 9 |
| `signature` | `unknown` | 9 |
| `unknown` | `other` | 7 |
| `date_of_filling` | `unknown` | 6 |
| `other` | `unknown` | 6 |
| `other` | `passing_year` | 6 |
| `other` | `enrollment_number` | 5 |
| `full_name` | `other` | 4 |
| `other` | `category` | 4 |
| `passing_year` | `other` | 4 |
| `bank_account_number` | `other` | 3 |
| `other` | `current_address_line2` | 3 |
| `current_address_line1` | `other` | 3 |
| `date_of_filling` | `other` | 3 |

Never-fill marks on compared fields: {'signature': 17, 'office_use': 40}.
