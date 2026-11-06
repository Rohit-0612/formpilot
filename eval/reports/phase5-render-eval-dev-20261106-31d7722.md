# Fill correctness and placement, read back from the rendered PDFs — dev

- Detector `flat@31d7722`; provider `groq:openai/gpt-oss-120b` (replay); policy "LLM confidence >= 0.99, once per form" then "confirm all" (P5-D7); created 2026-11-06T10:48:03+00:00; tag `None`
- Printed text is read back from each rendered PDF and judged against the persona as the fill eval judges value precision. *Correct of printed*: right / printed values (a printed field with no compared label counts as not right). *Correct of fillable*: right / compared fields with a fillable reference type.
- Placement is measured against the human-labelled box each printed field was matched to. IoU and containment (share of the field's box inside the label box) are per field; the character shares count printed characters inside the label box.
- Label boxes: human. Reference types: Claude-written (P3-D6). Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

## Totals per persona

| Persona | Printed | Right | Correct of printed | Fillable | Correct of fillable | Match-level right | Printed-text errors | IoU mean / median | IoU ≥ 0.5 | Containment mean / median | Chars inside (centre) | Chars inside (whole) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| asha_verma | 64 | 59 | 92.2 % | 241 | 24.5 % | 59 | 0 | 0.857 / 1.000 | 85.9 % | 0.869 / 1.000 | 92.7 % | 80.4 % |
| meera_iyer | 46 | 43 | 93.5 % | 241 | 17.8 % | 43 | 0 | 0.887 / 1.000 | 87.0 % | 0.891 / 1.000 | 90.0 % | 86.7 % |
| ravi_kumar | 61 | 57 | 93.4 % | 241 | 23.6 % | 57 | 0 | 0.855 / 1.000 | 85.2 % | 0.862 / 1.000 | 92.2 % | 75.7 % |

Most dev label boxes were pre-annotated with the detector's boxes and then checked by the human, so an IoU near 1 there partly says the human kept the detector's box. On the forms labelled from scratch (21_india_post_pmjjby_claim_form, 41_india_post_pli_name_change_form):

| Persona | Printed | IoU mean / median | IoU ≥ 0.5 | Containment mean | Chars inside (centre) | Chars inside (whole) |
|---|--:|--:|--:|--:|--:|--:|
| asha_verma | 10 | 0.441 / 0.473 | 30.0 % | 0.482 | 64.7 % | 0.0 % |
| meera_iyer | 4 | 0.404 / 0.433 | 0.0 % | 0.441 | 25.5 % | 0.0 % |
| ravi_kumar | 10 | 0.441 / 0.473 | 30.0 % | 0.482 | 70.5 % | 0.0 % |

## Per form (asha_verma)

| Form | Printed | Right | Correct of printed | Fillable | Correct of fillable | IoU mean | Containment mean | Chars inside (centre) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 01_sbi_account_opening_form | 16 | 14 | 87.5 % | 74 | 18.9 % | 0.900 | 0.920 | 100.0 % |
| 02_sbi_kyc_annexure_a | 11 | 11 | 100.0 % | 24 | 45.8 % | 1.000 | 1.000 | 100.0 % |
| 03_sbi_kyc_annexure_b | 6 | 6 | 100.0 % | 21 | 28.6 % | 1.000 | 1.000 | 100.0 % |
| 06_union_bank_nomination_form | 1 | 1 | 100.0 % | 4 | 25.0 % | 0.967 | 0.967 | 100.0 % |
| 21_india_post_pmjjby_claim_form | 10 | 9 | 90.0 % | 28 | 32.1 % | 0.441 | 0.482 | 64.7 % |
| 23_lic_claim_form_a_3783 | 3 | 2 | 66.7 % | 13 | 15.4 % | 1.000 | 1.000 | 100.0 % |
| 25_cdlsiet_btech_admission_form | 8 | 8 | 100.0 % | 47 | 17.0 % | 1.000 | 1.000 | 100.0 % |
| 30_allahabad_univ_enrollment_form | 4 | 4 | 100.0 % | 14 | 28.6 % | 0.522 | 0.522 | 90.7 % |
| 32_niftem_student_declaration_form | 4 | 3 | 75.0 % | 11 | 27.3 % | 1.000 | 1.000 | 100.0 % |
| 39_cebs_joining_report | 1 | 1 | 100.0 % | 3 | 33.3 % | 1.000 | 1.000 | 100.0 % |
| 41_india_post_pli_name_change_form | 0 | 0 | — | 2 | 0.0 % | — | — | — |

## Printed-text errors and judgement differences

None: every printed field reads back as the text the renderer was given.
