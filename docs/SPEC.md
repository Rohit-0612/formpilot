# FormPilot — Project Specification

Version 1.0. This document is the architecture contract. Changes to sections 4 (Form IR),
7 (data model) or 8 (API) require an explicit decision recorded in `docs/decisions/`.

---

## 1. Problem and pitch

People fill the same details (name, parents' names, address, date of birth, PAN, bank details)
into different forms again and again: scholarship forms, college and onboarding forms, bank and
KYC forms. Many of these forms are PDFs, and many are not even fillable.

**FormPilot** turns "a 20-page form" into "7 questions and a review screen":

1. Upload a form.
2. The system detects the fields and understands what each one asks for.
3. Known values come from the user's profile vault; the rest are asked as a few grouped questions.
4. Every value is validated (formats, checksums, fits in the box).
5. The user reviews each field with its **source** (profile, answer, inferred) and confidence.
6. The user downloads the filled PDF.

Interview framing: *a document-understanding pipeline with a compiler-style architecture —
multiple input frontends into a common Form IR, rule-first + LLM field understanding with
schema-constrained outputs, deterministic validation, human-in-the-loop review, and an eval
harness gated in CI.*

## 2. Scope

**v1 (Phases 1–5):** flat (text-layer) PDFs end to end. The fillable (AcroForm) path is kept as a
small secondary path, tested on synthetic fixtures.
**v2 (Phases 6–7):** scanned PDFs and pages with unusable text layers, via OCR; provider
comparison, CI eval gate, deploy.
**Stretch (Phase 8):** photo of a paper form (perspective correction + numbered guide), MCP server.

Scope set after the Phase 0 reality check: 0 of 20 collected real forms were fillable (17 flat,
3 scanned). See `docs/decisions/phase-0.md`.

**Non-goals:** auto-submitting web forms, handwriting recognition, legal drafting,
"works for every form" claims. MVP targets 2–3 form families chosen in Phase 0.

## 3. Architecture overview

Compiler analogy: **frontends** turn any input into one intermediate representation (the Form IR),
**passes** enrich the IR, **backends** turn the IR into outputs.

```text
                 FRONTENDS (input -> FormIR)
  acroform.py        flat.py              scanned.py            photo.py (stretch)
  widgets ->         words+lines ->       OCR words+lines ->    deskew -> scanned
  fields             blanks -> fields     blanks -> fields
        \                 |                    |                    /
         +----------------+--------------------+-------------------+
                                   |
                               FormIR
                                   |
                 PASSES (FormIR -> FormIR), in this order
   1. understand   rules first (keyword dictionary), LLM for unresolved fields
   2. match        semantic type -> profile vault value (deterministic)
   3. questions    group unfilled fields into the fewest questions
   4. answers      (runs when the user answers) parse answers into field values
   5. validate     format / checksum / option checks (deterministic)
   6. fit          will the value fit the box at >= min font size?
                                   |
                     HUMAN REVIEW (web UI): edit, confirm, adjust box
                                   |
                 BACKENDS (FormIR -> output)
   acroform_fill.py      overlay.py                 guide.py (stretch)
   set widget values     draw text in bbox          numbered guide sheet
```

Runtime components:

```text
Next.js web  --->  FastAPI API  --->  PostgreSQL (users, documents, IR versions, audit, vault)
                        |
                        +--> Redis  --->  arq worker (analyze / render / cleanup jobs)
                        |                      |
                        +--> File storage      +--> LLM provider (Ollama local | Groq API | Fake)
```

Why a worker: OCR and LLM calls take seconds to minutes and must not run inside an HTTP request.
The API returns `202 Accepted` with a job id; the web app polls job status.

## 4. The Form IR (core contract)

Defined in `backend/app/ir/models.py` with Pydantic v2. Serialized as JSON and stored per version.

```python
class SourceKind(str, Enum):
    FILLABLE = "fillable"        # AcroForm widgets present
    FLAT_TEXT = "flat_text"      # text layer, no widgets
    SCANNED = "scanned"          # image-only pages
    PHOTO = "photo"              # camera image (stretch)

class FieldKind(str, Enum):
    TEXT = "text"; CHECKBOX = "checkbox"; RADIO = "radio"
    CHOICE = "choice"; DATE = "date"; SIGNATURE = "signature"; UNKNOWN = "unknown"

class BBox(BaseModel):
    page: int                     # 0-based
    x0: float; y0: float; x1: float; y1: float   # PDF points, origin TOP-LEFT

class Option(BaseModel):          # for checkbox / radio / choice
    value: str                    # value to write into the PDF (e.g. "/On", export value)
    label: str | None = None
    bbox: BBox | None = None

class ValueSource(str, Enum):
    PROFILE = "profile"; USER_ANSWER = "user_answer"
    LLM_INFERRED = "llm_inferred"; USER_EDIT = "user_edit"; NONE = "none"

class FieldStatus(str, Enum):
    DETECTED = "detected"; FILLED = "filled"; NEEDS_INPUT = "needs_input"
    NEEDS_REVIEW = "needs_review"; CONFIRMED = "confirmed"; SKIPPED = "skipped"

class ValidationResult(BaseModel):
    validator: str                # e.g. "pan_format", "fits_box"
    ok: bool
    message: str | None = None    # human-readable, never contains the value itself

class Field(BaseModel):
    id: str                       # stable within a document, e.g. "p0_f012"
    kind: FieldKind
    native_name: str | None       # AcroForm field name, if any
    label_text: str | None        # nearest label text
    context_text: str | None      # section heading / surrounding text
    bbox: BBox
    max_chars: int | None = None
    options: list[Option] = []
    semantic_type: SemanticType = SemanticType.UNKNOWN
    semantic_confidence: float = 0.0
    semantic_method: Literal["rule", "llm", "user", "none"] = "none"
    value: str | None = None
    value_source: ValueSource = ValueSource.NONE
    validations: list[ValidationResult] = []
    status: FieldStatus = FieldStatus.DETECTED

class TraceEvent(BaseModel):
    pass_name: str; field_id: str | None; change: str; at: datetime

class FormIR(BaseModel):
    schema_version: int = 1
    document_id: UUID
    source_kind: SourceKind
    page_sizes: list[tuple[float, float]]   # (width, height) in points
    fields: list[Field]
    trace: list[TraceEvent] = []
```

Rules: field ids are never reused within a document; passes never delete fields (they may mark
them `SKIPPED`); every change is appended to `trace`.

## 5. Semantic types

Defined in `backend/app/ir/semantic_types.py` as `SemanticType(str, Enum)`, each entry with:
a description (used in the LLM prompt), keyword patterns (English and common Hindi transliterations
such as "pita ka naam"), the profile key it maps to, a `sensitive` flag, and default validators.

Initial list (extend only via a decision record):

- Identity: `full_name`, `first_name`, `middle_name`, `last_name`, `father_name`, `mother_name`,
  `guardian_name`, `spouse_name`, `date_of_birth`, `age`, `gender`, `nationality`, `category`,
  `marital_status`
- Contact: `email`, `phone_mobile`, `phone_alternate`
- Address (current and permanent variants): `address_line1`, `address_line2`, `city`,
  `district`, `state`, `pincode`, `country` — as `current_*` and `permanent_*`
- IDs (sensitive): `pan`, `aadhaar`, `passport_number`, `voter_id`
- Bank (sensitive): `bank_name`, `bank_account_number`, `ifsc`, `bank_branch`
- Education: `institution_name`, `course`, `enrollment_number`, `year_of_study`,
  `percentage_or_cgpa`, `passing_year`
- Form-local: `date_of_filling`, `place`, `signature`, `declaration_checkbox`
- Fallbacks: `other` (understood but not in the vault, always asked), `unknown`

## 6. Pipeline details

### 6.1 Detection (frontends)

`frontends/detect.py` decides `SourceKind`:
widgets present → `FILLABLE`; else meaningful text layer on most pages → `FLAT_TEXT`;
else → `SCANNED`.

**Text-layer quality check.** A page's text layer is used only if it looks like real text. If it
looks garbled (e.g. legacy non-Unicode Hindi fonts, whose glyphs extract as Latin-extended letters
or as ASCII letters mixed with punctuation), that page is treated like a scanned page and routed
to OCR.

**acroform.py (v1, secondary path; tested on synthetic fixtures).** Read widgets with PyMuPDF.
Map widget types to `FieldKind`; for checkboxes record on/off export values; for radio groups and
choice fields record `options`. Label text: the widget's tooltip/alternate name if present, else
the nearest text span to the left or above within a distance threshold. Convert rects to top-left
origin.

**flat.py (v1, primary path).** Extract words with coordinates (PyMuPDF). Detect entry areas:
underscore runs (`____`), horizontal drawing lines, empty rectangles, small squares (checkboxes)
using PyMuPDF drawings, with an OpenCV fallback on a rasterized page. Associate each entry area
with the nearest label (same row to the left, else directly above). Sanity checks: entry boxes
must not overlap each other; boxes smaller than the minimum font height are flagged.

**scanned.py (v2).** Rasterize at 300 DPI, OCR with Tesseract (`eng` + `hin`) to get
words with boxes, detect lines/boxes with OpenCV, then reuse the flat.py association logic.
Also used for pages whose text layer fails the quality check.

**photo.py (stretch).** Detect the page quadrilateral, apply perspective correction, then treat as
a scanned page.

### 6.2 Understanding pass (rules first, LLM second)

1. **Rule matcher:** normalized label + context against the keyword patterns from section 5.
   A unique strong match → `semantic_method="rule"`, confidence 0.95.
2. **LLM for the rest:** batch all unresolved fields of a page into one request:
   input `[{id, kind, label_text, context_text, options}]`, output
   `[{id, semantic_type, confidence}]` constrained to the enum via JSON schema. Validate with
   Pydantic; one retry on invalid output; otherwise `unknown`.
3. Current vs permanent address is decided from context (section headings), not just the label.
4. Self-reported LLM confidence is treated as a heuristic, not a probability. Fields below the
   review threshold (config, default 0.7) get status `NEEDS_REVIEW`.

The eval compares three modes: rules-only, LLM-only, rules+LLM. This comparison goes in the README.

### 6.3 Match pass

Deterministic lookup: `semantic_type → profile key → value`. Derived values are computed in code
(e.g. `full_name` from first/middle/last; `age` from `date_of_birth` and today's date;
`date_of_filling` = today). Filled fields get `value_source=PROFILE`, status `FILLED`.

### 6.4 Question planning pass

Group `NEEDS_INPUT` fields into questions using deterministic groups (address group, name group,
bank group, education group). One question per group, from templates in code. Checkbox/radio/choice
fields become multiple-choice questions using their `options`. Target: fewer questions than fields,
measured in eval.

### 6.5 Answer parsing

Structured answers (dates, choices) are parsed in code. Free-text answers for a group
(e.g. a full address) are parsed by the LLM into the group's fields via a Pydantic schema, then
validated. The user may tick "save to my profile" per answer (sensitive types require explicit opt-in).

### 6.6 Validation pass (deterministic)

| Semantic type | Rule |
|---|---|
| `pan` | `^[A-Z]{5}[0-9]{4}[A-Z]$` |
| `aadhaar` | 12 digits, first digit 2–9, Verhoeff checksum valid |
| `ifsc` | `^[A-Z]{4}0[A-Z0-9]{6}$` |
| `*pincode` | `^[1-9][0-9]{5}$` |
| `phone_*` | optional `+91`/`0`, then `^[6-9][0-9]{9}$` |
| `email` | standard email validation |
| `date_of_birth`, dates | valid date; output in the format hinted by the label (DD/MM/YYYY default); DOB not in the future |
| choice / radio | value must be one of the field's options |
| any text | `max_chars` respected if known |

Failures set status `NEEDS_REVIEW` with a message that never contains the value.

### 6.7 Fit pass

Compute text width at the default font size (config, default 10 pt) for the field box; shrink down
to the minimum (default 6 pt); if it still does not fit, flag `fits_box=false` for review.

### 6.8 Review (UI)

PDF rendered page by page with field boxes overlaid (colour by status). Side panel per field:
label, value, source badge, confidence, validation messages, edit box, confirm button. For flat
and scanned forms the user can drag/resize a box (`USER_EDIT` recorded in trace). Bulk action:
"confirm all fields with no warnings".

### 6.9 Rendering (backends)

- `overlay.py` (primary renderer in v1): draw text inside the bbox with the fit-pass font size;
  checkboxes get an "X".
- `acroform_fill.py` (secondary): write values into widgets (checkbox → its on-value), regenerate
  appearances, optional flatten.
- `guide.py` (stretch): numbered markers on the page image plus a list "Box 3: write ...".
Only `CONFIRMED` fields are rendered.

## 7. Data model (PostgreSQL)

- `users(id, email, password_hash, created_at)`
- `documents(id, owner_id, original_filename, sha256, source_kind, status, page_count,
  created_at, expires_at)` — status: `uploaded | analyzing | ready | rendering | done | failed`
- `form_ir_versions(id, document_id, version, ir_json JSONB, created_at)` — append-only
- `jobs(id, document_id, type, status, error, created_at, finished_at)` — types: `analyze`, `render`
- `profiles(user_id, encrypted_blob, updated_at)` — encrypted with Fernet; key from env
- `audit_events(id, document_id, field_id, event, actor, created_at)` — no values stored

Files (uploads, rendered outputs) live in a `Storage` interface; v1 uses a local volume.

## 8. API (FastAPI, prefix `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | JWT auth |
| POST | `/documents` | upload (multipart) → 202 `{document_id, job_id}` |
| GET | `/documents/{id}` | status, source kind, page count |
| GET | `/documents/{id}/pages/{n}.png` | rendered page image for the viewer |
| GET | `/documents/{id}/ir` | latest Form IR (sensitive values masked) |
| GET | `/documents/{id}/questions` | current question list |
| POST | `/documents/{id}/answers` | submit answers → re-runs answers/validate/fit passes |
| PATCH | `/documents/{id}/fields/{field_id}` | edit value, bbox, or status |
| POST | `/documents/{id}/confirm-all` | confirm fields with no warnings |
| POST | `/documents/{id}/render` | → 202 `{job_id}` |
| GET | `/documents/{id}/output` | download filled PDF |
| DELETE | `/documents/{id}` | delete document and files now |
| GET, PUT | `/profile` | read (masked) / update the vault |
| GET | `/jobs/{id}` | job status |
| GET | `/health` | liveness incl. DB and Redis |

Upload limits (config): 20 MB, 50 pages, PDF magic-bytes check (images in stretch phase).

## 9. Tech stack

| Layer | Choice | Note |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic | |
| Jobs | Redis + arq | async, lighter than Celery |
| PDF | PyMuPDF | read widgets, words with coordinates, drawings, rendering. **AGPL-3.0**: the repo is public and licensed AGPL-3.0 |
| OCR (v2) | Tesseract via pytesseract | `eng` + `hin` language packs, both required |
| Vision (v2) | OpenCV | lines, boxes, perspective |
| LLM | `LLMProvider` interface: `OllamaProvider` (default, local), `GroqProvider` (optional API), `FakeProvider` (tests) | model name from config; start with a 7–8B instruct model, fall back to 3B on low-RAM machines |
| LLM cache | recorded responses keyed by hash(provider, model, prompt, schema) | makes CI eval deterministic and free |
| Frontend | Next.js (App Router), TypeScript, Tailwind, TanStack Query, pdf page images from API | types generated with `openapi-typescript` |
| Tests | pytest, Playwright (one happy-path e2e) | |
| Infra | Docker Compose, GitHub Actions, Makefile | deploy on a free tier in Phase 7 |

## 10. Evaluation

Layout:

```text
eval/
  dataset/dev/*.pdf      blank public forms for tuning
  dataset/test/*.pdf     blank public forms, held out
  labels/<form>.json     human-written: fields (bbox, kind, semantic_type)
  personas/*.json        synthetic people with format-valid fake IDs
  invalid_inputs.json    synthetic wrong values for validator tests
  run_eval.py            CLI: --split dev|test --mode rules|llm|hybrid --provider ...
  baseline.json          committed metrics for the CI gate
  reports/               generated JSON + Markdown
```

Metrics:

| Metric | Definition |
|---|---|
| Detection precision / recall | predicted vs labelled fields, match if IoU ≥ 0.5 on the same page |
| Semantic accuracy | share of matched fields with the correct semantic type |
| Fill correctness | render with a persona, read back values, compare to expected |
| Placement IoU (v1) | mean IoU of rendered text box vs labelled entry box |
| Validator catch rate | share of `invalid_inputs.json` rejected; plus false-reject rate on persona values |
| Questions per form | number of questions vs number of fields needing input |
| Latency / cost | per form, per provider |

Labelling protocol: the semantic-type labels are written **blind** (predictions hidden). Bounding
boxes may start from the detector's output but every box must be checked and adjusted by a human;
each label file records `"verified_by_human": true`.

## 11. Security and privacy

- JWT auth; users can only access their own documents (checked in the service layer).
- Vault encrypted at rest (Fernet, key from env). This protects the database dump; it is not
  end-to-end encryption and the README says so.
- Sensitive types masked in responses, never logged, saved to the vault only on explicit opt-in.
- Uploads and outputs expire after 24 h (arq cron). `DELETE` removes files immediately.
- PDFs are opened only in the worker, never in the API process.

## 12. Repository layout

```text
formpilot/
  CLAUDE.md  README.md  LICENSE  Makefile  docker-compose.yml  .env.example
  .github/workflows/ci.yml
  docs/  SPEC.md  PLAN.md  reality_check.md  decisions/
  backend/
    pyproject.toml
    app/
      main.py  config.py  logging.py
      api/          routes, schemas, deps
      services/     documents, profile, jobs
      db/           models, session, migrations/
      ir/           models.py, semantic_types.py
      frontends/    detect.py, acroform.py, flat.py, scanned.py, photo.py
      passes/       understand.py, match.py, questions.py, answers.py, validate.py, fit.py
      validators/   india.py, common.py, verhoeff.py
      backends/     acroform_fill.py, overlay.py, guide.py
      llm/          provider.py, ollama.py, groq.py, fake.py, cache.py, prompts/
      vault/        crypto.py, service.py
      storage/      base.py, local.py
      jobs/         worker.py, tasks.py
    tests/          unit/, integration/, fixtures/
  web/              Next.js app
  eval/             see section 10
```
