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

## Known issues

- **PyMuPDF SWIG `DeprecationWarning` on import (suppressed in pytest).** PyMuPDF 1.28.2's
  SWIG-generated extension types (`SwigPyPacked`, `SwigPyObject`, `swigvarlink`) have no
  `__module__`, and Python 3.12 warns when they are imported. It is inside PyMuPDF and harmless.
  Python attributes the warning to `importlib._bootstrap`, not to `pymupdf`, so the
  `filterwarnings` entry in `backend/pyproject.toml` cannot be scoped by module; it matches only
  these three exact messages as `DeprecationWarning`. Revisit when PyMuPDF ships bindings built
  with a SWIG version that sets `__module__`.

## In my own words

