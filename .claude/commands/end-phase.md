---
description: Close out a phase — finalise the decision record, tick verified deliverables, commit and push
argument-hint: <phase-number>
---

You are closing out **Phase $ARGUMENTS** of FormPilot. Follow CLAUDE.md throughout.

If `$ARGUMENTS` is empty or not a phase number that exists in `docs/PLAN.md`, stop and ask
which phase to close. Do not start any work on the next phase.

## 0. Gather facts first

- Read `docs/SPEC.md`, `docs/PLAN.md` (the Phase $ARGUMENTS section) and any existing
  `docs/decisions/phase-$ARGUMENTS.md`.
- Review what was actually built: `git log main..HEAD --oneline` on the current phase branch,
  plus the changed files.
- Run `make test` (and `make lint`). Paste the command and its summary line. A deliverable
  counts as verified only if it exists in the repo **and** its tests pass in this run.
- Every number you write (accuracy, latency, counts) must come from a run in this repo. If it
  was not measured, write "not measured yet".

## a. Finalise `docs/decisions/phase-$ARGUMENTS.md`

Create or update it with exactly these sections:

1. **What was built** — deliverables, with the files/modules that implement them.
2. **Key decisions and alternatives considered** — for each: the choice, the alternatives,
   and why this one.
3. **Known limitations**
4. **Open issues** — bugs, unverified acceptance checks, TODOs, anything deferred.
5. **Notes for the next phase** — what the next phase needs to know or watch out for.
6. **In my own words** — leave this heading with an empty body. The human writes it.
   Never fill it in, not even with a placeholder answer to the teach-back questions.

## b. Update `docs/PLAN.md`

- Change `[ ]` to `[x]` only for Phase $ARGUMENTS deliverables and acceptance checks you
  verified in step 0.
- **Never tick the gate line** (`**Gate $ARGUMENTS:** — [ ] passed`). Only the human ticks it.
- Do not move the `CURRENT` marker and do not touch other phases.
- List anything you could not verify under "Open issues" in the decision record instead.

## c. Commit and push

- Make sure the working tree contains no secrets, `.env` files, uploaded forms or personal data.
- Commit only these doc changes, with a message such as
  `docs: close out phase $ARGUMENTS decision record and plan checklist`
  (plus the attribution trailer given in the session).
- Push the current phase branch (`git push -u origin HEAD`). Never force-push to main.

Finish by showing: the commit hash, `git status`, which items you ticked, and which items
remain open for the human.
