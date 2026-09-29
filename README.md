# FormPilot

A document-understanding pipeline that fills PDF forms.

Upload a form, and FormPilot detects its fields, works out what each one asks for, fills what it
already knows from your profile, asks the fewest possible questions for the rest, validates every
value, lets you review everything, and returns a filled PDF.

Architecture in one line: multiple input frontends into a common **Form IR**, rule-first + LLM
field understanding with schema-constrained outputs, deterministic validation, human-in-the-loop
review, and an evaluation harness gated in CI. See [docs/SPEC.md](docs/SPEC.md).

> **Status:** early development — Phase 1 (skeleton and infrastructure).
> See [docs/PLAN.md](docs/PLAN.md). Nothing is usable yet.

## How to run

Requirements: Docker (with Compose v2), GNU make, Python 3.12 with [uv](https://docs.astral.sh/uv/),
Node.js 22.

```bash
make up      # build and start everything, run migrations
make down    # stop
make test    # unit tests
```

Details will be filled in as Phase 1 lands.

## Evaluation

Not measured yet.

## Limitations

FormPilot does not fill every form. Supported inputs and known failure cases will be listed here
from real evaluation runs.

## License

[AGPL-3.0](LICENSE) (PyMuPDF is AGPL-3.0).
