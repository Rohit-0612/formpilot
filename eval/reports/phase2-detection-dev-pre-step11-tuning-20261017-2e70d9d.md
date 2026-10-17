# Detection eval — dev split — pre-step11-tuning

- Detector: `flat@2e70d9d`; run at 2026-10-17T19:53:27+00:00.
- Match: one-to-one, greedy by IoU, IoU ≥ 0.5 on the same page (SPEC §10); IoU ≥ 0.3 shown as a diagnostic.
- Scored: labelled pages whose text layer is OK and that are in the labelling subset (eval/labelling/subset.py): 01_sbi_account_opening_form pages 1, 4; 02_sbi_kyc_annexure_a all pages; 03_sbi_kyc_annexure_b page 2; 06_union_bank_nomination_form all pages; 21_india_post_pmjjby_claim_form all pages; 23_lic_claim_form_a_3783 all pages; 25_cdlsiet_btech_admission_form all pages; 30_allahabad_univ_enrollment_form all pages; 32_niftem_student_declaration_form all pages; 39_cebs_joining_report all pages; 41_india_post_pli_name_change_form all pages.
- All numbers below are measured by this run.

## Overall

| | Precision | Recall | TP | FP | FN | Precision @ 0.3 | Recall @ 0.3 |
|---|--:|--:|--:|--:|--:|--:|--:|
| all scored pages | 87.7 % | 77.2 % | 487 | 68 | 144 | 92.1 % | 81.0 % |

## By kind

| Kind | Recall (labelled boxes found) | Precision (predicted boxes correct) |
|---|--:|--:|
| text | 76.6 % (320/418) | 85.3 % (320/375) |
| comb | 62.5 % (60/96) | 85.7 % (60/70) |
| checkbox | 91.5 % (107/117) | 97.3 % (107/110) |

Matched pairs, predicted kind → labelled kind: checkbox->checkbox: 107, comb->comb: 60, text->text: 320

## Anchoring check

Forms labelled from scratch (no pre-filled boxes) against pre-filled forms. If the detector scores clearly better on the pre-filled forms, pre-annotation may be biasing the labels.

| | Precision | Recall | TP | FP | FN | Precision @ 0.3 | Recall @ 0.3 |
|---|--:|--:|--:|--:|--:|--:|--:|
| from scratch | 43.8 % | 32.3 % | 21 | 27 | 44 | 75.0 % | 55.4 % |
| pre-filled | 91.9 % | 82.3 % | 466 | 41 | 100 | 93.7 % | 83.9 % |

## Per form

| Form | Precision | Recall | TP | FP | FN | Precision @ 0.3 | Recall @ 0.3 |
|---|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 92.2 % | 81.9 % | 154 | 13 | 34 | 95.8 % | 85.1 % |
| 02_sbi_kyc_annexure_a | 100.0 % | 82.4 % | 42 | 0 | 9 | 100.0 % | 82.4 % |
| 03_sbi_kyc_annexure_b | 97.1 % | 89.5 % | 68 | 2 | 8 | 97.1 % | 89.5 % |
| 06_union_bank_nomination_form | 100.0 % | 96.4 % | 27 | 0 | 1 | 100.0 % | 96.4 % |
| 21_india_post_pmjjby_claim_form (from scratch) | 39.3 % | 24.4 % | 11 | 17 | 34 | 85.7 % | 53.3 % |
| 23_lic_claim_form_a_3783 | 89.4 % | 65.6 % | 42 | 5 | 22 | 93.6 % | 68.8 % |
| 25_cdlsiet_btech_admission_form | 81.7 % | 91.3 % | 94 | 21 | 9 | 82.6 % | 92.2 % |
| 30_allahabad_univ_enrollment_form | 100.0 % | 48.4 % | 15 | 0 | 16 | 100.0 % | 48.4 % |
| 32_niftem_student_declaration_form | 100.0 % | 100.0 % | 16 | 0 | 0 | 100.0 % | 100.0 % |
| 39_cebs_joining_report | 100.0 % | 88.9 % | 8 | 0 | 1 | 100.0 % | 88.9 % |
| 41_india_post_pli_name_change_form (from scratch) | 50.0 % | 50.0 % | 10 | 10 | 10 | 60.0 % | 60.0 % |

## Not scored

- 01_sbi_account_opening_form: labelled pages 2, 3, 5, 6, 7, 8, 9 are outside the labelling subset (not scored)
- 03_sbi_kyc_annexure_b: labelled pages 1 are outside the labelling subset (not scored)
- 37_aees_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 38_vnsgu_joining_report: no page with a usable text layer (needs OCR, Phase 6)
- 42_allahabad_univ_diploma_admission_form: no page with a usable text layer (needs OCR, Phase 6)

## Dataset notes

Known gaps in the test split (docs/reality_check.md, human decision 2026-10-11): the test split has no Hindi-only form, and no bilingual form with a clean Unicode Hindi text layer. Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer to test later; dev stays unchanged. This report uses the dev split only.
