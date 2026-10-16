"""Synthetic PDFs with known ground truth, for unit tests (CLAUDE.md §5).

Each fixture is built in memory, deterministically, and returns the PDF bytes together with what
a correct frontend should find: the document's source kind, each page's text layer, and the
expected fields. To look at them:

    cd backend && uv run python -m tests.fixtures.pdfs --out /tmp/formpilot-fixtures

writes NAME.pdf and NAME.json (the ground truth) for every fixture.

Ground-truth conventions (the flat frontend and the labelling guide follow the same ones):
- Boxes are IR coordinates: PDF points, origin top-left of the displayed page.
- Line-type entry areas (underscore runs, dot leaders, drawn lines, thin filled rectangles used
  as lines): the line's x-span; vertically from the writing line up by one row height
  (ROW_HEIGHT = 1.2 x the label's font size). The writing line is the text baseline for
  underscores and dots, and the centre of the stroke for drawn lines.
- Rectangles, table cells and checkbox squares: the drawn rectangle.
- Comb rows: the union of the cells, max_chars = number of cells; a row is split where the gap
  between cells is wider than one cell or a printed separator sits between cells (decision D8).
- Multi-line entries (e.g. an address on three writing lines): each writing line is its own box
  and its own field. Grouping lines into one logical field is out of scope for Phase 2.
- A human labeller draws line-type boxes "from the start to the end of the line, and from the line
  up to a little above the height of the label's capital letters". With the x-span right, any
  height from 0.6x to 2.4x the font size still matches the convention box at IoU >= 0.5
  (tests/unit/test_geometry.py).
- Expected labels have a trailing ":" removed. `label=None` means "not asserted".

The fillable fixture is written as raw PDF objects rather than with PyMuPDF's widget API: PyMuPDF
cannot create a real radio group (a parent field with kids and distinct on-states), and raw
objects make every /Rect known exactly for the coordinate test.
"""

import argparse
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from functools import cache
from itertools import pairwise
from pathlib import Path

import pymupdf

from app.ir.models import FieldKind, SourceKind, TextLayer

FONT = "helv"
BOLD_FONT = "hebo"
FONT_SIZE = 10.0
ROW_HEIGHT = 1.2 * FONT_SIZE
A4 = (595.0, 842.0)
LETTER = (612.0, 792.0)
COMB_CELL = (14.0, 16.0)  # width, height
CHECKBOX_SIZE = 9.0

Box = tuple[float, float, float, float]  # (x0, y0, x1, y1), IR coordinates


@dataclass(frozen=True)
class ExpectedOption:
    value: str  # export value
    label: str | None
    bbox: Box | None


@dataclass(frozen=True)
class ExpectedField:
    page: int
    bbox: Box
    kind: FieldKind
    label: str | None = None  # None: not asserted
    context: str | None = None  # None: not asserted
    max_chars: int | None = None
    native_name: str | None = None
    options: tuple[ExpectedOption, ...] = ()


@dataclass(frozen=True)
class PdfFixture:
    name: str
    description: str
    data: bytes
    source_kind: SourceKind | None  # None when the file cannot be analysed (encrypted)
    text_layers: tuple[TextLayer, ...]
    fields: tuple[ExpectedField, ...] = ()
    encrypted: bool = False

    def ground_truth(self) -> dict[str, object]:
        data = asdict(self)
        del data["data"]
        return data


# --- drawing helpers ----------------------------------------------------------------------


def _width(text: str, size: float = FONT_SIZE, font: str = FONT) -> float:
    return pymupdf.get_text_length(text, fontname=font, fontsize=size)


def _text(
    page: pymupdf.Page,
    x: float,
    baseline: float,
    text: str,
    font: str = FONT,
    size: float = FONT_SIZE,
    color: tuple[float, float, float] | None = None,
) -> None:
    # Black text is written without a colour, so fixtures from before the colour option keep
    # their bytes (the recorded Label Studio export pins their SHA-256).
    extra = {"color": color} if color is not None else {}
    page.insert_text((x, baseline), text, fontname=font, fontsize=size, **extra)


def _line_box(x0: float, x1: float, writing_line: float) -> Box:
    return (x0, writing_line - ROW_HEIGHT, x1, writing_line)


def _labelled_leader(
    page: pymupdf.Page, page_no: int, x: float, baseline: float, label: str, leader: str
) -> ExpectedField:
    """Write "<label> <leader>" as one string; return the leader's ground truth."""
    _text(page, x, baseline, f"{label} {leader}")
    x0 = x + _width(f"{label} ")
    return ExpectedField(
        page_no, _line_box(x0, x0 + _width(leader), baseline), FieldKind.TEXT, label.rstrip(":")
    )


ELLIPSIS = "…"
# Helvetica's ellipsis is 1000/1000 em wide (Adobe AFM).
ELLIPSIS_WIDTH = FONT_SIZE


def _winansi_text(page: pymupdf.Page, x: float, baseline: float, text: str) -> None:
    """Write text in Helvetica with WinAnsiEncoding, so "…" extracts as U+2026.

    PyMuPDF's insert_text writes base-14 fonts with its own Latin encoding, which has no
    ellipsis; real forms use "……" leaders a lot (most leader runs on the dev forms).
    Assumes the page has text already (so its /Resources has a /Font dictionary) and a
    MediaBox starting at (0, 0).
    """
    doc = page.parent
    font = doc.get_new_xref()
    doc.update_object(
        font, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    resources = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources, "Font/FWinAnsi", f"{font} 0 R")

    encoded = text.encode("cp1252")
    escaped = encoded.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    y = page.mediabox.height - baseline
    stream = doc.get_new_xref()
    doc.update_object(stream, "<<>>")
    doc.update_stream(
        stream, b"BT /FWinAnsi %g Tf 1 0 0 1 %g %g Tm (%s) Tj ET" % (FONT_SIZE, x, y, escaped)
    )
    contents = [*page.get_contents(), stream]
    doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{c} 0 R" for c in contents) + "]")


def _rect(page: pymupdf.Page, box: Box, fill: bool = False) -> None:
    page.draw_rect(pymupdf.Rect(box), color=(0, 0, 0), fill=(0, 0, 0) if fill else None, width=0.5)


def _line(page: pymupdf.Page, x0: float, y0: float, x1: float, y1: float) -> None:
    page.draw_line((x0, y0), (x1, y1), color=(0, 0, 0), width=0.5)


def _comb(page: pymupdf.Page, x: float, top: float, cells: int, spacing: float = 0.0) -> Box:
    """Draw a row of comb cells; return the union box."""
    width, height = COMB_CELL
    for i in range(cells):
        left = x + i * (width + spacing)
        _rect(page, (left, top, left + width, top + height))
    return (x, top, x + cells * width + (cells - 1) * spacing, top + height)


def _scan_like_pixmap(width: int, height: int) -> pymupdf.Pixmap:
    """A grey image with dark bars, standing in for a scanned page or a logo."""
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, width, height), False)
    pix.clear_with(235)
    for top in range(height // 10, height - 4, max(height // 12, 6)):
        pix.set_rect(pymupdf.IRect(width // 10, top, width - width // 10, top + 2), (40,))
    return pix


def _new_doc(*sizes: tuple[float, float]) -> pymupdf.Document:
    doc = pymupdf.open()
    for width, height in sizes:
        doc.new_page(width=width, height=height)
    return doc


def _bytes(doc: pymupdf.Document) -> bytes:
    """Serialise without a random file id, so the same fixture always has the same bytes."""
    try:
        return doc.tobytes(no_new_id=True, garbage=1, deflate=True)
    finally:
        doc.close()


# --- page contents shared by several fixtures --------------------------------------------

KRUTI_LINES = (
    # Legacy Kruti Dev encoding: Devanagari glyphs mapped onto ASCII letters and punctuation.
    "vkosnd dk uke % [kkrk la[;k % gLrk{kj",
    "firk dk uke % irk % fnukad % LFkku",
    "[kkrk la[;k [kkrk la[;k gLrk{kj fu;qfDr",
    "inuke % foHkkx % dk;kZy; % {ks=",
    'eSa ;g ?kks"k.kk djrk gw¡ fd mijksDr fooj.k lgh gS',
)

MOJIBAKE_LINES = (
    # Legacy-font text that extracts as Latin-1 letters.
    "ÂæßðÎÙ ·¤æ ÙæÖ  ÂèÌæ ·¤æ ÙæÖ  ÁÙÖ  çÌçÍ",
    "Âêßü ·¤æÚU  ÂÌæ  ÕñÀU¤  ÚUæÁØ  çÁÜæ  ·¤æðÇU",
    "ãSÌæÿæÚU  çÎÙæ¢·¤  SÍæÙ  ÂÎÙæÖ  çß¼æ»",
)


def _kruti_page(page: pymupdf.Page, with_entry: bool = True) -> None:
    for i, line in enumerate(KRUTI_LINES * 3):
        _text(page, 72, 100 + i * 18, line)
    if with_entry:
        # An underscore run on a garbled page must not become a field (it is routed to OCR).
        _text(page, 72, 400, "uke % " + "_" * 30)


def _simple_form_page(page: pymupdf.Page, page_no: int) -> list[ExpectedField]:
    _text(page, 72, 80, "APPLICANT DETAILS", font=BOLD_FONT, size=12)
    return [
        _labelled_leader(page, page_no, 72, 120, "Name:", "_" * 30),
        _labelled_leader(page, page_no, 72, 150, "Mobile:", "_" * 20),
    ]


# --- flat fixtures ------------------------------------------------------------------------


def flat_underscores() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    _text(page, 72, 80, "APPLICATION FORM", font=BOLD_FONT, size=14)
    fields = [_labelled_leader(page, 0, 72, 120, "Name:", "_" * 30)]

    # Underscores attached to the label: one extracted word "Roll No:_______________".
    _text(page, 72, 150, "Roll No:" + "_" * 15)
    x0 = 72 + _width("Roll No:")
    fields.append(
        ExpectedField(0, _line_box(x0, x0 + _width("_" * 15), 150), FieldKind.TEXT, "Roll No")
    )

    # Two entries on one row.
    city, state = "_" * 12, "_" * 12
    row = f"City: {city}   State: {state}"
    _text(page, 72, 180, row)
    city_x0 = 72 + _width("City: ")
    state_x0 = 72 + _width(f"City: {city}   State: ")
    fields += [
        ExpectedField(0, _line_box(city_x0, city_x0 + _width(city), 180), FieldKind.TEXT, "City"),
        ExpectedField(
            0, _line_box(state_x0, state_x0 + _width(state), 180), FieldKind.TEXT, "State"
        ),
    ]

    # Label on the row above the entry.
    _text(page, 72, 220, "Address of the applicant")
    _text(page, 72, 244, "_" * 60)
    fields.append(
        ExpectedField(
            0,
            _line_box(72, 72 + _width("_" * 60), 244),
            FieldKind.TEXT,
            "Address of the applicant",
        )
    )
    return PdfFixture(
        "flat_underscores",
        "Underscore runs: label left, attached to the label, two per row, label above",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


def flat_dot_leaders() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    # Three dots end a sentence; they are not an entry area.
    _text(page, 72, 90, "Please read the instructions carefully...")
    fields = [_labelled_leader(page, 0, 72, 120, "Father's name", "." * 40)]
    _winansi_text(page, 72, 150, "Mother's name " + ELLIPSIS * 15)
    x0 = 72 + _width("Mother's name ")
    fields.append(
        ExpectedField(
            0, _line_box(x0, x0 + 15 * ELLIPSIS_WIDTH, 150), FieldKind.TEXT, "Mother's name"
        )
    )
    date, place = "." * 20, "." * 20
    _text(page, 72, 180, f"Date {date}   Place {place}")
    date_x0 = 72 + _width("Date ")
    place_x0 = 72 + _width(f"Date {date}   Place ")
    fields += [
        ExpectedField(0, _line_box(date_x0, date_x0 + _width(date), 180), FieldKind.TEXT, "Date"),
        ExpectedField(
            0, _line_box(place_x0, place_x0 + _width(place), 180), FieldKind.TEXT, "Place"
        ),
    ]
    return PdfFixture(
        "flat_dot_leaders",
        "Dot leaders ('.....' and ellipsis characters); a sentence ending in '...' is not one",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


def flat_lines() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    heading = "PERSONAL DETAILS"
    _text(page, 72, 100, heading, font=BOLD_FONT, size=12)
    # Decorative underline beneath the heading: not an entry area.
    _line(page, 72, 102.5, 72 + _width(heading, 12, BOLD_FONT), 102.5)

    _text(page, 72, 140, "Full name")
    _line(page, 160, 141, 450, 141)  # stroked line

    _text(page, 72, 170, "Occupation")
    _rect(page, (160, 170.7, 450, 171.3), fill=True)  # thin filled rectangle used as a line

    fields = (
        ExpectedField(0, _line_box(160, 450, 141), FieldKind.TEXT, "Full name", heading),
        ExpectedField(0, _line_box(160, 450, 171), FieldKind.TEXT, "Occupation", heading),
    )
    return PdfFixture(
        "flat_lines",
        "Drawn entry lines (stroked and thin filled rectangle); a heading underline is not one",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        fields,
    )


def flat_boxes() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []

    _text(page, 72, 130, "Email")
    email = (160.0, 116.0, 450.0, 134.0)
    _rect(page, email)
    fields.append(ExpectedField(0, email, FieldKind.TEXT, "Email"))

    _text(page, 72, 170, "Remarks")
    remarks = (72.0, 178.0, 520.0, 238.0)
    _rect(page, remarks)
    fields.append(ExpectedField(0, remarks, FieldKind.TEXT, "Remarks"))

    # A framed notice: the rectangle contains text, so it is not an entry area.
    _rect(page, (72, 260, 520, 290))
    _text(page, 80, 279, "Read all instructions before filling the form.")

    # A table drawn with lines: labels in the first column, entries in the second.
    xs, ys = (72.0, 200.0, 450.0), (320.0, 340.0, 360.0, 380.0)
    for y in ys:
        _line(page, xs[0], y, xs[-1], y)
    for x in xs:
        _line(page, x, ys[0], x, ys[-1])
    for (top, bottom), label in zip(pairwise(ys), ("Bank name", "Branch", "IFSC"), strict=True):
        _text(page, 76, bottom - 6, label)
        fields.append(ExpectedField(0, (xs[1], top, xs[2], bottom), FieldKind.TEXT, label))

    return PdfFixture(
        "flat_boxes",
        "Empty rectangles (label left and above), a framed notice, a table with an entry column",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


def flat_checkboxes() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []

    _text(page, 72, 130, "Gender")
    for x, option in ((140.0, "Male"), (200.0, "Female"), (270.0, "Other")):
        box = (x, 122.0, x + CHECKBOX_SIZE, 122.0 + CHECKBOX_SIZE)
        _rect(page, box)
        _text(page, x + 13, 130, option)
        fields.append(ExpectedField(0, box, FieldKind.CHECKBOX, option))

    declaration = "I hereby declare that the information given is true."
    box = (72.0, 160.0, 72.0 + CHECKBOX_SIZE, 160.0 + CHECKBOX_SIZE)
    _rect(page, box)
    _text(page, 86, 168, declaration)
    fields.append(ExpectedField(0, box, FieldKind.CHECKBOX, declaration))

    return PdfFixture(
        "flat_checkboxes",
        "Checkbox squares with option labels to the right, and a declaration checkbox",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


def flat_comb() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []
    cell_width, cell_height = COMB_CELL

    _text(page, 72, 134, "PAN")
    fields.append(ExpectedField(0, _comb(page, 160, 120, 10), FieldKind.TEXT, "PAN", max_chars=10))

    # Cells with a small gap (2 pt, less than a cell) are still one row.
    _text(page, 72, 174, "Aadhaar")
    fields.append(
        ExpectedField(
            0, _comb(page, 160, 160, 12, spacing=2), FieldKind.TEXT, "Aadhaar", max_chars=12
        )
    )

    # A gap wider than one cell splits the row (decision D8).
    _text(page, 72, 214, "Account number")
    first = _comb(page, 160, 200, 5)
    second = _comb(page, first[2] + 2 * cell_width, 200, 5)
    fields += [
        ExpectedField(0, first, FieldKind.TEXT, "Account number", max_chars=5),
        ExpectedField(0, second, FieldKind.TEXT, None, max_chars=5),
    ]

    # DD / MM / YYYY: the gaps are narrower than a cell, but printed separators split the row.
    _text(page, 72, 254, "Date of birth")
    top, gap = 240.0, 10.0
    x = 160.0
    for count, label in ((2, "Date of birth"), (2, None), (4, None)):
        box = _comb(page, x, top, count)
        fields.append(ExpectedField(0, box, FieldKind.TEXT, label, max_chars=count))
        x = box[2] + gap
        if count != 4:
            _text(page, box[2] + (gap - _width("/")) / 2, top + cell_height - 4, "/")

    return PdfFixture(
        "flat_comb",
        "Comb rows: contiguous, small spacing, split by a wide gap, split by separators (D8)",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


def flat_multiline() -> PdfFixture:
    """Entries spanning several writing lines: one field per line (Phase 2 convention)."""
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []

    # Underscore runs: label on the first line, continuation lines aligned beneath it.
    first = _labelled_leader(page, 0, 72, 120, "Permanent address:", "_" * 50)
    fields.append(first)
    x0, _, x1, _ = first.bbox
    for baseline in (144.0, 168.0):
        _text(page, x0, baseline, "_" * 50)
        fields.append(ExpectedField(0, _line_box(x0, x1, baseline), FieldKind.TEXT, None))

    # Drawn lines: label above, three writing lines.
    _text(page, 72, 220, "Correspondence address")
    for i, y in enumerate((244.0, 268.0, 292.0)):
        _line(page, 72, y, 500, y)
        label = "Correspondence address" if i == 0 else None
        fields.append(ExpectedField(0, _line_box(72, 500, y), FieldKind.TEXT, label))

    return PdfFixture(
        "flat_multiline",
        "Multi-line address entries (underscores and drawn lines): one field per writing line",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


GREY = (0.6, 0.6, 0.6)
HINT_SIZE = 7.0


def _hinted_row(page: pymupdf.Page, x: float, top: float, hints: str) -> list[Box]:
    """A contiguous comb row; each character of `hints` is one cell ("." = no hint)."""
    width, height = COMB_CELL
    cells: list[Box] = []
    for i, hint in enumerate(hints):
        cell = (x + i * width, top, x + (i + 1) * width, top + height)
        _rect(page, cell)
        if hint != ".":
            hx = cell[0] + (width - _width(hint, HINT_SIZE)) / 2
            _text(page, hx, top + height - 5, hint, size=HINT_SIZE, color=GREY)
        cells.append(cell)
    return cells


def _union(cells: list[Box]) -> Box:
    return (cells[0][0], cells[0][1], cells[-1][2], cells[-1][3])


def flat_hinted_comb() -> PdfFixture:
    """Rule 1 (Step 5): grey hints inside cells are entry areas, one field per hinted part.

    Parts are split halfway through the empty cells between two hints, an odd middle cell going
    to the earlier part (proposed rule, docs/decisions/phase-2.md, Step 5).
    """
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []

    _text(page, 72, 134, "Name")
    name = _hinted_row(page, 160, 120, "..FIRSTNAME..MIDDLENAME..")  # 2 + 9 + 2 + 10 + 2
    first, middle = name[:12], name[12:]  # the two blank cells between the hints are split 1 + 1
    fields += [
        ExpectedField(0, _union(first), FieldKind.TEXT, "Name", max_chars=len(first)),
        ExpectedField(0, _union(middle), FieldKind.TEXT, None, max_chars=len(middle)),
    ]

    _text(page, 72, 174, "Surname")
    surname = _hinted_row(page, 160, 160, "...LASTNAME...")
    fields.append(ExpectedField(0, _union(surname), FieldKind.TEXT, "Surname", max_chars=14))

    # A hinted date row follows D8: DD / MM / YYYY.
    _text(page, 72, 214, "Date of birth")
    date = _hinted_row(page, 160, 200, "DDMMYYYY")
    for cells, label in ((date[:2], "Date of birth"), (date[2:4], None), (date[4:], None)):
        fields.append(ExpectedField(0, _union(cells), FieldKind.TEXT, label, max_chars=len(cells)))

    return PdfFixture(
        "flat_hinted_comb",
        "Rule 1: comb rows with grey hints; one field per hinted part; hinted date as D8",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


WIDE_CELL = (26.0, 18.0)


def flat_wide_cells() -> PdfFixture:
    """Rule 2 (Step 5): wide cells, one character each = comb; one group each = one field each."""
    doc = _new_doc(A4)
    page = doc[0]
    fields: list[ExpectedField] = []
    width, height = WIDE_CELL

    _text(page, 72, 134, "Date of birth")
    cells = [(160 + i * width, 120.0, 160 + (i + 1) * width, 120 + height) for i in range(8)]
    for cell in cells:
        _rect(page, cell)
    fields.append(ExpectedField(0, _union(cells), FieldKind.TEXT, "Date of birth", max_chars=8))

    _text(page, 72, 174, "Date of joining")
    x = 160.0
    for group, cell_width, label in (
        ("DD", 40.0, "Date of joining"),
        ("MM", 40.0, None),
        ("YYYY", 60.0, None),
    ):
        cell = (x, 160.0, x + cell_width, 160 + height)
        _rect(page, cell)
        hx = x + (cell_width - _width(group, HINT_SIZE)) / 2
        _text(page, hx, 160 + height - 5, group, size=HINT_SIZE, color=GREY)
        fields.append(ExpectedField(0, cell, FieldKind.TEXT, label))
        x += cell_width

    return PdfFixture(
        "flat_wide_cells",
        "Rule 2: wide one-character cells form a comb; group cells (DD | MM | YYYY) are fields",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        tuple(fields),
    )


SIGNATURE_BOX = (72.0, 110.0, 300.0, 180.0)
NAME_CELL = (72.0, 200.0, 400.0, 220.0)
PHOTO_BOX = (420.0, 110.0, 520.0, 220.0)
THUMB_BOX = (420.0, 240.0, 520.0, 300.0)


def flat_label_inside() -> PdfFixture:
    """Rule 3 (Step 5): a label printed inside a cell; the box covers only the empty part.

    Photo and thumb-impression boxes get no box: nothing is written there.
    """
    doc = _new_doc(A4)
    page = doc[0]
    ascender = pymupdf.Font("helv").ascender * FONT_SIZE

    _rect(page, SIGNATURE_BOX)
    caption = "(Signature of the applicant)"
    caption_baseline = SIGNATURE_BOX[3] - 5
    _text(
        page, (SIGNATURE_BOX[0] + SIGNATURE_BOX[2] - _width(caption)) / 2, caption_baseline, caption
    )
    signature = (*SIGNATURE_BOX[:3], caption_baseline - ascender)

    _rect(page, NAME_CELL)
    _text(page, NAME_CELL[0] + 4, NAME_CELL[3] - 6, "Name:")
    name = (NAME_CELL[0] + 4 + _width("Name:"), NAME_CELL[1], NAME_CELL[2], NAME_CELL[3])

    _rect(page, PHOTO_BOX)
    _text(page, PHOTO_BOX[0] + 8, PHOTO_BOX[1] + 50, "Affix recent")
    _text(page, PHOTO_BOX[0] + 8, PHOTO_BOX[1] + 64, "photograph")
    _rect(page, THUMB_BOX)
    _text(page, THUMB_BOX[0] + 8, THUMB_BOX[3] - 8, "Thumb impression")

    return PdfFixture(
        "flat_label_inside",
        "Rule 3: labels printed inside cells; photo and thumb-impression boxes get no box",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        (
            ExpectedField(0, signature, FieldKind.TEXT, None),
            ExpectedField(0, name, FieldKind.TEXT, None),
        ),
    )


def flat_rotated() -> PdfFixture:
    """A page with /Rotate 90; ground truth is mapped with PyMuPDF's rotation matrix."""
    doc = _new_doc(A4)
    page = doc[0]
    expected = _labelled_leader(page, 0, 72, 120, "Name:", "_" * 30)
    page.set_rotation(90)
    rotated = pymupdf.Rect(expected.bbox) * page.rotation_matrix
    fields = (
        ExpectedField(0, (rotated.x0, rotated.y0, rotated.x1, rotated.y1), FieldKind.TEXT, "Name"),
    )
    return PdfFixture(
        "flat_rotated",
        "An underscore entry on a page with /Rotate 90",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        fields,
    )


# --- text-layer fixtures ------------------------------------------------------------------


def text_layer_garbled_kruti() -> PdfFixture:
    doc = _new_doc(A4)
    _kruti_page(doc[0])
    return PdfFixture(
        "text_layer_garbled_kruti",
        "Kruti Dev-style legacy Hindi text (ASCII letters with punctuation inside words)",
        _bytes(doc),
        SourceKind.SCANNED,
        (TextLayer.GARBLED,),
    )


def text_layer_garbled_mojibake() -> PdfFixture:
    doc = _new_doc(A4)
    for i, line in enumerate(MOJIBAKE_LINES * 3):
        _text(doc[0], 72, 100 + i * 18, line)
    return PdfFixture(
        "text_layer_garbled_mojibake",
        "Legacy Hindi text that extracts as Latin-1 letters",
        _bytes(doc),
        SourceKind.SCANNED,
        (TextLayer.GARBLED,),
    )


def text_layer_image_only() -> PdfFixture:
    doc = _new_doc(A4)
    doc[0].insert_image(doc[0].rect, pixmap=_scan_like_pixmap(595, 842))
    return PdfFixture(
        "text_layer_image_only",
        "A full-page image and no text: a scanned page",
        _bytes(doc),
        SourceKind.SCANNED,
        (TextLayer.NONE,),
    )


def text_layer_sparse_signature() -> PdfFixture:
    """Fewer than 50 non-space characters and no image: OK, not routed to OCR (decision D1)."""
    doc = _new_doc(LETTER)
    page = doc[0]
    fields = (
        _labelled_leader(page, 0, 72, 700, "Signature:", "_" * 20),
        _labelled_leader(page, 0, 72, 730, "Date:", "_" * 10),
    )
    return PdfFixture(
        "text_layer_sparse_signature",
        "A sparse signature page: little text, no image (D1: stays OK)",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
        fields,
    )


def text_layer_sparse_small_logo() -> PdfFixture:
    doc = _new_doc(A4)
    page = doc[0]
    page.insert_image(pymupdf.Rect(72, 40, 132, 100), pixmap=_scan_like_pixmap(60, 60))
    _text(page, 150, 80, "Joining report", font=BOLD_FONT, size=14)
    return PdfFixture(
        "text_layer_sparse_small_logo",
        "Little text and a small logo: the image does not cover most of the page, so OK",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,),
    )


def mixed_mostly_flat() -> PdfFixture:
    doc = _new_doc(A4, A4, A4)
    fields = _simple_form_page(doc[0], 0) + _simple_form_page(doc[1], 1)
    _kruti_page(doc[2])
    return PdfFixture(
        "mixed_mostly_flat",
        "Two usable pages and one garbled page: flat_text, the garbled page needs OCR",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK, TextLayer.OK, TextLayer.GARBLED),
        tuple(fields),
    )


def mixed_mostly_scanned() -> PdfFixture:
    doc = _new_doc(A4, A4, A4)
    fields = _simple_form_page(doc[0], 0)
    doc[1].insert_image(doc[1].rect, pixmap=_scan_like_pixmap(595, 842))
    _kruti_page(doc[2])
    return PdfFixture(
        "mixed_mostly_scanned",
        "One usable page, one image page, one garbled page: scanned (not more than half OK)",
        _bytes(doc),
        SourceKind.SCANNED,
        (TextLayer.OK, TextLayer.NONE, TextLayer.GARBLED),
        tuple(fields),
    )


# --- fillable fixture (raw PDF objects) ---------------------------------------------------

# MediaBox [0 0 612 792], CropBox [10 20 602 782]: the displayed page is 592 x 762 points and
# IR coordinates are (x - 10, 782 - y). The expected boxes below are worked out by hand.
_FILLABLE_OBJECTS = {
    1: b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [5 0 R 6 0 R 7 0 R 8 0 R 11 0 R]"
    b" /NeedAppearances true /DA (/Helv 0 Tf 0 g) /DR << /Font << /Helv 4 0 R >> >> >> >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /CropBox [10 20 602 782]"
    b" /Resources << /Font << /F1 4 0 R >> >> /Contents 12 0 R"
    b" /Annots [5 0 R 6 0 R 7 0 R 9 0 R 10 0 R 11 0 R] >>",
    4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    # Text field with a tooltip (/TU).
    5: b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (full_name) /TU (Full name of the applicant)"
    b" /Rect [150 680 400 698] /P 3 0 R /F 4 /DA (/Helv 10 Tf 0 g) >>",
    # Text field without a tooltip; its label "Mobile" is printed to the left. /MaxLen 10.
    6: b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (mobile_no) /MaxLen 10"
    b" /Rect [150 640 300 658] /P 3 0 R /F 4 /DA (/Helv 10 Tf 0 g) >>",
    # Checkbox whose on-state is /Agreed (not the common /Yes).
    7: b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) /TU (I agree to the terms)"
    b" /Rect [72 600 84 612] /P 3 0 R /F 4 /V /Off /AS /Off"
    b" /AP << /N << /Agreed 13 0 R /Off 14 0 R >> >> >>",
    # Radio group: parent field (radio + no-toggle-to-off flags) with two kids.
    8: b"<< /FT /Btn /Ff 49152 /T (gender) /TU (Gender) /V /Off /Kids [9 0 R 10 0 R] >>",
    9: b"<< /Type /Annot /Subtype /Widget /Parent 8 0 R /Rect [150 560 162 572] /P 3 0 R /F 4"
    b" /AS /Off /AP << /N << /Male 13 0 R /Off 14 0 R >> >> >>",
    10: b"<< /Type /Annot /Subtype /Widget /Parent 8 0 R /Rect [220 560 232 572] /P 3 0 R /F 4"
    b" /AS /Off /AP << /N << /Female 13 0 R /Off 14 0 R >> >> >>",
    # Combo box with (export value, display text) pairs.
    11: b"<< /Type /Annot /Subtype /Widget /FT /Ch /Ff 131072 /T (state) /TU (State)"
    b" /Opt [[(UP) (Uttar Pradesh)] [(MH) (Maharashtra)]] /V (UP)"
    b" /Rect [150 520 300 538] /P 3 0 R /F 4 /DA (/Helv 10 Tf 0 g) >>",
}
_FILLABLE_STREAMS = {
    12: b"BT /F1 12 Tf 72 720 Td (APPLICANT) Tj ET\n"
    b"BT /F1 10 Tf 72 644 Td (Mobile) Tj ET\n"
    b"BT /F1 10 Tf 166 562 Td (Male) Tj ET\n"
    b"BT /F1 10 Tf 236 562 Td (Female) Tj ET\n",
    13: b"0 g 2 2 8 8 re f",  # on appearance
    14: b"",  # off appearance
}
_FILLABLE_STREAM_DICTS = {
    12: b"",
    13: b" /Type /XObject /Subtype /Form /BBox [0 0 12 12]",
    14: b" /Type /XObject /Subtype /Form /BBox [0 0 12 12]",
}


def _raw_pdf(
    objects: dict[int, bytes], streams: dict[int, bytes], stream_dicts: dict[int, bytes]
) -> bytes:
    """Assemble numbered objects into a PDF file with a correct cross-reference table."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects.keys() | streams.keys()):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode()
        if number in streams:
            body = streams[number]
            out += b"<< /Length %d%s >>\nstream\n" % (len(body), stream_dicts[number])
            out += body + b"\nendstream"
        else:
            out += objects[number]
        out += b"\nendobj\n"
    xref_at = len(out)
    count = max(offsets) + 1
    out += f"xref\n0 {count}\n0000000000 65535 f \n".encode()
    for number in range(1, count):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


def fillable_basic() -> PdfFixture:
    fields = (
        ExpectedField(
            0,
            (140, 84, 390, 102),
            FieldKind.TEXT,
            "Full name of the applicant",
            native_name="full_name",
        ),
        ExpectedField(
            0, (140, 124, 290, 142), FieldKind.TEXT, "Mobile", max_chars=10, native_name="mobile_no"
        ),
        ExpectedField(
            0,
            (62, 170, 74, 182),
            FieldKind.CHECKBOX,
            "I agree to the terms",
            native_name="agree",
            options=(ExpectedOption("Agreed", None, (62, 170, 74, 182)),),
        ),
        ExpectedField(
            0,
            (140, 210, 222, 222),  # union of the two radio buttons
            FieldKind.RADIO,
            "Gender",
            native_name="gender",
            options=(
                ExpectedOption("Male", "Male", (140, 210, 152, 222)),
                ExpectedOption("Female", "Female", (210, 210, 222, 222)),
            ),
        ),
        ExpectedField(
            0,
            (140, 244, 290, 262),
            FieldKind.CHOICE,
            "State",
            native_name="state",
            options=(
                ExpectedOption("UP", "Uttar Pradesh", None),
                ExpectedOption("MH", "Maharashtra", None),
            ),
        ),
    )
    return PdfFixture(
        "fillable_basic",
        "AcroForm: text (tooltip / label left / MaxLen), checkbox, radio group, combo; offset "
        "CropBox",
        _raw_pdf(_FILLABLE_OBJECTS, _FILLABLE_STREAMS, _FILLABLE_STREAM_DICTS),
        SourceKind.FILLABLE,
        (TextLayer.OK,),
        fields,
    )


# --- files the upload path must handle ----------------------------------------------------

MAX_PAGES_PLUS_ONE = 51  # SPEC §8 limit is 50 pages


def too_many_pages() -> PdfFixture:
    doc = _new_doc(*([A4] * MAX_PAGES_PLUS_ONE))
    for number, page in enumerate(doc, start=1):
        _text(page, 72, 72, f"Page {number}")
    return PdfFixture(
        "too_many_pages",
        f"{MAX_PAGES_PLUS_ONE} pages, one more than the upload limit",
        _bytes(doc),
        SourceKind.FLAT_TEXT,
        (TextLayer.OK,) * MAX_PAGES_PLUS_ONE,
    )


def encrypted() -> PdfFixture:
    """Needs a user password. Not byte-deterministic: encryption uses a random salt."""
    doc = _new_doc(A4)
    _text(doc[0], 72, 72, "Confidential")
    try:
        data = doc.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-pass", user_pw="user-pass"
        )
    finally:
        doc.close()
    return PdfFixture("encrypted", "Encrypted with a user password", data, None, (), encrypted=True)


# --- registry and CLI ---------------------------------------------------------------------

BUILDERS: dict[str, Callable[[], PdfFixture]] = {
    builder.__name__: builder
    for builder in (
        flat_underscores,
        flat_dot_leaders,
        flat_lines,
        flat_boxes,
        flat_checkboxes,
        flat_comb,
        flat_multiline,
        flat_hinted_comb,
        flat_wide_cells,
        flat_label_inside,
        flat_rotated,
        text_layer_garbled_kruti,
        text_layer_garbled_mojibake,
        text_layer_image_only,
        text_layer_sparse_signature,
        text_layer_sparse_small_logo,
        mixed_mostly_flat,
        mixed_mostly_scanned,
        fillable_basic,
        too_many_pages,
        encrypted,
    )
}
NAMES = tuple(BUILDERS)


@cache
def get(name: str) -> PdfFixture:
    """A fixture, built once per test session."""
    return BUILDERS[name]()


def write_all(out: Path, names: Iterable[str] = NAMES) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in names:
        fixture = BUILDERS[name]()
        pdf_path = out / f"{name}.pdf"
        pdf_path.write_bytes(fixture.data)
        json_path = out / f"{name}.json"
        json_path.write_text(json.dumps(fixture.ground_truth(), indent=2) + "\n")
        written += [pdf_path, json_path]
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic PDF fixtures to a folder.")
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    args = parser.parse_args(argv)
    write_all(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
