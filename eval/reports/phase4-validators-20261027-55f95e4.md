# Validator eval

> Invalid inputs and personas are synthetic, written by Claude Code (P4-D3). No model.

- Detector `flat@55f95e4`; created 2026-10-27T07:02:33+00:00
- **Catch rate: 89.2 % (33/37)** of the wrong values in `eval/invalid_inputs.json`.
- **False-reject rate: 0.0 % (0/21)** of the persona values that have a validator, formatted as FormPilot fills them.

## Not caught (limits of format checks)

| Type | Why it is wrong |
|---|---|
| `pan` | valid shape (holder-type letter is not checked) |
| `current_pincode` | valid shape (not a real PIN code; existence is not checked) |
| `email` | a typo in the domain (deliverability is not checked) |
| `date_of_birth` | valid but implausible (age is not checked) |
