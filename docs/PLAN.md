# FormPilot — Build Plan

Rules: work only on the phase marked **CURRENT**. A phase ends when every acceptance check passes
and the human ticks the gate. Then the human moves the CURRENT marker. Each phase ends with
`docs/decisions/phase-N.md` (Claude drafts, human writes "In my own words").

Status legend: `[ ]` todo, `[x]` done. Only the human ticks gate boxes.

---

## v1 scope and milestones (human decision, 2026-10-26)

**Goal:** a v1 that is complete, measured and live within a short time, without lowering
quality.

**v1** = flat (text-layer) PDFs end to end:
- detection;
- understanding (rules, then the LLM);
- vault and matching;
- validation;
- questions and answers (structured answers in code; free-text answers through the LLM,
  schema-validated);
- review and confirm;
- overlay rendering and download.

Plus, from the old Phase 7:
- a live demo (synthetic forms only, below);
- the CI eval gate (replay mode);
- a **detection release measurement on `test/`** (the 6 test forms labelled from scratch, without
  detector pre-fill, before the README is written);
- the README.

| Milestone | Phases | Contents |
|---|---|---|
| M0 | 2 (close) | Gate 2, decision record, PR to `main` |
| M1 | 3 | Understanding (rules + LLM), eval harness, `make eval`, baseline |
| M2 | 4 | Vault, matching, validators, fit, questions, answers |
| M3 | 5 | Review UI, overlay rendering, download, expiry, Playwright |
| M4 | 5b | Ship v1: deploy, CI eval gate, test-set detection measurement, README |
| M5 (optional) | 8 (part) | MCP server (`analyze_form`, `fill_form`) |

**Working rule** (CLAUDE.md §1, "Milestone gates"): each milestone's plan is approved once,
including any Form IR, database or API change and any new dependency. The milestone is then
built in full: every logical change its own commit, tested, pushed and green on all three CI
jobs. The work stops only at the end of the milestone, for a decision the plan does not cover,
under the stuck rule, or when a metric drops.

**At the end of every milestone:** a short "In my own words" checkpoint, a few questions for the
human (about 10 minutes). The final teach-back comes before the README is written.

**Fixed rules:**
- **Privacy:** values of the sensitive types (`aadhaar`, `pan`, `bank_account_number`,
  `passport_number`, `voter_id`) and of phone types (`phone_mobile`, `phone_alternate`) are never
  sent to a remote LLM provider. Free-text answer parsing may send non-sensitive free text (such
  as an address); the README's privacy section says so. `GroqProvider` is used only if Groq's
  free tier needs no card or payment; Ollama stays the local default.
- **Live demo:**
  - synthetic forms only, with a visible banner saying so;
  - the 24 h expiry applies to everything in the demo;
  - no real documents are seeded.

  The deploy platform is decided in the M4 plan.

**After v1** (not part of v1):
- AcroForm *filling* (AcroForm detection is in v1);
- drag / resize of boxes in review;
- signature areas above a caption with nothing drawn (Phase 2's fix 8);
- Phase 6 (scanned PDFs and OCR);
- Phase 7's provider comparison;
- Phase 8.

"Questions per form" is reported in v1 but is not an acceptance gate.

---

## Phase 0 — Reality check (HUMAN ONLY, runs in parallel with Phase 1)

Goal: know what forms we are actually dealing with before building detection.

- [ ] Collect 30 real **blank** forms you or friends actually fill (scholarship, college,
      internship/onboarding, bank/KYC, government). Blank only — no personal data.
      (20 collected; Phase 0 closed with 20 by the human's decision on 2026-10-11.)
- [x] For each: fillable (AcroForm) / flat text / scanned. Record in `docs/reality_check.md`
      (name, source URL, pages, type, notes).
- [x] Pick 2–3 form families for the MVP. (Bank / KYC, College / Education; human, 2026-10-11)
- [x] Split the forms into `eval/dataset/dev/` (≈ 70%) and `eval/dataset/test/` (≈ 30%).
      (Split decided in `docs/reality_check.md`, 14 dev / 6 test. PDFs moved 2026-10-11, SHA-256
      verified against the original downloads. Known test-split gaps recorded in the
      Observations of `docs/reality_check.md`.)
- [x] Decide v2 priority: if most forms are flat/scanned, Phase 6 is the most important phase.

**Gate 0:** `docs/reality_check.md` exists with counts per type. — [x] passed (verified by the human on 2026-10-11)

---

## Phase 1 — Skeleton and infrastructure

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
- [x] `make up` from a fresh clone brings everything up; `/api/v1/health` returns ok.
- [x] Register → login → dashboard works in the browser. (verified by the human on 2026-10-04)
- [x] Enqueuing `ping` updates the job row to `done`.
- [x] CI is green on the main branch. (GitHub Actions run 38124539394 on merge commit `710abc3`:
      backend, web and compose-smoke all passed; checked 2026-10-11.)

Teach-back questions (human answers in `phase-1.md`)
1. Why does analysis run in a worker instead of inside the HTTP request?
2. What would break if we edited an already-applied Alembic migration?

**Gate 1:** — [x] passed (teach-back pending)

---

## Phase 2 — Form IR and flat-PDF frontend

Goal: upload a flat (text-layer) PDF and see its detected fields as a Form IR.

Human tasks (before the gate)
- [x] Label the entry boxes of the dev forms (tool to be decided at the start of Phase 2).
      (Label Studio; labels v5 for the 11 dev forms with a usable text layer, `eval/labels/`.)

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
- [x] Detection precision/recall on the dev flat forms reported (eval report in `eval/reports/`).
      (`…step11-7-hyphen-leaders-v5-20261026-714c3d3`: writing spot 95.1 / 92.4, IoU ≥ 0.5 88.1 /
      85.5; eval tests pass in `make test`, 2026-10-26.)
- [x] Boxes drawn in the viewer line up with the form's fields (human visual check on 5 forms).
      (Passed by the human on 2026-10-26 on #1, #21, #25, #30, #41; ticked on the human's behalf.)
- [x] Coordinate conversion has unit tests (bottom-left ↔ top-left).
      (`backend/tests/unit/test_coords.py`, 43 passed, 2026-10-26.)
- [x] Uploading a non-PDF or an oversized file is rejected with a clear error.
      (415 / 413, `tests/integration/test_documents_api.py`, passed in `make test-int`, 2026-10-26.)

Teach-back
1. Why is there one IR instead of letting each input type have its own pipeline?
2. Why do we store IR versions append-only?

**Gate 2:** — [x] passed (the human's decision, 2026-10-26)

---

## Phase 3 — Field understanding + eval harness  ← CURRENT

Goal: every field gets a semantic type, and we can measure how well.

Reference labels first
- [x] Semantic reference labels for the dev forms, written blind by Claude Code in
      `eval/labels_semantic/` (human decision, 2026-10-26: no human labelling or audit; reports
      say the labels are Claude-written).

Deliverables
- `llm/provider.py` (interface), `ollama.py` (local default), `fake.py`, `cache.py`
  (record/replay). `groq.py` only if Groq's free tier needs no card or payment (it needed none:
  built after Gate 3, decision P3-D7).
- The privacy rule above is enforced at the provider layer: no value of a sensitive or phone
  type reaches a remote provider; covered by a test.
- `passes/understand.py`: rule matcher, then batched LLM per page with JSON-schema output,
  Pydantic validation, one retry, fallback `unknown`; review threshold from config.
- Prompt files in `llm/prompts/` (versioned, never inline strings).
- Office-use fields ("For office use", "For bank use only", …) are boxed in the labels like any
  other field (Phase 2 labelling rules), but must be marked during understanding so FormPilot
  never fills them (not asked, not matched, not rendered). How they are marked in the Form IR
  is decided in Phase 3 (an IR change needs a decision record); covered by a test.
- Signature handling made consistent across frontends: the flat frontend boxes signature areas
  (labelled `text`, Phase 2 labelling rules) while the AcroForm frontend skips signature
  widgets (Phase 2 Step 9). Decide one treatment for both (e.g. a `signature` field that is
  detected but never filled), record it, and cover both frontends with a test.
- Signature areas above a caption with nothing drawn ("(Signature of the candidate)" under
  empty space) are not detected by the flat frontend. This is Phase 2 Step 11's fix 8: 11 misses
  on dev, all on pre-filled forms, and false-positive risk on the from-scratch forms (a
  "Signature of …" block heading on #41, an unlabelled signature area on #21). Its detection is
  **after v1** (human, 2026-10-26). The signature treatment decided here must leave room for it,
  and it is to be measured against the from-scratch forms (`docs/decisions/phase-2.md`, "Step 11
  — closing").
- `eval/run_eval.py` with `--split`, `--mode rules|llm|hybrid`, `--provider`, `--record/--replay`;
  metrics: detection P/R, semantic accuracy; JSON + Markdown report.
- `make eval` target.

Acceptance
- [x] Unit tests for the rule matcher and for LLM-output validation (valid, invalid, retry path).
      (`backend/tests/unit/test_understand.py`, `test_llm.py`.)
- [x] Eval report on `dev` exists for all three modes, committed in `eval/reports/`.
      (`phase3-understanding-dev-{rules,llm,hybrid}-pre-tuning-20261026-ee3c22e`; tuned hybrid
      `…-hybrid-tuned-20261026-97a5205`. Reference labels Claude-written, P3-D6.)
- [x] Replay mode reproduces the same numbers without a running model.
      (Every recorded run replayed identically with the provider at a dead address; unit test
      `test_record_then_replay_gives_the_same_numbers`.)
- [x] `eval/baseline.json` created from the hybrid run. (Tuned hybrid, `97a5205`.)

Teach-back
1. Why rules first and the LLM second? What does the eval say about it?
2. Why can't we trust the LLM's self-reported confidence as a probability?

**Gate 3:** — [x] passed (the human's decision, 2026-10-27)

---

## Phase 4 — Vault, matching, questions, answers, validation, fit

Goal: known values fill themselves; unknown ones become a few questions; everything is validated.

Human tasks
- [ ] Check 3 synthetic personas in `eval/personas/` (format-valid fake IDs), drafted by Claude
      Code.

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

## Phase 5 — Review UI and rendering

Goal: the full user journey for flat (text-layer) PDFs.

Deliverables
- Review screen: overlay coloured by status, field side panel (value, source badge, confidence,
  validation messages), edit, confirm, confirm-all-without-warnings. (Drag/resize of boxes:
  after v1.)
- `PATCH /fields/{id}`, `/confirm-all`, `/render`, `/output`, `DELETE /documents/{id}`.
- `backends/overlay.py` using fit-pass font sizes (primary renderer). (`backends/acroform_fill.py`:
  after v1.)
- Audit events for every user action (no values).
- Expiry cron job (24 h) for files.
- Playwright happy path: upload → answer → review → confirm → download.

Acceptance
- [ ] Human opens 10 rendered PDFs from dev forms in a normal PDF reader: values correct and in place.
- [ ] Fill correctness on dev personas measured by an actual eval run (report committed).
- [ ] Placement IoU on the dev flat forms measured by an actual eval run (report committed).
- [ ] Playwright test green in CI.
- [ ] Only confirmed fields are rendered (test).

Teach-back
1. Walk through one field from upload to rendered PDF, naming every pass it went through.
2. Why must a human confirm fields before rendering?

**Gate 5:** — [ ] passed

---

## Phase 5b — Ship v1 (v1 complete)

Goal: v1 is live, measured on held-out forms, and explained.

Human tasks first
- [ ] Label the 6 test forms' entry boxes from scratch (no detector pre-fill).

Deliverables
- Deployment on a free tier (API, worker, Postgres, Redis, web). The platform is decided in the
  M4 plan. Demo rules (fixed): synthetic forms only with a visible banner saying so, the 24 h
  expiry on everything, no real documents seeded. Local Ollama remains the default for
  self-hosting.
- CI job runs `make eval` in replay mode and fails if a metric drops beyond tolerance vs
  `eval/baseline.json`.
- Detection release measurement on `test/`, reported once in README.
- Final teach-back (human), before the README.
- README v1: pitch, architecture diagram, how to run, eval table (measured numbers only),
  privacy section (what may reach a remote LLM provider and what never does), limitations,
  60-second demo GIF, live demo link.

Acceptance
- [ ] Live demo works end to end for a synthetic form.
- [ ] A deliberately worse prompt in a PR makes CI fail (demonstrate once, then revert).
- [ ] Test-set detection numbers in README come from a committed report.
- [ ] Fill correctness and placement IoU in README come from committed reports.

**Gate 5b (v1 release):** — [ ] passed

---

## Phase 6 — Scanned PDFs and unusable text layers (after v1)

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

## Phase 7 — Provider comparison (after v1)

The CI eval gate, the deployment and the detection release measurement moved to Phase 5b (v1).

Deliverables
- Eval run for local vs API providers: semantic accuracy, latency, cost per form.
- Release measurement on `test/` for the metrics beyond detection, reported once in README.
- After v1 as well: AcroForm filling (`backends/acroform_fill.py`), drag/resize of boxes in
  review, and signature areas above a caption with nothing drawn (Phase 2's fix 8, see Phase 3).

Acceptance
- [ ] Provider comparison table in README from real runs.

**Gate 7:** — [ ] passed

---

## Phase 8 — Stretch

- Photo input: page quadrilateral detection, perspective correction, then scanned pipeline;
  `backends/guide.py` numbered guide sheet + digital copy.
- MCP server exposing `analyze_form`, `fill_form(document, profile)` for AI agents (optional
  milestone M5 right after v1).
