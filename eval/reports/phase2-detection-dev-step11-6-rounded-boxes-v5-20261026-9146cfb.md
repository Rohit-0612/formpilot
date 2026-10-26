# Detection eval — dev split — step11-6-rounded-boxes-v5

- Detector: `flat@9146cfb`; run at 2026-10-26T07:12:25+00:00.
- **Primary metric: writing-spot match** — same page, x-interval IoU ≥ 0.5, vertical centres at most 0.5 times the taller box's height apart; box height is not scored (docs/decisions/phase-2.md). Precision, recall, TP, FP, FN and the by-kind table use it.
- Secondary metric: IoU ≥ 0.5 on the same page (SPEC §10), in the last two columns. IoU ≥ 0.3 is in the JSON as a diagnostic. Matching is one-to-one and greedy under each rule.
- Scored: labelled pages whose text layer is OK and that are in the labelling subset (eval/labelling/subset.py): 01_sbi_account_opening_form pages 1, 4, 5, 8, 9; 02_sbi_kyc_annexure_a all pages; 03_sbi_kyc_annexure_b page 2; 06_union_bank_nomination_form all pages; 21_india_post_pmjjby_claim_form all pages; 23_lic_claim_form_a_3783 all pages; 25_cdlsiet_btech_admission_form all pages; 30_allahabad_univ_enrollment_form all pages; 32_niftem_student_declaration_form all pages; 39_cebs_joining_report all pages; 41_india_post_pli_name_change_form all pages.
- All numbers below are measured by this run.

## Overall

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| all scored pages | 95.1 % | 92.0 % | 642 | 33 | 56 | 88.3 % | 85.4 % |

## Macro average

Mean of the per-form precision and recall, every form weighted equally (the table above pools all boxes, so large forms dominate it). A form without predicted boxes is left out of the precision mean, one without labelled boxes out of the recall mean; n = forms in each mean.

| | Precision | Recall | n (P / R) | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|
| all forms | 96.6 % | 89.8 % | 11 / 11 | 86.0 % | 79.8 % |
| from scratch | 92.0 % | 85.8 % | 2 / 2 | 48.8 % | 44.8 % |
| pre-filled | 97.6 % | 90.7 % | 9 / 9 | 94.2 % | 87.6 % |

## By kind (writing spot)

| Kind | Recall (labelled boxes found) | Precision (predicted boxes correct) |
|---|--:|--:|
| text | 90.3 % (383/424) | 93.4 % (383/410) |
| comb | 96.5 % (138/143) | 95.8 % (138/144) |
| checkbox | 92.4 % (121/131) | 100.0 % (121/121) |

Matched pairs, predicted kind → labelled kind: checkbox->checkbox: 121, comb->comb: 138, text->text: 383

## Anchoring check

Forms labelled from scratch (no pre-filled boxes) against pre-filled forms. If the detector scores clearly better on the pre-filled forms, pre-annotation may be biasing the labels.

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| from scratch | 90.9 % | 88.2 % | 60 | 6 | 8 | 43.9 % | 42.6 % |
| pre-filled | 95.6 % | 92.4 % | 582 | 27 | 48 | 93.1 % | 90.0 % |

## Per form

| Form | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 93.3 % | 97.1 % | 265 | 19 | 8 | 91.5 % | 95.2 % |
| 02_sbi_kyc_annexure_a | 100.0 % | 80.5 % | 33 | 0 | 8 | 97.0 % | 78.0 % |
| 03_sbi_kyc_annexure_b | 95.5 % | 96.9 % | 63 | 3 | 2 | 95.5 % | 96.9 % |
| 06_union_bank_nomination_form | 100.0 % | 96.4 % | 27 | 0 | 1 | 100.0 % | 96.4 % |
| 21_india_post_pmjjby_claim_form (from scratch) | 89.8 % | 91.7 % | 44 | 5 | 4 | 38.8 % | 39.6 % |
| 23_lic_claim_form_a_3783 | 89.8 % | 68.8 % | 44 | 5 | 20 | 85.7 % | 65.6 % |
| 25_cdlsiet_btech_admission_form | 100.0 % | 94.2 % | 97 | 0 | 6 | 99.0 % | 93.2 % |
| 30_allahabad_univ_enrollment_form | 100.0 % | 93.5 % | 29 | 0 | 2 | 79.3 % | 74.2 % |
| 32_niftem_student_declaration_form | 100.0 % | 100.0 % | 16 | 0 | 0 | 100.0 % | 100.0 % |
| 39_cebs_joining_report | 100.0 % | 88.9 % | 8 | 0 | 1 | 100.0 % | 88.9 % |
| 41_india_post_pli_name_change_form (from scratch) | 94.1 % | 80.0 % | 16 | 1 | 4 | 58.8 % | 50.0 % |

## Not scored

- 01_sbi_account_opening_form: labelled pages 2, 3, 6, 7 are outside the labelling subset (not scored)
- 03_sbi_kyc_annexure_b: labelled pages 1 are outside the labelling subset (not scored)
- 37_aees_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 38_vnsgu_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 42_allahabad_univ_diploma_admission_form: no page with a usable text layer (needs OCR, Phase 6)

## Dataset notes

Known gaps in the test split (docs/reality_check.md, human decision 2026-10-11): the test split has no Hindi-only form, and no bilingual form with a clean Unicode Hindi text layer. Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer to test later; dev stays unchanged. This report uses the dev split only.
