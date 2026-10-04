# Phase 0 — Reality check: decision record

> Decision taken by the human on 2026-10-04: **v1 is re-scoped from fillable PDFs to flat
> (text-layer) PDFs.** Gate 0 is not ticked yet; MVP families and the dev/test split are still
> open (`docs/reality_check.md`).

## What was measured

20 real blank forms were downloaded (PLAN target: 30) and classified by
`scripts/classify_forms.py` (PyMuPDF 1.28.2):

- **fillable** = at least one form widget; **flat** = no widgets and on average at least
  50 extracted text characters per page; **scanned** = otherwise.

| Type | Forms |
|---|--:|
| fillable | 0 |
| flat | 17 |
| scanned | 3 (#38, #40, #42) |
| total | 20 |

| Family | fillable | flat | scanned | total |
|---|--:|--:|--:|--:|
| Bank / KYC | 0 | 6 | 0 | 6 |
| College / Education | 0 | 5 | 1 | 6 |
| Job / Onboarding | 0 | 2 | 2 | 4 |
| Post Office / Insurance | 0 | 4 | 0 | 4 |

The "0 fillable" result was checked two ways: no file has an `/AcroForm` entry, XFA data or any
annotations, and the same script classifies a synthetic fillable PDF (2 widgets) as fillable.

Text-layer quality: 2 of the 17 flat forms (#5, #37) have text layers that extract as garbage
(legacy non-Unicode Hindi fonts); 3 more (#1, #30, #31) show smaller extraction problems.
Details in the Observations section of `docs/reality_check.md`.

## Options considered

1. **Keep the plan and collect fillable forms to fit it.** v1 stays "fillable PDFs end to end".
   - For: the AcroForm path is the easiest (fields, names and boxes come from the PDF); Phases
     2–5 would run as planned.
   - Against: none of the 20 forms in our sample is fillable, so v1 would solve a problem the
     sample does not have. An eval set made of specially collected fillable forms would not
     represent the forms users actually get, and the main work (flat detection) would wait
     until Phase 6.
2. **Re-scope v1 to the data: flat text-layer PDFs**, with the AcroForm path kept as a small
   secondary path tested on synthetic fixtures; scanned PDFs and unusable text layers in v2.
   - For: v1 covers 17 of 20 real forms; detection is measured on real forms from Phase 2.
   - Against: Phase 2 becomes harder (detect entry areas from words, lines and boxes instead of
     reading widgets); a human has to label entry boxes earlier; overlay rendering and box
     editing are needed in v1.

## Why re-scoping was chosen

- The plan's own Phase 0 rule applies: "if most forms are flat/scanned, Phase 6 is the most
  important phase". All 20 forms are flat or scanned, so the flat path is the product.
- v1 should be built and evaluated on the form type the data actually contains, so its metrics
  mean something for real users.
- Scanned forms (3 of 20) and garbled text layers (2 of 17 flat) both need OCR, which is a larger
  separate piece of work, so they stay in v2.
- The AcroForm path stays because it is small with PyMuPDF and keeps `SourceKind.FILLABLE`
  working; without real fillable forms it is tested on synthetic fixtures only.

## Impact on later phases

- **SPEC:** §2 (scope), §6.1 (text-layer quality check; flat is the v1 primary path, AcroForm
  secondary; scanned path also takes OCR-routed pages), §6.9 (overlay is the primary renderer).
- **Phase 2** becomes "Form IR and flat-PDF frontend": `flat.py` is the main frontend, plus the
  text-layer quality check that marks pages as needing OCR, AcroForm as a secondary deliverable,
  flat fixtures, and a detection eval (precision/recall on the dev flat forms). A human labels
  the dev forms' entry boxes before the gate; the labelling tool is chosen at the start of
  Phase 2.
- **Phase 3:** semantic types are added (blind) to the label files whose boxes were labelled in
  Phase 2.
- **Phase 5:** `overlay.py` is the primary renderer and `acroform_fill.py` secondary;
  drag/resize of boxes in the review UI moves here from Phase 6, because detected boxes on flat
  forms will not always be right.
- **Phase 6** becomes "Scanned PDFs and unusable text layers": OCR (Tesseract, `eng` + `hin`),
  reuse of the flat association logic, overlay rendering.
- **Dataset:** 20 forms instead of 30, and only 3 scanned ones, so the v2 scanned evaluation set
  will be small unless more scanned forms are collected.

### Follow-up decisions (human, 2026-10-04)

- **Per-page OCR routing in the Form IR (SPEC §4): decided at the start of Phase 2**, when
  `ir/models.py` is first created. `SourceKind` is per document, but the text-layer check works
  per page. Starting proposal: replace `page_sizes: list[tuple[float, float]]` with a list of
  per-page objects holding `width`, `height` and the text-layer quality (`ok` / `garbled` /
  `none`). As a Form IR change it needs its own decision record and approval.
- **OpenCV for flat pages:** Phase 2 starts with PyMuPDF vector drawings only. The OpenCV raster
  fallback is added in Phase 2 only if the detection eval shows misses caused by boxes drawn as
  images; otherwise it stays in Phase 6. Written into PLAN Phase 2.
- **Placement IoU moves to v1:** SPEC §10 marks it v1, and it is part of the Phase 5 acceptance.
- **Tesseract `hin` is required, not optional:** SPEC §6.1 and §9 now say `eng` + `hin`,
  matching PLAN Phase 6.

## In my own words

