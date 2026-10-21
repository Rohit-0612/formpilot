# Detection eval — dev split — pre-step11-tuning-v4

- Detector: `flat@0ee9999`; run at 2026-10-21T14:21:37+00:00.
- **Primary metric: writing-spot match** — same page, x-interval IoU ≥ 0.5, vertical centres at most 0.5 times the taller box's height apart; box height is not scored (docs/decisions/phase-2.md). Precision, recall, TP, FP, FN and the by-kind table use it.
- Secondary metric: IoU ≥ 0.5 on the same page (SPEC §10), in the last two columns. IoU ≥ 0.3 is in the JSON as a diagnostic. Matching is one-to-one and greedy under each rule.
- Scored: labelled pages whose text layer is OK and that are in the labelling subset (eval/labelling/subset.py): 01_sbi_account_opening_form pages 1, 4; 02_sbi_kyc_annexure_a all pages; 03_sbi_kyc_annexure_b page 2; 06_union_bank_nomination_form all pages; 21_india_post_pmjjby_claim_form all pages; 23_lic_claim_form_a_3783 all pages; 25_cdlsiet_btech_admission_form all pages; 30_allahabad_univ_enrollment_form all pages; 32_niftem_student_declaration_form all pages; 39_cebs_joining_report all pages; 41_india_post_pli_name_change_form all pages.
- All numbers below are measured by this run.

## Overall

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| all scored pages | 86.8 % | 77.5 % | 482 | 73 | 140 | 83.4 % | 74.4 % |

## Macro average

Mean of the per-form precision and recall, every form weighted equally (the table above pools all boxes, so large forms dominate it). A form without predicted boxes is left out of the precision mean, one without labelled boxes out of the recall mean; n = forms in each mean.

| | Precision | Recall | n (P / R) | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|
| all forms | 88.3 % | 77.0 % | 11 / 11 | 82.4 % | 73.0 % |
| from scratch | 74.6 % | 56.6 % | 2 / 2 | 44.6 % | 36.7 % |
| pre-filled | 91.4 % | 81.5 % | 9 / 9 | 90.8 % | 81.1 % |

## By kind (writing spot)

| Kind | Recall (labelled boxes found) | Precision (predicted boxes correct) |
|---|--:|--:|
| text | 78.5 % (317/404) | 84.5 % (317/375) |
| comb | 57.4 % (58/101) | 82.9 % (58/70) |
| checkbox | 91.5 % (107/117) | 97.3 % (107/110) |

Matched pairs, predicted kind → labelled kind: checkbox->checkbox: 107, comb->comb: 58, text->text: 317

## Anchoring check

Forms labelled from scratch (no pre-filled boxes) against pre-filled forms. If the detector scores clearly better on the pre-filled forms, pre-annotation may be biasing the labels.

| | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| from scratch | 77.1 % | 55.2 % | 37 | 11 | 30 | 43.8 % | 31.3 % |
| pre-filled | 87.8 % | 80.2 % | 445 | 62 | 110 | 87.2 % | 79.6 % |

## Per form

| Form | Precision | Recall | TP | FP | FN | Precision (IoU ≥ 0.5) | Recall (IoU ≥ 0.5) |
|---|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 91.0 % | 77.2 % | 152 | 15 | 45 | 91.0 % | 77.2 % |
| 02_sbi_kyc_annexure_a | 73.8 % | 75.6 % | 31 | 11 | 10 | 73.8 % | 75.6 % |
| 03_sbi_kyc_annexure_b | 81.4 % | 86.4 % | 57 | 13 | 9 | 81.4 % | 86.4 % |
| 06_union_bank_nomination_form | 100.0 % | 96.4 % | 27 | 0 | 1 | 100.0 % | 96.4 % |
| 21_india_post_pmjjby_claim_form (from scratch) | 89.3 % | 53.2 % | 25 | 3 | 22 | 39.3 % | 23.4 % |
| 23_lic_claim_form_a_3783 | 93.6 % | 68.8 % | 44 | 3 | 20 | 89.4 % | 65.6 % |
| 25_cdlsiet_btech_admission_form | 82.6 % | 92.2 % | 95 | 20 | 8 | 81.7 % | 91.3 % |
| 30_allahabad_univ_enrollment_form | 100.0 % | 48.4 % | 15 | 0 | 16 | 100.0 % | 48.4 % |
| 32_niftem_student_declaration_form | 100.0 % | 100.0 % | 16 | 0 | 0 | 100.0 % | 100.0 % |
| 39_cebs_joining_report | 100.0 % | 88.9 % | 8 | 0 | 1 | 100.0 % | 88.9 % |
| 41_india_post_pli_name_change_form (from scratch) | 60.0 % | 60.0 % | 12 | 8 | 8 | 50.0 % | 50.0 % |

## Not scored

- 01_sbi_account_opening_form: labelled pages 2, 3, 5, 6, 7, 8, 9 are outside the labelling subset (not scored)
- 03_sbi_kyc_annexure_b: labelled pages 1 are outside the labelling subset (not scored)
- 37_aees_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 38_vnsgu_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 42_allahabad_univ_diploma_admission_form: no page with a usable text layer (needs OCR, Phase 6)

## Dataset notes

Known gaps in the test split (docs/reality_check.md, human decision 2026-10-11): the test split has no Hindi-only form, and no bilingual form with a clean Unicode Hindi text layer. Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer to test later; dev stays unchanged. This report uses the dev split only.
