# Fill eval — dev, provider `groq:openai/gpt-oss-120b`

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.** Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

- Detector `flat@b315f23`; created 2026-10-27T06:47:26+00:00; tag `tuning`
- *Fill precision*: of the compared fields the policy fills, the share with the right semantic type. *Coverage*: right fills / compared fields with a fillable reference type. *Value correctness*: filled values equal to the value the reference type gets.
- **Chosen policy: LLM confidence >= 0.99, once per form** (target of 85.0 % fill precision **met**; chosen on `asha_verma`).

## Full persona (`asha_verma`)

| Policy | Filled | Fill precision | Coverage | Value correctness |
|---|--:|--:|--:|--:|
| every predicted type (no policy) | 196 | 64.8 % (127/196) | 52.7 % (127/241) | 65.3 % |
| LLM confidence >= 0.90 | 163 | 68.1 % (111/163) | 46.1 % (111/241) | 68.7 % |
| LLM confidence >= 0.95 | 135 | 75.6 % (102/135) | 42.3 % (102/241) | 75.6 % |
| LLM confidence >= 0.99 | 99 | 79.8 % (79/99) | 32.8 % (79/241) | 79.8 % |
| rules only | 73 | 74.0 % (54/73) | 22.4 % (54/241) | 74.0 % |
| LLM confidence >= 0.90, once per form | 130 | 70.0 % (91/130) | 37.8 % (91/241) | 70.8 % |
| LLM confidence >= 0.95, once per form | 105 | 79.0 % (83/105) | 34.4 % (83/241) | 79.0 % |
| LLM confidence >= 0.99, once per form **(chosen)** | 74 | 86.5 % (64/74) | 26.6 % (64/241) | 86.5 % |
| rules only, once per form | 59 | 81.4 % (48/59) | 19.9 % (48/241) | 81.4 % |

## Chosen policy, every persona

| Persona | Filled | Fill precision |
|---|--:|--:|
| `asha_verma` | 74 | 86.5 % |
| `meera_iyer` | 52 | 84.6 % |
| `ravi_kumar` | 64 | 92.2 % |
