# CLAUDE.md — FormPilot

FormPilot is a document-understanding pipeline that fills PDF forms. A user uploads a form
(fillable PDF, flat/scanned PDF, later a photo), the system detects the fields, understands what
each field asks for, fills what it already knows from the user's profile, asks the fewest possible
questions for the rest, validates every value, lets the user review everything, and returns a
filled PDF.

**At the start of every session, read these files before doing anything else:**
1. `docs/SPEC.md` — what we are building and the architecture contract.
2. `docs/PLAN.md` — the phases, the current phase, and its acceptance gate.
3. The latest file in `docs/decisions/` — what was decided last time.

If anything in a request conflicts with SPEC.md or PLAN.md, stop and ask. Do not silently
"improve" the spec.

If a nested instruction file (e.g. web/CLAUDE.md) conflicts with this file, this file wins.

---

## 1. Working agreement

- **One phase at a time.** Only work on the phase marked `CURRENT` in `docs/PLAN.md`.
  Never start the next phase, even if the current one looks done. The human marks a gate as passed.
- **Plan before code.** For every task, first state: which files will change, why, and how it
  will be tested. Wait for approval on anything that touches the Form IR schema, the database
  schema, or a public API contract.
- **Small steps, small commits.** One logical change per commit, conventional commit messages
  (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`). Run the tests before every commit.
- **"Done" means verified.** Never say a task is done unless you ran the relevant tests and they
  passed. Paste the command and the summary line of the result.
- **Never invent numbers.** Accuracy, latency or any metric in docs or README must come from an
  eval run in this repo. If it was not measured, write "not measured yet".
- **Stuck rule.** If the same bug survives two fix attempts, stop patching. Write a short
  root-cause note (what you observed, hypotheses, what you ruled out, the smallest failing
  reproduction) and ask the human. Stacking patches on an unexplained bug is forbidden.
- **No new dependencies without asking.** Name the package, why it is needed, and the
  alternative you considered.
- **End of phase:** draft `docs/decisions/phase-N.md` (what was built, alternatives considered,
  why this choice, known limitations). Leave the section "In my own words" empty — the human
  writes it.

## 2. Architecture invariants (never break these)

1. **Everything goes through the Form IR.** Frontends produce a `FormIR`. Passes transform a
   `FormIR`. Backends render a `FormIR`. No pass reads or writes a PDF directly. No backend
   re-detects fields.
2. **Passes are pure functions**: `def run(ir: FormIR, ctx: PassContext) -> FormIR`. No hidden
   I/O except through objects in `ctx` (LLM provider, profile, clock). Every pass records what
   it changed in `ir.trace`.
3. **LLM only understands; code decides.** The LLM is used for (a) classifying a field's
   semantic type when rules cannot, and (b) parsing free-text answers into fields. Validation,
   matching, rendering, and all acceptance decisions are deterministic code.
4. **LLM output is always schema-validated.** Use Pydantic models; semantic types come from the
   fixed `SemanticType` enum only. On invalid output: one retry with the validation error in the
   prompt, then mark the field `unknown`. Never parse LLM output with regex.
5. **No hardcoded provider.** All model calls go through `LLMProvider`. Tests use
   `FakeProvider` or recorded responses. Unit tests never touch the network.
6. **One coordinate system.** Inside the IR, all boxes are PDF points with origin at the
   **top-left** of the page (PyMuPDF convention). Convert at the edges (frontends/backends) only.
7. **Nothing is final without the user.** A filled PDF is only rendered from fields whose status
   is `confirmed` or that the user explicitly accepted in bulk.

## 3. Privacy and data rules

- Never commit real personal data. Fixtures and eval personas are synthetic only.
- Never log field **values**. Log document ids, field ids, pass names, timings.
- Sensitive semantic types (`aadhaar`, `pan`, `bank_account_number`, `passport_number`) are
  never saved to the profile vault unless the user opts in for that specific field; they are
  masked in API responses by default.
- Uploaded files and outputs expire (default 24 h) and are deleted by a scheduled job.

## 4. Code conventions

- Python 3.12, type hints everywhere, `ruff` for lint + format. No `print`; use the configured
  structured logger.
- FastAPI routes stay thin: validate input, call a service, return a schema. Logic lives in
  services and passes.
- SQLAlchemy 2.0 style + Alembic migrations. Never edit an applied migration; add a new one.
- Frontend: TypeScript strict mode. API types are generated from the backend OpenAPI schema;
  never hand-write request/response types.
- Config only via environment variables loaded in `app/config.py` (pydantic-settings). No IPs,
  keys, or paths in code.

## 5. Testing rules

- Every pass, validator, frontend and backend has unit tests.
- Validators: include known-valid and known-invalid vectors (e.g. Verhoeff test vectors).
- PDF tests use small synthetic PDFs generated in `tests/fixtures/` (commit the generator script).
- LLM-dependent tests use `FakeProvider` (scripted outputs) or the recorded-response cache.
- Warnings from our own code are fixed, never filtered. A warning raised inside third-party code
  that we cannot fix gets a narrowly scoped filter with a comment and a Known issues entry.
- Run: `make test` (unit), `make eval` (evaluation, needs a model or the recorded cache).

## 6. Evaluation rules

- `eval/labels/` is ground truth written by a human. **Never create, edit or "fix" label files.**
  If a label looks wrong, report it; the human decides.
- The dataset is split into `dev/` and `test/`. Tune prompts and thresholds only on `dev/`.
  Report `test/` numbers only when the human asks for a release measurement.
- Every eval run writes a JSON + Markdown report to `eval/reports/`. CI compares against
  `eval/baseline.json`; a drop beyond the allowed tolerance fails the build.

## 7. Out of scope (do not build, even if it seems helpful)

- Auto-submitting forms to any website; browser extensions.
- Drafting legal documents (e.g. writing a rental agreement). Filling blanks is fine.
- Handwriting recognition.
- RAG, vector databases, agent frameworks, LangChain. Direct HTTP calls to the model are enough.
- Any claim that FormPilot "fills every form".

## 8. Git workflow

- Each phase is built on its own branch named phase-N-short-name, created from main.
- Commit after every verified step (tests passed), using conventional commit messages.
- Push the branch after every commit.
- When a phase gate passes, open a pull request to main with `gh pr create`, summarising what was built and the acceptance check results. The human merges it after CI is green.
- Never commit secrets, .env files, uploaded forms, or personal data. Never force-push to main.
