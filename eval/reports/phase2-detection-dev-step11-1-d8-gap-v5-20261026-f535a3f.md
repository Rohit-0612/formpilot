# Detection eval — dev split — step11-1-d8-gap-v5

- Detector: `flat@f535a3f`; run at 2026-10-26T07:12:11+00:00.
- **Primary metric: writing-spot match** — same page, x-interval IoU ≥ 0.5, vertical centres at most 0.5 times the taller box's height apart; box height is not scored (docs/decisions/phase-2.md). Precision, recall, TP, FP, FN and the by-kind table use it.
- Secondary metric: IoU ≥ 0.5 on the same page (SPEC §10), in the last two columns. IoU ≥ 0.3 is in the JSON as a diagnostic. Matching is one-to-one and greedy under each rule.
- Scored: labelled pages whose text layer is OK and that are in the labelling subset (eval/labelling/subset.py): 01_sbi_account_opening_form pages 1, 4, 5, 8, 9; 02_sbi_kyc_annexure_a all pages; 03_sbi_kyc_annexure_b page 2; 06_union_bank_nomination_form all pages; 21_india_post_pmjjby_claim_form all pages; 23_lic_claim_form_a_3783 all pages; 25_cdlsiet_btech_admission_form all pages; 30_allahabad_univ_enrollment_form all pages; 32_niftem_student_declaration_form all pages; 39_cebs_joining_report all pages; 41_india_post_pli_name_change_form all pages.
- All numbers below are measured by this run.

## Overall

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| all scored pages | 85.7 % | 77.5 % | 541 | 90 | 157 | 82.7 % | 74.8 % |

## Macro average

Mean of the per-form precision and recall, every form weighted equally (the table above pools all boxes, so large forms dominate it). A form without predicted boxes is left out of the precision mean, one without labelled boxes out of the recall mean; n = forms in each mean.

| | Precision | Recall | n (P / R) | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|
| all forms | 87.9 % | 76.9 % | 11 / 11 | 81.9 % | 73.0 % |
| from scratch | 74.6 % | 56.0 % | 2 / 2 | 44.6 % | 36.5 % |
| pre-filled | 90.8 % | 81.6 % | 9 / 9 | 90.2 % | 81.1 % |

## By kind (writing spot)

| Kind | Recall (labelled boxes found) | Precision (predicted boxes correct) |
|---|--:|--:|
| text | 77.6 % (329/424) | 83.1 % (329/396) |
| comb | 63.6 % (91/143) | 85.8 % (91/106) |
| checkbox | 92.4 % (121/131) | 93.8 % (121/129) |

Matched pairs, predicted kind → labelled kind: checkbox->checkbox: 121, comb->comb: 91, text->text: 329

## Anchoring check

Forms labelled from scratch (no pre-filled boxes) against pre-filled forms. If the detector scores clearly better on the pre-filled forms, pre-annotation may be biasing the labels.

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| from scratch | 77.1 % | 54.4 % | 37 | 11 | 31 | 43.8 % | 30.9 % |
| pre-filled | 86.4 % | 80.0 % | 504 | 79 | 126 | 85.9 % | 79.5 % |

## Per form

| Form | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 87.2 % | 77.7 % | 212 | 31 | 61 | 87.2 % | 77.7 % |
| 02_sbi_kyc_annexure_a | 73.8 % | 75.6 % | 31 | 11 | 10 | 73.8 % | 75.6 % |
| 03_sbi_kyc_annexure_b | 80.0 % | 86.2 % | 56 | 14 | 9 | 80.0 % | 86.2 % |
| 06_union_bank_nomination_form | 100.0 % | 96.4 % | 27 | 0 | 1 | 100.0 % | 96.4 % |
| 21_india_post_pmjjby_claim_form (from scratch) | 89.3 % | 52.1 % | 25 | 3 | 23 | 39.3 % | 22.9 % |
| 23_lic_claim_form_a_3783 | 93.6 % | 68.8 % | 44 | 3 | 20 | 89.4 % | 65.6 % |
| 25_cdlsiet_btech_admission_form | 82.6 % | 92.2 % | 95 | 20 | 8 | 81.7 % | 91.3 % |
| 30_allahabad_univ_enrollment_form | 100.0 % | 48.4 % | 15 | 0 | 16 | 100.0 % | 48.4 % |
| 32_niftem_student_declaration_form | 100.0 % | 100.0 % | 16 | 0 | 0 | 100.0 % | 100.0 % |
| 39_cebs_joining_report | 100.0 % | 88.9 % | 8 | 0 | 1 | 100.0 % | 88.9 % |
| 41_india_post_pli_name_change_form (from scratch) | 60.0 % | 60.0 % | 12 | 8 | 8 | 50.0 % | 50.0 % |

## Not scored

- 01_sbi_account_opening_form: labelled pages 2, 3, 6, 7 are outside the labelling subset (not scored)
- 03_sbi_kyc_annexure_b: labelled pages 1 are outside the labelling subset (not scored)
- 37_aees_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 38_vnsgu_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 42_allahabad_univ_diploma_admission_form: no page with a usable text layer (needs OCR, Phase 6)

## Dataset notes

Known gaps in the test split (docs/reality_check.md, human decision 2026-10-11): the test split has no Hindi-only form, and no bilingual form with a clean Unicode Hindi text layer. Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer to test later; dev stays unchanged. This report uses the dev split only.
