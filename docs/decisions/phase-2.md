# Phase 2 — Form IR and flat-PDF frontend: decision record

> Status: **in progress** (started 2026-10-11 on branch `phase-2-flat-frontend`). Decisions are
> recorded here as they are taken; the close-out sections are filled in at the end of the phase.

## Decisions taken when the plan was approved (human, 2026-10-11)

### D1. Form IR: per-page text-layer quality (SPEC §4 change)

**Problem.** `SourceKind` is per document, but the text-layer quality check (SPEC §6.1) works per
page: a flat PDF can have one page in a legacy Hindi font (garbled) or one scanned page. The IR
had no place to say "this page needs OCR".

**Decision.** `FormIR.page_sizes: list[tuple[float, float]]` is replaced by
`FormIR.pages: list[PageInfo]`, where `PageInfo` holds `width`, `height` (points, displayed page)
and `text_layer: TextLayer`:

| `TextLayer` | Meaning | Phase 2 behaviour |
|---|---|---|
| `ok` | usable text layer | flat frontend detects fields |
| `garbled` | text present but extracts as garbage (e.g. legacy non-Unicode Hindi fonts) | no fields; trace event "needs OCR"; OCR in Phase 6 |
| `none` | fewer than 50 non-space characters **and** images cover most of the page area | no fields; trace event "needs OCR"; OCR in Phase 6 |

- **Human change to the proposal:** a page is `none` only when it has little text **and** is
  mostly image. A sparse page with no significant image content (e.g. a signature page) is `ok`
  and is not routed to OCR. A fixture and a test cover this case (Step 3).
- The list position is the page index (same as `BBox.page`); there is no separate `index`
  field, so the two cannot disagree.
- `SourceKind` stays per document: `fillable` if any widget exists; otherwise `flat_text` if more
  than half of the pages are `ok` (SPEC's "most pages"); otherwise `scanned`.
- `schema_version` stays 1: no IR had been stored before this change.
- Without changing the IR's shape: `BBox` validates `page >= 0`, `x0 < x1`, `y0 < y1` and finite
  coordinates; a `FormIR` validates that field ids are unique and that every box refers to an
  existing page. IR models reject unknown keys, so a stored IR that drifts from the schema fails
  loudly instead of losing data silently.

**Alternatives considered.**
- Keep `page_sizes` and add `ocr_pages: list[int]`: two parallel lists that can drift apart.
- A `SourceKind` per page: mixes "what the document is" with "how good this page's text is".

### D2. Sensitive semantic types

CLAUDE.md §3 named four sensitive types; SPEC §5's headings marked whole groups (IDs, bank) as
sensitive. **Decision:** `aadhaar`, `pan`, `bank_account_number`, `passport_number`, `voter_id`
(CLAUDE.md's four plus `voter_id`, also a government ID number). `bank_name`, `ifsc` and
`bank_branch` are public information; masking them would only add friction. SPEC §5 updated.

### D3. Upload page limit is enforced in the worker

SPEC §8 lists a 50-page upload limit, but SPEC §11 says PDFs are opened only in the worker, and
counting pages requires opening the PDF. **Decision:** the API checks size (20 MB) and magic bytes
(`%PDF-` within the first 1024 bytes) and rejects synchronously (413 / 415). The worker enforces
the page limit: the document becomes `failed` with job error `TooManyPages`, shown as a readable
message by `GET /documents/{id}`. Page images for the viewer are also rendered in the worker and
stored; the API only serves bytes. (SPEC §8 is updated with the upload step.)

### D4. New dependency `python-multipart`

FastAPI's multipart parser, needed for `POST /documents` (SPEC §8 "upload (multipart)").
Alternative: a raw `application/pdf` body (no dependency), rejected as a departure from SPEC §8.
The upload is capped by `Content-Length` and by reading at most limit + 1 bytes.

### D5. PyMuPDF becomes a runtime dependency

Moved from the dev group to the main dependencies (same version, 1.28.2), because the frontends
and page rendering run in the worker. AGPL-3.0 is already the repository licence.

### D6. `jobs.started_at` and the stale-job reaper

Migration `0002` adds `jobs.started_at timestamptz NULL`, set by `JobStore.mark_running`. On
worker startup, jobs that are `running` with `COALESCE(started_at, created_at)` older than
`JOB_TIMEOUT_SECONDS` are marked `failed` / `Stale`, and their documents `analyzing -> failed`.

### D7. API contract for Phase 2 (subset of SPEC §8)

- `POST /documents` (multipart `file`) → 202 `{document_id, job_id}`
- `GET /documents/{id}` → `{id, original_filename, status, source_kind, page_count, created_at,
  expires_at, job: {id, status, error_message}}`
- `GET /documents/{id}/ir` → latest Form IR, values of sensitive types masked
- `GET /documents/{id}/pages/{n}.png` → `n` is 0-based, like `BBox.page`
- `GET /jobs/{id}`
- Another user's document or job → 404 (not 403), so ids are not confirmed.

### D8. Comb boxes (detector and labelling convention)

A row of per-character cells is **one** field, with `max_chars` = the number of cells. The row
is split into separate fields where the gap between cells is clearly larger than the normal cell
spacing (e.g. more than one cell width), or where printed text or a separator sits between cells
(e.g. `DD MM YYYY` groups). Each checkbox square is its own field; grouping into radio options is
later work. Written into the labelling README and tested in `flat.py`.

### D9. Dotted leaders are entry areas

Runs of dots (`.....`, `…`) count as entry areas, like underscore runs; on the dev forms they are
more common than underscores. A detail of `flat.py` within SPEC §6.1, not a spec change.

### Labelling tool: Label Studio

Chosen by the human over VIA and a custom labeller (trade-offs in the Phase 2 plan). Run via
Docker outside the repo; not a project dependency. Anchoring check: the human labels #21 and #41
from scratch first, without pre-annotation; a script later compares those labels with the
detector output to show whether pre-annotation biases the labels.

### Phase 0 task left open

"Collect 30 forms" stays unticked with its note (20 collected; Phase 0 closed with 20 by the
human's decision).

## Step 1 — Form IR, semantic types, coordinates

- **StrEnum** for all IR enums (as in `app/db/models.py`); same JSON as SPEC's `(str, Enum)`.
- **Semantic types** (`app/ir/semantic_types.py`): one `TypeInfo` per type with description,
  keywords, profile key, sensitive flag and default validator names. Address types exist as
  `current_*` and `permanent_*`; the component keywords ("city", "pincode") are shared by both
  variants on purpose, because SPEC §6.2 decides current vs permanent from the section context.
  Keywords are English plus common Hindi transliterations (SPEC §5); Devanagari keywords, if
  needed, are tuned on dev data in Phase 3. Derived and form-local types (`age`,
  `date_of_filling`, `place`, `signature`, `declaration_checkbox`, `other`, `unknown`) have no
  profile key. Validator names are placeholders for the Phase 4 validators.
- **Coordinates** (`app/ir/coords.py`): conversions only at the edges (invariant 6).
  - PDF user space (origin bottom-left, page shown through its CropBox, possibly with a non-zero
    origin and a `/Rotate`) ↔ IR (points, origin top-left of the *displayed* page).
  - Pixels of a page image at a given DPI ↔ points.
  - Checked against PyMuPDF on 2026-10-11: `page.get_drawings()` (and text extraction) return
    coordinates of the **unrotated** page, relative to the CropBox, top-left origin;
    `page.rotation_matrix` maps them to the displayed page. The frontends must apply it. None of
    the 20 collected forms has a `/Rotate`, but the conversion handles 0/90/180/270 and is
    tested against PyMuPDF.

## Step 2 — PyMuPDF at runtime, synthetic PDF fixtures

- **PyMuPDF moved to the main dependencies (D5)**, same version 1.28.2; `uv.lock` only moves it
  out of the dev group.
- **Fixture generator** `backend/tests/fixtures/pdfs.py`: 18 fixtures built in memory, each with
  its ground truth (source kind, text layer per page, expected fields). Byte-deterministic
  (`tobytes(no_new_id=True, deflate=True)`), except the encrypted one (random salt).
  `python -m tests.fixtures.pdfs --out DIR` writes them with JSON ground truth for inspection.
  Covered: underscore runs (label left, attached, two per row, label above), dot and ellipsis
  leaders, drawn lines and thin filled rectangles, empty rectangles, a framed notice (negative),
  a table with an entry column, checkboxes, comb rows (contiguous, small spacing, split by a wide
  gap, split by `DD / MM / YYYY` separators — D8), a rotated page, Kruti Dev-style and Latin-1
  mojibake text, an image-only page, a sparse signature page without images (D1 amendment: `ok`),
  a sparse page with a small logo (`ok`), two mixed documents, an AcroForm document, 51 pages,
  and an encrypted file.
- **Box convention for entry areas** (confirmed by the human on 2026-10-12; goes into the
  labelling README in Step 5):
  - Line-type entries: the line's x-span, and vertically from the writing line up by one row
    height = 1.2 × the label's font size. The writing line is the text baseline for
    underscores and dots, and the stroke centre for drawn lines.
  - Rectangles, table cells and checkboxes: the drawn rectangle. Comb rows: the union of their
    cells.
  - **Labeller instruction:** "Draw from the start to the end of the line, and from the line up
    to a little above the height of the label's capital letters." The IoU ≥ 0.5 match tolerates
    this: with the x-span right, a box of 1.0× or 1.5× the font height matches the 1.2× box
    (IoU 0.83 and 0.80), and any height from 0.6× to 2.4× matches
    (`tests/unit/test_geometry.py`).
  - **Multi-line entries** (e.g. an address on two or three writing lines): each writing line is
    its own box and its own field. Grouping lines into one logical field is out of scope for
    Phase 2. Fixture `flat_multiline`.
- `app/ir/geometry.py` holds `iou()` and `MATCH_IOU = 0.5`, shared by the flat frontend (Step 4)
  and the detection eval (Step 6).
- **Ellipsis leaders.** On the dev forms, runs of "…" (U+2026) are the most common leader: 158
  runs vs 32 runs of plain dots (counted 2026-10-12). PyMuPDF's `insert_text` writes base-14
  fonts with its own Latin encoding, which has no ellipsis (it came out as "·" with the wrong
  width), so the fixture writes that line with a WinAnsi-encoded Helvetica resource; a test
  checks that it extracts as U+2026.
- **The AcroForm fixture is written as raw PDF objects.** PyMuPDF 1.28.2 cannot create a real
  radio group (two widgets with the same name become two separate fields, both with on-state
  `Yes`, and a radio with a value other than Off fails in `Widget._checker`). Raw objects give a
  real parent field with `/Male` and `/Female` kids, a checkbox on-state `/Agreed`, a combo box
  with export-value pairs, `/MaxLen`, and an offset CropBox — with every `/Rect` known exactly for
  the Step 9 coordinate test. PyMuPDF reads it back as intended (tested).
- Not verified locally: the Docker daemon was not running, so the slim image with PyMuPDF was
  not built here; the CI compose-smoke job builds it from scratch.

## Step 3 — Source kind and per-page text layer (`app/frontends/detect.py`)

- Implements D1 as amended: `none` needs both fewer than 50 non-space characters **and** image
  coverage above 0.5 of the page ("most of the page area"); exactly half is not most. A blank
  page with no image is `ok` (nothing to OCR).
- Garbled-text heuristics and thresholds are ported unchanged from the Phase 0 classifier, but
  applied per page instead of per document. The Phase 0 script keeps its own copy; it is a
  one-off helper and is not imported by the app.
- Image coverage is the exact union area of image boxes (placed and inline images), clipped to
  the page, so overlapping images count once. PyMuPDF reports image boxes on the unrotated page;
  coverage is computed against the unrotated page rect (tested with a rotated page).
- `detect()` also returns per-page diagnostics (character count, coverage, reasons) — counts
  only, never text — for trace events and the eval report.
- **Dev forms (printed 2026-10-12, not asserted in CI):** #37 `garbled` (354 Latin-extended
  letters); #38 and #42 `none` on every page (0 characters, 100 % image); all 27 pages of the
  other 11 forms `ok`. #3's 43 images cover less than 30 % of any page. Consequence of D1: #37
  is now source kind `scanned` (Phase 0 called it "flat"), because its only page is garbled.

## Step 4 — Flat frontend (`app/frontends/flat.py`)

- **Entry areas** (PyMuPDF only): leader runs from per-character boxes (underscores; dots and
  ellipses, where 1–3 dots stay part of the text, e.g. "No.", "e.g.", "true."); horizontal
  lines, including thin rectangles and lines drawn in pieces; stroked rectangles and axis-aligned
  quads; table cells rebuilt from horizontal and vertical lines; comb rows (D8); checkboxes
  (squares of 5–16 pt). A line touched by two or more vertical lines is a table rule, a line
  under printed text is an underline, a box with text inside is not an entry, and a box that
  contains other boxes is a frame.
- **Overlaps** are resolved by priority (checkbox, comb, box, drawn line, leader). Line entries
  on different writing lines are trimmed, not dropped, so dense rows keep every line; one under
  a box starts at the box's bottom edge. Every drop is a trace event. Output boxes never overlap
  (tested on every fixture).
- **Labels**: same row to the left (bounded by the previous field on the row, nearest phrase),
  checkboxes to the right first; otherwise the nearest text line directly above. Trailing ":"
  removed; a "label" without letters or digits (e.g. "/") is no label. **Context**: the nearest
  heading above (bold, larger than the page's median font, or an all-caps line of 2+ words).
- Boxes lower than 6 pt get `ValidationResult("min_box_height", ok=False)`. Ids are
  `p{page}_f{nnn}` in reading order. Pages that are not `ok` get one trace event and no fields.
- All thresholds are first guesses checked on the synthetic fixtures only; tuning is Step 11,
  against the human labels on dev.
- **Two bugs found on the dev overlays (visual sanity check) and fixed**, each with a regression
  test; nothing was tuned:
  1. Segment merging grouped by a rounded position and kept the earlier segment's start, so a
     comb divider on form #3 was swallowed by a short segment at almost the same x further down
     the page; comb rows came out fragmented. Now segments are clustered by position, then
     merged in order of start.
  2. Form #3 draws its checkboxes as quads whose corners start at the top right; PyMuPDF's
     `Quad.is_rectangular` is False for that order, so all 16 were ignored. Now any axis-aligned
     quad counts as a rectangle.
- **Detector output on the dev forms** (2026-10-12, after the fixes; detector counts, not
  ground truth): 942 fields on the 27 `ok` pages of 11 forms — 622 text (251 of them comb rows)
  and 320 checkboxes. Per form: #1 427, #2 42, #3 197, #6 27, #21 28, #23 47, #25 115, #30 15,
  #32 16, #39 8, #41 20. #1 (9 pages) takes about 1 s.
- **Seen on the overlays, left for Step 11** (questions for the labels, not clear bugs):
  cells with printed grey hints (`F I R S T N A M E`, `D D M M Y Y Y Y`) count as "text inside",
  so comb rows split around them and hinted date rows are missed; rows of wide cells (26–27 pt,
  wider than the 20 pt comb-cell limit, e.g. #25 date of birth and Aadhaar) are separate boxes,
  not combs; cells with their label printed inside are not entries. (Correction 2026-10-16: the
  cell width was first estimated as "about 40 pt" from overlay pixels; measured, it is 26–27 pt.)
  The human's labelling rules for these cases are in the Step 5 section.
- Overlays for visual checks go to `eval/overlays/` (gitignored, like the PDFs).

## Step 5 — Label Studio tooling (`eval/labelling/`)

- **Labelling rules (human, 2026-10-16)**, written into `eval/labelling/README.md` and the
  target for Step 11 tuning. Top rule: *draw a box where a person would write, split into the
  parts a person would write separately.* From it:
  1. cells with printed grey hints are entry areas, not labels: a hinted name row is one comb
     field; a hinted date row follows D8 (`DD` / `MM` / `YYYY` as separate fields);
  2. rows of wide cells: one character per cell → one comb row; one group per cell (`DD`, `MM`)
     → each cell its own field (D8). The dev forms only have the first case;
  3. a cell with its label printed inside: the box covers only the empty writable part.
- Proposed by Claude in the README, to be confirmed by the human: no box for areas where nothing
  is handwritten (photo boxes); signature/thumb areas are `text` boxes; "for office use" fields
  are boxed like any other.
- **Partial labelling (human, 2026-10-16):** label files record `labelled_pages`; the converter
  accepts partially labelled forms (a page counts once its annotation is submitted; skipped or
  untouched pages are unlabelled; a form with no labelled page gets no file). The Step 6 eval
  scores only labelled pages and lists the others.
- **Labelling order:** #21 and #41 from scratch (no pre-annotations; anchoring check), then the
  medium forms, then #1 and #3. Tasks are exported in this order.
- **One task per page**, only `ok` pages (27 tasks on dev; #37, #38, #42 have none), rendered at
  150 DPI; pre-annotations are the flat detector's boxes as Label Studio predictions (894 boxes;
  none on #21 and #41). Box kinds: `text`, `comb` (a text field with `comb: true` in the label
  file), `checkbox`. Boxes travel as percent of the page, so the conversion to points does not
  depend on the DPI; an accepted pre-annotation converts back to the detector box exactly
  (tested).
- **Label file** (`eval/labelling/schema.py`, validated on read and write): form, PDF SHA-256,
  `verified_by_human`, `prefilled_from` (detector commit, or null for from-scratch forms),
  source, `labelled_pages`, every page's size, fields (id `p{page}_l{nnn}` in reading order,
  bbox in points, kind, `comb`, `max_chars` (unused for now), `semantic_type` (Phase 3)).
  The converter refuses: two submitted annotations on one page, rotated or unlabelled boxes,
  boxes under 1 pt, a PDF whose SHA-256 differs, a JSON-MIN export, and overwriting label files
  without `--overwrite`. Claude never runs it on a real export.
- **Label Studio 1.23.2** (latest release, 2026-09-29), image `heartexlabs/label-studio:1.23.2`
  (0.36 GB, not the "~1 GB" estimated in the plan). Not a project dependency; runs in Docker
  with the page images served as local files.
- **Verified end to end on 2026-10-16** with a throwaway container and synthetic fixture PDFs:
  the labelling config is accepted, the local-files storage and the task import work, the page
  images are served, predictions appear only on pre-filled forms, and the JSON export converts
  to the expected label files. That export is kept as a test fixture
  (`backend/tests/fixtures/labelstudio_export_1.23.2.json`; synthetic, no personal data) so
  the converter is tested against the real export format. Not verified: the exact click path in
  the web UI (the README follows the 1.23.2 docs); legacy API tokens are disabled by default in
  1.23.2, which only matters for scripts, not for labelling in the browser.
- **Tooling layout:** the code lives in `eval/` (SPEC §10) and runs with the backend's
  environment (`PYTHONPATH=backend`, Makefile targets `label-tasks`, `label-convert`,
  `label-examples`); ruff and pytest cover it (`make lint` and CI lint `../eval`; pytest has the
  repo root on its path).
- The README's example images are rendered from the dev forms into the gitignored
  `eval/labelling/examples/` and not committed, like the forms and overlays.

## Known issues

- **PyMuPDF SWIG `DeprecationWarning` on import (suppressed in pytest).** PyMuPDF 1.28.2's
  SWIG-generated extension types (`SwigPyPacked`, `SwigPyObject`, `swigvarlink`) have no
  `__module__`, and Python 3.12 warns when they are imported. It is inside PyMuPDF and harmless.
  Python attributes the warning to `importlib._bootstrap`, not to `pymupdf`, so the
  `filterwarnings` entry in `backend/pyproject.toml` cannot be scoped by module; it matches only
  these three exact messages as `DeprecationWarning`. Revisit when PyMuPDF ships bindings built
  with a SWIG version that sets `__module__`.

## Known limitations

- **Searchable scans.** A scanned page with an OCR text layer (invisible text over a full-page
  image) has enough characters, so it is `ok`, but its entry boxes are part of the image, not
  vector drawings; the Phase 2 flat frontend will find few or no fields there. None of the dev
  forms is like this. To revisit with OCR in Phase 6.
- **Undetected garbling.** Unicode Devanagari with wrongly extracted vowel signs (form #30) is
  not detected by the heuristics and stays `ok`.

## In my own words

