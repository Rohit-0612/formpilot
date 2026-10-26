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

### Third relabel by Claude Code (human request, 2026-10-21)

Two annotation edits on #1, made in Label Studio by Claude Code at the human's request; like the
earlier relabels, an exception to CLAUDE.md §6 granted for these edits only. They answer the
label questions raised by fix 2 (below, under the ablation table).

- **Decisions (human, 2026-10-21).** Based on the labelling rules and the printed form, not on the
  detector's output.
  - **#1 page 1, task 17, `p0_l023` (date of birth):** split into three `comb` boxes DD / MM /
    YYYY, like the other hinted dates (rule 1; already pending from the human's earlier review).
    New boxes at the label's height (y 279.3–290.5), outer edges kept (x 70.9 and 173.6), inner
    edges at the printed cell edges x 97.5 and 123.0.
  - **#1 page 4, task 20:** a `text` box for each of the six `INITIALS` boxes in the office-use
    section (office-use rule; grey-hinted cells are entry areas), along the printed rectangles
    (x 335.5–390.8; y 697.1, 714.6, 731.7, 748.3, 765.0, 781.7, each 12.8 pt high).
  - **#1 page 1, task 17, name row 2 (`p0_l018` + `p0_l019`):** the human's rule was: keep the
    21 + 18 split if a printed separator or thicker line marks it, otherwise merge into one comb
    (rule 1). **Evidence: none.** The row is 39 identical cells, 12.75–12.76 pt wide, all
    stroked 0.4 pt in the same dark blue; nothing is drawn at the split (x 339.9). The only
    difference along the row is a white fill on the first 16 cells, which changes at x 276.1
    (not at the split; invisible on the white page; row 1 has the same change). **Merged** into
    one `comb` box, the exact union (x 72.0–569.5, y 241.6–254.3).
  - **STD rows** (`p0_l118` / `p0_l119`, `p0_l120` / `p0_l121`): labels kept (5 + 10); recorded
    as detector misses (Known limitations).
- **How.** As before: a consistent backup of the Label Studio database first; the existing
  annotations edited in place through Label Studio's data model (`Annotation.save()`), each edit
  refused if the annotation had changed since the backup (Label Studio was restarted after a
  Docker Desktop restart; its database was checked equal to the backup before editing).
  Checked afterwards: only annotations 17 and 20 changed, each equal to the dry run; still one
  annotation per task; no task data, pre-annotation, draft or other annotation changed. Boxes:
  task 17 122 → 123 (−3 +4), task 20 68 → 74.
- **Verified by the human (2026-10-21):** tasks 17 and 20 checked visually after reloading: the
  date of birth is three combs, name row 2 is one comb, the six `INITIALS` boxes are there;
  Update was not clicked anywhere. Export and conversion followed.
- **Export and conversion (Claude Code, after the human's check) → labels v3:**
  `label-studio export 1 JSON` → `~/Downloads/formpilot-dev-boxes-20261021-181323.json`; against
  the v2 export only tasks 17 and 20 differ, one annotation per task, no task data changed.
  `make label-convert … OVERWRITE=1`: label content changed only in #1 (page 1: the date of birth
  1 comb → 3, name row 2 2 combs → 1; page 4: 6 `text` boxes added; 475 → 482 boxes), exactly
  the planned boxes; the other 10 files differ only in `source` (the export's file name), kept as
  converted (option A, as for the earlier conversions). All 11 files validate (schema, PDF
  SHA-256, page count, `verified_by_human`, `prefilled_from` null only for #21 / #41, every
  subset page labelled).

### Fourth relabel by Claude Code, and the human's re-review of #21 and #41 (2026-10-21)

- **A detector-prompted correction to a from-scratch form.** Fix 5 (blanks after a colon) found
  two blanks on #21 page 2 that have no label: "Policy No:" and "Name of the Post Office:" at the
  top of the discharge receipt (label question 4). The human decided they are entry areas (top
  rule; like page 1's "2. POLICY NO. :", which is labelled) and asked Claude Code to add a `text`
  box for each, in the existing annotation (task 2), as for the earlier relabels.
- **Why this matters (human).** Corrections prompted by the detector only fix errors in the
  detector's favour: a label the detector disagrees with gets looked at, and a missing label
  where the detector also finds nothing is never noticed. On #21 and #41, the forms labelled
  without pre-filled boxes and so the least biased signal, this pushes their numbers up. To
  balance it, the human re-reviews #21 and #41 in Label Studio without detector boxes, against
  the labelling rules, before the next export (below).
- **The boxes** follow the human's own convention on that page, not the detector's box: for the
  10 labelled boxes that directly follow a label ending in ":", the median start is 3.4 pt after
  the colon, the median top 8.5 pt above the text baseline and the median bottom 0.1 pt below it;
  the right end is the right edge of the receipt's own text lines just below (x 539.8; the
  human's right ends on that page vary too much to follow). "Policy No:" → x 120.0–539.8, y
  86.3–94.9; "Name of the Post Office:" → x 185.2–539.8, y 99.8–108.3. They overlap no existing
  box.
- **How.** As before: a consistent backup of the Label Studio database first; the existing
  annotation (task 2) edited in place through Label Studio's data model, refused if it had
  changed since the backup. Checked afterwards: only annotation 2 changed, equal to the dry run
  (22 → 24 boxes); still one annotation per task; no task data, pre-annotation, draft or other
  annotation changed.
- **Verified by the human (2026-10-21):** the two new boxes on #21 page 2 are correct.
- **Human re-review of #21 (tasks 1 and 2) and #41 (task 3) without detector boxes (2026-10-21):**
  done against the labelling rules (these tasks never had pre-annotations); the human made no
  other change. Checked in the Label Studio database: against the backup taken before the edit,
  only annotation 2 differs, and it equals the edit. Export and conversion followed.
- **Export and conversion (Claude Code, after the human's check) → labels v4:**
  `label-studio export 1 JSON` → `~/Downloads/formpilot-dev-boxes-20261021-195101.json`; against
  the v3 export only task 2 differs, one annotation per task, no task data changed.
  `make label-convert … OVERWRITE=1`: label content changed only in #21 (page 2: the two `text`
  boxes added, 45 → 47), exactly the planned boxes; the other 10 files differ only in `source`,
  kept as converted (option A). All 11 files validate (schema, PDF SHA-256, page count,
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

## Macro average (human request 2026-10-21; written before any number was computed)

**Why (human).** #1 holds a large share of all labelled boxes on the scored pages, so the pooled
(micro) precision and recall are mostly #1. A macro average weights every form equally.

**Definition.** For each form, precision = TP / (TP + FP) and recall = TP / (TP + FN) over that
form's scored pages (the per-form numbers the report already has). Macro precision is the
unweighted mean of the per-form precisions; macro recall the mean of the per-form recalls. A form
with no predicted boxes has no precision and is left out of the precision mean; a form with no
labelled boxes is left out of the recall mean (a form with labels but no predictions counts with
recall 0). Each mean states how many forms it covers. Computed for both metrics (writing spot,
IoU ≥ 0.5), for all forms, from scratch and pre-filled. `make eval-detect` reports it next to the
pooled numbers, which stay the primary summary in the report and the ablation table. Rows measured
before the macro existed get it from the per-form counts in their committed reports, with the
same function (`eval.detection.macro`); no detector is re-run for that.

## Step 11 — tuning on dev: ablation table (from baseline v5)

**Baselines.** The committed pre-tuning report (`…pre-step11-tuning-20261017-2e70d9d`, labels v1)
is unchanged. Each relabel re-measures the earlier rows on the new labels with the detector they
had, run from a temporary worktree at that commit (detection identical to the commit; only the
labels differ), so every row of the current table is on the same labels.
- **Labels v2** (second relabel): baseline v2 = the original pre-Step-11 detector (`0ee9999`) on
  the corrected labels, `…pre-step11-tuning-v2-20261019-0ee9999`. The relabel alone moved the
  numbers: writing spot 91.2 / 80.2 → 87.2 / 79.0, because the original detector gives one box per
  cell on the two rows that are now combs (#2, #3: TP −11 each, FP +11 each) and finds only one
  part of each split #1 comb (FN +2).
- **Labels v3** (third relabel, 2026-10-21, after fix 2): baseline v3 =
  `…pre-step11-tuning-v3-20261021-0ee9999`; fix 1 and fix 2 re-run as
  `…step11-1-d8-gap-v3-20261021-f535a3f` and `…step11-2-hinted-rows-v3-20261021-9541889`. The
  relabel alone (same detector): writing spot 87.2 / 79.0 → 86.8 / 77.7; only #1 changes (TP
  154 → 152, FP 13 → 15, FN 36 → 45: the original detector finds none of the three date-of-birth
  parts or the six `INITIALS` boxes, and neither of its two name-row-2 boxes matches the merged
  comb).
- **Labels v4** (fourth relabel, 2026-10-21, after fix 5; #21 page 2 gets two blanks): all four
  rows re-run as `…pre-step11-tuning-v4-…-0ee9999`, `…step11-1-d8-gap-v4-…-f535a3f`,
  `…step11-2-hinted-rows-v4-…-9541889` and `…step11-5-colon-blanks-v4-…-5fef220` (with the current
  eval code, which adds the macro average; matching is unchanged). The relabel alone: only #21
  changes. The baseline, fix 1 and fix 2 find nothing at the two spots (#21 FN 20 → 22; from
  scratch recall 56.9 → 55.2 %); fix 5 found both, so its two false positives become matches
  (#21 TP 42 → 44, FP 7 → 5; from scratch 78.4 / 89.2 → 81.1 / 89.6). This is the bias the human
  pointed out: a detector-prompted correction can only move the numbers in the detector's favour;
  the human's re-review of #21 and #41 without detector boxes found nothing else to change.
- **Labels v5** (the pending label fixes, applied once at the end of Step 11; export
  `formpilot-dev-boxes-20261026-124015.json`, see "Pending label fixes"), together with a
  **subset change**: #1 pages 5, 8 and 9 are scored (`subset.py`, the held-out check of rule 3).
  - All eight rows were re-run as `…-v5-20261026-<commit>`, each from a worktree at its commit
    with the current eval code and subset.
  - A fresh run of the main tree (fix 7's detector) gives results identical to the fix 7 row.
  - The relabel and subset change alone (fix 7): pooled 97.8 / 92.6 → 95.1 / 92.4, from scratch
    91.3 / 94.0 → 91.3 / 92.6. Three forms change:
    - #1: TP 195 → 265, FP 0 → 19, FN 2 → 8. The three new pages, where the detector does worse
      (page 8 has no entry area and 10 detector boxes; rule 3's holdout result is below the
      table), and page 9's name row split into three combs.
    - #3: TP 64 → 63, FP 2 → 3. `p1_l041` was removed, so the detector's 3 pt box became a false
      positive: a correction against the detector.
    - #21: FN 0 → 1. The official's signature area was added, and the detector does not find it:
      also against the detector.
- From scratch was unchanged by the v2 and v3 relabels.

**Procedure.** One fix per commit; after each, `make eval-detect TAG=step11-<n>-…` on dev
(labelling subset, current labels), report committed, row added here. Writing spot is the primary
metric; from scratch (#21, #41) is the main signal. Δ is against the previous row.

**Current table (labels v5, scored subset with #1 pages 5, 8, 9).** Writing spot unless the
column says IoU; pooled unless it says macro.
- In the value columns, Δ (in brackets) is against the **same row on labels v4**, i.e. the effect
  of the relabel and the subset change.
- The last column lists the per-form changes against the **previous v5 row**, i.e. the fix
  itself.

| Row | Commit | Writing spot P / R (all) | Macro writing spot P / R (all) | From scratch P / R | Pre-filled P / R | IoU ≥ 0.5 P / R (all) | Forms changed vs previous v5 row (writing spot) |
|---|---|---|---|---|---|---|---|
| Baseline v5 | `0ee9999` | 85.7 / 77.2 (−1.2 / −0.3) | 87.9 / 76.9 (−0.5 / −0.1) | 77.1 / 54.4 (+0.0 / −0.8) | 86.4 / 79.7 (−1.4 / −0.5) | 82.7 / 74.5 (−0.8 / +0.1) | — (TP 539, FP 90, FN 159) |
| Fix 1 — D8 gap split | `f535a3f` | 85.7 / 77.5 (−1.2 / −0.3) | 87.9 / 76.9 (−0.5 / −0.2) | 77.1 / 54.4 (+0.0 / −0.8) | 86.4 / 80.0 (−1.4 / −0.5) | 82.7 / 74.8 (−0.8 / +0.0) | #1: TP 210 → 212, FN 63 → 61 |
| Fix 2 — rule 1, hinted rows | `9541889` | 89.0 / 84.5 (−1.1 / +0.1) | 88.7 / 79.2 (−0.6 / −0.3) | 77.1 / 54.4 (+0.0 / −0.8) | 89.9 / 87.8 (−1.3 / −0.2) | 86.1 / 81.8 (−0.7 / +0.5) | #1: TP 212 → 255, FP 31 → 14, FN 61 → 18; #3: TP 56 → 62, FN 9 → 3 |
| Fix 5 — blanks after a colon | `5fef220` | 88.5 / 88.1 (−1.2 / −0.2) | 88.8 / 84.9 (−0.7 / −0.4) | **81.1 / 88.2 (+0.0 / −1.3)** | 89.4 / 88.1 (−1.5 / −0.0) | 83.5 / 83.1 (−0.5 / +0.5) | #21: TP 25 → 44, FP 3 → 5, FN 23 → 4; #41: TP 12 → 16, FP 8 → 9, FN 8 → 4; #1: TP 255 → 256, FP 14 → 16, FN 18 → 17; #2: TP 31 → 32, FN 10 → 9; #23: FP 3 → 5 |
| Fix 3 — rule 2, wide cells | `c41510e` | 94.2 / 88.7 (−2.1 / −0.2) | 93.9 / 85.4 (−0.7 / −0.4) | 81.1 / 88.2 (+0.0 / −1.3) | 95.9 / 88.7 (−2.7 / −0.1) | 88.9 / 83.7 (−1.4 / +0.4) | #25: TP 95 → 97, FP 20 → 0, FN 8 → 6; #2: TP 32 → 33, FP 11 → 0, FN 9 → 8; #3: TP 62 → 63, FP 14 → 3, FN 3 → 2 |
| Fix 4 — rule 3, label inside a cell | `fdbb165` | 94.0 / 92.0 (−2.5 / −0.1) | 93.9 / 89.8 (−0.7 / −0.4) | 81.1 / 88.2 (+0.0 / −1.3) | 95.6 / 92.4 (−3.1 / −0.1) | 87.3 / 85.4 (−1.6 / +0.5) | #30: TP 15 → 29, FN 16 → 2; #1: TP 256 → 265, **FP 16 → 19**, FN 17 → 8 |
| Fix 6 — rounded boxes | `9146cfb` | 95.1 / 92.0 (−2.7 / −0.1) | 96.6 / 89.8 (−0.7 / −0.4) | **90.9 / 88.2 (+0.0 / −1.3)** | 95.6 / 92.4 (−3.1 / −0.1) | 88.3 / 85.4 (−1.8 / +0.5) | #41: FP 9 → 1 |
| Fix 7 — hyphen leaders | `714c3d3` | **95.1 / 92.4 (−2.7 / −0.2)** | **96.6 / 90.4 (−0.7 / −0.4)** | **91.3 / 92.6 (+0.0 / −1.4)** | **95.6 / 92.4 (−3.1 / −0.1)** | 88.1 / 85.5 (−1.8 / +0.5) | #21: TP 44 → 47, FN 4 → 1 |

After fix 7 on v5: macro from scratch 92.3 / 89.0 (2 forms), macro pre-filled 97.6 / 90.7
(9 forms). Fix 7, final counts: TP 645, FP 33, FN 53.

By kind:
- text recall 91.0 % (386/424), precision 93.5 %;
- comb recall 96.5 % (138/143), precision 95.8 %;
- checkbox recall 92.4 % (121/131), precision 100 %.

**Held-out check of rule 3 (fix 4) on #1 pages 5, 8, 9** (labels v5; the pages were not used for
tuning).
- **Rule 3 boxes:** 7 on these pages, **3 correct: precision 42.9 %.**
  - Correct: the two signature boxes on page 5 and the one on page 9.
  - Wrong: page 8's space above a bottom-aligned "Yes", its heading row "C For Association of
    persons…" and its notes block, and page 9's table header cell.

  This is the same 3 / 4 split the by-eye judgement found (fix 4 note).
- **Effect of fix 4 against fix 3 on #1 as a whole:** TP +9, FP +3.
  - Page 4's six signature cells account for 6 of the matches; the holdout pages for the other
    3.
  - The +3 false positives are the 4 wrong rule 3 boxes minus page 9's page-wide "Date:" colon
    blank, which fix 4 dropped. That blank was itself a false positive: the v5 label there,
    `p8_l066` (x 41.9–212.3), is too short for it to match.
  - On v5, fix 4 therefore lowers pooled precision by 0.2 and pre-filled precision by 0.3; on
    v4 it raised both by 0.1.
- **The whole holdout (#1 pages 5, 8, 9) at fix 7:** TP 70, FP 19, FN 6. Page 8 (instructions
  only, 0 labels) gets 10 detector boxes, 3 of them from rule 3.
- **Caveat** (human, 2026-10-22): two of the three holdout pages (5 and 9) are re-reviewed
  pre-filled pages from `flat@5fe80d0` (before fix 4), so the holdout is not fully unbiased; only
  page 8 was labelled from scratch.

**History: labels v4** (superseded by the v5 table above; reports committed). Pooled P / R unless
the column says macro (writing spot, the mean over the 11 forms, each weighted equally; section
"Macro average"). Every row was run on labels v4 and its report carries the macro average.

| Row | Commit | Writing spot P / R (all) | Macro writing spot P / R (all) | From scratch P / R | Pre-filled P / R | IoU ≥ 0.5 P / R (all) | Forms changed (writing spot) |
|---|---|---|---|---|---|---|---|
| Baseline v4 | `0ee9999` | 86.8 / 77.5 | 88.3 / 77.0 | 77.1 / 55.2 | 87.8 / 80.2 | 83.4 / 74.4 | — (comb recall 57.4 %, 58/101) |
| Fix 1 — D8 gap split (amended twice) | `f535a3f` | 86.9 / 77.8 (+0.0 / +0.3) | 88.4 / 77.1 (+0.0 / +0.1) | 77.1 / 55.2 (±0) | 87.8 / 80.5 (+0.0 / +0.4) | 83.5 / 74.8 (+0.1 / +0.3) | #1: TP 152 → 154, FN 45 → 43 (167 → 169 boxes) |
| Fix 2 — rule 1, hinted rows | `9541889` | 90.1 / 84.4 (+3.2 / +6.6) | 89.3 / 79.5 (+0.9 / +2.4) | 77.1 / 55.2 (±0) | 91.2 / 87.9 (+3.4 / +7.4) | 86.8 / 81.4 (+3.3 / +6.6) | #1: TP 154 → 189, FP 15 → 0, FN 43 → 8 (169 → 189 boxes); #3: TP 57 → 63, FN 9 → 3 (70 → 76 boxes); comb recall 59.4 % → 94.1 % (95/101) |
| Fix 5 — blanks after a colon (done before fixes 3 and 4, human decision) | `5fef220` | 89.7 / 88.3 (−0.3 / +3.9) | 89.4 / 85.2 (+0.1 / +5.7) | **81.1 / 89.6 (+4.0 / +34.3)** | 90.9 / 88.1 (−0.3 / +0.2) | 84.0 / 82.6 (−2.8 / +1.3) | #21: TP 25 → 44, FP 3 → 5, FN 22 → 3 (28 → 49 boxes); #41: TP 12 → 16, FP 8 → 9, FN 8 → 4 (20 → 25); #2: TP 31 → 32, FN 10 → 9 (42 → 43); #23: FP 3 → 5 (47 → 49); text recall 80.0 % (323/404) → 85.9 % (347/404) |
| Fix 3 — rule 2, wide cells | `c41510e` | 96.3 / 88.9 (+6.6 / +0.6) | 94.6 / 85.8 (+5.2 / +0.5) | 81.1 / 89.6 (±0) | 98.6 / 88.8 (+7.7 / +0.7) | 90.2 / 83.3 (+6.3 / +0.6) | #25: TP 95 → 97, FP 20 → 0, FN 8 → 6 (115 → 97 boxes); #2: TP 32 → 33, FP 11 → 0, FN 9 → 8 (43 → 33); #3: TP 63 → 64, FP 13 → 2, FN 3 → 2 (76 → 66); comb recall 94.1 % → 98.0 % (99/101) |
| Fix 4 — rule 3, label inside a cell | `fdbb165` | 96.5 / 92.1 (+0.1 / +3.2) | 94.6 / 90.2 (+0.0 / +4.4) | 81.1 / 89.6 (±0) | 98.7 / 92.4 (+0.1 / +3.6) | 88.9 / 84.9 (−1.4 / +1.6) | #30: TP 15 → 29, FN 16 → 2 (15 → 29 boxes); #1: TP 189 → 195, FN 8 → 2 (189 → 195 boxes on the scored pages); text recall 85.9 % (347/404) → 90.8 % (367/404) |
| Fix 6 — rounded boxes | `9146cfb` | 97.8 / 92.1 (+1.3 / +0.0) | 97.3 / 90.2 (+2.7 / +0.0) | **90.9 / 89.6 (+9.8 / ±0)** | 98.7 / 92.4 (±0) | 90.1 / 84.9 (+1.2 / +0.0) | #41: TP 16 → 16, FP 9 → 1, FN 4 → 4 (25 → 17 boxes); text precision 94.6 % → 96.6 % |
| Fix 7 — hyphen leaders | `714c3d3` | 97.8 / 92.6 (+0.0 / +0.5) | 97.4 / 90.7 (+0.1 / +0.6) | **91.3 / 94.0 (+0.4 / +4.5)** | 98.7 / 92.4 (±0) | 89.8 / 85.0 (−0.3 / +0.2) | #21: TP 44 → 47, FP 5 → 5, FN 3 → 0 (49 → 52 boxes); text recall 90.8 % (367/404) → 91.6 % (370/404) |

After fix 5 the macro from scratch is 76.9 / 86.8 (2 forms) and the macro pre-filled 92.2 / 84.9
(9 forms; writing spot). After fix 3: 76.9 / 86.8 and 98.5 / 85.6. After fix 4: 76.9 / 86.8 and
98.5 / 90.9. After fix 6: 92.0 / 86.8 and 98.5 / 90.9. After fix 7: 92.3 / 90.0 and 98.5 / 90.9.

**History: labels v3** (superseded by the v4 table above; reports committed). The macro values of
the first three rows come from the per-form counts in their committed reports; a fresh
`make eval-detect` at `a200f52` (fix 2's detector) gives the same macro and pooled numbers.

| Row | Commit | Writing spot P / R (all) | Macro writing spot P / R (all) | From scratch P / R | Pre-filled P / R | IoU ≥ 0.5 P / R (all) | Forms changed (writing spot) |
|---|---|---|---|---|---|---|---|
| Baseline v3 | `0ee9999` | 86.8 / 77.7 | 88.3 / 77.2 | 77.1 / 56.9 | 87.8 / 80.2 | 83.4 / 74.7 | — (comb recall 57.4 %, 58/101) |
| Fix 1 — D8 gap split (amended twice) | `f535a3f` | 86.9 / 78.1 (+0.0 / +0.3) | 88.4 / 77.3 (+0.0 / +0.1) | 77.1 / 56.9 (±0) | 87.8 / 80.5 (+0.0 / +0.4) | 83.5 / 75.0 (+0.1 / +0.3) | #1: TP 152 → 154, FN 45 → 43 (167 → 169 boxes) |
| Fix 2 — rule 1, hinted rows | `9541889` | 90.1 / 84.7 (+3.2 / +6.6) | 89.3 / 79.7 (+0.9 / +2.4) | 77.1 / 56.9 (±0) | 91.2 / 87.9 (+3.4 / +7.4) | 86.8 / 81.6 (+3.3 / +6.6) | #1: TP 154 → 189, FP 15 → 0, FN 43 → 8 (169 → 189 boxes); #3: TP 57 → 63, FN 9 → 3 (70 → 76 boxes); comb recall 59.4 % → 94.1 % (95/101) |
| Fix 5 — blanks after a colon (done before fixes 3 and 4, human decision) | `5fef220` | 89.4 / 88.2 (−0.7 / +3.5) | 89.0 / 85.2 (−0.3 / +5.5) | **78.4 / 89.2 (+1.3 / +32.3)** | 90.9 / 88.1 (−0.3 / +0.2) | 83.7 / 82.6 (−3.1 / +1.0) | #21: TP 25 → 42, FP 3 → 7, FN 20 → 3 (28 → 49 boxes); #41: TP 12 → 16, FP 8 → 9, FN 8 → 4 (20 → 25); #2: TP 31 → 32, FN 10 → 9 (42 → 43); #23: FP 3 → 5 (47 → 49); text recall 80.3 % (323/402) → 85.8 % (345/402) |

After fix 2 the macro recall (79.7 %) is 5 points below the pooled recall (84.7 %): the fixes so
far helped #1 and #3, which hold most of the boxes; the smaller forms are unchanged. Macro from
scratch / pre-filled after fix 2: 74.6 / 57.8 and 92.5 / 84.6 (writing spot; 2 and 9 forms).

**History: labels v2** (superseded; reports committed).

| Row | Commit | Writing spot P / R (all) | From scratch P / R | Pre-filled P / R | IoU ≥ 0.5 P / R (all) | Forms changed (writing spot) |
|---|---|---|---|---|---|---|
| Baseline v2 | `0ee9999` | 87.2 / 79.0 | 77.1 / 56.9 | 88.2 / 81.6 | 83.8 / 75.9 | — |
| Fix 1 — D8 gap split (amended twice) | `f535a3f` | 87.3 / 79.3 (+0.0 / +0.3) | 77.1 / 56.9 (±0) | 88.2 / 81.9 (+0.0 / +0.4) | 83.8 / 76.2 (+0.1 / +0.3) | #1: TP 154 → 156, FN 36 → 34 (169 boxes); the 3- and 2-cell country-code parts found |
| Fix 2 — rule 1, hinted rows | `9541889` | 88.5 / 84.2 (+1.3 / +4.9) | 77.1 / 56.9 (±0) | 89.5 / 87.4 (+1.3 / +5.5) | 85.2 / 81.1 (+1.4 / +4.9) | #1: TP 156 → 180, FP 13 → 9, FN 34 → 10 (169 → 189 boxes); #3: TP 57 → 63, FN 9 → 3 (70 → 76 boxes); comb recall 62.0 % → 92.0 % |

Fix 1 history (labels v1, kept as evidence; reports committed): as first written
(`step11-1-d8-gap-…-3833df9`) it regressed to 90.2 / 77.0 from 91.2 / 80.2 (#2 TP −10, #3 TP −10)
and led to the second D8 amendment; capped (`step11-1b-d8-gap-capped-…-f535a3f`) it measured
90.8 / 80.2 on labels v1. #25 is unchanged by fix 1 on both label versions.

**Fix 2 — labelling rule 1, hinted rows** (`9541889`, report `step11-2-hinted-rows-20261021-9541889`).
- **What the dev forms show.** The hints on #1 and #3 are grey text (`#939598`, luminance 0.58)
  at the labels' size (6 pt; 5.6–5.9 pt on #3), one letter per cell; the label text is black or
  dark blue (`#2A2076`, luminance 0.16; the lightest is 2 characters of `#1F497D` on #3, 0.27).
  On the scored pages, all text lighter than luminance 0.3 is on #1 and #3, and it is all
  hints. The cells of a hinted row are identical 0.4 pt boxes: nothing printed marks where one
  part ends.
- **Rule as implemented** (the README's rule 1, not shaped to the labels): text with luminance
  0.4–0.85 is a hint (white text, on a dark banner, stays text). A hint never hides its cell and
  is never a label or context. A comb run is split into hinted parts: consecutive hinted cells
  are one part; the empty cells between two parts are shared halfway, an odd middle cell going
  to the earlier part; empty cells before the first / after the last part join it. A run of
  repeated letters (`DDMMYYYY`, one letter per cell, each letter at least twice) splits per
  letter (D8). Touching parts start at the previous cell's edge (drawn cell edges overlap by a
  fraction of a point, which otherwise drops a part as overlapping).
- **Tests.** The `flat_hinted_comb` strict xfail is removed (it passes). New unit tests: the
  luminance band, the part split (halfway, odd middle cell, date-like runs, words such as `STD`
  that stay one part), and hints that are neither labels nor hide their cells. Two eval tests
  that used `flat_hinted_comb` as an imperfect detector now use a label file with an extra
  spot.
- **Effect.** Only #1 and #3 change (every other dev form's boxes are identical). From scratch
  unchanged (no hints on #21 / #41); no regression.
- **What is left on the hinted rows of #1** on labels v2 (the label questions below): page 1's
  date of birth (3 FP, 1 FN), name row 2's second part and the two STD rows (3 FN), and page 4's
  six `INITIALS` boxes (6 FP). After the third relabel (labels v3) only the two STD rows' 5-cell
  parts remain (2 FN, Known limitations); #1 has no false positive left.

**Fix 5 — blanks after a colon** (`5fef220`, report `step11-5-colon-blanks-20261021-5fef220`;
done before fixes 3 and 4 at the human's request, 2026-10-21, because it is the main fix for the
from-scratch forms).
- **Why the order could change (checked on the dev pages before writing code).** For every miss
  on #21, #41, #2, #30 and #6: the colon-blank misses (#21 17, #41 4, #2 1) all have a colon and
  nothing drawn, and none lies in a drawn cell; the rule-3 misses (#30, 14) all lie in drawn
  cells, and only one of them follows a colon; fix 3's misses (#25's wide cells) hold no text.
  With "skip inside a drawn cell" the two rules are disjoint, so fix 5 depends on neither.
- **Rule.** A token ending in `:` or `:-` gets a line entry on its baseline (1.2 × its font size
  high), from 0.3 em after the colon to the next text on the line (0.3 em before it) or the page's
  text margin (the right end of its widest text), if that leaves at least 3 em. Skipped when
  something is drawn there (a leader, line or box overlapping it, or a drawn horizontal line in
  the band: that is the entry), when the colon lies inside a drawn cell (rule 3, fix 4), and when
  a drawn cell starts within 2.5 em below the colon line (the colon introduces a table). Lowest
  overlap priority. Its label is the phrase before the colon, also when the colon is printed
  apart ("2. POLICY NO.            :"); `:-` is stripped from labels like `:`.
- **How the exclusions were chosen.** A read-only prototype over all scored pages listed every
  colon with room after it. The candidates that matched no label were looked at on renders (local
  only): section headings followed by a table (#6 ×5, #25, #30) and a table header cell (#6).
  Bold and capitals were checked as heading cues and rejected: #21's and #41's real field labels
  are bold, #21's are in capitals. A "followed by a numbered list" cue would remove one more
  false positive (#21 "Mandatory requirements:-") and was left out to keep the rule simple. A
  first version also ended the blank at a drawn vertical line; on #1 that left slivers between a
  label and the comb right after it (12 boxes), so it was removed before measuring.
- **Effect** (labels v3, as first measured). From scratch, writing spot: recall 56.9 → 89.2 %,
  precision 77.1 → 78.4 % (on labels v4: 55.2 → 89.6 % and 77.1 → 81.1 %). Pre-filled:
  −0.3 / +0.2 (#2 one blank found; #23 two false positives). Only #2, #21, #23 and #41 change
  (and #1 pages 5 and 9, outside the subset: 3 boxes).
- **Secondary metric falls on from-scratch precision (43.8 → 36.5 %, IoU ≥ 0.5).** The new boxes
  are 1.2 × the font size high, the hand-drawn from-scratch labels about 0.6× (the box-height
  convention, see the pre-tuning baseline); the writing spots match, the boxes do not. Not a
  detection error; reported because it is the SPEC §10 metric.
- **False positives left (7 on labels v3; 5 on labels v4, after the two blanks below were labelled):** #21 page 2 "Mandatory requirements:-" (a heading over a numbered
  list) and "Details of nominee / appointee (in case nominee is minor):" (a heading over the
  E-mail / Branch / IFSC lines); #41 "Documents Enclosed:" (a heading over a list); #23
  "Particulars regarding the claimant :" and "…other policies on the life of the deceased :"
  (sentences introducing a list and a header-column table); and two that look like real blanks
  without labels (label question 4 below).

**Fix 3 — labelling rule 2, wide cells** (`c41510e`, report `step11-3-wide-cells-20261021-c41510e`;
labels v4).
- **What the dev forms show.** Four labelled comb rows were found as one box per cell: #25's
  date of birth (8 cells, 26–27 × 16 pt) and Aadhaar (12 cells, 20–26 × 19.5 pt), #2's Account
  No. and #3's row at y 787 (11 cells each, 19.1–20.1 pt wide; the cells just over 20 pt broke
  the run). Cell shape does not tell one character from a group: #3's one-character cells are
  20 × 9.6 pt.
- **Rule.** The comb cell width limit goes from 20 to **30 pt** (height limit unchanged, 25 pt);
  neighbouring cells must still have similar widths (ratio 0.7–1.43) and D8's gap rules still
  split. 30 pt is a threshold chosen on dev (allowed: thresholds are tuned on dev), checked
  read-only before writing code: 25 pt misses #25's cells and fuses the 20–21 pt cells in the
  middle of #25's Aadhaar row into a 3-cell comb; 30 pt changes exactly the four rows above and
  nothing else; 35 pt merges #1 page 4's separate 33 pt "Queue No." / "Initials" boxes (10 pt
  apart) into 2-cell combs. Rule 2's second case: a cell whose grey hint is a group (`DD`)
  holds the group and is a field of its own, whatever its width (it never joins a comb).
- **Tests.** The `flat_wide_cells` strict xfail is removed (it passes; it fails with the old
  limit); a unit test for 28 pt group cells (fails without the group rule) and the hinted-part
  split of group cells. Only the rule 3 xfail (`flat_label_inside`, fix 4) is left.
- **Effect.** Only #2, #3 and #25 change, and only those four rows (each now one comb, labelled
  "Account No.", "2. Date of Birth", "11. AADHAR No."). From scratch unchanged (no wide cells on
  #21 / #41). Comb precision stays 100 % (99/99).
- **Known limitation.** A run of two or three separate boxes up to 30 pt wide, close together
  with no text between them, would be read as one comb; none on dev.

**Fix 4 — labelling rule 3, label inside a cell** (`fdbb165`, report
`step11-4-label-inside-20261022-fdbb165`; labels v4).
- **What the dev forms show.**
  - #30's 14 misses: a ruled table with one cell per row (x 55–562), the bilingual label at the
    cell's left edge, then the blank. Two rows have a second phrase: "(Yes / No)" after the blank,
    and "ई-मेल न० (E-Mail ID)" between two blanks. One miss is the second line of the office-use
    box at the top of the page (the blank after "नामांकन संख्या :").
  - #1 page 4's 6 remaining misses: signature boxes drawn as cells, with the caption
    "(Signature of the Applicant/Thumb impression of the Applicant)" at the bottom; labelled above
    the caption.
  - #6's one miss, counted under rule 3 in the pre-tuning analysis, lies only inside the page
    border, not in a cell of its own: not rule 3, unchanged.
- **Rule** (the README's rule 3). In a drawn cell with text inside, a caption at the bottom (all
  the text in the lower part, at least 2 em of space above it and less below it than above) leaves
  the space above it as the entry, full cell width. Otherwise each text line that starts at the
  cell's left edge (within 2 em) has a blank after each of its phrases, up to the next phrase or
  the cell's edge (0.3 em from either), between the cell's other text lines; a blank needs at
  least 5 em. The label is the phrase before the blank (or the caption). Skipped:
  - frames (cells around other cells);
  - the label cells of a table: another cell starts at the cell's right edge, on the same row,
    and that cell is the entry;
  - cells holding a drawn entry (a leader or a line);
  - photo and thumb-impression boxes (the words "photo" / "thumb"), unless the text also asks for
    a signature ("sign": #1's captions offer a signature or a thumb impression);
  - a phrase that ends a sentence (a last word of four or more letters ending in a full stop, so
    "No." is not one): a notice or an instruction, not a label.
- **How the exclusions were chosen.** A read-only prototype over all scored pages listed every
  candidate. Without exclusions it found the 14 #30 blanks and 49 false positives:
  - 31 in table label cells (#2's left column, #6's nominee and guardian tables, #21's bank
    table, #25's "State");
  - centred headings and captions ("POSB account details", "(कार्यालय उपयोग हेतु)", #1's
    applicant captions);
  - #3's photo box;
  - the headings of #1 page 4's witness cells, whose entries are drawn leaders;
  - short trailing gaps: 4.4 em of cell padding after #30's "(Yes / No)", #2's "YES" / "NO" and
    "(If applicable)". The smallest real blank is 9.4 em, so 5 em.

  The caption case found #1's 6 signature boxes. As first written it also boxed the space above
  text in the middle of a box (#1 page 1's rubber-stamp box, #3 page 2's signature box, neither
  labelled), hence "less space below than above". The full-stop rule comes from the pinned
  `flat_boxes` fixture (a framed notice, approved in Step 4 as no entry), not from dev: it changes
  no dev candidate.
- **Tests.** The `flat_label_inside` strict xfail is removed (it passes); it was the last one, so
  `STEP_11_RULES` is gone. New unit tests (two labels in one cell, table label cells, room, centred
  text and a stamp box, a cell with a drawn entry, a signature caption that mentions a thumb
  impression, sentence ends); each one fails with its exclusion disabled (checked one by one).
- **Effect.** On the scored pages only #1 and #30 change; no false positive added. From scratch
  unchanged: no candidate on #21 or #41. IoU ≥ 0.5 finds 10 of the 20 new matches. The other 10
  are the same writing spots with larger boxes: full cell height on #30's rows (27 pt; the labels
  are 13–19 pt), and full cell width on #1's signature boxes (268 pt; the labels about 160).
- **Outside the scored subset** (#1 pages 5, 8 and 9, looked at on local renders only, not tuned
  on): 7 boxes added, 1 removed. (First written as "not labelled": wrong. These pages had
  submitted pre-filled boxes from `flat@5fe80d0` and were only outside the subset. They are scored
  from labels v5: see "Held-out check of rule 3".)
  - 3 look right: the signature boxes above the captions on page 5 (2) and page 9.
  - 4 look wrong: on page 8, the space above a bottom-aligned "Yes" in a tall table row, the gap
    after a bold heading row in a table ("C For Association of persons…"), and a blank in a
    notes block after "…in Sl. No. 16." (a sentence ending in a number, which the full-stop rule
    does not catch); on page 9, the trailing gap in a table header cell.
  - Removed: page 9's "Date:" colon blank. It ran across the page through the drawn signature box,
    so it now overlaps the new signature box and is dropped (it was the wrong shape before).

  See Known limitations.

**Fix 6 — rounded boxes** (`9146cfb`, report `step11-6-rounded-boxes-20261022-9146cfb`; labels v4).
- **What the dev form shows.** #41's 8 Yes / No / NA cells (24 × 11 pt, orange outline) are
  rounded rectangles drawn as four lines and four corner curves, not as `re` items. The extractor
  saw only the straight lines: the top and bottom edges (20.3 pt) became two drawn lines, and the
  short sides, cut off by the corner curves 1.8 pt away, did not touch them, so they were not
  taken for table rules. The bottom line's entry matched the label; the top line's entry, above
  the cell, was a false positive (8 of #41's 9).
- **Rule.** A stroked, closed run of lines and curves whose straight lines all lie on its
  bounding box (a box with rounded corners or rounded ends) is handled like a drawn rectangle:
  one box (or checkbox), structural edges that are never writing lines. Curves-only shapes
  (circles) are not boxes.
- **Scope: stroked outlines only.** A read-only count over the dev forms found such shapes on
  #41 (8, stroked), #1 (1, a fill-only logo) and #3 page 2 (80, fill-only: glyphs drawn as
  paths). Applying the rule to fill-only shapes too would drop their straight edges as segments;
  on dev that removes one box on #3 page 2, a 3.3 × 4.2 pt box that matches a label (label
  question 6 below). Fill-only shapes are left as before, so the fix changes #41 only.
- **Tests.** New fixture `flat_rounded_boxes` (three rounded cells, a rounded checkbox, a rounded
  remarks box): it fails without the fix. Unit tests: a circle is no box; a fill-only rounded
  shape is left as before (fails without the stroke condition).
- **Effect.** Only #41 changes: each cell is now one box (16 boxes → 8), every match kept, 8
  false positives gone. From scratch precision 81.1 → 90.9 % (writing spot), recall unchanged.
  #41's last false positive is the "Documents Enclosed:" colon blank (fix 5). The cells' labels
  are mostly empty or a neighbouring line's words, as before (label text is Phase 3's concern).

**Fix 7 — hyphen leaders** (`714c3d3`, report `step11-7-hyphen-leaders-20261022-714c3d3`; labels
v4; plan shown to and approved by the human before any code, 2026-10-22).
- **What the dev forms show.** After fix 6, #21 (from scratch) had 3 misses, all printed as runs
  of hyphens (U+002D), and no hyphen-related false positive:
  - page 1 `p0_l018`: 58 hyphens alone on their line (x 324–501), a signature line above
    "(Signature of the Nominee* /Claimant)";
  - page 2 `p1_l003`: "from the `----------------------`(Name of Insurance Company)", the run
    touching the next word;
  - page 2 `p1_l004`: "Account No.,`---- -----------------`", two runs one space apart.
- **Risk scan before the rule** (read-only; runs of 2 or more of U+002D, U+2010–U+2015, U+2212
  and the full-width forms):
  - On every scored dev page, the only runs are these four, all on #21. There is no dash
    separator, text table rule, `---` placeholder or `--` anywhere else, and none on the unscored
    pages either.
  - The dev forms have 166 single dashes (`E-mail`, `Rs.2,00,000/-`, `Date:-`, ranges such as
    `2023-24`).
  - So the false-positive risks have no real example on dev and are covered by synthetic negative
    tests only.
- **Rule.**
  - Hyphens, the Unicode hyphen, en and em dashes are leader characters.
  - A run of at most 3 dots and fewer than 4 dashes stays in the word, so `E-mail`, `2023-24`,
    `/-`, `:-` (fix 5's colon ending), `Rs.-` and a `---` placeholder remain text. Before, dots
    alone did this; text without dashes extracts as before.
  - A leader counts with at least 4 dashes after the usual merge (runs on one baseline at most
    0.5 em apart).
  - A dash leader with no word containing a letter or digit on its row is a separator, not an
    entry, when it spans at least 80 % of the page's text width, or when `+` / `|` joints sit on
    its row (a table rule drawn in text). 80 % is a judgement value: dev has no separator to tune
    it on. #21's signature line, alone on its row, spans 37 %.
  - Underscore and dot leaders are unchanged.
- **Tests.**
  - New fixture `flat_hyphen_leaders`: a labelled run, a run touching the next word, two runs
    merged, an en-dash run, and a signature dash line above its caption. It fails without the fix.
  - Negative tests: short dash runs stay in their words and give no field; `H. No. --- ,
    Sector 4` gives none (fails with a minimum of 3); a dash line across the text width gives
    none; a `+-----+-----+` table rule gives none; and a wide dash line after a label stays an
    entry.
  - Each test was checked to fail with its guard disabled.
- **Effect.**
  - Only #21 changes, on every dev form and page (scored or not): 3 boxes added, none removed,
    and the 3 misses found. From scratch writing spot: recall 89.6 → 94.0 %, precision 90.9 →
    91.3 %. #41 and every pre-filled form are unchanged.
  - **IoU ≥ 0.5 precision dips** (overall 90.1 → 89.8 %, from scratch 43.9 → 43.5 %). Only 1 of
    the 3 new matches (`p1_l004`) also matches at IoU ≥ 0.5; the other two reach 0.485 and 0.49,
    because the hand-drawn boxes are about 0.5–0.75 × the detector's 1.2 em line height. This is
    the box-height convention, as in fix 5, not a detection error.
  - One existing #21 box (the underscore line under `p1_l003`) has a different label text: "from
    the" instead of "from the ----------------------(Name", since the dashes are no longer a word.
    The new signature line's label is the line above ("…may fill in the claim form."), not its
    caption below, as for every leader (label text is Phase 3's concern).

**Label question from fix 6 (reported to the human 2026-10-22; decided the same day: remove it, as pending label fix 2).**
6. **#3 page 2, `p1_l041`** (`text`, x 55.8–59.1, y 444.8–449.0: 3.3 × 4.2 pt). It sits exactly
   on one of the page's small fill-only shapes, glyphs drawn as vector paths, which the detector
   rebuilds into a tiny cell; the label has the detector's box to the tenth of a point (#3 was
   pre-filled). Nobody writes in a 3 pt area, so it looks like a kept pre-filled box rather than
   an entry area. Removing it would go **against** the detector (its box would become a false
   positive). Fix 6 does not touch it (fill-only shapes are left as before), so the numbers above
   do not depend on the answer.

**Label question from fix 4 (reported to the human 2026-10-22; decided the same day: add the box, as a pending label fix).**
5. **#3 page 2, the applicant's signature box** (x 411–565, y 579–632, right of the arrow at the
   bottom of the page). A drawn box with "Signature/Thumb impression of the Applicant" and
   "Please sign in black ink only" printed in its middle; no label. Under the labelling rules
   (signature areas get a `text` box) it would be a `text` box, as #1 page 4's applicant
   signature cells are. The detector does not box it either (the text is in the middle of the
   box, not a caption at its bottom), so the numbers above do not depend on the answer.

   **Decision (human, 2026-10-22):** yes, under the labelling rules it is a `text` box, the same
   as #1 page 4's. This correction goes **against** the detector, not in its favour: the detector
   does not find the box, so adding it adds a miss (#3 recall falls). Not edited now; it is the
   first entry in "Pending label fixes".

   **Changed by the human during v5 (2026-10-26):** the applicant's writing spot is the empty area
   to the left of the caption box, where the printed arrow points (between the PHOTO box and the
   arrow). The caption rectangle (x 411–565, y 579–632) is only an instruction label and gets
   **no** box. That area was already labelled in v4: `p1_l047` (`text`, 132.0, 581.1, 361.0,
   633.1). So no edit was needed and the counts above do not move.

**Pending label fixes** (human decision 2026-10-22). Label corrections decided during Step 11
are collected here and not applied one by one. At the end of Step 11 they are applied once, as
**labels v5**, by Claude Code in Label Studio (existing annotations only, backup first), verified
by the human in Label Studio before export, then exported, converted and committed; the whole
ablation table is then re-run once on v5 (each row from a worktree at its commit), keeping the v4
table as history. Each entry records whether the correction favours the detector or goes against
it.

| # | Form, page | Correction | Decided | Direction |
|---|---|---|---|---|
| 1 | #3, page 2 | add a `text` box for the applicant's signature box (x 411–565, y 579–632; label question 5). Rule: a box whose text asks for a signature gets a `text` box even if it also mentions a thumb impression (`eval/labelling/README.md`, added 2026-10-22) | human, 2026-10-22 | against the detector (an added miss) |
| 2 | #3, page 2 | remove `p1_l041` (`text`, 3.3 × 4.2 pt at x 55.8, y 444.8, over a vector-drawn letter; label question 6): an anchoring leftover from the pre-filled boxes. The human verifies it in Label Studio during v5 | human, 2026-10-22 | against the detector (its box becomes a false positive) |
| 3 | #1, pages 5, 8, 9 | label from scratch (no pre-filled boxes) and add the three pages to the scored subset, as a held-out check of rule 3's precision (fix 4; see Known limitations). `subset.py` changes with the v5 conversion, not before. Any decision to tighten rule 3 waits for these v5 numbers | human, 2026-10-22 | neutral (new pages, labelled without the detector) |
| 4 | #21, page 1 | decide blind in Label Studio: the space above "(Signature of authorized official of the Post Offc)" (caption at x 326–548, y 696; nothing drawn, not labelled). Under the labelling rules, signature and office-use areas get a `text` box. Found by the fix 8 scan | human, 2026-10-22 (to decide during v5) | against the detector if added (the detector does not box it now: recall falls) |

**All four applied as labels v5** (2026-10-22 to 2026-10-26).
- **Export.** `formpilot-dev-boxes-20261026-124015.json`, taken by Claude Code from the live
  project after the human's checks; converted with `make label-convert … OVERWRITE=1`.
- **Diff against the v4 export:** only tasks 1, 24, 25 and 27 changed, as listed below.
  - The label files changed only on #1 (482 → 477 fields), #3 (192 → 191) and #21 (47 → 48).
  - Every file's `source` line names the new export, as at every conversion.
- **Two earlier exports were not converted:** `project-1-at-2026-10-22-18-41-ca445175.json` and
  `…20261023-002821/-003137.json`. Task 27 was still unchanged in them.

| # | Status | Provenance |
|---|---|---|
| 1 | **already satisfied in v4, no edit** | The human changed the fix during v5: the writing spot is the empty area the printed arrow points to, left of the caption box, and the caption rectangle gets no box. `p1_l047` (132.0, 581.1, 361.0, 633.1) already covers it (label question 5). |
| 2 | **applied** | Human decision, applied by Claude Code through the Label Studio database (the human's deletion in the browser had not been saved): `p1_f043` (= `p1_l041`) removed from annotation 27, 66 → 65 regions, refusing unless exactly that region went and the annotation was unchanged since 2026-10-19 13:53. Database backup first, and only annotation 27 differed from it afterwards. **Verified by the human** in Label Studio before the export. The backup was in the session scratchpad and was later lost when `/tmp` was cleared; the v4 export keeps the annotation's earlier state. |
| 3 | **applied, with a caveat** | #1 pages 5, 8, 9 added to `subset.py` (and the README's subset table); the pages were labelled by the human in Label Studio. Task 21 (page 5): the pre-filled boxes re-reviewed and kept as correct (9 boxes). Task 24 (page 8): relabelled from scratch, all 6 pre-filled boxes deleted; the page has no entry area (an instructions-only reference table). Task 25 (page 9): the pre-filled boxes re-reviewed; only the name row changed, split by rule 1 into first / middle / last name combs (1 comb + 1 text box → 3 combs; 66 → 67). **Caveat:** 2 of the 3 holdout pages are re-reviewed pre-filled pages from `flat@5fe80d0` (before fix 4), so the holdout is not fully unbiased. |
| 4 | **applied: box added** (the human's blind decision) | Task 1 (#21 page 1): one `text` box at (328.2, 667.2, 539.2, 690.3), the space above the caption. Against the detector: #21 FN 0 → 1. |

**Label question from fix 5 (reported to the human 2026-10-21; decided the same day: add both boxes, see "Fourth relabel by Claude Code").**
4. **#21 page 2, "Policy No:" and "Name of the Post Office:"** (top of the discharge receipt, x
   120–545 and 185–545, y 82–108). Nothing is drawn after either colon; the policy number and the
   post office name are written there, as on page 1's "2. POLICY NO. :" (labelled). Under the top
   rule each would be a `text` box; neither is labelled (#21 was labelled from scratch). They
   count as 2 false positives now.

**Label questions from fix 2 (reported to the human 2026-10-21; decided by the human the same day, see "Third relabel by Claude Code").**
1. **#1 page 1, `p0_l023` (date of birth).** 8 touching cells hinted `D D M M Y Y Y Y` are labelled
   as one comb box. Rule 1 says a hinted date is three boxes, and the other seven hinted dates
   on #1 and #3, built the same way (e.g. `p0_l000`–`p0_l002`, top right of the same page), are
   labelled as three.
2. **#1 page 4, six `INITIALS` boxes** (x 335.5–390.8, y 697–794, "for office use only"). Each box
   has the word `INITIALS` printed in grey inside; none is labelled. Under the labelling rules
   (grey-hinted cells are entry areas; office-use areas get a `text` box) they would each be a
   `text` box.
3. **Splits with no printed boundary** (consistent with the top rule, not with rule 1's wording):
   the STD rows `p0_l118` / `p0_l119` and `p0_l120` / `p0_l121` (15 cells hinted `S T D` in the
   first three, labelled 5 + 10) and name row 2 `p0_l018` / `p0_l019` (one `LASTNAME` hint in the
   middle, labelled 21 + 18 cells). Rule 1 as written gives one box per row. Recorded as
   detector misses unless the human decides otherwise.

## Step 11 — closing (human decision, 2026-10-22)

**Tuning is closed at fix 7.** Fixes done, in order: 1, 2, 5, 3, 4, 6, 7, one commit each, each
measured on the dev labels only. Fix 8 was not done (below). No test-set form was run.

**Final ablation table, labels v4** (writing spot unless the column says IoU; full table with Δ
and per-form changes: "Step 11 — tuning on dev: ablation table").

| Row | Commit | Pooled P / R | Macro P / R | From scratch P / R | Pre-filled P / R | IoU ≥ 0.5 P / R |
|---|---|---|---|---|---|---|
| Baseline v4 | `0ee9999` | 86.8 / 77.5 | 88.3 / 77.0 | 77.1 / 55.2 | 87.8 / 80.2 | 83.4 / 74.4 |
| Fix 1 — D8 gap split | `f535a3f` | 86.9 / 77.8 | 88.4 / 77.1 | 77.1 / 55.2 | 87.8 / 80.5 | 83.5 / 74.8 |
| Fix 2 — rule 1, hinted rows | `9541889` | 90.1 / 84.4 | 89.3 / 79.5 | 77.1 / 55.2 | 91.2 / 87.9 | 86.8 / 81.4 |
| Fix 5 — blanks after a colon | `5fef220` | 89.7 / 88.3 | 89.4 / 85.2 | 81.1 / 89.6 | 90.9 / 88.1 | 84.0 / 82.6 |
| Fix 3 — rule 2, wide cells | `c41510e` | 96.3 / 88.9 | 94.6 / 85.8 | 81.1 / 89.6 | 98.6 / 88.8 | 90.2 / 83.3 |
| Fix 4 — rule 3, label inside a cell | `fdbb165` | 96.5 / 92.1 | 94.6 / 90.2 | 81.1 / 89.6 | 98.7 / 92.4 | 88.9 / 84.9 |
| Fix 6 — rounded boxes | `9146cfb` | 97.8 / 92.1 | 97.3 / 90.2 | 90.9 / 89.6 | 98.7 / 92.4 | 90.1 / 84.9 |
| **Fix 7 — hyphen leaders (final)** | `714c3d3` | **97.8 / 92.6** | **97.4 / 90.7** | **91.3 / 94.0** | **98.7 / 92.4** | **89.8 / 85.0** |

Baseline v4 → fix 7, from the two reports:
- pooled writing spot +10.9 / +15.1 (TP 482 → 576, FP 73 → 13, FN 140 → 46);
- from scratch +14.2 / +38.8 (TP 37 → 63, FP 11 → 6, FN 30 → 4);
- pre-filled +10.9 / +12.3;
- macro +9.0 / +13.7.

From-scratch IoU ≥ 0.5 precision ends 0.3 below the baseline (43.8 → 43.5 %). The colon blanks
(fix 5) and hyphen leaders (fix 7) are 1.2 em high, while the hand-drawn boxes on #21 and #41
are lower (the box-height convention); the writing spots match.

All of these are dev numbers, measured on labels v4.

**Re-run on labels v5** (2026-10-26, with #1 pages 5, 8, 9 now scored; the table is in the
ablation section):
- Fix 7 measures 95.1 / 92.4 pooled, 91.3 / 92.6 from scratch and 95.6 / 92.4 pre-filled
  (TP 645, FP 33, FN 53).
- Rule 3's precision on the held-out pages is 3 / 7.

The remaining-errors inventory below is the v4 one.

**Fix 8 (signature area above its caption) is deferred to Phase 3** (human decision, 2026-10-22).
- It could help only pre-filled forms: at best +10 of the 11 misses of its kind (#2, #3, #25,
  #30).
- It risks 1–2 false positives on #21 and #41, our only from-scratch forms: #41's "Signature of
  BPM/SPM/PM/ CPC in-Charge" is a block heading, and #21's "(Signature of authorized official of
  the Post Offc)" has empty space above and no label (pending label fix 4).
- It also overlaps the open Phase 3 signature decision (flat signature areas are boxed, AcroForm
  signature widgets are skipped).
- Signature-above-caption detection will be designed in Phase 3, together with that decision
  (`docs/PLAN.md`, Phase 3).

**Remaining errors at fix 7** (labels v4, scored dev pages: 46 misses, 13 false positives). The
full inventory, with page, text and bbox for each, is in
`eval/reports/phase2-detection-dev-step11-7-hyphen-leaders-20261022-714c3d3-inventory.md`.

| Group | Misses | False positives | Forms | Status |
|---|--:|--:|---|---|
| Tables whose columns exist only as header text (E) | 19 | 3 | #23 | known limitation: needs table-structure inference |
| Signature area above its caption, nothing drawn (D) | 11 | — | #2, #3, #25, #30 | deferred to Phase 3 (fix 8) |
| Tick spots with no printed square (F) | 10 | — | #2, #41 | known limitation: nothing to detect |
| Blank after a label without a colon ("To,", "Countersigned by", "(   )"), nothing drawn | 3 | — | #6, #23, #39 | known limitation |
| STD code parts not split | 2 | — | #1 | known limitation (fix 2) |
| Colon inside a frame (between fix 5's and fix 4's rules) | 1 | — | #3 | known limitation |
| Headings ending in a colon | — | 5 | #21 ×2, #23 ×2, #41 | known limitation (fix 5) |
| Empty "OR" separator column (J) | — | 3 | #21 | known limitation |
| Dashed rules drawn across the page | — | 2 | #3 | known limitation |
| **Total** | **46** | **13** | | |

From scratch: #21 has 0 misses and 5 false positives, #41 4 misses and 1 false positive; none of
them is in fix 8's scope.

**OpenCV raster fallback: stays in Phase 6.** The pre-tuning error analysis found no miss caused
by boxes drawn as images, and none of the fixes needed one. No new dependency was added in
Step 11.

**Integration tests at the end of Step 11: done** (the last item of the Step 11 plan,
2026-10-22). `make test-int` at `32c2c34`: 66 passed, 824 deselected.

## v1 re-scope and milestone gates (human decision, 2026-10-26)

**Why.** Phase 2 took about two weeks, mostly because of process: a stop after every step, an
ablation row per fix, and five relabels. The human wants a complete, measured, live v1 soon
(placement season) without lowering quality.

**Decisions.**
- **v1 scope** (PLAN.md "v1 scope and milestones", SPEC §2):
  - v1 is flat PDFs end to end, plus from the old Phase 7: a live demo, the CI eval gate, and a
    detection release measurement on the 6 test forms, labelled from scratch before the README.
  - After v1: AcroForm filling, drag/resize in review, fix 8, Phase 6 (OCR), Phase 7's provider
    comparison.
  - LLM parsing of free-text answers stays in v1 (SPEC §6.5).
  - "Questions per form" is reported, not gated.
- **Milestone gates** (CLAUDE.md §1): one approved plan per milestone, covering its IR / database
  / API changes and dependencies. Stops happen only at the milestone's end, for an unplanned
  decision, under the stuck rule, or on a metric drop.
- **"In my own words" checkpoint** at the end of every milestone (about 10 minutes); the final
  teach-back comes before the README.
- **Privacy invariant** (CLAUDE.md §3, SPEC §11):
  - Values of the sensitive types (D2) and of the phone types never reach a remote LLM provider.
  - Non-sensitive free text (such as an address) may, and the README says so.
  - Groq is used only if its free tier needs no card or payment; Ollama stays the local default.
- **Public demo rules** (SPEC §11): synthetic forms only, with a visible banner; the 24 h expiry
  on everything; no real documents seeded. The deploy platform is decided in the M4 plan.
- **Language:** repository files stay in English.

**Also corrected:** CLAUDE.md §3 listed four sensitive types; D2 had added `voter_id`.

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

- **The 30 pt comb cell limit was chosen on dev with a narrow margin (Step 11, fix 3).** It must
  let #25's 27 pt one-character cells form a comb and must keep #1's 33 pt separate office-use
  boxes apart; 30 pt is the only round value checked that does both, and the margin is 3 pt on
  either side. It is a dev-tuned threshold and must be checked on the test set (at the release
  measurement, when the human asks for it). A run of two or three separate boxes up to 30 pt
  wide, close together with no text between them, would be read as one comb; none on dev.
  **Possible future improvement:** detect comb cells by their shape rather than an absolute
  width: near-square cells (or cells of one repeated size) in a uniform row of several equal,
  touching cells, so the decision does not depend on how wide a form draws its cells.

- **Rule 3 reads layout, not meaning (Step 11, fix 4).** Whether text in a cell is a label with a
  blank after it, a heading, a table value or an instruction is decided from position only (left
  edge, centred, bottom caption, a cell to the right, 5 em of room, a sentence-ending full stop).
  On dev's tuning pages this adds no false positive. #1 pages 5, 8 and 9 (not tuned on; at the
  time outside the scored subset and judged by eye) are the first held-out sign of rule 3's
  precision on unseen pages:
  - **7 new boxes, 4 of them wrong:** a bottom-aligned table value, a heading row and a header
    cell in tables, and a notes block. The other 3 are signature boxes.
  - **1 entry lost:** page 9's "Date:" colon blank, which now overlaps the new signature box. It
    did not match its label either, so it costs nothing in the score.

  **Measured on labels v5** (the three pages scored): rule 3 precision on them is **3 / 7 =
  42.9 %**, and fix 4 adds 3 matches and 3 false positives there. Two of the three pages are
  re-reviewed pre-filled pages, so the check is not fully unbiased. Any decision to tighten rule 3
  is the human's, on these numbers. Rule 3's precision must also be checked on the test set (at
  the release measurement, when the human asks for it). The photo / thumb / signature words are English only; a Hindi-only photo
  box with its words printed inside could get a box.

- **Flat detection errors left at the end of Step 11.** 46 misses and 13 false positives remain
  on the scored dev pages (labels v4). They are grouped, with counts and status, in "Step 11 —
  closing"; the full list is in the fix 7 report's inventory notes. The main ones:
  - tables whose columns exist only as header text (needs table-structure inference);
  - tick spots with no printed square;
  - headings ending in a colon (fix 5);
  - the empty "OR" separator column;
  - blanks after a label without a colon;
  - signature areas above a caption with nothing drawn (deferred to Phase 3).

- **STD code parts are not split (Step 11, fix 2).** On #1 page 1 the two telephone rows are
  15 touching cells hinted `S T D` in the first three; the labels split them 5 + 10 (STD code,
  then number; the human's decision, top rule). Nothing printed marks the split, and labelling
  rule 1 joins empty cells after the last hint to the last part, so the detector gives one
  15-cell comb per row: 2 misses on dev. Splitting would need knowledge of STD code lengths.

- **Searchable scans.** A scanned page with an OCR text layer (invisible text over a full-page
  image) has enough characters, so it is `ok`, but its entry boxes are part of the image, not
  vector drawings; the Phase 2 flat frontend will find few or no fields there. None of the dev
  forms is like this. To revisit with OCR in Phase 6.
- **Undetected garbling.** Unicode Devanagari with wrongly extracted vowel signs (form #30) is
  not detected by the heuristics and stays `ok`.

## In my own words

