# Phase 0 — Reality check

Blank forms downloaded for evaluation, classified by `scripts/classify_forms.py` (PyMuPDF
1.28.2) on 2026-09-29. Sources and numbering: `eval/incoming/sources.md`. The PDFs themselves
are in `eval/dataset/dev/` and `eval/dataset/test/` locally (moved there from `eval/incoming/`
on 2026-10-11, see Split) and are never committed.

Type rules (from the script): **fillable** = at least one form widget; **flat** = no widgets and
on average at least 50 extracted text characters per page; **scanned** = otherwise. Notes are the
script's flags; the garbled-text flag is a heuristic for a human to confirm.

Language (form metadata, not an eval label; added 2026-10-11): **English** = the form's labels
and instructions are in English only (a Hindi letterhead alone does not count); **Bilingual** =
labels or instructions in both Hindi and English; **Hindi** = Hindi only. Read from the text layer
where it is clean, and from rendered pages for every page of every form, including the scanned
(#38, #40, #42) and legacy-font (#5, #37) ones. "(check)" marks the uncertain ones for a human.

Regenerate the measurements with:

```bash
uv run --project backend python scripts/classify_forms.py eval/dataset/dev
uv run --project backend python scripts/classify_forms.py eval/dataset/test
```

## Forms

| # | Name | Family | Source URL | Pages | Type | Language | Notes |
|--:|---|---|---|--:|---|---|---|
| 1 | Account Opening Form for Resident Individuals (Part-I) | Bank / KYC | <https://sbi.co.in/documents/16012/1557541/121120-Account%20Opening%20Form%20for%20Individuals.pdf/dcda1685-52a5-3eb3-5b14-9ece820b188a?t=1605181536320&utm_source=chatgpt.com> | 9 | flat | English |  |
| 2 | KYC Annexure A – Self Declaration for KYC Updation | Bank / KYC | <https://sbi.bank.in/documents/16012/0/KYC%2BAnnexure%2BA%2B%282%29.pdf/2b1959f1-e839-66c5-beac-711fe6d8b553?t=1752933016548> | 1 | flat | English |  |
| 3 | KYC Annexure B – KYC Updation Form | Bank / KYC | <https://sbi.bank.in/documents/16012/0/KYC%2BAnnexure%2BB%2B%282%29.pdf/768facc2-cc61-245d-834b-b8cfdbc45757?t=1752933035205> | 2 | flat | English |  |
| 4 | Form DA 1 – Nomination | Bank / KYC | <https://sbi.co.in/documents/16012/12924450/26082021_Nomination%2BForm%2BDA1.pdf/5c942ab6-e4e9-fb08-f115-4bebf5727c53?t=1629974391761&utm_source=chatgpt.com> | 1 | flat | English |  |
| 5 | Account Opening Form – Residential Individual | Bank / KYC | <https://www.unionbankofindia.co.in/pdf/A4AccountopeningformResidentialIndividual.pdf?utm_source=chatgpt.com> | 2 | flat | Bilingual | garbled text, possible legacy Hindi font: 124 words with punctuation inside (Kruti Dev-style) |
| 6 | Nomination Form | Bank / KYC | <https://www.unionbankofindia.co.in/pdf/Nomination%20Form-%20website.pdf?utm_source=chatgpt.com> | 2 | flat | English |  |
| 21 | PMJJBY Claim Form | Post Office / Insurance | <https://www.indiapost.gov.in/documents/offerings/schemesandservices/pmsby/PMJJBYClaimFormandSOPforclaimsettlment.pdf?utm_source=chatgpt.com> | 2 | flat | English |  |
| 22 | PMSBY Claim Form | Post Office / Insurance | <https://www.indiapost.gov.in/insurance-services/pmsby> | 2 | flat | English |  |
| 23 | Claim Form A – Form 3783 | Post Office / Insurance | <https://licindia.in/documents/d/guest/3783?utm_source=chatgpt.com> | 3 | flat | English |  |
| 25 | B.Tech Admission Form 2026–27 | College / Education | <https://cdlsiet.ac.in/admission-advertisement/?utm_source=chatgpt.com> | 4 | flat | English |  |
| 28 | Application for Issue of Bonafide Certificate – Foreign Students | College / Education | <https://cse.manit.ac.in/sites/default/files/FORMAT%20OF%20APPLICATION%20BONA-FIDE%20CERTIFICATE%20FOREIGN%20STUDENTS.pdf?utm_source=chatgpt.com> | 2 | flat | English |  |
| 30 | Enrollment Form | College / Education | <https://www.allduniv.ac.in/student/download-forms?utm_source=chatgpt.com> | 1 | flat | Bilingual (check) |  |
| 31 | Merit-cum-Means Scholarship Form – 1st Installment | College / Education | <https://iiita.ac.in/scholarships-financial-aid?utm_source=chatgpt.com> | 2 | flat | English (check) |  |
| 32 | Student Declaration Form 2026 | College / Education | <https://niftem.ac.in/admission?utm_source=chatgpt.com> | 1 | flat | English |  |
| 37 | Joining Report | Job / Onboarding | <https://www.aees.gov.in/downloads.html?utm_source=chatgpt.com> | 1 | flat | Bilingual | garbled text, possible legacy Hindi font: 354 Latin-extended letters mixed into the text |
| 38 | Joining Report for New Recruitment | Job / Onboarding | <https://vnsgu.ac.in/form_for_employees?utm_source=chatgpt.com> | 1 | scanned | English | no text layer on 1/1 pages |
| 39 | Joining Report Form | Job / Onboarding | <https://www.cbs.ac.in/administration/download-forms?utm_source=chatgpt.com> | 1 | flat | English |  |
| 40 | Joining Report | Job / Onboarding | <https://iasst.gov.in/forms-downloads/?utm_source=chatgpt.com> | 1 | scanned | Bilingual | no text layer on 1/1 pages |
| 41 | Postal Life Insurance – Name Change Form | Post Office / Insurance | not recorded | 1 | flat | English |  |
| 42 | Diploma Course Admission Application Form | College / Education | not recorded | 2 | scanned | Hindi | no text layer on 2/2 pages |

## Counts per type

| Type | Forms |
|---|--:|
| fillable | 0 |
| flat | 17 |
| scanned | 3 |
| **total** | **20** |

By family:

| Family | fillable | flat | scanned | total |
|---|--:|--:|--:|--:|
| Bank / KYC | 0 | 6 | 0 | 6 |
| College / Education | 0 | 5 | 1 | 6 |
| Job / Onboarding | 0 | 2 | 2 | 4 |
| Post Office / Insurance | 0 | 4 | 0 | 4 |

By language:

| Language | Forms |
|---|--:|
| English | 15 (incl. #31, check) |
| Bilingual | 4 (incl. #30, check) |
| Hindi | 1 |

## MVP form families (pick 2-3)

MVP form families: Bank / KYC, College / Education

## Split

- Dev (14): #1, #2, #3, #6, #25, #30, #32, #42, #21, #23, #41, #37, #38, #39
- Test (6): #4, #5, #28, #31, #22, #40
- Checks: every family appears in both dev and test; scanned forms in both (dev #38, #42; test
  #40); legacy Hindi font forms in both (dev #37; test #5); MVP tuning focus is Bank / KYC and
  College / Education, and all four families stay in the eval.
- Moved on 2026-10-11 from `eval/incoming/` into `eval/dataset/dev/` and `eval/dataset/test/` as
  listed above. Form #1 was copied in from the original download first. All 20 files match the
  originals in the human's local download folder by SHA-256; the originals are kept unchanged.

## Observations

- Legacy non-Unicode Hindi fonts in #5 and #37: the text layer exists but extracts as garbage.
- #6 is a securities nomination form, not a deposit-account one.
- #1 (SBI) contains 122 odd Latin-extended letters (0.4% of its letters, e.g. "Tel. (Oģ)"),
  below the script's garbled-text threshold; probably a few mis-mapped glyphs.
- #31 (IIIT Allahabad) has a few mis-mapped characters in its Hindi heading (4 Latin-extended
  letters mixed into the Devanagari), below the script's threshold.
- #30 (Allahabad enrollment) uses real Unicode Devanagari, but some vowel signs extract wrong
  (e.g. "वकए" where the form means "किए"); the script's heuristic cannot detect this.
- Language (check): #30 is mostly Hindi; most field labels carry an English translation, but
  field 1, field 12, the education rows and the instructions are Hindi only. #31 is English
  except for the institute's name in Hindi in the letterhead.
- Forms that ask for a value *in Hindi* while the form itself is English: #25 (student's and
  parents' names in Hindi) and #32 (names in English and Hindi).
- Known gaps in the test split (human decision 2026-10-11: keep the split as it is):
  1. Test has no Hindi-only form (the only one, #42, is in dev).
  2. Test has no bilingual form with a clean Unicode Hindi text layer (#5 uses a legacy font,
     #40 is scanned).
  Planned follow-up: add one Hindi-only form and one bilingual form with a clean text layer to
  test later; dev stays unchanged. Every Phase 2 eval report must mention these two gaps.
