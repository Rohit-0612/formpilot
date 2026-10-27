# Fill eval — dev, provider `ollama:qwen3:8b`

> **Reference labels: written by Claude Code (claude-opus-5-5), blind to the model's output, not by a human (decision P3-D6). Accuracy is agreement with them.** Personas: synthetic, drafted by Claude Code, not checked by a human (P4-D3).

- Detector `flat@b315f23`; created 2026-10-27T06:47:23+00:00; tag `comparison`
- *Fill precision*: of the compared fields the policy fills, the share with the right semantic type. *Coverage*: right fills / compared fields with a fillable reference type. *Value correctness*: filled values equal to the value the reference type gets.
- **Chosen policy: LLM confidence >= 0.95, once per form** (**target of 85.0 % fill precision missed**: chosen as the most precise candidate with coverage of at least 20.0 %; chosen on `asha_verma`).

## Full persona (`asha_verma`)

| Policy | Filled | Fill precision | Coverage | Value correctness |
|---|--:|--:|--:|--:|
| every predicted type (no policy) | 203 | 57.6 % (117/203) | 48.5 % (117/241) | 58.1 % |
| LLM confidence >= 0.90 | 202 | 57.9 % (117/202) | 48.5 % (117/241) | 58.4 % |
| LLM confidence >= 0.95 | 127 | 70.1 % (89/127) | 36.9 % (89/241) | 70.1 % |
| LLM confidence >= 0.99 | 120 | 68.3 % (82/120) | 34.0 % (82/241) | 68.3 % |
| rules only | 73 | 74.0 % (54/73) | 22.4 % (54/241) | 74.0 % |
| LLM confidence >= 0.90, once per form | 157 | 63.1 % (99/157) | 41.1 % (99/241) | 63.7 % |
| LLM confidence >= 0.95, once per form **(chosen)** | 96 | 76.0 % (73/96) | 30.3 % (73/241) | 76.0 % |
| LLM confidence >= 0.99, once per form | 89 | 74.2 % (66/89) | 27.4 % (66/241) | 74.2 % |
| rules only, once per form | 59 | 81.4 % (48/59) | 19.9 % (48/241) | 81.4 % |

## Chosen policy, every persona

| Persona | Filled | Fill precision |
|---|--:|--:|
| `asha_verma` | 96 | 76.0 % |
| `meera_iyer` | 69 | 73.9 % |
| `ravi_kumar` | 80 | 83.8 % |
