# Render checks — dev

- Detector `flat@bfacffa`; provider `groq:openai/gpt-oss-120b` (replay); created 2026-11-03T15:04:10+00:00; tag `before`
- Checks (decision P5-D11): *characters* inside their box or comb cell; *dates* printed all or none; *never_fill*: nothing printed in a never-fill field or an office-use area; *ticks* only from the user's own choice. Counts are failures.

| Form | Printed | characters | dates | never_fill | ticks |
|---|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 20 | 0 | 0 | 0 | 0 |
| 02_sbi_kyc_annexure_a | 11 | 0 | 0 | 0 | 0 |
| 03_sbi_kyc_annexure_b | 8 | 0 | 1 | 0 | 1 |
| 06_union_bank_nomination_form | 1 | 0 | 0 | 0 | 0 |
| 21_india_post_pmjjby_claim_form | 10 | 0 | 0 | 0 | 0 |
| 23_lic_claim_form_a_3783 | 3 | 0 | 0 | 0 | 0 |
| 25_cdlsiet_btech_admission_form | 10 | 2 | 0 | 0 | 0 |
| 30_allahabad_univ_enrollment_form | 4 | 0 | 0 | 0 | 0 |
| 32_niftem_student_declaration_form | 4 | 0 | 0 | 0 | 0 |
| 39_cebs_joining_report | 1 | 0 | 0 | 0 | 0 |
| 41_india_post_pli_name_change_form | 2 | 0 | 0 | 2 | 0 |
| **Total** | | **2** | **1** | **2** | **1** |

## Failures

- 03_sbi_kyc_annexure_b, page 2, `p1_f045`: dates: date printed without month, year
- 03_sbi_kyc_annexure_b, page 2, `p1_f000`: ticks: ticked from profile
- 25_cdlsiet_btech_admission_form, page 1, `p0_f019`: characters: a character on a comb cell divider
- 25_cdlsiet_btech_admission_form, page 1, `p0_f019`: characters: a character on a comb cell divider
- 41_india_post_pli_name_change_form, page 1, `p0_f013`: never_fill: below an official-only heading
- 41_india_post_pli_name_change_form, page 1, `p0_f014`: never_fill: below an official-only heading
