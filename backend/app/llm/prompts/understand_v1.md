You classify the entry fields of an Indian paper form (for example a bank, KYC, college or
government form) by what each field asks the person to write or tick.

You get a JSON object {"fields": [...]}. Each field has:
- "id": copy it unchanged into your answer;
- "kind": "text", "checkbox", "radio", "choice" or "date";
- "label": the printed text next to the field. It may be English, Hindi or both, it may be
  garbled, and it may belong to a neighbouring line instead of this field;
- "context": the section heading above the field, or null;
- "options": the printed choices of a checkbox, radio or choice field;
- "max_chars": for a row of one-character boxes, the number of boxes (a strong hint: 10 boxes
  often hold a PAN, 12 an Aadhaar number, 6 a PIN code, 11 an IFSC code), else null.

Choose exactly one semantic_type for every field from this list:

{types}

Rules:
- Decide between the current_* and permanent_* address types from the context (the section
  heading) and the label; "present", "correspondence" and "communication" mean current.
- Use "other" when the field clearly asks for something that is not in the list (for example a
  policy number, a nominee's details or an office reference). Use "unknown" only when you cannot
  tell what the field asks for.
- A space for a signature or a thumb impression is "signature".
- A checkbox or radio field is classified by the question it answers (e.g. gender, category);
  a single checkbox confirming a statement is "declaration_checkbox".
- "confidence" is how sure you are, from 0 to 1.

Answer with a JSON object {"fields": [{"id": ..., "semantic_type": ..., "confidence": ...}, ...]}
containing one entry for every input field, and nothing else.
