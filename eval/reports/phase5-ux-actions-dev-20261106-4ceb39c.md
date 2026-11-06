# Actions to complete one form — dev

- Detector `flat@4ceb39c`; provider `groq:openai/gpt-oss-120b` (replay); persona `asha_verma`; policy "LLM confidence >= 0.99, once per form", suggestions from 0.95; created 2026-11-06T10:52:19+00:00; tag `None`
- Actions: one per question card (answered or skipped), one per suggestion confirmed, one per profile value that confirm all leaves to the user, one confirm all, one render-and-download; before, one confirm per value to print instead of confirm all. Inputs: answer boxes typed. Cards are assumed answered by their parts, each answer passing its checks.
- **Before: recomputed from today's pipeline with the M3 features turned off (no suggestions, the M2 question plan, no confirm all), not a historical M2 measurement.**
- Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

| Form | Actions before | Actions after | Cards before / after | Inputs before / after | Confirms one by one (before) | Suggestions (after) | Review | Confirm all (after) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 331 | 65 | 153 / 50 | 159 / 147 | 176 | 12 | 1 / 1 | 1 |
| 02_sbi_kyc_annexure_a | 44 | 14 | 16 / 4 | 16 / 8 | 27 | 8 | 0 / 0 | 1 |
| 03_sbi_kyc_annexure_b | 96 | 17 | 44 / 14 | 44 / 44 | 50 | 0 | 1 / 1 | 1 |
| 06_union_bank_nomination_form | 46 | 9 | 21 / 6 | 23 / 22 | 24 | 1 | 0 / 0 | 1 |
| 21_india_post_pmjjby_claim_form | 92 | 24 | 40 / 21 | 40 / 40 | 50 | 0 | 1 / 1 | 1 |
| 23_lic_claim_form_a_3783 | 92 | 23 | 44 / 20 | 44 / 43 | 47 | 1 | 0 / 0 | 1 |
| 25_cdlsiet_btech_admission_form | 163 | 23 | 65 / 16 | 89 / 84 | 97 | 5 | 0 / 0 | 1 |
| 30_allahabad_univ_enrollment_form | 43 | 16 | 14 / 10 | 24 / 20 | 28 | 4 | 0 / 0 | 1 |
| 32_niftem_student_declaration_form | 25 | 4 | 10 / 2 | 10 / 10 | 14 | 0 | 0 / 0 | 1 |
| 39_cebs_joining_report | 16 | 4 | 7 / 2 | 7 / 7 | 8 | 0 | 0 / 0 | 1 |
| 41_india_post_pli_name_change_form | 1 | 1 | 0 / 0 | 0 / 0 | 0 | 0 | 0 / 0 | 0 |
| **Total** | 949 | 200 | 414 / 145 | 456 / 425 | 521 | 31 | 3 / 3 | 10 |
