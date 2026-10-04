# FormPilot — Build Plan

Rules: work only on the phase marked **CURRENT**. A phase ends when every acceptance check passes
and the human ticks the gate. Then the human moves the CURRENT marker. Each phase ends with
`docs/decisions/phase-N.md` (Claude drafts, human writes "In my own words").

Status legend: `[ ]` todo, `[x]` done. Only the human ticks gate boxes.

---

## Phase 0 — Reality check (HUMAN ONLY, runs in parallel with Phase 1)

Goal: know what forms we are actually dealing with before building detection.

- [ ] Collect 30 real **blank** forms you or friends actually fill (scholarship, college,
      internship/onboarding, bank/KYC, government). Blank only — no personal data.
- [ ] For each: fillable (AcroForm) / flat text / scanned. Record in `docs/reality_check.md`
      (name, source URL, pages, type, notes).
- [ ] Pick 2–3 form families for the MVP.
- [ ] Split the forms into `eval/dataset/dev/` (≈ 70%) and `eval/dataset/test/` (≈ 30%).
- [ ] Decide v2 priority: if most forms are flat/scanned, Phase 6 is the most important phase.

**Gate 0:** `docs/reality_check.md` exists with counts per type. — [ ] passed

---

## Phase 1 — Skeleton and infrastructure  ← CURRENT

Goal: an empty but real product skeleton that runs with one command.

Deliverables
- Monorepo layout from SPEC §12; `README.md` stub; `LICENSE` (AGPL-3.0); `.env.example`.
- Backend: FastAPI app, `config.py` (pydantic-settings), structured logging, `/api/v1/health`
  checking DB and Redis.
- PostgreSQL + SQLAlchemy 2.0 + Alembic; initial migration for `users`, `documents`, `jobs`,
  `form_ir_versions`, `profiles`, `audit_events` (SPEC §7).
- Auth: register/login with hashed passwords and JWT; a `current_user` dependency.
- Storage interface + local implementation.
- arq worker with a no-op `ping` job and job-status table updates.
- Web: Next.js + TypeScript + Tailwind shell with login page and an empty dashboard;
  generated API types from OpenAPI.
- Docker Compose: `api`, `worker`, `postgres`, `redis`, `web`. Ollama runs on the host (not in compose).
- Makefile: `make up`, `make down`, `make test`, `make lint`, `make migrate`, `make types`.
- GitHub Actions: ruff, pytest (with Postgres + Redis services), web type-check and build.

Acceptance
- [ ] `make up` from a fresh clone brings everything up; `/api/v1/health` returns ok.
- [ ] Register → login → dashboard works in the browser.
- [ ] Enqueuing `ping` updates the job row to `done`.
- [ ] CI is green on the main branch.

Teach-back questions (human answers in `phase-1.md`)
1. Why does analysis run in a worker instead of inside the HTTP request?
2. What would break if we edited an already-applied Alembic migration?

**Gate 1:** — [ ] passed

---

## Phase 2 — Form IR and flat-PDF frontend

Goal: upload a flat (text-layer) PDF and see its detected fields as a Form IR.

Human tasks (before the gate)
- [ ] Label the entry boxes of the dev forms (tool to be decided at the start of Phase 2).

Deliverables
- `ir/models.py` exactly as SPEC §4; `ir/semantic_types.py` with the list from SPEC §5
  (descriptions + keywords + profile keys + sensitive flags).
- `frontends/detect.py` and `frontends/flat.py`: words with coordinates, underscore runs, drawn
  lines and rectangles, checkbox squares, label association, box sanity checks.
  Entry areas come from PyMuPDF vector drawings only. The OpenCV raster fallback (SPEC §6.1) is
  added in Phase 2 only if the detection eval shows misses caused by boxes drawn as images;
  otherwise it stays in Phase 6.
- Text-layer quality check in `frontends/detect.py`: pages whose text layer looks garbled (e.g.
  legacy non-Unicode Hindi fonts) are marked as needing OCR. OCR itself stays in Phase 6.
- Secondary: `frontends/acroform.py` (text, checkbox, radio, choice; options with export values;
  label from tooltip or nearest text; top-left coordinates), tested on synthetic fixtures.
- Upload endpoint with size/page/magic-byte limits → `analyze` job → IR version 1 saved.
- `GET /documents/{id}`, `/ir`, `/pages/{n}.png`.
- Web: upload page, job progress, page viewer with field boxes overlaid (no editing yet).
- Test fixtures: a script that generates small synthetic flat PDFs (underscore runs, lines,
  boxes, checkbox squares) and fillable PDFs (text, checkbox, radio, choice) for unit tests.
- Detection eval: precision/recall of detected entry boxes against the human labels on the dev
  flat forms (match if IoU ≥ 0.5 on the same page, SPEC §10); JSON + Markdown report in
  `eval/reports/`.
- On worker startup, mark jobs left in running state beyond the job timeout as failed (Stale),
  so a crashed worker never leaves a document stuck in analyzing. Add a `jobs.started_at`
  column if needed.

Acceptance
- [ ] Detection precision/recall on the dev flat forms reported (eval report in `eval/reports/`).
- [ ] Boxes drawn in the viewer line up with the form's fields (human visual check on 5 forms).
- [ ] Coordinate conversion has unit tests (bottom-left ↔ top-left).
- [ ] Uploading a non-PDF or an oversized file is rejected with a clear error.

Teach-back
1. Why is there one IR instead of letting each input type have its own pipeline?
2. Why do we store IR versions append-only?

**Gate 2:** — [ ] passed

---

## Phase 3 — Field understanding + eval harness

Goal: every field gets a semantic type, and we can measure how well.

Human tasks first
- [ ] Add semantic types to the dev form label files (`eval/labels/`), written blind.
- [ ] Create 3 synthetic personas in `eval/personas/` (format-valid fake IDs).

Deliverables
- `llm/provider.py` (interface), `ollama.py`, `fake.py`, `cache.py` (record/replay).
  `groq.py` may be a stub until Phase 7.
- `passes/understand.py`: rule matcher, then batched LLM per page with JSON-schema output,
  Pydantic validation, one retry, fallback `unknown`; review threshold from config.
- Prompt files in `llm/prompts/` (versioned, never inline strings).
- `eval/run_eval.py` with `--split`, `--mode rules|llm|hybrid`, `--provider`, `--record/--replay`;
  metrics: detection P/R, semantic accuracy; JSON + Markdown report.
- `make eval` target.

Acceptance
- [ ] Unit tests for the rule matcher and for LLM-output validation (valid, invalid, retry path).
- [ ] Eval report on `dev` exists for all three modes, committed in `eval/reports/`.
- [ ] Replay mode reproduces the same numbers without a running model.
- [ ] `eval/baseline.json` created from the hybrid run.

Teach-back
1. Why rules first and the LLM second? What does the eval say about it?
2. Why can't we trust the LLM's self-reported confidence as a probability?

**Gate 3:** — [ ] passed

---

## Phase 4 — Vault, matching, questions, answers, validation, fit

Goal: known values fill themselves; unknown ones become a few questions; everything is validated.

Deliverables
- `vault/`: Fernet encryption, profile read/update service, masking, sensitive opt-in.
- Decide how audit events without a document (profile changes) are stored; add a migration if needed.
- `passes/match.py` including derived values (full name, age, today's date).
- `validators/` per SPEC §6.6 including `verhoeff.py`; `passes/validate.py`; `passes/fit.py`.
- `passes/questions.py` (groups + templates) and `passes/answers.py` (code parsing +
  LLM parsing of free-text groups with schema validation).
- Endpoints: `/questions`, `/answers`, `/profile`.
- Web: questions screen; profile page with masked sensitive fields and per-field opt-in.
- Eval: fill correctness with personas, validator catch rate + false-reject rate, questions per form.

Acceptance
- [ ] Verhoeff and all validators pass published/known test vectors; invalid inputs file is
      rejected at the expected rate; zero false rejects on persona values.
- [ ] With a full persona in the vault, a dev form needs only questions for fields the persona
      lacks (checked in an integration test).
- [ ] Sensitive values never appear in logs (a test asserts this on captured logs).
- [ ] Eval report updated; baseline updated only if metrics did not drop.

Teach-back
1. Why is validation deterministic code and not the LLM?
2. What does the vault encryption protect against, and what does it not?

**Gate 4:** — [ ] passed

---

## Phase 5 — Review UI and rendering (v1 complete)

Goal: the full user journey for flat (text-layer) PDFs.

Deliverables
- Review screen: overlay coloured by status, field side panel (value, source badge, confidence,
  validation messages), edit, confirm, confirm-all-without-warnings.
- Review UI: drag/resize boxes (`USER_EDIT` in trace).
- `PATCH /fields/{id}`, `/confirm-all`, `/render`, `/output`, `DELETE /documents/{id}`.
- `backends/overlay.py` using fit-pass font sizes (primary renderer).
- Secondary: `backends/acroform_fill.py` (values, checkbox on-values, appearance regeneration,
  optional flatten).
- Audit events for every user action (no values).
- Expiry cron job (24 h) for files.
- Playwright happy path: upload → answer → review → confirm → download.
- README v1: pitch, architecture diagram, how to run, eval table (measured numbers only),
  limitations, 60-second demo GIF.

Acceptance
- [ ] Human opens 10 rendered PDFs from dev forms in a normal PDF reader: values correct and in place.
- [ ] Fill correctness on dev personas reported in README from an actual eval run.
- [ ] Placement IoU on the dev flat forms reported in README from an actual eval run.
- [ ] Playwright test green in CI.
- [ ] Only confirmed fields are rendered (test).

Teach-back
1. Walk through one field from upload to rendered PDF, naming every pass it went through.
2. Why must a human confirm fields before rendering?

**Gate 5 (v1 release):** — [ ] passed

---

## Phase 6 — Scanned PDFs and unusable text layers

Human tasks first
- [ ] Label the scanned dev forms (entry boxes + semantic types, blind).

Deliverables
- `frontends/scanned.py`: rasterize 300 DPI, OCR with Tesseract (`eng` + `hin`), OpenCV
  lines/boxes, reuse of the flat association logic. Also handles pages that the Phase 2
  text-layer check marked as needing OCR.
- Overlay render (`backends/overlay.py`) for scanned and OCR-routed pages.
- Eval: detection P/R and placement IoU on scanned and OCR-routed dev forms, reported separately
  from flat.

Acceptance
- [ ] Separate metrics for flat vs scanned (and OCR-routed pages) in the eval report.
- [ ] Human visual check of 10 overlay outputs on scanned forms.
- [ ] Known failure cases written in README limitations (with examples).

Teach-back
1. How is a label associated with its entry box, and where does it fail?
2. Why is scanned harder than flat, in terms of the pipeline?

**Gate 6:** — [ ] passed

---

## Phase 7 — Provider comparison, CI eval gate, deploy

Deliverables
- `llm/groq.py` complete; eval run for local vs API: semantic accuracy, latency, cost per form.
- CI job runs `make eval` in replay mode and fails if a metric drops beyond tolerance vs
  `eval/baseline.json`.
- Deployment on a free tier (API + worker + Postgres + Redis + web) using the API provider;
  local Ollama remains the default for self-hosting. Live demo link in README.
- Release measurement on `test/` split, reported once in README.

Acceptance
- [ ] Provider comparison table in README from real runs.
- [ ] A deliberately worse prompt in a PR makes CI fail (demonstrate once, then revert).
- [ ] Live demo works for a public blank form.

**Gate 7:** — [ ] passed

---

## Phase 8 — Stretch

- Photo input: page quadrilateral detection, perspective correction, then scanned pipeline;
  `backends/guide.py` numbered guide sheet + digital copy.
- MCP server exposing `analyze_form`, `fill_form(document, profile)` for AI agents.
