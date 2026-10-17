# Phase 2 — Form IR and flat-PDF frontend: decision record

> Status: **in progress** (started 2026-10-11 on branch `phase-2-flat-frontend`). Steps 0–7 are
> done; **next is Step 8**. A fresh session continues from the "Remaining plan" section below.
> Decisions are recorded here as they are taken; the close-out sections are filled in at the end
> of the phase.

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
- **Rule 1 refined (human, 2026-10-16):** one comb box per hinted part (e.g. FIRST NAME and
  MIDDLE NAME are separate boxes), because people write them separately and Phase 3 gives them
  different semantic types. The detector change belongs to Step 11. Where the form does not show
  where one part ends (form #1: uniform cells, hints placed differently in every row), Claude
  proposed: split halfway through the empty cells between two hints, an odd middle cell going to
  the earlier part; empty cells before the first hint belong to the first part, those after the
  last hint to the last part. **Approved by the human on 2026-10-17.** The README, the fixture
  `flat_hinted_comb` and the local #1 example use it.
- **No-box areas (human, 2026-10-16):** photo boxes and thumb-impression areas get no box
  (nothing is written there); signature areas are `text` boxes; "for office use" fields are boxed
  like any other field, and Phase 3 must mark them so FormPilot never fills them (added to the
  Phase 3 deliverables in PLAN.md).
- **README images (human, 2026-10-16):** no crops of dev forms are committed. The README images
  are rendered from three new synthetic fixtures (`flat_hinted_comb`, `flat_wide_cells`,
  `flat_label_inside`, one per rule) plus existing ones, committed in `eval/labelling/images/`
  (`make label-images`); a test checks they match the fixtures byte for byte. The dev-form
  crops stay local (`make label-examples`, gitignored). The three rule fixtures carry the
  rules' ground truth; the flat detector does not follow them yet, so their ground-truth test is
  a strict xfail until Step 11.
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
- Fixture text in black is written without a colour operator, so adding the grey-hint option
  did not change the bytes of existing fixtures (the recorded Label Studio export pins their
  SHA-256; the converter rejected the export when they changed, as it should).

## Step 6 — Detection eval (`eval/detection.py`, `make eval-detect`)

- **What it computes** (before the full Phase 3 harness): for every dev PDF with a label file,
  run `detect` + `flat.run` (pure functions, no database or worker) and, per labelled page whose
  text layer is `ok`, match predicted and labelled boxes one-to-one, greedily by descending IoU,
  keeping pairs with IoU ≥ 0.5 on the same page (SPEC §10; ties broken by index, so results are
  deterministic). TP = matched pairs, FP = unmatched predictions, FN = unmatched labels;
  precision and recall are micro-averaged over pages and forms. No scipy: greedy matching, not
  an optimal assignment (with one-to-one IoU ≥ 0.5 the two rarely differ).
- **Also reported:** per form; recall by labelled kind and precision by predicted kind (text,
  comb, checkbox); predicted → labelled kind on matched pairs; the same counts at IoU ≥ 0.3 as a
  diagnostic only; the **anchoring check** — from-scratch forms (`prefilled_from: null`, i.e.
  #21 and #41) against pre-filled forms; and what was not scored: labelled pages that need OCR,
  unlabelled `ok` pages, forms without a label file, forms with no `ok` page (#37, #38, #42).
  Every report ends with the dataset notes (the two test-split gaps).
- **Safeguards:** only `--split dev` is accepted (CLAUDE.md §6); a label file whose PDF SHA-256
  or page count differs from the PDF, or a label file without a PDF, stops the run.
- **Output:** `eval/reports/phase2-detection-dev-<date>-<commit>.{json,md}`. No report is
  committed until there are label files; the first real report comes in Step 11. A smoke run on
  the dev split without labels (2026-10-16, written outside the repo) listed all 14 forms as
  not scored, as expected.
- The matching functions are plain and importable, for reuse by Phase 3's `run_eval.py`.

## Step 7 — Stale jobs and storage wiring (D6)

- **Migration `0002`** adds `jobs.started_at timestamptz NULL` (upgrade adds, downgrade drops;
  `0001` untouched). `JobStore.mark_running` sets it to `now()`. SPEC §7 lists the column.
- **Reaper** `JobStore.fail_stale(timeout_seconds)`: one transaction; jobs `running` with
  `COALESCE(started_at, created_at) < now() - timeout` become `failed`, error `Stale`,
  `finished_at = now()`; their documents that are `analyzing` become `failed`. Returns the job
  ids and logs them (ids and a count only). A job that waited in the queue longer than the
  timeout is not stale once it has started: `started_at` decides, `created_at` only for rows
  from before `0002`.
- **Worker startup** calls it once with `JOB_TIMEOUT_SECONDS`.
- **Migrations run before api and worker (human, 2026-10-17).** First version: `make up` started
  the stack and only then ran `alembic upgrade head` in the api container, so on a fresh
  database the worker started before the `jobs` table existed; the reaper was made best effort
  so the worker would not crash. The human chose to fix the order instead: compose has a
  one-shot `migrate` service (same image, `alembic upgrade head`, after Postgres is healthy),
  and `api` and `worker` depend on it with `condition: service_completed_successfully`.
  `make up` is now only `docker compose up -d --build --wait`; `make migrate` stays for
  applying a new migration to a running stack. The reaper keeps the log-and-continue fallback
  as a safety net, logged at **ERROR** (`stale_jobs_check_failed`, exception type and stack
  only), because after this change it can only fail on a real problem (database down, schema
  behind). Verified 2026-10-17 on a throwaway compose project with a fresh database: `up
  --wait` exits 0, `migrate` exits 0 (`0002 (head)`), the worker starts without the error,
  health is ok, a ping job reaches `done`.
- **Storage:** `app.storage.make_storage(settings)` → `LocalStorage(settings.storage_root)`;
  created once in the API lifespan (`app.state.storage`, dependency `get_storage`) and in the
  worker (`ctx["storage"]`). Nothing uses it yet; uploads (Step 8) will.
- **Limitation:** only `analyzing` documents are moved to `failed`. A stale `render` job (Phase
  5) would leave its document `rendering`; to revisit when the render job exists.

## Labelling subset and no-box areas (human, 2026-10-17)

- **Subset scored by the detection eval** (1-based pages): forms #2, #6, #21, #23, #25, #30,
  #32, #39 and #41 in full; #1 pages 1 and 4 only; #3 page 2 only. Fixed in
  `eval/labelling/subset.py` and applied by `make eval-detect` (the CLI always applies it).
  Labelled pages outside the subset (e.g. a page submitted instead of skipped) are not scored and
  are listed under "Not scored" and in the JSON (`labelled_outside_subset_not_scored`); subset
  pages without labels are listed as not labelled. A subset that names a form without a PDF, or
  a page beyond the form's page count, stops the run.
- **Box kinds for special areas:** signature areas and office-use areas are boxed with the
  `text` label; photograph and thumb-impression areas get no box. Written into
  `eval/labelling/README.md` (table under "Do not box").

### One label edit made by Claude Code (human request, 2026-10-18)

The only label change not made by the human by hand. CLAUDE.md §6 says Claude never creates
or edits labels; the human made an exception for this one edit, asked for it explicitly and checks
it visually.

- **What:** form #25, page 1 (Label Studio task 10, annotation 10). The date-of-birth row (8
  cells, about 27 pt wide, one character each, no hints or separators) and the Aadhaar row (12
  cells) were labelled as one `text` box per cell. Labelling rule 2 (one character per cell →
  one comb box) makes each row one `comb` box. Replaced: the 8 boxes later converted as
  `p0_l005`–`p0_l012` by one `comb` box over their outer edge (x 120.9–336.0, y 106.9–123.0 pt),
  and the 12 boxes `p0_l026`–`p0_l037` by one `comb` box (x 127.6–425.6, y 289.6–309.1 pt).
  The new boxes are the exact union of the replaced ones; their Label Studio ids are
  `claude_dob_comb` and `claude_aadhaar_comb`.
- **How:** the existing annotation was edited in place (no new annotation) through Label
  Studio's own data model (`Annotation.save()` in the container's Django shell), after a
  consistent backup of the Label Studio database; the edit refused to run if the annotation had
  changed since the backup. Checked afterwards against the backup: only annotation 10 changed
  (87 → 69 boxes; the other 67 boxes identical), still one annotation per task, no task data,
  pre-annotation or other annotation changed.
- **Verified by the human (2026-10-18):** both comb boxes checked visually in task 10, nothing
  else changed. The human also re-checked #6 page 2 and #32 page 1 (every detector box kept
  unchanged) and confirmed them as correct.

### Export and conversion run by Claude Code (human request, 2026-10-18)

After the human had verified the labels by hand, Claude Code ran the export and the conversion
at the human's request (the hand-off rule "Claude never runs the converter on a real export"
was lifted for this run).

- **Export:** `label-studio export 1 JSON` (the CLI in the container; JSON, not JSON-MIN) →
  `~/Downloads/formpilot-dev-boxes-20261018-011720.json`, outside the repo. Cross-checks: against
  the human's earlier export, only task 10 differs (87 → 69 boxes); against the human's own
  export of the same state (`forms27-2.json`), annotations, boxes and task data are identical
  (the only difference is how `completed_by` is serialised: the CLI writes the user object, the
  UI only the user id). 27 tasks, one annotation each.
- **Conversion:** `make label-convert EXPORT=~/Downloads/formpilot-dev-boxes-20261018-011720.json
  OVERWRITE=1`. Compared with the previous label files: #25 lost the 20 cell boxes and gained the
  two comb boxes (101 other boxes unchanged; 62 of their ids renumbered, because ids follow
  reading order); the other 10 files differ only in `source` (the export's file name). The
  human chose to keep all 11 files as converted (option A). All 11 validate against the schema,
  match their PDF's SHA-256 and page count, have `verified_by_human: true`, and #21 / #41 have
  `prefilled_from: null`. No email address or other personal data is in the label files.

## Pre-tuning baseline (before Step 11, 2026-10-18)

`make eval-detect TAG=pre-step11-tuning` (new `--tag` option: names the report files and title)
→ `eval/reports/phase2-detection-dev-pre-step11-tuning-20261017-2e70d9d.{json,md}` (the date
in the name is the UTC run date). Labelling subset only; IoU ≥ 0.5.

| | Precision | Recall | TP | FP | FN |
|---|--:|--:|--:|--:|--:|
| all scored pages | 87.7 % | 77.2 % | 487 | 68 | 144 |
| from scratch (#21, #41) | 43.8 % | 32.3 % | 21 | 27 | 44 |
| pre-filled (other 9) | 91.9 % | 82.3 % | 466 | 41 | 100 |

- **Anchoring check: a large gap.** At IoU ≥ 0.3 the from-scratch forms reach 75.0 % / 55.4 %,
  so many of their boxes overlap the detector's but are drawn differently. A one-off read-only
  diagnostic (not part of the committed eval) on #21: of 45 labelled boxes, 20 overlap no
  detector box at all (real misses); 14 overlap with IoU < 0.5, and for those the labelled box
  is about half the detector's height (median ratio 0.50; width ratio 0.94, same bottom edge),
  i.e. the hand-drawn boxes are about 0.6× the font size, where the detector uses 1.2× — the
  lower edge of the tolerance in the labelling README. #41 shows the same ratio (0.52). On
  pre-filled pages the box heights come from the detector, so the gap mixes possible
  pre-annotation bias with a box-height convention difference. To be looked at in Step 11
  (decision for the human: whether the line-entry box height convention or the matching needs
  revisiting); nothing was changed.
- Lowest recall among pre-filled forms: #30 48.4 %, #23 65.6 %; comb recall 62.5 % (60/96).

## Remaining plan (hand-off, 2026-10-17)

Everything a fresh session needs to continue Phase 2 from the repo alone. It supersedes the plan
approved in the 2026-10-11 session; the decisions above (D1–D9, Steps 1–6) still apply.

### How to work

- Read `CLAUDE.md`, `docs/SPEC.md`, `docs/PLAN.md` and this file first.
- **One step per turn.** After each step: run the tests, commit (conventional message), push,
  show the human the exact test commands and their summary lines, then **stop** and wait for the
  human's go-ahead. Wait for CI on the pushed commit and report its run id and result.
- `make lint` (backend + `eval/` + web) and `make test` before every commit; `make test-int`
  when a step touches the database, Redis or the worker (needs Docker).
- Never create or edit files in `eval/labels/` (human ground truth); never report `test/`
  numbers; never commit dev-form PDFs or renders of them (`eval/overlays/`,
  `eval/labelling/examples/`, `eval/labelling/work/` are gitignored).

### Where things stand

- Branch `phase-2-flat-frontend`; Steps 0–7 committed and pushed (Step 7: see its section
  above). CI green on every pushed head up to Step 6 (run 38937110232 on `63ba5e2`).
- Built: Form IR (`app/ir/`), `detect.py`, `flat.py`, synthetic fixtures
  (`backend/tests/fixtures/pdfs.py`), Label Studio tooling (`eval/labelling/`), detection eval
  (`eval/detection.py`, `make eval-detect`).
- **2026-10-18:** labelling finished and verified; the 11 label files are committed in
  `eval/labels/` (sections above).
- **Human task (was in progress):** labelling the dev boxes in Label Studio (container
  `formpilot-labelstudio`, data in `eval/labelling/work/`; tasks generated at `flat@5fe80d0`).
  Order: #21 and #41 from scratch, then the medium forms, then #1 and #3. The human runs
  `make label-convert EXPORT=…` and commits the label files (or asks Claude to commit them).
  Do not regenerate the tasks (`python -m eval.labelling.tasks --force`) while labelling is in
  progress: re-importing duplicates tasks.

### Step 7 — Storage wiring and stale jobs (D6)

- **D6 (approved):** migration `0002` adds `jobs.started_at timestamptz NULL`;
  `JobStore.mark_running` sets it. On worker startup, jobs that are `running` with
  `COALESCE(started_at, created_at) < now() - JOB_TIMEOUT_SECONDS` become `failed`, error
  `Stale`, `finished_at = now()`; documents of those jobs that are `analyzing` become `failed`.
  Runs once per worker start. No other table changes.
- Files: `app/db/models.py` (`Job.started_at`),
  `app/db/migrations/versions/0002_jobs_started_at.py` (upgrade adds, downgrade drops; never edit
  `0001`), `app/services/jobs.py` (`started_at` in `mark_running`, `JobStore.fail_stale()`
  returning the failed job ids), `app/jobs/tasks.py` (call the reaper in `startup`; put the
  storage in `ctx["storage"]`), `app/storage/__init__.py` (`make_storage(settings)` →
  `LocalStorage(settings.storage_root)`), `app/main.py` (lifespan: `app.state.storage`),
  `app/api/deps.py` (`get_storage`).
- Tests: integration — migration up/down and the existing drift tests (models vs migrated
  schema, CHECK names, enum inserts); `mark_running` sets `started_at`; the reaper fails only
  stale running jobs (fresh running, queued and finished jobs untouched; a legacy row with NULL
  `started_at` uses `created_at`) and moves their `analyzing` documents to `failed`. Unit —
  `make_storage` and `get_storage`.

### Step 8 — Upload, analyze job, read endpoints (D3, D4, D7)

- **D3 (approved):** the API never opens a PDF (SPEC §11). It checks size (`MAX_UPLOAD_MB`,
  default 20) and magic bytes (`%PDF-` within the first 1024 bytes) and rejects synchronously:
  413 (too large) / 415 (not a PDF), with a clear error body. The worker enforces the page limit
  (`MAX_PAGES`, default 50): document `failed`, job error `TooManyPages`. Page PNGs for the
  viewer are rendered in the worker (`PAGE_IMAGE_DPI`, proposed default 144) and stored as
  `documents/<id>/pages/<n>.png`; the API only serves bytes. SPEC §8 gets the upload step written
  down.
- **D4 (approved):** add `python-multipart` (FastAPI's multipart parser). Cap the upload by
  `Content-Length` before reading, and read the stream in chunks up to limit + 1 bytes (a missing
  or lying `Content-Length` is still caught).
- **D7 (approved) API contract**, prefix `/api/v1`, all require login:
  - `POST /documents` (multipart field `file`) → 202 `{document_id, job_id}`
  - `GET /documents/{id}` → `{id, original_filename, status, source_kind, page_count,
    created_at, expires_at, job: {id, status, error_message}}`
  - `GET /documents/{id}/ir` → latest Form IR, values of sensitive types masked
  - `GET /documents/{id}/pages/{n}.png` → `n` 0-based like `BBox.page`; 404 when out of range
    or not rendered yet
  - `GET /jobs/{id}`
  - another user's document or job → 404, not 403 (ids are not confirmed)
- Upload flow (`app/services/documents.py`): validate → SHA-256 → insert `Document`
  (`original_filename` ≤ 255 chars, `expires_at = now + FILE_TTL_HOURS`) → `storage.put(
  "documents/<id>/original.pdf")` → commit → `JobService.create_job(ANALYZE, document_id)`.
  The API needs an arq pool in the lifespan (`create_queue`, as the CLI does). A storage failure
  rolls back; an enqueue failure marks the document `failed`. Filenames and field values are
  never logged.
- Analyze job (`app/jobs/tasks.py` `analyze`, via `run_tracked`; logic in
  `app/services/analysis.py`, rendering in `app/frontends/page_images.py`): document
  `analyzing` → load bytes → open (encrypted → `EncryptedPdf`; unreadable → `UnreadablePdf`) →
  page limit → `detect` → frontend by source kind (`flat_text` → `flat.run`; `fillable` →
  `acroform` from Step 9, until then an IR without fields and a trace event; `scanned` → IR
  without fields, every page traced as needing OCR) → render PNGs → `FormIRVersion` version 1
  (`ir.model_dump(mode="json")`) → document `ready` with `source_kind` and `page_count`.
  Any failure → document `failed`. Job errors are class names; `GET /documents/{id}` maps them
  to readable messages (e.g. "The PDF has more than 50 pages.").
- Config (`app/config.py`, `.env.example`): `MAX_UPLOAD_MB`, `MAX_PAGES`, `PAGE_IMAGE_DPI`.
- Files: also `app/api/routes/documents.py`, `app/api/routes/jobs.py`,
  `app/api/schemas/documents.py`; then `make types` (CI fails on stale generated types).
- Tests: unit — magic bytes, size cap (incl. a lying `Content-Length`), masking, error-message
  mapping. Integration — upload → worker → IR v1 and PNGs stored, document `ready`; non-PDF →
  415; oversized → 413; the 51-page fixture → `failed` / `TooManyPages`; the encrypted fixture →
  `failed`; another user → 404; captured logs contain no filenames or values.

### Step 9 — AcroForm frontend (secondary)

- `app/frontends/acroform.py`, routed from `analysis.py` for `fillable`. Text, checkbox, radio,
  choice; options with export values (checkbox on-state, e.g. `/Agreed`; radio group = one
  field whose options are the kids' on-states, bbox = union of the kids; choice `/Opt` pairs);
  `max_chars` from `/MaxLen`; label from the tooltip (`/TU`), else the nearest text left/above
  (reuse the flat label logic). Boxes: `widget.rect * page.rotation_matrix`.
- Tests on `fillable_basic` (its expected fields are in the fixture), plus the acceptance test
  "coordinate conversion bottom-left ↔ top-left": the raw `/Rect` read from the PDF object,
  converted with `app/ir/coords.py`, equals the IR bbox (offset CropBox).

### Step 10 — Web: upload, progress, viewer

- `web/src/app/documents/new/page.tsx` (upload), `web/src/app/documents/[id]/page.tsx` (status
  polled with TanStack Query until `ready`/`failed`, readable error), `web/src/components/
  page-viewer.tsx` (page PNG with the IR boxes on top, scaled by image width / page width,
  coloured by kind; no editing), `web/src/lib/api/documents.ts`, a link from the dashboard.
  Request/response types only from the generated `schema.d.ts`.
- Tests: lint, typecheck, build (CI); a manual `make up` run uploading a dev form. The human
  does the visual check on 5 forms (Gate 2 item).

### Step 11 — Eval on the human labels, tuning, OpenCV decision

- Needs the human's label files in `eval/labels/`. Run `make eval-detect`; commit the report in
  `eval/reports/`. Tune `flat.py` on dev only, re-run, commit each report.
- To implement (labelling rules, Step 5): rule 1 (hinted cells, one comb per hinted part, the
  approved split rule; hinted dates as D8), rule 2 (wide cells: one character per cell → comb;
  groups → one field per cell), rule 3 (label inside a cell → only the empty part; no box for
  photo and thumb-impression areas). Remove each strict xfail in `tests/unit/test_flat.py`
  (`STEP_11_RULES`) as its rule lands. Also check the comb cell-width limit (20 pt; #25's cells
  are 26–27 pt).
- Report the anchoring check (from-scratch #21/#41 vs pre-filled forms) to the human.
- OpenCV raster fallback: only if the eval shows misses caused by boxes drawn as images (#3 has
  43 images), and only with the human's approval (new dependency); otherwise it stays in Phase 6.
- Seen but not part of the detection metric: some labels are incomplete (#25 row 3 lost
  "Father's" and the superscript "th"); label quality matters for Phase 3.

### Step 12 — Close-out

- `/end-phase 2`: finish this record (what was built, alternatives, limitations), tick the PLAN
  items that have evidence. Gate 2 acceptance (`docs/PLAN.md`): eval report in `eval/reports/`;
  human visual check on 5 forms; coordinate conversion unit tests (Step 1 `test_coords.py`,
  Step 9); non-PDF / oversized upload rejected with a clear error (Step 8). Only the human ticks
  the gate. After the gate: PR to `main` with `gh pr create` (summary + acceptance results).

### Open items

- Human: labelling (above); Phase 1 teach-back and the "In my own words" sections of
  `phase-0.md`, `phase-1.md` and this file.
- Step 8: the masking format for sensitive values in `GET /documents/{id}/ir` is not decided
  yet (Phase 2 IRs have no values, but the path is built and tested now) — propose it in the
  Step 8 plan.
- The recorded Label Studio export (`backend/tests/fixtures/labelstudio_export_1.23.2.json`)
  pins the SHA-256 of fixtures `flat_underscores`, `flat_boxes` and `mixed_mostly_flat`;
  changing those fixtures means re-recording the export with a throwaway Label Studio.
- The README's Label Studio click path follows the 1.23.2 docs; the flow itself was verified
  through the API, not by clicking.
- Labels for the scanned/garbled dev forms (#37, #38, #42) are a Phase 6 task.
- Phase 3 must mark office-use fields so FormPilot never fills them (added to `docs/PLAN.md`).

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

