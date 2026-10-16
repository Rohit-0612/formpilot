# Labelling entry boxes (Phase 2)

You draw a box around every **entry area** on the dev pages — every place where a person writes
or ticks something. The detection eval (Step 6) compares the detector's boxes with yours
(match = IoU ≥ 0.5 on the same page). Semantic types come later, in Phase 3, written blind.

> **Top rule: draw a box where a person would write, split into the parts a person would write
> separately.**

Everything below follows from that rule. When a case is not covered, apply the top rule and
write the case down for the decision record.

## Kinds (keys 1–3 in Label Studio)

| Key | Label | Use for |
|---|---|---|
| 1 | `text` | a line, dotted leader, underscore run, empty box or table cell you write into |
| 2 | `comb` | a row of per-character cells, as one box (see rules 1 and 2) |
| 3 | `checkbox` | a small square to tick |

## How to draw each kind

**Line entries (underscores, dots, drawn lines).** Draw from the start to the end of the line,
and from the line up to a little above the height of the label's capital letters.

![Line entries: from the start to the end of the dots, from the dots up to a little above the
capital letters](examples/line-entries.png)

The match tolerates hand-drawn heights: with the start and end right, any height from 0.6× to
2.4× the font size still matches (the detector uses 1.2×).

**Boxes, table cells, checkboxes.** Draw along the printed rectangle.

**Comb rows (decision D8).** One box over the whole row of cells. Split the row where the gap
between cells is clearly larger than the normal spacing (more than one cell width), or where
printed text or a separator sits between cells (for example `DD / MM / YYYY`).

**Multi-line entries** (an address on two or three lines): one box per writing line. Do not
group lines into one box; that is out of scope for Phase 2.

**Rule 1 — cells with printed grey hints are entry areas, not labels.** A hinted name row
(`F I R S T N A M E`) is one comb field. A hinted date row follows D8: `DD`, `MM` and `YYYY`
are separate fields.

![Rule 1: each hinted name row is one comb box; the hinted date row is three boxes, DD / MM /
YYYY](examples/rule1-hinted-cells.png)

**Rule 2 — rows of wide cells.** If each cell takes one character, the row is a comb (one box).
If each cell takes a group (`DD` in one cell, `MM` in the next), each cell is its own field, as
in D8. The dev forms only have the first case; the example below is #25's date of birth (eight
wide cells, one digit each).

![Rule 2: eight wide cells, one character each, are one comb box](examples/rule2-wide-cells.png)

**Rule 3 — a cell with its label printed inside.** The box covers only the empty, writable part
of the cell, not the label.

![Rule 3: only the empty part above the printed caption](examples/rule3-label-inside.png)

**Do not box:** printed labels, headings, instructions, and areas where nothing is written by
hand (e.g. a box to paste a photograph). **Do box:** signature and thumb-impression areas
(as `text`), and "for office use" fields — a person writes there too.

The example images are rendered from the dev forms and are not committed (like the forms
themselves). Create them with `make label-examples` (from the repo root).

## Labelling order

1. **#21 and #41 from scratch** — these tasks have no pre-filled boxes (anchoring check, below).
2. **The medium forms:** #2, #6, #23, #25, #30, #32, #39.
3. **#1 and #3 last** — about two thirds of all boxes are on these two.

The tasks are imported in this order, so "Label All Tasks" walks through them in it.

**Anchoring check.** Pre-filled boxes may make you accept what the detector found and miss what
it did not. Because #21 and #41 are labelled without pre-filling, the detection eval (Step 6)
reports them separately from the pre-filled forms: if the detector scores clearly better on the
pre-filled forms, pre-annotation may be biasing the labels. On pre-filled pages, first look over
the whole page for entry areas that have no box, then check the existing boxes.

## Partial labelling

You do not have to finish a form in one go. A page counts as labelled once you **submit** it
(a page with no entry areas: delete every box and submit). Pages you have not submitted, or
skipped, are not labelled; the label file lists the labelled pages (`labelled_pages`), and the
eval scores only those and lists the rest. Export and convert as often as you like.

## Setup, step by step

Run everything from the repo root. Docker Desktop must be running.

**1. Render the pages and write the tasks** (once):

```bash
make label-tasks
```

This writes `eval/labelling/work/files/` (page images and `tasks.json`; gitignored). It refuses
to run again once `tasks.json` exists, because importing tasks twice duplicates them.

**2. Start Label Studio 1.23.2:**

```bash
mkdir -p eval/labelling/work/ls-data
docker run -d --name formpilot-labelstudio -p 127.0.0.1:8080:8080 \
  -v "$PWD/eval/labelling/work/ls-data:/label-studio/data" \
  -v "$PWD/eval/labelling/work/files:/label-studio/files/formpilot" \
  -e LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
  -e LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=/label-studio/files \
  heartexlabs/label-studio:1.23.2
```

Wait about 20 seconds, then open <http://localhost:8080> and **Sign up** (the account exists
only in `eval/labelling/work/ls-data`).

**3. Create the project.** **Create Project** → name it `FormPilot dev boxes` →
**Labeling Setup** → **Custom template** → switch to **Code** → replace everything with the
contents of `eval/labelling/labeling_config.xml` → **Save**.

**4. Connect the page images.** Project **Settings** → **Cloud Storage** →
**Add Source Storage** → **Local Files** → **Next**:

- Storage Title: `formpilot`
- Absolute local path: `/label-studio/files/formpilot`
- **Test connection**, then **Next**
- Import Method: **Tasks**; leave File Name Filter empty; **Next**
- Click **Save** — *not* "Save & Sync" (syncing would create an extra task per image file).

**5. Turn on pre-filled boxes.** Project **Settings** → **Annotation** → **Live Predictions**:
switch it on and select the predictions `flat@<commit>` → **Save**.

**6. Import the tasks.** Open the project → **Import** → **Upload Files** → choose
`eval/labelling/work/files/tasks.json` → **Import**. You should see 27 tasks, starting with
#21.

**7. Label.** **Label All Tasks**. The header shows the form and page. Press `1`, `2` or `3`,
then drag a box; zoom with the mouse wheel; delete a selected box with Backspace. Correct the
pre-filled boxes, add missing ones, delete wrong ones, then **Submit** to go to the next page.

**8. Export and convert** (whenever you want, also halfway): **Export** → **JSON** (not
JSON-MIN) → **Export**. Then:

```bash
make label-convert EXPORT=~/Downloads/<exported-file>.json
# later runs replace the existing label files:
make label-convert EXPORT=~/Downloads/<exported-file>.json OVERWRITE=1
```

This writes `eval/labels/<form>.json` for every form with at least one labelled page and prints
the labelled and unlabelled pages (1-based, as in a PDF viewer; the files store 0-based page
indexes). It stops with a message naming the task to fix if something is off (for example two
submitted annotations on one page, or a rotated box). Label files are ground truth: commit them
yourself, or ask Claude to commit them — Claude never edits them.

**Stopping and resuming.** `docker stop formpilot-labelstudio` and later
`docker start formpilot-labelstudio`. Your work is kept in `eval/labelling/work/ls-data` — do not
delete `eval/labelling/work/` until the labels are converted and committed.

## Files

| File | What |
|---|---|
| `labeling_config.xml` | Label Studio labelling interface (3 kinds, upright boxes only) |
| `tasks.py` | `make label-tasks`: renders the `ok` dev pages at 150 DPI, one task per page, with the detector's boxes as predictions (none for #21 and #41) |
| `convert.py` | `make label-convert`: Label Studio JSON export → `eval/labels/<form>.json` |
| `schema.py` | the label file format, validated on every read and write |
| `examples.py` | `make label-examples`: the example images above |
