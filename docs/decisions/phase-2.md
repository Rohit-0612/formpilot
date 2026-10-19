# Phase 2 — Form IR and flat-PDF frontend: decision record

> Status: **in progress** (started 2026-10-11 on branch `phase-2-flat-frontend`). Steps 0–10
> are done; **next is Step 11**. A fresh session continues from the "Remaining plan" section below.
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

## Step 8 — Upload, analyze job, read endpoints (D3, D4, D7)

Plan approved by the human on 2026-10-18, with the four proposals below and three additions.

- **Endpoints** (D7): `POST /documents` (multipart `file`) → 202 `{document_id, job_id}`;
  `GET /documents/{id}` (with the latest job and a readable `error_message`);
  `GET /documents/{id}/ir`; `GET /documents/{id}/pages/{n}.png` (0-based); `GET /jobs/{id}`.
  Another user's document or job, and a job without a document (ping), answer 404.
- **Size cap while reading** (approved proposal): Starlette parses the whole multipart body
  before a route sees the file, so `app/api/uploads.py` reads the body itself: a declared
  `Content-Length` over `MAX_UPLOAD_MB` + 64 KiB framing is refused before reading; the received
  bytes are counted and reading stops past that cap (catches a missing or false length); the file
  part is checked against the exact limit. The multipart schema is declared in the OpenAPI
  document by hand (`openapi_extra`), so the generated web types still have it.
- **New dependency** `python-multipart` 0.0.32 (D4, approved): Starlette's form parser needs it.
- **Job queue connected on first use** (approved proposal): arq pings Redis with retries when a
  pool is created, so the API creates it on the first upload (one pool, behind a lock) instead
  of at startup; an unreachable Redis is a 503 and nothing is stored. Closed at shutdown.
- **Upload service** (`app/services/documents.py`): file name reduced to its base name without
  control characters, at most 255 characters (display only, never logged); original stored
  first, then the row committed (a failed commit deletes the file); an enqueue failure marks the
  document `failed` and answers 503.
- **Analyze job** (`app/services/analysis.py`, task `analyze`): document `uploaded → analyzing`
  (conditional update), PDF opened in a thread so the event loop and arq's health check stay
  responsive. **PyMuPDF is not thread-safe**, also across documents, so a process-wide lock
  allows one PDF at a time per worker. Errors: `EncryptedPdf` (needs a password),
  `UnreadablePdf`, `TooManyPages` (more than `MAX_PAGES`); their class names are the job error
  codes (D3), so they keep names without the usual `Error` suffix (scoped `noqa`, and a test
  pins the names). **Scanned documents go through `flat.run` too** (approved proposal): fields on
  usable pages, a "needs OCR" trace event for the others. Fillable documents get an IR without
  fields and a trace event until Step 9. Page PNGs (`PAGE_IMAGE_DPI`, default 144; the displayed
  page, so IR boxes scale by dpi / 72) go to `documents/<id>/pages/<n>.png`; then IR version 1
  and the document (`ready`, source kind, page count) are written in one transaction. Any
  failure, cancellation included, moves the document `analyzing → failed`.
- **Readable job errors** for `GET /documents/{id}` and `GET /jobs/{id}`: `TooManyPages`,
  `EncryptedPdf`, `UnreadablePdf`, `Stale`, `Cancelled`, `EnqueueFailed:*` have their own
  messages; any other error is "The analysis failed." (internal errors are not explained).
- **Masking** (proposal approved, plus the human's additions 1 and 3): `app/services/masking.py`
  and the response type `MaskedFormIR` (`app/api/schemas/ir.py`), which masks whenever it is
  built, from a model, a dict or stored JSON. Format `XXXX` + last 4 characters (separators
  removed) for values of 8+ characters, else `XXXX`; fixed prefix, so the length is not
  revealed; idempotent. **Defence in depth (addition 1):** a value that looks like a D2
  identifier is masked whatever the field's semantic type — Aadhaar `[2-9]` + 11 digits (no
  checksum required), PAN, Indian passport (`A1234567`), voter ID (`ABC1234567`), bank account
  9–18 digits — matched on the whole value with spaces, hyphens and (since 2026-10-19) a
  leading `+` removed; before that fix a `+`-prefixed number such as `+234567890124` matched no
  pattern. **Phone exception (approved by the human on 2026-10-19, with conditions):** in a
  field understood as `phone_mobile` / `phone_alternate`, a value in Indian mobile format (10
  digits starting 6–9, optional `+91` or leading `0`) is not masked; any other value in a phone
  field (an Aadhaar, an account-shaped number starting with 5, `91…` without `+`, another
  country code) is masked as everywhere else, and a mobile-shaped value in any other field is
  masked. Limitations: see Known limitations.
  **Rule (addition 3):** every Form IR returned to the client is masked — written into SPEC §8;
  enforced by a test that walks the OpenAPI document and fails if any response, at any depth,
  contains a plain `FormIR` (with a test that the check catches a nested one). The check uses
  the OpenAPI document because FastAPI 0.141 keeps included routers lazily, so `app.routes`
  does not list the API routes.
- **Page images** (addition 2): `Cache-Control: private, no-store`.
- **Config:** `MAX_UPLOAD_MB=20`, `MAX_PAGES=50`, `PAGE_IMAGE_DPI=144` (`.env.example`).
- Tests: unit — masking (formats, every sensitive type, defence-in-depth values in other
  fields, phone exception, stored IR untouched, the OpenAPI rule), upload reading (exact limit,
  limit + 1, declared length over the cap refused before reading, false or missing length caught
  while reading, malformed bodies), magic bytes, file names, error messages, `analyze_pdf` on the
  fixtures (flat, scanned, fillable, 51 pages, encrypted, unreadable), page image size on a
  rotated page, the lazy queue (no connection at startup, one pool for concurrent first uses,
  503). Integration — upload → real worker → IR v1, PNG and job read back; 415 and 413 store
  nothing; 422 without a file; 51 pages and encrypted fail with readable messages; enqueue
  failure → document `failed` + 503; other user 404 and anonymous 401 on all four GET
  endpoints; masked IR response with the database unchanged; no file name or value in the logs.
  The test worker helper moved to `tests/integration/workers.py`.

## Step 9 — AcroForm frontend (minimal; plan approved 2026-10-19)

- **Why minimal, and why now.** PLAN lists `frontends/acroform.py` as a secondary Phase 2
  deliverable; SPEC §2 keeps the fillable path small and tested on synthetic fixtures, because
  Phase 0 found 0 of 20 real forms fillable. Since Step 8, any PDF with a widget is `fillable`
  and got an IR without fields — a dead end in an existing path. Reading widgets is exact (no
  heuristics), so the step is small. Not done: eval (no real fillable form), tuning, web,
  filling (`acroform_fill.py`, Phase 5), hybrid widget + printed-blank detection. Alternative
  considered: defer to Phase 5 (a PLAN change, and the dead end would stay).
- **Built** (`app/frontends/acroform.py`, routed from `analysis.py` for `fillable`): text →
  `TEXT` (`max_chars` from `/MaxLen`); checkbox → `CHECKBOX` with its on-state as the one option
  (e.g. `Agreed`); a radio group → one `RADIO` field per page, options = the buttons' on-states
  with their boxes and the text right of each button, field box = union of the buttons; combo /
  list box → `CHOICE` with `/Opt` (export value, display text). Label: tooltip (`/TU`), else the
  flat frontend's label logic (entries left then above; tick boxes right first; a radio group's
  own label left or above the group), only on pages whose text layer is `ok`. Context: the flat
  heading logic. Boxes: widget rects (unrotated page) mapped to the displayed page with the flat
  frontend's transform. Ids `p{page}_f{nnn}` in the flat reading order. One trace event per
  field and per skipped widget.
- **Reuse, not copies:** `flat.py` exposes `page_text`, `label_for`, `label_right_of`,
  `context_for`, `displayed`, `reading_order`, wrapping its private functions (separate
  `refactor` commit). No behaviour change: the flat tests pass, and a detection eval run after
  the refactor equals the committed both-metrics report in every number.
- **New fixture `fillable_rotated`** (PyMuPDF-built, byte-deterministic): a text widget labelled
  by printed text and a push button on a `/Rotate 90` page. Existing fixtures unchanged (the
  SHA-256 values pinned by the recorded Label Studio export still match).
- **Gate 2 acceptance "coordinate conversion bottom-left ↔ top-left":** besides the Step 1
  `test_coords.py`, `test_raw_pdf_rects_converted_with_coords_equal_the_ir_boxes` reads each
  widget's raw `/Rect` and the page's raw `/CropBox` (or `/MediaBox`) and `/Rotate` from the PDF
  objects — independent of PyMuPDF's transforms — converts them with `app/ir/coords.py`, and
  checks they equal the IR boxes: offset CropBox (`fillable_basic`, 6 widgets) and `/Rotate 90`
  (`fillable_rotated`).
- Tests: unit — both fixtures against their hand-written ground truth (kind, box ±0.01 pt,
  label, name, `max_chars`, options with values, labels and boxes, reading order); form values
  (`/V`) not copied; ids and trace, push button skipped; on a page without a usable text layer
  only tooltips label fields; the document is not changed; the raw `/Rect` check. Integration —
  a `fillable_basic` upload through the real worker → `ready`, `fillable`, five fields of the
  expected kinds. No API change (`make types` gives no diff).

## Step 10 — Web: upload, progress, page viewer (plan approved 2026-10-19)

- **Pages:** `/documents/new` (upload), `/documents/[id]` (status polled every 1.5 s while
  `uploaded` / `analyzing`, then the viewer or the failure), dashboard link "Upload a form".
  There is no document list: no list endpoint exists (SPEC §8, D7). `AppHeader` and
  `useRequireUser` were extracted from the dashboard (separate `refactor` commit).
- **Masked IR only (human requirement):** the generated web schema has `MaskedFormIR` and no
  plain `FormIR` (guaranteed by the backend OpenAPI test). `lib/api/documents.ts` defines the
  only IR type the web uses and a `@ts-expect-error` guard on `components["schemas"]["FormIR"]`:
  typecheck fails if a plain FormIR ever appears (checked once by hand: pointing the guard at an
  existing type fails with TS2578). The viewer never shows values; box titles show the printed
  label and the kind.
- **Readable failures (human requirement):** a failed document shows the API's
  `job.error_message` from Step 8 (fallback "The analysis failed."); a missing or another user's
  document: "This form was not found. It may have expired or belong to another account."; IR,
  page image and network errors inline via the existing `userMessage`.
- **Viewer:** one page at a time; boxes positioned in percent of the page size from the IR
  (the PNG shows the displayed page, so no pixel size is needed); colour by kind with a legend;
  radio groups show the group box and each button's box; pages that need OCR get a note. Page
  PNGs are fetched with the session cookie (`parseAs: "blob"`) rather than `<img src>` to the
  API (cross-origin cookies would break on separate hosts); the object URL is set through a ref
  in an effect and revoked in its cleanup (correct under StrictMode, no state in the effect).
- **Upload size in the browser (approved recommendation):** `NEXT_PUBLIC_MAX_UPLOAD_MB` (build
  argument, compose passes the API's `MAX_UPLOAD_MB`, default 20) gives "The file is larger than
  20 MB." before uploading, because browsers often report the API's early 413 as a network
  error. The API stays the authority.
- **Verified 2026-10-19** on a throwaway compose stack (fresh database) with headless Chrome
  driven over the DevTools protocol (a scratch script, not committed; no new dependency): login
  → dashboard; `flat_boxes` ready with 5 boxes over the loaded page image; no values shown;
  `fillable_basic` with the radio group and its 2 button boxes; `mixed_mostly_scanned` with the
  OCR note; 51 pages and encrypted fail with their readable messages; non-PDF → "The file is not
  a PDF."; 21 MB → the size message; dev form #2 ready (42 fields), boxes on their cells in the
  screenshot (viewed locally, not committed); another user's document and an invalid id → not
  found; logged out → login. 13 of 13 checks passed.
- No web test runner exists and none was added (a new dependency); Playwright is Phase 5.
- **Observation:** page images show what the PDF itself draws, including a fillable form's own
  widget values (e.g. the combo box's default "UP" in `fillable_basic`), while the IR never
  copies them. Images are served only to the owner (`private, no-store`), so this exposes nothing
  to anyone else; noted for Phase 5, when filled values are rendered.

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

### Second relabel by Claude Code (human request, 2026-10-19)

Four annotation edits, made in Label Studio by Claude Code at the human's request, after the
human confirmed each one. Like the #25 fix, an exception to CLAUDE.md §6 (Claude never edits
labels) granted for these edits only.

- **Why.** Fix 1 of Step 11 (the amended D8) changed the detector's output on #1, #2 and #3. A
  read-only scan of all 11 dev label files for rows that labelling rule 2 says should be one
  comb (adjacent `text` boxes of similar width, ≤ 34 pt wide, ≤ 3 pt apart, one character each)
  found exactly two such rows; the human confirmed both. Separately, two #1 comb labels span a
  gap that the amended D8 splits; the human opened both tasks and checked the printed form.
- **Basis (human).** The decisions were based on the field label, the cell structure and the
  labelling rules — not on the detector's output.
  - **#2 page 1, task 4:** the "Account No." row, `p0_l038`–`p0_l048` (11 one-character
    cells, 19.1–20.1 pt wide) → **one `comb` box** over their outer edge (x 30.8–250.0,
    y 724.5–737.3). Rule 2.
  - **#3 page 2, task 27:** `p1_l063`–`p1_l073` (11 one-character cells, 19.9–20.0 pt wide) →
    **one `comb` box** (x 33.6–253.6, y 787.3–796.9). Rule 2.
  - **#1 page 1, task 17:** `p0_l115`, "Mobile No." → **split 3 + 10**: x 53.8–92.0 (3 cells)
    and x 104.8–232.4 (10 cells), same height. The last 10 cells hold the 10-digit mobile
    number and the cells before the gap a country code — parts written separately, like the STD
    code rule.
  - **#1 page 4, task 20:** `p3_l007`, "Mobile Number of the Nominee" → **split 2 + 10**: x
    110.3–135.8 and x 142.2–269.7. Same reasoning.
  - The split points of #1 come from the printed cell edges (vertical lines at 92.0 / 104.8 and
    135.8 / 142.2), not from the detector's boxes.
- **How.** As for #25: a consistent backup of the Label Studio database first; the existing
  annotations edited in place through Label Studio's data model (`Annotation.save()`), each
  edit refused if the annotation had changed since the backup; the new boxes are the exact
  union (merges) or the printed-cell spans at the label's height (splits). Checked afterwards:
  only annotations 4, 17, 20 and 27 changed, each equal to the dry run; still one annotation
  per task; no task data, pre-annotation, draft or other annotation changed. Boxes: task 4
  51 → 41, task 27 76 → 66, task 17 121 → 122, task 20 67 → 68.
- **Verified by the human (2026-10-19):** tasks 4, 27, 17 and 20 checked visually after
  reloading, all correct; Update was not clicked anywhere. Export and conversion followed.
- **Export and conversion (Claude Code, after the human's check):** `label-studio export 1 JSON`
  → `~/Downloads/formpilot-dev-boxes-20261019-203955.json`; against the previous export only
  tasks 4, 17, 20 and 27 differ, one annotation per task, no task data changed.
  `make label-convert … OVERWRITE=1`: label content changed only in #1 (2 combs → 4), #2 (11
  boxes → 1 comb) and #3 (11 boxes → 1 comb), exactly the planned boxes; the other 8 files
  differ only in `source` (the export's file name), kept as converted as decided for the first
  conversion (option A). All 11 files validate (schema, PDF SHA-256, page count,
  `verified_by_human`, `prefilled_from` null only for #21 / #41, every subset page labelled).

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

## Writing-spot matching (human decision 2026-10-19; written before any number was computed)

**Principle (human).** The detection eval measures whether the detector found the same
**writing spot** as the labeller — the same place on the page where a person writes — not
whether the two boxes have the same height. Box height is a drawing convention (the detector
uses 1.2× the label's font size; the from-scratch labels are about 0.6×, see the pre-tuning
baseline) and is not scored.

**Rule (proposed by Claude, fixed before computing numbers).** A predicted box P and a labelled
box L, on the same page, mark the same writing spot if both hold:

1. **Same horizontal extent:** the IoU of their x-intervals,
   |[P.x0, P.x1] ∩ [L.x0, L.x1]| / |[P.x0, P.x1] ∪ [L.x0, L.x1]|, is at least **0.5**.
2. **Same writing row:** the distance between their vertical centres is at most **0.5 × the
   taller box's height**: |cy(P) − cy(L)| ≤ 0.5 × max(h(P), h(L)).

Matching stays one-to-one and greedy, now ordered by horizontal IoU (descending), then by
centre distance relative to the taller height (ascending), then by index — deterministic, as
before.

**Why these thresholds (geometry, not dev numbers).**
- The rule asks for a distance "relative to the font size", but neither the label files nor
  the IR record a font size; box height is the scale both have. The taller box is the reference,
  because the shorter one may be a thin hand-drawn box.
- Same spot, different heights, same writing line (the bottom edge): with heights h and k·h,
  the centres are |1 − k|·h/2 apart and the limit is max(1, k)·h/2, so every k from 0 up to any
  height matches. The 0.6× hand-drawn box against the detector's 1.2× box (k = 0.5) is well
  inside.
- Neighbouring writing lines must not match. Line pitch is at least about one font size; with
  the detector's box of 1.2× font size the limit is 0.6× font size, while centres on adjacent
  lines are at least about 0.7× apart (pitch minus half the height difference of a 0.6× and a
  1.2× box). Multi-line entries (one box per line) therefore stay separate.
- Horizontal IoU ≥ 0.5 is the same threshold as SPEC §10, on one axis: a comb row labelled as one
  box against 8 per-cell predictions does not match (each cell covers 1/8), which is correct —
  they are different fields.
- A checkbox 2 pt off in both directions (9 pt square) has horizontal IoU 7/11 ≈ 0.64 and
  centre distance 2 ≤ 4.5: it matches, where plain IoU (49/113 ≈ 0.43) did not. (Wording made
  precise on 2026-10-19 while writing the tests, before any number was computed; the rule is
  unchanged. Off on one axis only, plain IoU is already 0.64.)

**Known edge case.** A labelled box much taller than the line pitch (e.g. 2.4× font size drawn
over dense lines) can reach the centre of the line above; the greedy order then prefers the
closer centre, but ties are possible (a box exactly halfway between two lines; the tie goes to
the lower predicted index — pinned by a test). Not expected under the labelling rules (the README asks for
"a little above the capital letters").

**Reporting.** `make eval-detect` reports the writing-spot match as the **primary** metric
(overall, by kind, anchoring check, per form) and plain IoU ≥ 0.5 (SPEC §10) as the
**secondary** metric; IoU ≥ 0.3 stays in the JSON as a diagnostic. The committed pre-tuning
report (`phase2-detection-dev-pre-step11-tuning-20261017-2e70d9d`) is left unchanged; the
baseline is re-reported under both metrics in a new report. No label is changed. SPEC §10's
detection metric is IoU ≥ 0.5; this adds a primary metric for Phase 2 detection and keeps the
SPEC metric — SPEC §10 gets a note pointing here.

### Baseline under both metrics (2026-10-19)

Same detector and labels as the pre-tuning report, with the rule above implemented:
`make eval-detect TAG=pre-step11-tuning-both-metrics` →
`eval/reports/phase2-detection-dev-pre-step11-tuning-both-metrics-20261019-23dea75.{json,md}`.
The IoU ≥ 0.5 numbers equal the committed pre-tuning report exactly (that report is unchanged).

| | Writing spot P | Writing spot R | TP / FP / FN | IoU ≥ 0.5 P | IoU ≥ 0.5 R |
|---|--:|--:|--:|--:|--:|
| all scored pages | 91.2 % | 80.2 % | 506 / 49 / 125 | 87.7 % | 77.2 % |
| from scratch (#21, #41) | 77.1 % | 56.9 % | 37 / 11 / 28 | 43.8 % | 32.3 % |
| pre-filled (other 9) | 92.5 % | 82.9 % | 469 / 38 / 97 | 91.9 % | 82.3 % |

- **Anchoring check under the writing-spot rule:** the precision gap mostly closes (#21: 39.3 % →
  89.3 %), which confirms most of it was the box-height convention. A recall gap remains
  (56.9 % vs 82.9 %; #21 recall 55.6 %, 20 of 45 labelled spots not found at all). This data
  cannot tell whether that is a detector weakness on these two forms or pre-annotation hiding
  misses on the pre-filled forms; Step 11 looks at the missed spots on #21 and #41.
- Lowest writing-spot recall: #30 48.4 %, comb rows 62.5 % (60/96), #23 68.8 %.

## D8 amended: split comb rows at gaps relative to the row (human, 2026-10-19; written before any number was computed)

**Observation that prompted it.** On a synthetic test form of the human's (not in the eval
dataset; never used for tuning) a date row of 16 pt cells grouped `DD │ MM │ YYYY` by 8 pt gaps,
and a name row grouped `FIRST │ LAST` by a 10 pt gap, each came out as one comb box. The
captions sit below the cells, so the "printed text between cells" condition does not apply.
`flat.py` implemented D8's example threshold literally (`gap > one cell width`), so an 8–10 pt
gap in an otherwise contiguous row never split it — although D8's own wording ("clearly larger
than the normal cell spacing") says it should.

**Rule (human).** A comb row is split where the gap between two neighbouring cells is larger
than **max(3 pt, 2 × the median gap in that row)**, instead of larger than one cell width.
- "Gaps" are the distances between consecutive cells of the row as found, before any split;
  the median is taken over all of them. Contiguous cells have gap 0, so in a row whose cells
  mostly touch, any gap over 3 pt splits it.
- The other D8 condition stays: printed text or a separator between cells also splits.
- Unchanged: each part keeps `max_chars` = its number of cells; a row of contiguous cells
  without separators stays one comb (e.g. a date of birth with no gaps: one box, as the human
  confirmed for the test form).
- Edge cases of the median (noted, not changed): a two-cell row has one gap, which is its own
  median and never larger than twice itself, so it is never split by a gap. With an even number
  of gaps the median is the mean of the middle two, so a three-cell row with gaps [0, 8] has
  median 4 and threshold 8, and is not split either. Short rows like these are reported in
  Step 11 if they occur on dev.

**Second amendment (human, 2026-10-19), made after fix 1's dev measurement revealed a
regression.** Applied literally, the rule above lost D8's original protection, "a gap wider than
a cell always splits". The comb grouper collects every small box on a line before applying the
gap rule, so a line of *separate* small boxes spaced regularly far apart has a large median gap
and a threshold larger still: on #3 two checkboxes 62 pt apart became one 2-cell comb (median 62,
threshold 124), and on #2 / #3 cells of about 20 pt — half measured 19.9 pt, half 20.1 pt, so
only every other one passed the 20 pt comb-cell limit — left candidates 40 pt apart that merged
into one wide comb (threshold 80) and pushed out the cells between them. Fix 1 as first written
measured writing spot P 90.2 / R 77.0 against the baseline 91.2 / 80.2 (#2 TP 42 → 32, #3 TP
68 → 58; from scratch unchanged). **Rule now:** split where gap >
**min(cell width, max(3 pt, 2 × the row's median gap))** — a gap wider than a cell always
splits (old D8), and the median rule adds splits for narrow gaps in rows whose cells otherwise
touch. Written before re-measuring.

**How it is checked (Step 11).** A new synthetic generator fixture with 16 pt cells grouped by
8 pt and 10 pt gaps (captions below the cells) and a contiguous row is the unit test. Then
`make eval-detect` on the dev labels only: every form where the number of detected boxes changes
is reported to the human — improvements and regressions, especially #1 and #25. The human's
synthetic test form stays out of tuning.

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

- Branch `phase-2-flat-frontend`; Steps 0–10 committed and pushed (Steps 7–10: see their
  sections above). CI green on every pushed head up to Step 6 (run 38937110232 on `63ba5e2`).
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
- Step 8 (done): masking decided and built (Step 8 section). Open for the human: the phone
  exception in the defence-in-depth masking.
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

- **Known inconsistency: signatures differ between frontends.** Flat signature areas are boxed
  (labelled `text`, Phase 2 labelling rules, so the flat detector is scored on them), while
  AcroForm signature widgets are skipped (Step 9). Signature handling must be made consistent
  across frontends in Phase 3 (added to the Phase 3 deliverables in `docs/PLAN.md`).

- **AcroForm (Step 9), synthetic fixtures only.** Hybrid documents (widgets plus printed
  blanks): only the widgets are detected, because a document with any widget is `fillable`.
  Push buttons, signature fields and unknown widget types are skipped (trace event). Values a
  form carries (`/V`) are not copied into the IR. A radio group whose buttons lie on several
  pages becomes one field per page. No real fillable form has been evaluated (Phase 0 found
  none).

- **Masking: misclassified phone field.** A bank account field misclassified as a phone field
  (`phone_mobile` / `phone_alternate`) whose value happens to be in Indian mobile format (10
  digits starting 6–9) is not masked, because of the approved phone exception (Step 8).
- **Masking: identifiers inside longer values.** Defence-in-depth masking matches whole values
  only; an identifier inside a longer value (e.g. an Aadhaar number written into an address
  line) is not caught. Fields whose semantic type is sensitive are always masked. Both cases are
  pinned by `test_known_limitations_are_what_they_say`.
- **Worker throughput: one PDF at a time.** PyMuPDF is not thread-safe, also across documents,
  so a process-wide lock lets each worker process analyse one PDF at a time (Step 8); other jobs
  wait for the lock. Throughput scales with worker processes, not with arq's concurrent jobs.
  Not measured yet.

- **Searchable scans.** A scanned page with an OCR text layer (invisible text over a full-page
  image) has enough characters, so it is `ok`, but its entry boxes are part of the image, not
  vector drawings; the Phase 2 flat frontend will find few or no fields there. None of the dev
  forms is like this. To revisit with OCR in Phase 6.
- **Undetected garbling.** Unicode Devanagari with wrongly extracted vowel signs (form #30) is
  not detected by the heuristics and stays `ok`.

## In my own words

