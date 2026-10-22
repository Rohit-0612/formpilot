# Remaining errors at the end of Step 11 (labels v4, detector `714c3d3`)

Notes to the report `phase2-detection-dev-step11-7-hyphen-leaders-20261022-714c3d3` (generated
files unchanged). Written by Claude Code on 2026-10-22, read-only analysis.

**Method.**
- Every unmatched label (miss) and unmatched detector box (false positive) on the scored dev
  pages, under the writing-spot rule.
- Totals match the report: 46 misses, 13 false positives.
- Causes were read from the page geometry (text on the row, text inside, above and below, drawn
  lines and cells). The unclear ones were checked by eye on local renders, which are never
  committed.
- Pages are 1-based, as in a PDF viewer. Bboxes are (x0, y0, x1, y1) in PDF points, top-left
  origin.

Summary and status per group: `docs/decisions/phase-2.md`, "Step 11 — closing".

## Misses (46)

### 1. Tables whose columns exist only as header text (19, #23 page 2)

| Labels | Where |
|---|---|
| `p1_l000`–`p1_l004` | "Particulars regarding other policies" table, row 1, under the column headers (y 92–102, x 89–520); one drawn line per row |
| `p1_l005`–`p1_l009` | same table, row 2 (y 108–119, x 90–524) |
| `p1_l013`–`p1_l015` | doctors table, row "1." (y 311–326), three columns at x ≈ 121–202, 256–371, 404–501; nothing drawn |
| `p1_l016`–`p1_l018` | row "2." (y 333–347) |
| `p1_l019`–`p1_l021` | row "3." (y 355–368) |

### 2. Signature area above its caption, nothing drawn (11; fix 8, deferred to Phase 3)

| Form, page | Label | Bbox | Caption below |
|---|---|---|---|
| #2 p1 | `p0_l030` | (424.9, 566.2, 540.4, 581.9) | Signature/Thumb Impression of Customer |
| #2 p1 | `p0_l039` | (437.3, 729.2, 551.6, 737.1) | Signature of Bank Official with Seal |
| #3 p2 | `p1_l064` | (395.6, 781.5, 529.5, 796.9) | Signature of Bank Official with Seal |
| #25 p1 | `p0_l067` | (55.1, 767.8, 188.1, 784.9) | (Signature of Father/Guardian) |
| #25 p1 | `p0_l068` | (378.0, 764.0, 503.4, 783.0) | (Signature of the candidate) |
| #25 p2 | `p1_l001` | (62.7, 387.7, 239.4, 401.0) | (Signature of Father/Guardian with name) |
| #25 p2 | `p1_l002` | (345.8, 383.9, 511.0, 401.0) | (Full Signature of Student with name) |
| #25 p2 | `p1_l013` | (408.4, 792.5, 531.9, 813.4) | Chairman (Admission Committee): no signature word |
| #25 p4 | `p3_l006` | (337.2, 640.4, 479.3, 666.9) | Signature of Parents / Guarding |
| #30 p1 | `p0_l029` | (40.2, 687.2, 138.0, 697.5) | Signature with date / Office Seal |
| #30 p1 | `p0_l030` | (379.9, 683.1, 512.8, 696.5) | प्रार्थी का हस्ताक्षर (Applicant's Full Signature with date); "भवदीय" directly above |

### 3. Tick spots with no printed square (10)

- #2 p1 `p0_l022`–`p0_l027`: above Salary / Business Income / Agriculture / Investment /
  Pension / Others (y 395–407, x 183–535).
- #41 p1 `p0_l003`–`p0_l006`: on the "change/correction in name of …" line (y 196–204, x
  68–358).

### 4. Blank after a label without a colon, nothing drawn (3)

- #6 p1 `p0_l000` (105.2, 97.2, 215.4, 112.2), after "To,".
- #23 p3 `p2_l001` (175.2, 173.4, 289.6, 187.7), after "Countersigned by".
- #39 p1 `p0_l008` (372.7, 619.3, 498.7, 630.3), between "(" and ")".

### 5. STD rows (2, #1 page 1)

- `p0_l119` (377.8, 787.5, 442.2, 799.2), "STD Tel. (Off.)".
- `p0_l121` (379.5, 805.9, 442.2, 816.8), "Tel. (Res)".

The 5-cell STD code part of a 15-cell row is not split (Known limitations).

### 6. Colon inside a frame (1, #3 page 2)

- `p1_l065` (419.5, 808.8, 540.6, 814.8): "Date:" with nothing drawn after it, inside a large
  frame. Fix 5 skips colons inside a drawn cell and fix 4 skips frames, so it falls between the
  two rules.

## False positives (13)

### a. Headings ending in a colon (5; fix 5)

- #21 p2 (445.7, 296.5, 544.8, 309.8): "Details of nominee / appointee (in case nominee is
  minor):"
- #21 p2 (197.4, 471.0, 544.8, 484.3): "Mandatory requirements :-"
- #23 p1 (283.9, 288.9, 519.2, 301.0): "1. Particulars regarding the claimant :"
- #23 p2 (408.7, 42.4, 521.6, 54.5): "…other policies on the life of the deceased :"
- #41 p1 (178.8, 217.2, 367.4, 230.5): "Documents Enclosed:"

### b. Empty "OR" separator column (3, #21 page 1)

- x 256.2–279.5 at y 456.4–473.3, 473.3–490.4 and 490.4–507.4, between the POSB and bank
  account tables.

### c. Row lines of the header-column tables taken as one wide entry (3, #23 page 2)

- (88.6, 91.6, 523.4, 103.7), (88.6, 106.7, 523.4, 118.8) and (88.6, 369.7, 523.4, 381.8).
  Same cause as group 1.

### d. Dashed rules drawn across the page (2, #3 page 2)

- (28.9, 140.5, 566.4, 142.4) and (28.9, 187.9, 566.4, 191.0): dashed rules under rows of comb
  fields, taken as writing lines.

## From scratch (#21, #41)

- #21: 0 misses; 5 false positives (a ×2, b ×3).
- #41: 4 misses (group 3); 1 false positive (a).
- None of them is in fix 8's scope.

## Fix 8 scan (why it was deferred)

Every line of the scored pages containing "sign", "seal", "stamp", "हस्ताक्षर" or "मुहर" was
checked for empty space above it (2.5 em, the caption's width: no text, nothing drawn, no
detector box).
- **Matches it could add:** 9 captions with empty space and a label above (#2 ×2, #3 ×1,
  #25 ×5, #30 ×1), all on pre-filled forms. #30 `p0_l030` also needs the box to stop at the
  nearest text above, which makes 10. #25 `p1_l013` has no signature word.
- **Likely false positives:**
  - #41 p1, "Signature of BPM/SPM/PM/ CPC in-Charge": a block heading over Name / Designation /
    Office Stamp, from scratch;
  - #21 p1, "(Signature of authorized official of the Post Offc)": empty above, not labelled,
    from scratch (pending label fix 4);
  - #1 p1, "Designation/Profession:": "sign" inside a word, avoidable;
  - #23 p3, "IF THE DECLARANT SIGNS IN VERNACULAR…": an instruction, avoidable.
