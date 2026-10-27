"""Flat (text-layer) PDF frontend: detect entry areas and their labels (SPEC §6.1).

Entry areas come from PyMuPDF only (no OpenCV in Phase 2):
- leader runs in the text: underscores, dots and ellipses ("Name: ______", "Date ......"), and
  dashes ("Policy No. -----------", Step 11 fix 7);
- drawn horizontal lines, including thin rectangles used as lines;
- empty rectangles (also with rounded corners) and empty table cells (cells rebuilt from
  horizontal and vertical lines);
- comb rows of per-character cells, merged into one field (decision D8), one field per hinted
  part when the cells carry grey hints (labelling rule 1);
- small squares: checkboxes;
- the empty part of a cell with its label printed inside (labelling rule 3, Step 11 fix 4);
- blanks after a colon where nothing is drawn ("NAME OF THE BANK :  ", Step 11 fix 5).

Box convention (docs/decisions/phase-2.md, Step 2): a line-type entry spans the line and rises
ROW_HEIGHT_FACTOR x the font size above its writing line; boxes are the drawn rectangle; a comb
row is the union of its cells. Each writing line of a multi-line entry is its own field.

Only pages whose text layer is OK are processed; the others get a trace event (they need OCR,
Phase 6). PyMuPDF reports text and drawings on the unrotated page, so all work happens there and
boxes are mapped to the displayed page with `page.rotation_matrix` at the end.

The thresholds are first guesses checked on synthetic fixtures; they are tuned on the dev labels
in Step 11, never on the test split.
"""

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from itertools import pairwise
from typing import Literal
from uuid import UUID

import pymupdf

from app.frontends.detect import Detection
from app.ir.models import (
    BBox,
    DatePart,
    Field,
    FieldGroup,
    FieldKind,
    FormIR,
    TextLayer,
    TraceEvent,
    ValidationResult,
)
from app.ir.phrases import (
    asks_upper_case,
    instructs_upper_case,
    is_instruction,
    mentions_office_use,
)

STAGE = "frontend.flat"

ROW_HEIGHT_FACTOR = 1.2
# Leaders: weight in dots per character; "…" counts as three dots.
DOTS = {".": 1, "…": 3}
# Dashes (Step 11, fix 7; dev form #21's "-----------"): fewer than MIN_HYPHENS in a row are
# text ("E-mail", "2023-24", "/-", ":-"). A dash line with no words on its row is a separator
# when it spans SEPARATOR_WIDTH_SHARE of the text width (a judgement value: dev has no
# separator), or a table rule when "+" / "|" joints sit on its row.
HYPHENS = frozenset("-\u2010\u2013\u2014")  # hyphen, Unicode hyphen, en and em dash
LEADER_WEIGHT = {"_": 1, **DOTS} | dict.fromkeys(HYPHENS, 1)
MIN_UNDERSCORES = 3
MIN_DOT_WEIGHT = 5
MIN_HYPHENS = 4
MIN_LEADER_WIDTH = 10.0
SEPARATOR_WIDTH_SHARE = 0.8
TABLE_JOINTS = frozenset("+|")
# Drawn lines and boxes.
MIN_LINE_LENGTH = 15.0
MAX_LINE_THICKNESS = 2.0
AXIS_TOLERANCE = 0.5  # a segment this close to horizontal/vertical counts as axis-aligned
SNAP = 1.5  # points: coordinates this close are "the same"
MERGE_GAP = 3.0  # collinear segments closer than this are one segment
MIN_CELL_SIZE = 3.0
MAX_BOX_PAGE_SHARE = 0.5
CHECKBOX_SIZE = (5.0, 16.0)
SQUARE_RATIO = (0.75, 1.33)
# Labelling rule 2 (Step 11, fix 3): cells up to 30 pt wide can hold one character each (#25's
# date-of-birth cells are 27 pt). Chosen on dev: above the widest one-character cells labelled
# as combs, below the nearest separate boxes (#1's 33 pt office-use boxes, which would merge).
COMB_CELL_MAX = (30.0, 25.0)  # width, height
# D8 as amended twice (docs/decisions/phase-2.md, 2026-10-19): a comb row splits where a gap is
# larger than min(cell width, max(MIN_SPLIT_GAP, SPLIT_GAP_FACTOR x the median gap of that row)).
MIN_SPLIT_GAP = 3.0
SPLIT_GAP_FACTOR = 2.0
# A hinted word after one empty cell that completes the word before it ("FIRST _ NAME", "ACCOUNT _
# NO"): the two are one part (Phase 5, P5-D8).
COMPLETING_HINTS = frozenset({"NAME", "NO", "NUMBER", "CODE"})
# Hints of a date part: one letter repeated ("DD", "MM", "YYYY", "YY").
DATE_HINT_PARTS: dict[str, DatePart] = {"D": "day", "M": "month", "Y": "year"}
# Labelling rule 1: grey hints printed inside entry cells ("D D M M Y Y Y Y", "F I R S T N A M E")
# are not labels. Text whose luminance is in this band is a hint: label text on the dev forms is
# black, dark blue or blue (luminance <= 0.27), hints are grey (0.58); white text sits on a dark
# fill (a heading banner) and stays text.
HINT_LUMINANCE = (0.4, 0.85)
# Blanks after a colon (Step 11, fix 5): a phrase ending in ":" or ":-" with nothing drawn after
# it. The blank needs room for a few characters, and a colon line directly above a drawn table
# introduces the table instead.
COLON_ENDINGS = (":", ":-")
MIN_COLON_BLANK_EM = 3.0
TABLE_BELOW_EM = 2.5
# Labelling rule 3 (Step 11, fix 4): a label printed inside a drawn cell; the entry is the cell's
# empty part. The label starts at the cell's left edge, and the blank after it needs room for a
# short answer (on dev the real blanks are >= 9.4 em, a cell's padding after a trailing
# "(Yes / No)" is 4.4 em). A caption at the bottom of a cell (a signature box) leaves the space
# above it. Photo and thumb-impression boxes get no box: nothing is written there.
MIN_INSIDE_BLANK_EM = 5.0
INSIDE_LEFT_EM = 2.0
CAPTION_SPACE_EM = 2.0
NO_ENTRY_WORDS = ("photo", "thumb")
MIN_BOX_HEIGHT = 6.0  # SPEC §6.7 minimum font size; smaller boxes are flagged
# Labels.
LABEL_GAP_EM = 2.0  # words further apart than this (in font sizes) are separate phrases
LABEL_MAX_DISTANCE = 250.0
LABEL_ABOVE_MAX_GAP_EM = 2.5
HEADING_SIZE_FACTOR = 1.15

Rect = tuple[float, float, float, float]

# Candidate priorities when boxes overlap: lower wins.
_PRIORITY = {"checkbox": 0, "comb": 1, "box": 2, "line": 3, "leader": 4, "inside": 5, "colon": 6}


@dataclass(frozen=True)
class _Token:
    """A word of label text (leader characters excluded)."""

    text: str
    rect: Rect
    baseline: float
    size: float

    @property
    def vcenter(self) -> float:
        return (self.rect[1] + self.rect[3]) / 2


@dataclass(frozen=True)
class _TextLine:
    text: str
    rect: Rect
    size: float
    bold: bool


@dataclass(frozen=True)
class _Leader:
    x0: float
    x1: float
    baseline: float
    size: float
    underscores: int
    dot_weight: int
    hyphens: int


@dataclass(frozen=True)
class _Segment:
    pos: float  # y for horizontal, x for vertical
    start: float
    end: float
    structural: bool = False  # an edge of a drawn rectangle


@dataclass
class _Candidate:
    rect: Rect
    kind: FieldKind
    group: str  # key of _PRIORITY
    source: str  # human-readable, for the trace
    writing_line: float | None = None  # line-type entries only
    max_chars: int | None = None
    label: str | None = None
    context: str | None = None
    validations: list[ValidationResult] = field(default_factory=list)
    no_fill_reason: Literal["office_use"] | None = None
    case_hint: Literal["label", "page"] | None = None  # write the value upper-case
    hint: str | None = None  # the grey hint printed in a comb part ("FIRST NAME", "DD")
    date_part: DatePart | None = None
    # P5-D8: ("choices" | "table_row" | "line_row", number, row); a line row is a table_row
    answer_group: tuple[str, int, int] | None = None
    answer_group_label: str | None = None

    @property
    def line_type(self) -> bool:
        return self.writing_line is not None


@dataclass(frozen=True)
class _PageText:
    tokens: list[_Token]
    lines: list[_TextLine]
    leaders: list[_Leader]
    median_size: float
    hints: list[_Token] = field(default_factory=list)  # one per character; never labels


# --- small geometry helpers ---------------------------------------------------------------


def _area(r: Rect) -> float:
    return max(r[2] - r[0], 0.0) * max(r[3] - r[1], 0.0)


def _intersection(a: Rect, b: Rect) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def _iou(a: Rect, b: Rect) -> float:
    inter = _intersection(a, b)
    return inter / (_area(a) + _area(b) - inter) if inter else 0.0


def _contains(outer: Rect, inner: Rect, tol: float = SNAP) -> bool:
    return (
        outer[0] - tol <= inner[0]
        and outer[1] - tol <= inner[1]
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def _vertical_overlap(a: Rect, b: Rect) -> float:
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


# --- text ---------------------------------------------------------------------------------


def _stays_in_word(run: list[dict]) -> bool:
    """Short punctuation belongs to the text, not a leader: up to three dots ("No.", "e.g.",
    "...") and fewer than MIN_HYPHENS dashes ("E-mail", "2023-24", "/-", ":-", "---")."""
    dots = sum(1 for char in run if char["c"] == ".")
    dashes = sum(1 for char in run if char["c"] in HYPHENS)
    return dots + dashes == len(run) and dots <= 3 and dashes < MIN_HYPHENS


def _split_span(chars: list[dict], size: float) -> tuple[list[list[dict]], list[list[dict]]]:
    """Split a span's characters into words (label text) and leader runs."""
    words: list[list[dict]] = []
    runs: list[list[dict]] = []
    word: list[dict] = []
    run: list[dict] = []

    def end_run() -> None:
        nonlocal word, run
        if not run:
            return
        if _stays_in_word(run):
            word.extend(run)
        else:
            if word:
                words.append(word)
                word = []
            runs.append(run)
        run = []

    for char in chars:
        c = char["c"]
        if c in LEADER_WEIGHT:
            run.append(char)
            continue
        end_run()
        if c.isspace():
            if word:
                words.append(word)
                word = []
            continue
        if word and char["bbox"][0] - word[-1]["bbox"][2] > 0.3 * size:
            words.append(word)  # no space character, but a visible gap
            word = []
        word.append(char)
    end_run()
    if word:
        words.append(word)
    return words, runs


def _is_hint(color: int) -> bool:
    """Grey text, by its sRGB luminance (Rec. 709 weights on the encoded values)."""
    r, g, b = ((color >> shift) & 0xFF for shift in (16, 8, 0))
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255
    return HINT_LUMINANCE[0] <= luminance <= HINT_LUMINANCE[1]


def _extract_text(page: pymupdf.Page) -> _PageText:
    flags = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    tokens: list[_Token] = []
    lines: list[_TextLine] = []
    leaders: list[_Leader] = []
    hints: list[_Token] = []
    sizes: list[float] = []

    for block in page.get_text("rawdict", flags=flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            words_in_line: list[str] = []
            line_size, line_bold = 0.0, False
            for span in line["spans"]:
                size = float(span["size"])
                words, runs = _split_span(span["chars"], size)
                leaders += [_leader(run, size) for run in runs]
                if _is_hint(span.get("color", 0)):
                    # Hints count per character: each one sits in its own comb cell.
                    hints += [_token([char], size) for word in words for char in word]
                    continue
                tokens += [_token(word, size) for word in words]
                words_in_line += ["".join(c["c"] for c in word) for word in words]
                sizes += [size] * sum(len(word) for word in words)
                line_size = max(line_size, size)
                line_bold = line_bold or bool(span["flags"] & 16) or "bold" in span["font"].lower()
            if words_in_line:
                text = " ".join(words_in_line)
                lines.append(_TextLine(text, tuple(line["bbox"]), line_size, line_bold))

    median_size = statistics.median(sizes) if sizes else 10.0
    leaders = [leader for leader in _merge_leaders(leaders) if not _is_separator(leader, tokens)]
    return _PageText(tokens, lines, leaders, median_size, hints)


def _token(chars: list[dict], size: float) -> _Token:
    x0 = min(c["bbox"][0] for c in chars)
    y0 = min(c["bbox"][1] for c in chars)
    x1 = max(c["bbox"][2] for c in chars)
    y1 = max(c["bbox"][3] for c in chars)
    return _Token("".join(c["c"] for c in chars), (x0, y0, x1, y1), chars[0]["origin"][1], size)


def _leader(chars: list[dict], size: float) -> _Leader:
    return _Leader(
        x0=chars[0]["bbox"][0],
        x1=chars[-1]["bbox"][2],
        baseline=chars[0]["origin"][1],
        size=size,
        underscores=sum(1 for c in chars if c["c"] == "_"),
        dot_weight=sum(LEADER_WEIGHT[c["c"]] for c in chars if c["c"] in DOTS),
        hyphens=sum(1 for c in chars if c["c"] in HYPHENS),
    )


def _merge_leaders(leaders: list[_Leader]) -> list[_Leader]:
    """Join runs on the same baseline separated by at most a space ("_ _ _", split spans)."""
    merged: list[_Leader] = []
    for leader in sorted(leaders, key=lambda r: (round(r.baseline), r.x0)):
        last = merged[-1] if merged else None
        if (
            last is not None
            and abs(last.baseline - leader.baseline) <= 1.0
            and leader.x0 - last.x1 <= 0.5 * leader.size
        ):
            merged[-1] = _Leader(
                last.x0,
                max(last.x1, leader.x1),
                last.baseline,
                max(last.size, leader.size),
                last.underscores + leader.underscores,
                last.dot_weight + leader.dot_weight,
                last.hyphens + leader.hyphens,
            )
        else:
            merged.append(leader)
    return [
        leader
        for leader in merged
        if (
            leader.underscores >= MIN_UNDERSCORES
            or leader.dot_weight >= MIN_DOT_WEIGHT
            or leader.hyphens >= MIN_HYPHENS
        )
        and leader.x1 - leader.x0 >= MIN_LEADER_WIDTH
    ]


def _is_separator(leader: _Leader, tokens: Sequence[_Token]) -> bool:
    """A dash line with no words on its row is a printed separator when it spans most of the
    text width, or a table rule drawn in text when "+" / "|" joints sit on its row."""
    if not leader.hyphens:
        return False
    row = [t for t in tokens if abs(t.baseline - leader.baseline) <= max(0.4 * leader.size, SNAP)]
    if any(ch.isalnum() for t in row for ch in t.text):
        return False
    if any(set(t.text) <= TABLE_JOINTS for t in row):
        return True
    left = min((t.rect[0] for t in tokens), default=leader.x0)
    right = max((t.rect[2] for t in tokens), default=leader.x1)
    return leader.x1 - leader.x0 >= SEPARATOR_WIDTH_SHARE * (right - left)


# --- drawings -----------------------------------------------------------------------------


@dataclass
class _Drawings:
    horizontal: list[_Segment]
    vertical: list[_Segment]
    rects: list[Rect]


def _extract_drawings(page: pymupdf.Page) -> _Drawings:
    horizontal: list[_Segment] = []
    vertical: list[_Segment] = []
    rects: list[Rect] = []

    def add_rect_like(rect: pymupdf.Rect, stroked: bool) -> None:
        rect = pymupdf.Rect(rect).normalize()
        if rect.height <= MAX_LINE_THICKNESS and rect.width > MAX_LINE_THICKNESS:
            horizontal.append(_Segment((rect.y0 + rect.y1) / 2, rect.x0, rect.x1))
        elif rect.width <= MAX_LINE_THICKNESS and rect.height > MAX_LINE_THICKNESS:
            vertical.append(_Segment((rect.x0 + rect.x1) / 2, rect.y0, rect.y1))
        elif stroked and rect.width > MAX_LINE_THICKNESS:
            r = (rect.x0, rect.y0, rect.x1, rect.y1)
            rects.append(r)
            # Edges take part in table reconstruction, but are never entry lines themselves.
            horizontal.extend([_Segment(r[1], r[0], r[2], True), _Segment(r[3], r[0], r[2], True)])
            vertical.extend([_Segment(r[0], r[1], r[3], True), _Segment(r[2], r[1], r[3], True)])

    for drawing in page.get_drawings():
        stroked = drawing.get("color") is not None and "s" in (drawing.get("type") or "")
        items: list[tuple] = []
        for path in _subpaths(drawing["items"]):
            box = _rounded_box(path) if stroked else None
            if box is None:
                items += path
            else:
                add_rect_like(box, stroked)  # its straight edges are sides, not writing lines
        for item in items:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) <= AXIS_TOLERANCE and abs(p1.x - p2.x) > AXIS_TOLERANCE:
                    y = (p1.y + p2.y) / 2
                    horizontal.append(_Segment(y, min(p1.x, p2.x), max(p1.x, p2.x)))
                elif abs(p1.x - p2.x) <= AXIS_TOLERANCE and abs(p1.y - p2.y) > AXIS_TOLERANCE:
                    x = (p1.x + p2.x) / 2
                    vertical.append(_Segment(x, min(p1.y, p2.y), max(p1.y, p2.y)))
            elif item[0] == "re":
                add_rect_like(item[1], stroked)
            elif item[0] == "qu" and _is_axis_aligned(item[1]):
                add_rect_like(item[1].rect, stroked)

    return _Drawings(_merge_segments(horizontal), _merge_segments(vertical), rects)


def _subpaths(items: list[tuple]) -> list[list[tuple]]:
    """A drawing's items split into connected runs of lines and curves; "re" and "qu" items
    stand alone."""
    paths: list[list[tuple]] = []
    for item in items:
        previous = paths[-1][-1] if paths else None
        if (
            item[0] in ("l", "c")
            and previous is not None
            and previous[0] in ("l", "c")
            and abs(item[1] - previous[-1]) <= AXIS_TOLERANCE
        ):
            paths[-1].append(item)
        else:
            paths.append([item])
    return paths


def _rounded_box(path: list[tuple]) -> pymupdf.Rect | None:
    """A closed run of lines and curves whose straight lines all lie on its bounding box: a box
    with rounded corners (dev form #41), or None. A shape of curves only (a circle) is not."""
    kinds = {item[0] for item in path}
    if kinds != {"l", "c"} or abs(path[0][1] - path[-1][-1]) > AXIS_TOLERANCE:
        return None
    box = pymupdf.Rect(path[0][1], path[0][1])
    for item in path:
        for point in item[1:]:
            box |= point
    for kind, p1, p2, *_ in path:
        if kind != "l":
            continue
        on_side = (
            abs(p1.y - p2.y) <= AXIS_TOLERANCE
            and min(abs(p1.y - box.y0), abs(p1.y - box.y1)) <= AXIS_TOLERANCE
        ) or (
            abs(p1.x - p2.x) <= AXIS_TOLERANCE
            and min(abs(p1.x - box.x0), abs(p1.x - box.x1)) <= AXIS_TOLERANCE
        )
        if not on_side:
            return None
    return box


def _is_axis_aligned(quad: pymupdf.Quad) -> bool:
    """True if the quad is an axis-aligned rectangle, whatever the order of its corners.

    PyMuPDF's `Quad.is_rectangular` is False for corners listed in a rotated order, which
    some forms use for plain squares (dev form #3).
    """
    points = (quad.ul, quad.ur, quad.ll, quad.lr)
    xs = sorted(p.x for p in points)
    ys = sorted(p.y for p in points)
    return (
        xs[1] - xs[0] <= AXIS_TOLERANCE
        and xs[3] - xs[2] <= AXIS_TOLERANCE
        and ys[1] - ys[0] <= AXIS_TOLERANCE
        and ys[3] - ys[2] <= AXIS_TOLERANCE
    )


def _merge_segments(segments: list[_Segment]) -> list[_Segment]:
    """Join collinear, touching or nearly touching segments (e.g. a line drawn in pieces).

    Segments are first grouped by position (within AXIS_TOLERANCE of the group's first one),
    then the intervals inside each group are merged in order of their start.
    """
    groups: list[list[_Segment]] = []
    for seg in sorted(segments, key=lambda s: s.pos):
        if groups and seg.pos - groups[-1][0].pos <= AXIS_TOLERANCE:
            groups[-1].append(seg)
        else:
            groups.append([seg])

    merged: list[_Segment] = []
    for group in groups:
        current: list[_Segment] = []
        for seg in sorted(group, key=lambda s: s.start):
            if current and seg.start > max(s.end for s in current) + MERGE_GAP:
                merged.append(_join(current))
                current = []
            current.append(seg)
        merged.append(_join(current))
    return merged


def _join(parts: list[_Segment]) -> _Segment:
    return _Segment(
        pos=sum(s.pos for s in parts) / len(parts),
        start=min(s.start for s in parts),
        end=max(s.end for s in parts),
        structural=all(s.structural for s in parts),
    )


def _touches(h: _Segment, v: _Segment) -> bool:
    return h.start - SNAP <= v.pos <= h.end + SNAP and v.start - SNAP <= h.pos <= v.end + SNAP


def _grid_cells(horizontal: list[_Segment], vertical: list[_Segment]) -> list[Rect]:
    """Cells bounded by horizontal and vertical segments (tables, comb rows drawn as lines)."""
    cells: list[Rect] = []
    by_y = sorted(horizontal, key=lambda s: s.pos)
    for top in by_y:
        hanging = sorted(
            (
                v
                for v in vertical
                if top.start - SNAP <= v.pos <= top.end + SNAP
                and v.start - SNAP <= top.pos
                and v.end > top.pos + SNAP
            ),
            key=lambda v: v.pos,
        )
        for left, right in pairwise(hanging):
            if right.pos - left.pos < MIN_CELL_SIZE:
                continue
            bottom_limit = min(left.end, right.end) + SNAP
            for bottom in by_y:
                if bottom.pos <= top.pos + MIN_CELL_SIZE:
                    continue
                if bottom.pos > bottom_limit:
                    break
                if bottom.start - SNAP <= left.pos and right.pos <= bottom.end + SNAP:
                    cells.append((left.pos, top.pos, right.pos, bottom.pos))
                    break
    return cells


# --- candidates ---------------------------------------------------------------------------


def _row_height(size: float) -> float:
    return ROW_HEIGHT_FACTOR * size


def _leader_candidates(text: _PageText) -> list[_Candidate]:
    candidates = []
    for leader in text.leaders:
        counts = {
            "underscore run": leader.underscores,
            "dot leader": leader.dot_weight,
            "hyphen leader": leader.hyphens,
        }
        kind = max(counts, key=counts.__getitem__)  # ties: the earlier kind, as before
        rect = (leader.x0, leader.baseline - _row_height(leader.size), leader.x1, leader.baseline)
        candidates.append(
            _Candidate(rect, FieldKind.TEXT, "leader", kind, writing_line=leader.baseline)
        )
    return candidates


def _is_underline(seg: _Segment, text: _PageText) -> bool:
    """A line drawn under printed text (e.g. an underlined heading) is not an entry area."""
    covered = 0.0
    for token in text.tokens:
        if token.baseline < seg.pos - token.size or token.baseline > seg.pos + 1.0:
            continue
        covered += max(0.0, min(token.rect[2], seg.end) - max(token.rect[0], seg.start))
    return covered >= 0.5 * (seg.end - seg.start)


def _line_label_size(seg: _Segment, text: _PageText) -> float:
    """Font size of the text on the line's row, left of it; else the page's median size."""
    row = [
        t
        for t in text.tokens
        if t.rect[2] <= seg.start + SNAP and seg.pos - t.size <= t.baseline <= seg.pos + SNAP
    ]
    return max(row, key=lambda t: t.rect[2]).size if row else text.median_size


def _line_candidates(drawings: _Drawings, text: _PageText) -> list[_Candidate]:
    candidates = []
    for seg in drawings.horizontal:
        if seg.structural or seg.end - seg.start < MIN_LINE_LENGTH:
            continue
        # Table rules are touched by two or more vertical lines; an entry line is not.
        if sum(1 for v in drawings.vertical if _touches(seg, v)) >= 2:
            continue
        if _is_underline(seg, text):
            continue
        size = _line_label_size(seg, text)
        rect = (seg.start, seg.pos - _row_height(size), seg.end, seg.pos)
        candidates.append(_Candidate(rect, FieldKind.TEXT, "line", "drawn line", seg.pos))
    return candidates


def _in_cell(rect: Rect, token: _Token) -> bool:
    cx = (token.rect[0] + token.rect[2]) / 2
    return rect[0] <= cx <= rect[2] and rect[1] <= token.vcenter <= rect[3]


def _has_text_inside(rect: Rect, tokens: Sequence[_Token]) -> bool:
    return any(_in_cell(rect, token) for token in tokens)


def _box_candidates(
    drawings: _Drawings, grid: list[Rect], text: _PageText, page_area: float
) -> list[_Candidate]:
    sources: list[tuple[Rect, str]] = [(r, "rectangle") for r in drawings.rects]
    sources += [(c, "table cell") for c in grid]

    boxes: list[tuple[Rect, str]] = []
    for rect, source in sources:
        if rect[2] - rect[0] < MIN_CELL_SIZE or rect[3] - rect[1] < MIN_CELL_SIZE:
            continue
        if _area(rect) > MAX_BOX_PAGE_SHARE * page_area:
            continue
        if any(_iou(rect, kept) > 0.9 for kept, _ in boxes):
            continue  # the same box drawn as a rectangle and rebuilt from lines
        if _has_text_inside(rect, text.tokens):
            continue
        boxes.append((rect, source))

    # A box that contains other boxes is a frame (table border, comb outline), not an entry.
    boxes = [
        (rect, source)
        for rect, source in boxes
        if not any(other != rect and _contains(rect, other) for other, _ in boxes)
    ]

    combs, singles, single_hints = _group_combs(
        [rect for rect, _ in boxes], text.tokens, text.hints
    )
    source_of = dict(boxes)
    candidates = combs
    for rect in singles:
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        ratio = width / height
        if (
            SQUARE_RATIO[0] <= ratio <= SQUARE_RATIO[1]
            and CHECKBOX_SIZE[0] <= max(width, height) <= CHECKBOX_SIZE[1]
        ):
            candidates.append(_Candidate(rect, FieldKind.CHECKBOX, "checkbox", "checkbox"))
        else:
            source = source_of.get(rect, "comb cell")  # a one-cell hinted part, trimmed
            cand = _Candidate(rect, FieldKind.TEXT, "box", source)
            cand.hint = single_hints.get(rect)
            candidates.append(cand)
    return candidates


def _group_combs(
    rects: list[Rect], tokens: Sequence[_Token], hints: Sequence[_Token] = ()
) -> tuple[list[_Candidate], list[Rect], dict[Rect, str]]:
    """Merge rows of small adjacent cells into comb fields (decision D8, labelling rule 1).

    Returns the combs, the cells left single, and the hint printed in a single cell that is a
    hinted part of its own ("DD" in one wide cell)."""
    small = [
        r for r in rects if r[2] - r[0] <= COMB_CELL_MAX[0] and r[3] - r[1] <= COMB_CELL_MAX[1]
    ]
    small_set = set(small)
    rest = [r for r in rects if r not in small_set]

    rows: list[list[Rect]] = []
    for rect in sorted(small, key=lambda r: (round(r[1]), r[0])):
        for row in rows:
            first = row[0]
            if abs(first[1] - rect[1]) <= 1.0 and abs(first[3] - rect[3]) <= 1.0:
                row.append(rect)
                break
        else:
            rows.append([rect])

    combs: list[_Candidate] = []
    singles: list[Rect] = list(rest)
    single_hints: dict[Rect, str] = {}
    for row in rows:
        row.sort(key=lambda r: r[0])
        gaps = [b[0] - a[2] for a, b in pairwise(row)]
        split_gap = max(MIN_SPLIT_GAP, SPLIT_GAP_FACTOR * statistics.median(gaps or [0.0]))
        runs = [[row[0]]]
        for cell in row[1:]:
            if _continues_comb(runs[-1][-1], cell, tokens, split_gap):
                runs[-1].append(cell)
            else:
                runs.append([cell])
        for run in runs:
            run_hints = [_hint_in(cell, hints) for cell in run]
            for start, end in _hinted_parts(run_hints):
                # Parts cut from one run share a cell edge; drawn edges can overlap by a
                # fraction of a point, so a part starts where the previous cell ends.
                left = run[start - 1][2] if start else None
                hint = _hint_text(run_hints[start:end])
                cand = _close_comb(run[start:end], combs, singles, left)
                if cand is not None:
                    cand.hint = hint
                elif hint is not None:
                    single_hints[singles[-1]] = hint
    return combs, singles, single_hints


def _hint_text(hints: Sequence[str]) -> str | None:
    """The hint of a part as words: cells hinted F I R S T _ N A M E -> "FIRST NAME"."""
    words: list[str] = []
    word = ""
    for hint in hints:
        if hint:
            word += hint
        elif word:
            words.append(word)
            word = ""
    if word:
        words.append(word)
    return " ".join(_spaced(w) for w in words) or None


def _spaced(word: str) -> str:
    """ "FIRSTNAME" -> "FIRST NAME": a hint printed without the space before its last word."""
    for last in sorted(COMPLETING_HINTS, key=len, reverse=True):
        if word.upper().endswith(last) and len(word) > len(last) + 1:
            return f"{word[: -len(last)]} {word[-len(last) :]}"
    return word


def _date_part(hint: str | None) -> DatePart | None:
    """ "DD" -> day, "MM" -> month, "YYYY" / "YY" -> year; any other hint is not a date part."""
    letters = (hint or "").replace(" ", "").upper()
    if len(letters) < 2 or len(set(letters)) != 1:
        return None
    return DATE_HINT_PARTS.get(letters[0])


def _hint_in(cell: Rect, hints: Sequence[_Token]) -> str:
    inside = [
        h
        for h in hints
        if cell[0] <= (h.rect[0] + h.rect[2]) / 2 <= cell[2] and cell[1] <= h.vcenter <= cell[3]
    ]
    return "".join(h.text for h in sorted(inside, key=lambda h: h.rect[0]))


def _hinted_parts(hints: Sequence[str]) -> list[tuple[int, int]]:
    """Split a comb run into its hinted parts (labelling rule 1), as [start, end) cell ranges.

    hints[i] is the hint printed in cell i ("" for none). Consecutive hinted cells are one part,
    except a date-like run of repeated letters ("DDMMYYYY"), which splits where the letter changes
    (D8), and a cell whose hint is a group ("DD"), which is a part of its own (rule 2). The empty
    cells between two parts are shared halfway, an odd middle cell going to the earlier part;
    empty cells before the first part and after the last part join it. A run without hints is
    one part.
    """
    hinted: list[tuple[int, int]] = []
    for i, hint in enumerate(hints):
        if not hint:
            continue
        group = len(hint) > 1  # a cell for a group ("DD"), not one character: its own part
        if hinted and hinted[-1][1] == i and not group and len(hints[i - 1]) == 1:
            hinted[-1] = (hinted[-1][0], i + 1)
        else:
            hinted.append((i, i + 1))
    joined: list[tuple[int, int]] = []
    for start, end in hinted:
        if (
            joined
            and start == joined[-1][1] + 1
            and "".join(hints[start:end]).upper() in COMPLETING_HINTS
            and all(len(h) == 1 for h in hints[joined[-1][0] : end] if h)
        ):
            joined[-1] = (joined[-1][0], end)  # "FIRST _ NAME": one part
        else:
            joined.append((start, end))
    parts = [part for start, end in joined for part in _date_groups(hints, start, end)]
    if not parts:
        return [(0, len(hints))]
    cuts = [end + (next_start - end + 1) // 2 for (_, end), (next_start, _) in pairwise(parts)]
    bounds = [0, *cuts, len(hints)]
    return list(pairwise(bounds))


def _date_groups(hints: Sequence[str], start: int, end: int) -> list[tuple[int, int]]:
    """Cells start..end hinted like "DDMMYYYY" (one letter per cell, every letter repeated) are
    one group per letter; any other hinted run ("FIRSTNAME", "STD") is one group."""
    letters = hints[start:end]
    groups: list[tuple[int, int]] = []
    for i, letter in enumerate(letters, start):
        if groups and hints[groups[-1][0]] == letter:
            groups[-1] = (groups[-1][0], i + 1)
        else:
            groups.append((i, i + 1))
    date_like = (
        len(groups) > 1
        and all(len(letter) == 1 for letter in letters)
        and all(group_end - group_start >= 2 for group_start, group_end in groups)
    )
    return groups if date_like else [(start, end)]


def _continues_comb(prev: Rect, cell: Rect, tokens: Sequence[_Token], split_gap: float) -> bool:
    prev_w, cell_w = prev[2] - prev[0], cell[2] - cell[0]
    if not 0.7 <= cell_w / prev_w <= 1.43:
        return False
    # D8: a gap wider than a cell always splits; a narrower one splits when it is clearly wider
    # than the row's usual spacing (split_gap).
    if cell[0] - prev[2] > min(max(prev_w, cell_w), split_gap):
        return False
    gap = (prev[2] - 0.5, prev[1], cell[0] + 0.5, prev[3])
    for token in tokens:  # printed text or a separator between the cells (D8)
        cx = (token.rect[0] + token.rect[2]) / 2
        if gap[0] <= cx <= gap[2] and _vertical_overlap(token.rect, gap) > 0.3 * (
            prev[3] - prev[1]
        ):
            return False
    return True


def _close_comb(
    run: list[Rect], combs: list[_Candidate], singles: list[Rect], left: float | None = None
) -> _Candidate | None:
    """Adds the comb (returned) or, for one cell, the single cell (None)."""
    if len(run) == 1:
        cell = run[0]
        singles.append(cell if left is None else (max(cell[0], left), *cell[1:]))
        return None
    x0 = run[0][0] if left is None else max(run[0][0], left)
    union = (x0, min(r[1] for r in run), run[-1][2], max(r[3] for r in run))
    comb = _Candidate(
        union,
        FieldKind.TEXT,
        "comb",
        f"comb row ({len(run)} cells)",
        max_chars=len(run),
    )
    combs.append(comb)
    return comb


def _inside_candidates(
    text: _PageText, cells: list[Rect], taken: list[_Candidate]
) -> list[_Candidate]:
    """Labelling rule 3: a drawn cell with its label printed inside; the entry is the empty part.

    A caption at the bottom of a cell (a signature box) leaves the space above it; otherwise each
    line that starts at the cell's left edge has a blank after each of its phrases, up to the next
    phrase or the cell's edge. Skipped: frames (cells around other cells), the label cells of a
    table (a cell starts at their right edge: that cell is the entry), cells holding a drawn entry,
    and photo and thumb-impression boxes.
    """
    unique: list[Rect] = []
    for cell in cells:
        if min(cell[2] - cell[0], cell[3] - cell[1]) < MIN_CELL_SIZE:
            continue
        if not any(_iou(cell, kept) > 0.9 for kept in unique):
            unique.append(cell)

    candidates: list[_Candidate] = []
    for cell in unique:
        tokens = [t for t in text.tokens if _in_cell(cell, t)]
        if not tokens or any(other is not cell and _contains(cell, other) for other in unique):
            continue
        if any(
            other is not cell and abs(other[0] - cell[2]) <= SNAP and _rows_overlap(other, cell)
            for other in unique
        ):
            continue
        if any(_contains(cell, c.rect) for c in taken):
            continue
        words = " ".join(t.text for t in tokens).lower()
        if any(word in words for word in NO_ENTRY_WORDS) and "sign" not in words:
            continue
        for cand in _caption_blank(cell, tokens) or _blanks_after_labels(cell, tokens):
            if not any(_intersection(cand.rect, c.rect) > 0 for c in taken):
                candidates.append(cand)
    return candidates


def _text_rows(tokens: Sequence[_Token]) -> list[list[_Token]]:
    """Tokens grouped into lines by baseline, each left to right."""
    rows: list[list[_Token]] = []
    for token in sorted(tokens, key=lambda t: (t.baseline, t.rect[0])):
        for row in rows:
            if abs(row[0].baseline - token.baseline) <= max(0.4 * token.size, SNAP):
                row.append(token)
                break
        else:
            rows.append([token])
    return [sorted(row, key=lambda t: t.rect[0]) for row in rows]


def _caption_blank(cell: Rect, tokens: Sequence[_Token]) -> list[_Candidate]:
    """All the text at the bottom of the cell: the entry is the space above it."""
    top, bottom = min(t.rect[1] for t in tokens), max(t.rect[3] for t in tokens)
    space = top - cell[1]
    if space < CAPTION_SPACE_EM * max(t.size for t in tokens) or cell[3] - bottom > 0.5 * space:
        return []
    caption = [t for row in _text_rows(tokens) for t in row]
    rect = (cell[0], cell[1], cell[2], top)
    return [
        _Candidate(
            rect,
            FieldKind.TEXT,
            "inside",
            "space above a caption in a cell",
            label=_clean_label(caption),
        )
    ]


def _blanks_after_labels(cell: Rect, tokens: Sequence[_Token]) -> list[_Candidate]:
    candidates = []
    for row in _text_rows(tokens):
        if row[0].rect[0] - cell[0] > INSIDE_LEFT_EM * row[0].size:
            continue  # centred or right-aligned text: a heading, not a label
        phrases = [[row[0]]]
        for prev, token in pairwise(row):
            if token.rect[0] - prev.rect[2] > LABEL_GAP_EM * max(prev.size, token.size):
                phrases.append([token])
            else:
                phrases[-1].append(token)
        for phrase, after in zip(phrases, [*phrases[1:], None], strict=True):
            if _ends_sentence(phrase[-1]):
                continue  # a notice or an instruction, not a label
            size = phrase[-1].size
            x0 = phrase[-1].rect[2] + 0.3 * size
            x1 = (after[0].rect[0] if after else cell[2]) - 0.3 * size
            if x1 - x0 < MIN_INSIDE_BLANK_EM * size:
                continue
            # Between the cell's other text lines above and below, where they reach the blank.
            beside = [t for t in tokens if t.rect[2] > x0 and t.rect[0] < x1]
            top = max(
                (t.rect[3] for t in beside if t.rect[3] <= phrase[-1].rect[1] + 0.5),
                default=cell[1],
            )
            bottom = min(
                (t.rect[1] for t in beside if t.rect[1] >= phrase[-1].rect[3] - 0.5),
                default=cell[3],
            )
            candidates.append(
                _Candidate(
                    (x0, top, x1, bottom),
                    FieldKind.TEXT,
                    "inside",
                    "blank after a label in a cell",
                    label=_clean_label(phrase),
                )
            )
    return candidates


def _ends_sentence(token: _Token) -> bool:
    """A word ending in a full stop ends a sentence ("form."); abbreviations ("No.") do not."""
    return token.text.endswith(".") and sum(ch.isalpha() for ch in token.text) > 3


def _colon_candidates(
    text: _PageText, drawings: _Drawings, cells: list[Rect], taken: list[_Candidate]
) -> list[_Candidate]:
    """Blanks after a colon with nothing drawn: from just after the colon to the next text on its
    line or the page's text margin; a line entry on the colon's baseline.

    Skipped where something is drawn (a leader, line or box is the entry), inside a drawn cell
    (a label inside a cell is labelling rule 3), and when a drawn table starts right below (the
    colon introduces the table).
    """
    if not text.tokens:
        return []
    margin = max(t.rect[2] for t in text.tokens)
    candidates = []
    for token in text.tokens:
        if not token.text.endswith(COLON_ENDINGS):
            continue
        size, baseline = token.size, token.baseline
        pad = 0.3 * size
        x0, top = token.rect[2] + pad, baseline - _row_height(size)
        x1 = min(
            (
                t.rect[0] - pad
                for t in text.tokens
                if t is not token
                and abs(t.baseline - baseline) <= max(0.4 * size, SNAP)
                and t.rect[0] >= token.rect[2] - 0.5
            ),
            default=margin,
        )
        if x1 - x0 < MIN_COLON_BLANK_EM * size:
            continue
        rect = (x0, top, x1, baseline)
        if any(_intersection(rect, c.rect) > 0 for c in taken):
            continue
        if any(
            h.start < x1 and h.end > x0 and top - SNAP <= h.pos <= baseline + 0.5 * size
            for h in drawings.horizontal
        ):
            continue
        if any(
            c[0] - SNAP <= token.rect[0]
            and token.rect[2] <= c[2] + SNAP
            and c[1] <= token.vcenter <= c[3]
            for c in cells
        ):
            continue
        if any(
            baseline < c[1] <= baseline + TABLE_BELOW_EM * size and c[0] < x1 and c[2] > x0
            for c in cells
        ):
            continue
        candidates.append(
            _Candidate(
                rect,
                FieldKind.TEXT,
                "colon",
                "blank after a colon",
                writing_line=baseline,
                label=_colon_label(token, text.tokens),
            )
        )
    return candidates


def _colon_label(colon: _Token, tokens: Sequence[_Token]) -> str | None:
    """The phrase that ends with the colon; a colon printed apart ("NAME OF THE BANK      :")
    still belongs to the phrase before it, however wide the gap."""
    row = [
        t
        for t in tokens
        if t is not colon
        and abs(t.baseline - colon.baseline) <= max(0.4 * colon.size, SNAP)
        and t.rect[2] <= colon.rect[0] + 0.5
    ]
    bare = colon.text in COLON_ENDINGS
    return _clean_label(_phrase(row if bare else [*row, colon], leftwards=True))


# --- overlaps -----------------------------------------------------------------------------


def _resolve_overlaps(
    candidates: list[_Candidate],
) -> tuple[list[_Candidate], list[tuple[_Candidate, _Candidate | None]]]:
    """Make sure no two entry boxes overlap.

    Candidates are taken by priority (checkbox, comb, box, drawn line, leader), then top to
    bottom. A later candidate that overlaps a kept one is dropped, except for line-type entries:
    - two line entries on different writing lines: the lower one starts at the upper one's
      writing line (dense rows); on the same writing line they are one entry drawn twice;
    - a line entry under a box: it starts at the box's bottom edge; mostly inside it: dropped.
    """
    ordered = sorted(
        candidates, key=lambda c: (_PRIORITY[c.group], c.rect[1], c.rect[0], c.rect[3])
    )
    kept: list[_Candidate] = []
    dropped: list[tuple[_Candidate, _Candidate | None]] = []
    for cand in ordered:
        rect = cand.rect
        blocker: _Candidate | None = None
        for index, other in enumerate(kept):
            if _intersection(rect, other.rect) == 0.0:
                continue
            if cand.writing_line is not None and other.writing_line is not None:
                if abs(cand.writing_line - other.writing_line) <= SNAP:
                    blocker = other
                    break
                if other.writing_line < cand.writing_line:
                    rect = (rect[0], max(rect[1], other.writing_line), rect[2], rect[3])
                else:
                    trimmed = (other.rect[0], cand.writing_line, other.rect[2], other.rect[3])
                    kept[index] = replace(other, rect=trimmed)
                continue
            if (
                cand.writing_line is not None
                and _intersection(rect, other.rect) < 0.5 * _area(rect)
                and other.rect[3] <= cand.writing_line
            ):
                rect = (rect[0], max(rect[1], other.rect[3]), rect[2], rect[3])
                continue
            blocker = other
            break
        if blocker is None and rect[3] - rect[1] >= 1.0:
            # Trimming against one box can still leave overlap with another: re-check.
            blocker = next((o for o in kept if _intersection(rect, o.rect) > 0), None)
            if blocker is None:
                kept.append(replace(cand, rect=rect))
                continue
        dropped.append((cand, blocker))
    return kept, dropped


# --- labels and context -------------------------------------------------------------------


def _same_row(cand: _Candidate, token: _Token) -> bool:
    if cand.writing_line is not None:
        return abs(token.baseline - cand.writing_line) <= max(0.4 * token.size, SNAP)
    return cand.rect[1] <= token.vcenter <= cand.rect[3]


def _rows_overlap(a: Rect, b: Rect) -> bool:
    overlap = _vertical_overlap(a, b)
    return overlap >= 0.5 * min(a[3] - a[1], b[3] - b[1])


def _phrase(tokens: list[_Token], leftwards: bool) -> list[_Token]:
    """The tokens nearest to the field that form one phrase (no gap wider than LABEL_GAP_EM)."""
    ordered = sorted(tokens, key=lambda t: t.rect[0], reverse=leftwards)
    phrase: list[_Token] = []
    for token in ordered:
        if phrase:
            prev = phrase[-1]
            gap = prev.rect[0] - token.rect[2] if leftwards else token.rect[0] - prev.rect[2]
            if gap > LABEL_GAP_EM * max(token.size, prev.size):
                break
        phrase.append(token)
    return sorted(phrase, key=lambda t: t.rect[0])


def _clean_label(tokens: Iterable[_Token]) -> str | None:
    text = " ".join(t.text for t in tokens).strip().removesuffix(":-").rstrip(":").strip()
    return text if any(ch.isalnum() for ch in text) else None


def _label_left(cand: _Candidate, others: list[_Candidate], tokens: list[_Token]) -> str | None:
    boundary = max(
        (
            o.rect[2]
            for o in others
            if o is not cand
            and o.rect[2] <= cand.rect[0] + SNAP
            and _rows_overlap(o.rect, cand.rect)
        ),
        default=cand.rect[0] - LABEL_MAX_DISTANCE,
    )
    row = [
        t
        for t in tokens
        if _same_row(cand, t) and t.rect[2] <= cand.rect[0] + 0.5 and t.rect[0] >= boundary - 0.5
    ]
    return _clean_label(_phrase(row, leftwards=True)) if row else None


def _label_right(cand: _Candidate, others: list[_Candidate], tokens: list[_Token]) -> str | None:
    boundary = min(
        (
            o.rect[0]
            for o in others
            if o is not cand
            and o.rect[0] >= cand.rect[2] - SNAP
            and _rows_overlap(o.rect, cand.rect)
        ),
        default=cand.rect[2] + LABEL_MAX_DISTANCE,
    )
    row = [
        t
        for t in tokens
        if _same_row(cand, t) and t.rect[0] >= cand.rect[2] - 0.5 and t.rect[2] <= boundary + 0.5
    ]
    if not row:
        return None
    nearest = min(row, key=lambda t: t.rect[0])
    if nearest.rect[0] - cand.rect[2] > LABEL_GAP_EM * nearest.size:
        return None
    return _clean_label(_phrase(row, leftwards=False))


def _label_above(cand: _Candidate, tokens: list[_Token], median_size: float) -> str | None:
    slack = 0.5 * median_size
    above = [
        t
        for t in tokens
        if t.rect[3] <= cand.rect[1] + 1.0
        and t.rect[3] >= cand.rect[1] - LABEL_ABOVE_MAX_GAP_EM * median_size
        and t.rect[2] > cand.rect[0] - slack
        and t.rect[0] < cand.rect[2]
    ]
    if not above:
        return None
    nearest = max(t.baseline for t in above)
    return _clean_label(
        t for t in sorted(above, key=lambda t: t.rect[0]) if nearest - t.baseline <= 0.5 * t.size
    )


def _is_heading(line: _TextLine, median_size: float) -> bool:
    letters = sum(1 for ch in line.text if ch.isalpha())
    if letters < 3 or is_instruction(line.text):
        return False  # "Please fill in CAPITAL LETTERS only." is not a section
    all_caps = line.text.upper() == line.text and len(line.text.split()) >= 2
    return line.bold or line.size >= HEADING_SIZE_FACTOR * median_size or all_caps


def _context(cand: _Candidate, text: _PageText) -> str | None:
    headings = [
        line
        for line in text.lines
        if line.rect[3] <= cand.rect[1] + 1.0 and _is_heading(line, text.median_size)
    ]
    if not headings:
        return None
    return max(headings, key=lambda line: (line.rect[3], -line.rect[0])).text


def _label(cand: _Candidate, candidates: list[_Candidate], text: _PageText) -> str | None:
    """Tick boxes look right first (the label follows the box); entries look left, then above."""
    if cand.kind in (FieldKind.CHECKBOX, FieldKind.RADIO):
        return (
            _label_right(cand, candidates, text.tokens)
            or _label_left(cand, candidates, text.tokens)
            or _label_above(cand, text.tokens, text.median_size)
        )
    return _label_left(cand, candidates, text.tokens) or _label_above(
        cand, text.tokens, text.median_size
    )


def _assign_text(candidates: list[_Candidate], text: _PageText) -> None:
    for cand in candidates:
        if cand.label is None:  # colon blanks and blanks inside cells already have theirs
            cand.label = _label(cand, candidates, text)
        cand.context = _context(cand, text)
        if cand.rect[3] - cand.rect[1] < MIN_BOX_HEIGHT:
            cand.validations.append(
                ValidationResult(
                    validator="min_box_height",
                    ok=False,
                    message=f"entry box is lower than {MIN_BOX_HEIGHT:g} pt",
                )
            )


# --- tables, hinted parts and tick-box rows (Phase 5, decision P5-D8) ---------------------


@dataclass(frozen=True)
class _Table:
    """A full grid of drawn cells: rows x columns, no merged cells."""

    number: int
    rows: int
    cols: int
    rects: dict[tuple[int, int], Rect]
    texts: dict[tuple[int, int], str | None]  # None: an empty cell

    @property
    def header(self) -> bool:
        """The top row names the columns: text in each of its cells, an empty cell below."""
        named = all(self.texts[(0, c)] for c in range(self.cols))
        return named and any(
            self.texts[(r, c)] is None for r in range(1, self.rows) for c in range(self.cols)
        )

    def entries(self) -> dict[tuple[int, int], Rect]:
        start = 1 if self.header else 0
        return {
            (r, c): rect
            for (r, c), rect in self.rects.items()
            if r >= start and self.texts[(r, c)] is None
        }

    @property
    def repeated_rows(self) -> bool:
        """Columns named by the header with an entry in two or more of them: each row is one
        instance (a class, a nominee). A header over one entry column is a label table."""
        return self.header and len({c for _, c in self.entries()}) >= 2

    def row_label(self, row: int) -> str | None:
        return self.texts[(row, 0)]


def _bands(spans: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    bands: list[tuple[float, float]] = []
    for lo, hi in sorted(spans):
        if not any(abs(lo - b[0]) <= SNAP and abs(hi - b[1]) <= SNAP for b in bands):
            bands.append((lo, hi))
    return bands


def _band_of(lo: float, hi: float, bands: list[tuple[float, float]]) -> int | None:
    for i, (b0, b1) in enumerate(bands):
        if abs(lo - b0) <= SNAP and abs(hi - b1) <= SNAP:
            return i
    return None


def _cell_text(cell: Rect, tokens: Sequence[_Token]) -> str | None:
    inside = [t for t in tokens if _in_cell(cell, t)]
    return _clean_label(t for row in _text_rows(inside) for t in row) if inside else None


def _adjacent(a: Rect, b: Rect) -> bool:
    """Two cells share an edge: side by side on a row, or one above the other in a column."""
    side = (abs(a[2] - b[0]) <= SNAP or abs(b[2] - a[0]) <= SNAP) and _rows_overlap(a, b)
    width = min(a[2] - a[0], b[2] - b[0])
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    stacked = (abs(a[3] - b[1]) <= SNAP or abs(b[3] - a[1]) <= SNAP) and overlap >= 0.5 * width
    return side or stacked


def _tables(cells: Sequence[Rect], text: _PageText) -> list[_Table]:
    """Drawn cells that form full grids of at least 2 x 2 (comb cells and tick boxes aside); a
    row of one cell across the whole table (a note) is left out."""
    unique: list[Rect] = []
    for cell in cells:
        width, height = cell[2] - cell[0], cell[3] - cell[1]
        if min(width, height) < MIN_CELL_SIZE:
            continue
        if width <= COMB_CELL_MAX[0] and height <= COMB_CELL_MAX[1]:
            continue
        if not any(_iou(cell, kept) > 0.9 for kept in unique):
            unique.append(cell)
    unique = [c for c in unique if not any(o is not c and _contains(c, o) for o in unique)]

    parent = list(range(len(unique)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(unique):
        for j in range(i + 1, len(unique)):
            if _adjacent(a, unique[j]):
                parent[root(i)] = root(j)
    members: dict[int, list[Rect]] = {}
    for i, cell in enumerate(unique):
        members.setdefault(root(i), []).append(cell)

    tables: list[_Table] = []
    for found in sorted(members.values(), key=lambda g: min((c[1], c[0]) for c in g)):
        # A row of one cell across the whole table is a note between the rows, not a row.
        left, right = min(c[0] for c in found), max(c[2] for c in found)
        group = [c for c in found if abs(c[0] - left) > SNAP or abs(c[2] - right) > SNAP]
        rows = _bands((c[1], c[3]) for c in group)
        cols = _bands((c[0], c[2]) for c in group)
        if len(rows) < 2 or len(cols) < 2 or len(group) != len(rows) * len(cols):
            continue
        rects: dict[tuple[int, int], Rect] = {}
        for cell in group:
            r, c = _band_of(cell[1], cell[3], rows), _band_of(cell[0], cell[2], cols)
            if r is not None and c is not None:
                rects[(r, c)] = cell
        if len(rects) != len(group):
            continue
        texts = {key: _cell_text(rect, text.tokens) for key, rect in rects.items()}
        tables.append(_Table(len(tables), len(rows), len(cols), rects, texts))
    return tables


def _in_table_header(cand: _Candidate, tables: Sequence[_Table]) -> bool:
    """A blank found inside a cell of a table's header row ("% / CGPA"): a column name."""
    return any(
        _contains(table.rects[(0, c)], cand.rect)
        for table in tables
        if table.repeated_rows
        for c in range(table.cols)
    )


def _label_tables(candidates: list[_Candidate], tables: Sequence[_Table], text: _PageText) -> None:
    """Entry cells of a table whose header names the columns get the column's name as label
    and the heading above the table as context. With two or more rows of entries, each row is
    a group (`table_row`, P5-D8) labelled by its first cell."""
    for table in tables:
        if not table.repeated_rows:
            continue
        entries = table.entries()
        found = {
            key: cand
            for cand in candidates
            for key, rect in entries.items()
            if _iou(cand.rect, rect) > 0.9
        }
        rows = {r for r, _ in found}
        top = table.rects[(0, 0)]
        context = _context(_Candidate(top, FieldKind.TEXT, "box", "table"), text)
        for (r, c), cand in found.items():
            cand.label = table.texts[(0, c)]
            cand.context = context
            if len(rows) >= 2:
                cand.answer_group = ("table_row", table.number, r)
                cand.answer_group_label = table.row_label(r)


def _row_lead(first: _Candidate, tokens: Sequence[_Token]) -> str | None:
    """The text a row starts with, before its first entry's own label: "(a) High School" in
    "(a) High School    Year ...... Roll No. ......"."""
    left = [t for t in tokens if _same_row(first, t) and t.rect[2] <= first.rect[0] + 0.5]
    label = _phrase(left, leftwards=True)
    rest = [t for t in left if t not in label]
    return _clean_label(_phrase(rest, leftwards=True)) if rest else None


def _group_repeated_rows(candidates: list[_Candidate], text: _PageText) -> None:
    """Rows in a row of the page with the same labelled entries in the same columns ("Year
    ...... Roll No. ...... Division ......" for each examination): each row is one instance, a
    `table_row` group (P5-D8) named by the text it starts with. Two such rows are enough; when
    the first entry's label differs per row (it is the row's own text: "(a) High School ......
    Roll No. ......"), three. Tables of drawn cells are grouped by `_label_tables`."""
    entries = sorted(
        (
            c
            for c in candidates
            if c.kind in _TEXT_KINDS and c.answer_group is None and c.label is not None
        ),
        key=lambda c: (c.rect[1], c.rect[0]),
    )
    rows: list[list[_Candidate]] = []
    for cand in entries:
        for row in rows:
            if _rows_overlap(row[0].rect, cand.rect):
                row.append(cand)
                break
        else:
            rows.append([cand])
    rows = [sorted(row, key=lambda c: c.rect[0]) for row in rows]

    def aligned(upper: list[_Candidate], lower: list[_Candidate]) -> bool:
        height = upper[0].rect[3] - upper[0].rect[1]
        return (
            len(upper) == len(lower) >= 2
            and all(
                min(a.rect[2], b.rect[2]) > max(a.rect[0], b.rect[0])
                for a, b in zip(upper, lower, strict=True)
            )
            and lower[0].rect[1] - upper[0].rect[3] <= 3 * height
        )

    def labels(row: list[_Candidate], skip: int) -> list[str | None]:
        return [c.label for c in row[skip:]]

    # skip = 0: every label repeats. skip = 1: the first entry's label is the row's own text
    # ("(a) High School ......"), the others repeat; then three rows or more.
    number = 0
    for skip, min_rows in ((0, 2), (1, 3)):
        runs: list[list[list[_Candidate]]] = []
        for row in rows:
            if any(c.answer_group is not None for c in row) or len(row) < 2 + skip:
                runs.append([])
                continue
            if (
                runs
                and runs[-1]
                and aligned(runs[-1][-1], row)
                and (labels(runs[-1][-1], skip) == labels(row, skip))
            ):
                runs[-1].append(row)
            else:
                runs.append([row])
        for run in runs:
            if len(run) < min_rows:
                continue
            for row in run:
                lead = _row_lead(row[0], text.tokens) if skip == 0 else row[0].label
                for cand in row:
                    cand.answer_group = ("line_row", number, 0)
                    cand.answer_group_label = lead
                number += 1


def _part_before(
    cand: _Candidate, done: Sequence[_Candidate], entry: dict[int, str | None]
) -> _Candidate | None:
    """The hinted part this one continues: the nearest one just left of it on its row, else the
    one directly above it starting at the same x (a name written over two rows)."""
    height = cand.rect[3] - cand.rect[1]
    left = [
        d
        for d in done
        if id(d) in entry
        and _rows_overlap(d.rect, cand.rect)
        and 0 <= cand.rect[0] - d.rect[2] <= 2 * height
    ]
    if left:
        return max(left, key=lambda d: d.rect[2])
    above = [
        d
        for d in done
        if id(d) in entry
        and abs(d.rect[0] - cand.rect[0]) <= 2 * SNAP
        and 0 <= cand.rect[1] - d.rect[3] <= 1.5 * height
    ]
    return max(above, key=lambda d: d.rect[3]) if above else None


def _label_hinted_parts(candidates: list[_Candidate]) -> None:
    """Hinted comb parts (labelling rule 1). A date part ("DD", "MM", "YYYY") gets the date's
    label and its `date_part`. A part hinted with words gets the hint as label, and the entry's
    label as context, when the hints tell parts apart ("FIRST NAME", "MIDDLE", "LAST NAME") or
    it has no label of its own; a lone part with its own label keeps it (a hint such as "PINXXX"
    shows the format). A part with no label of its own continues the part before it; one with
    its own label starts an entry."""
    hinted = sorted((c for c in candidates if c.hint), key=lambda c: (c.rect[1], c.rect[0]))
    entry: dict[int, str | None] = {}
    before: dict[int, _Candidate | None] = {}
    for cand in hinted:  # a part with a label of its own starts an entry
        before[id(cand)] = None if cand.label else _part_before(cand, hinted, entry)
        entry[id(cand)] = cand.label  # placeholder, so later parts see this one
    entry.clear()
    continued = {id(b) for b in before.values() if b is not None}
    for cand in hinted:
        own = cand.label
        prev = before[id(cand)]
        if own is None and prev is not None:
            own = entry[id(prev)]
        entry[id(cand)] = own
        part = _date_part(cand.hint)
        if part is not None:
            cand.date_part = part
            cand.label = own
        elif cand.label is None or prev is not None or id(cand) in continued:
            cand.label = cand.hint
            cand.context = own or cand.context


def _group_choice_rows(candidates: list[_Candidate], text: _PageText) -> None:
    """Tick boxes side by side after one label ("5. Gender: [ ] Male [ ] Female [ ] Other") are
    one `choices` group (P5-D8), labelled by that text. A row splits where other text or another
    entry sits between two boxes."""
    boxes = sorted(
        (c for c in candidates if c.kind is FieldKind.CHECKBOX),
        key=lambda c: (c.rect[1], c.rect[0]),
    )
    rows: list[list[_Candidate]] = []
    for box in boxes:
        for row in rows:
            if _rows_overlap(row[0].rect, box.rect):
                row.append(box)
                break
        else:
            rows.append([box])
    number = 0
    for row in rows:
        row.sort(key=lambda c: c.rect[0])
        runs = [[row[0]]]
        for prev, box in pairwise(row):
            between = any(
                c.kind is not FieldKind.CHECKBOX
                and c.rect[0] >= prev.rect[2] - SNAP
                and c.rect[2] <= box.rect[0] + SNAP
                and _rows_overlap(c.rect, box.rect)
                for c in candidates
            )
            if between or _label_left(box, candidates, text.tokens) != prev.label:
                runs.append([box])
            else:
                runs[-1].append(box)
        for run in runs:
            label = _label_left(run[0], candidates, text.tokens)
            if len(run) < 2 or label is None or any(b.label is None for b in run):
                continue
            for box in run:
                box.answer_group = ("choices", number, 0)
                box.answer_group_label = label
            number += 1


def _on_page(cand: _Candidate, page_rect: pymupdf.Rect) -> bool:
    """The entry's centre is on the visible page (a drawing outside it is never seen)."""
    cx, cy = (cand.rect[0] + cand.rect[2]) / 2, (cand.rect[1] + cand.rect[3]) / 2
    return page_rect.x0 <= cx <= page_rect.x1 and page_rect.y0 <= cy <= page_rect.y1


# --- page and document --------------------------------------------------------------------


# An office-use box is a small panel; a page frame that happens to hold the words must not mark
# every field on the page.
OFFICE_BOX_MAX_PAGE_SHARE = 0.15


def _mark_office_use(
    candidates: list[_Candidate], boxes: list[Rect], text: _PageText, page_area: float
) -> None:
    """A field inside a drawn box whose own text says "for office use" (in any line, not only
    the nearest heading; garbled Hindi tolerated) is never filled (decision P3-D1)."""
    for cand in candidates:
        enclosing = [
            r
            for r in boxes
            if _contains(r, cand.rect)
            and _area(r) > 1.2 * _area(cand.rect)
            and _area(r) <= OFFICE_BOX_MAX_PAGE_SHARE * page_area
        ]
        if not enclosing:
            continue
        box = min(enclosing, key=_area)
        inside = " ".join(line.text for line in text.lines if _contains(box, line.rect))
        if mentions_office_use(inside):
            cand.no_fill_reason = "office_use"


_TEXT_KINDS = frozenset({FieldKind.TEXT, FieldKind.DATE, FieldKind.UNKNOWN})


def instructs_upper_case_on(text: _PageText) -> bool:
    """A line of the page tells the reader to write in capital letters."""
    return any(instructs_upper_case(line.text) for line in text.lines)


def _mark_upper_case(candidates: list[_Candidate], text: _PageText) -> None:
    """Text fields whose own label asks for capital letters, or all of them when a page
    instruction does. A heading is not used: it is often the previous field's label."""
    page_wide = instructs_upper_case_on(text)
    for cand in candidates:
        if cand.kind not in _TEXT_KINDS:
            continue
        if asks_upper_case(cand.label):
            cand.case_hint = "label"
        elif page_wide:
            cand.case_hint = "page"


def _page_candidates(page: pymupdf.Page) -> tuple[list[_Candidate], list[str]]:
    text = _extract_text(page)
    drawings = _extract_drawings(page)
    unrotated = page.rect * page.derotation_matrix
    page_area = abs(unrotated)

    grid = _grid_cells(drawings.horizontal, drawings.vertical)
    cells = drawings.rects + grid
    candidates = _leader_candidates(text) + _line_candidates(drawings, text)
    candidates += _box_candidates(drawings, grid, text, page_area)
    candidates += _inside_candidates(text, cells, candidates)
    candidates += _colon_candidates(text, drawings, cells, candidates)
    tables = _tables(cells, text)
    notes = [
        f"dropped {c.source} in a table header" for c in candidates if _in_table_header(c, tables)
    ]
    candidates = [c for c in candidates if not _in_table_header(c, tables)]
    kept, dropped = _resolve_overlaps(candidates)
    notes += [
        f"dropped {cand.source} overlapping {other.source}"
        if other is not None
        else f"dropped {cand.source}: too low after trimming"
        for cand, other in dropped
    ]
    notes += [f"dropped {c.source} outside the page" for c in kept if not _on_page(c, unrotated)]
    kept = [c for c in kept if _on_page(c, unrotated)]
    _assign_text(kept, text)
    _label_tables(kept, tables, text)
    _group_repeated_rows(kept, text)
    _label_hinted_parts(kept)
    _group_choice_rows(kept, text)
    _mark_office_use(kept, cells, text, page_area)
    _mark_upper_case(kept, text)
    return kept, notes


def _displayed(rect: Rect, page: pymupdf.Page, page_no: int) -> BBox:
    r = (pymupdf.Rect(rect) * page.rotation_matrix).normalize()
    return BBox(page=page_no, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)


def _reading_order[T](boxes: list[tuple[BBox, T]]) -> list[tuple[BBox, T]]:
    """Top to bottom in rows, left to right within a row (displayed page)."""
    ordered = sorted(boxes, key=lambda item: ((item[0].y0 + item[0].y1) / 2, item[0].x0))
    rows: list[list[tuple[BBox, T]]] = []
    for item in ordered:
        center = (item[0].y0 + item[0].y1) / 2
        if rows:
            first = rows[-1][0][0]
            row_center = (first.y0 + first.y1) / 2
            if abs(center - row_center) <= max(3.0, 0.5 * min(first.height, item[0].height)):
                rows[-1].append(item)
                continue
        rows.append([item])
    return [item for row in rows for item in sorted(row, key=lambda i: i[0].x0)]


# --- reused by the AcroForm frontend (labels, context, boxes and order work the same) -------

PageText = _PageText


def page_text(page: pymupdf.Page) -> PageText:
    """Words, lines and leaders of a page, on the unrotated page (like widget rects)."""
    return _extract_text(page)


def _widget_candidate(rect: Rect, kind: FieldKind) -> _Candidate:
    x0, y0, x1, y1 = rect
    return _Candidate(rect=(x0, y0, x1, y1), kind=kind, group="widget", source="widget")


def label_for(
    rect: Rect, kind: FieldKind, text: PageText, others: Sequence[Rect] = ()
) -> str | None:
    """The label the flat frontend would give an entry area at rect (unrotated page).

    others are the page's other entry areas: a label never reaches past one of them.
    """
    cand = _widget_candidate(rect, kind)
    candidates = [cand, *(_widget_candidate(r, FieldKind.TEXT) for r in others)]
    return _label(cand, candidates, text)


def label_right_of(rect: Rect, text: PageText, others: Sequence[Rect] = ()) -> str | None:
    """Only the text to the right of rect, e.g. the label of one radio button."""
    cand = _widget_candidate(rect, FieldKind.CHECKBOX)
    candidates = [cand, *(_widget_candidate(r, FieldKind.TEXT) for r in others)]
    return _label_right(cand, candidates, text.tokens)


def context_for(rect: Rect, text: PageText) -> str | None:
    return _context(_widget_candidate(rect, FieldKind.TEXT), text)


def displayed(rect: Rect, page: pymupdf.Page, page_no: int) -> BBox:
    """A rect on the unrotated page -> an IR box on the displayed page."""
    return _displayed(rect, page, page_no)


def reading_order[T](boxes: list[tuple[BBox, T]]) -> list[tuple[BBox, T]]:
    return _reading_order(boxes)


def run(doc: pymupdf.Document, detection: Detection, document_id: UUID, at: datetime) -> FormIR:
    """Build a FormIR with the entry areas of every OK page. Reads the document only."""
    fields: list[Field] = []
    groups: list[FieldGroup] = []
    trace: list[TraceEvent] = []

    for page_no, (page, info) in enumerate(zip(doc, detection.pages, strict=True)):
        if info.text_layer is not TextLayer.OK:
            trace.append(
                TraceEvent(
                    pass_name=STAGE,
                    field_id=None,
                    change=f"page {page_no}: text layer {info.text_layer.value}, needs OCR; "
                    "no fields detected",
                    at=at,
                )
            )
            continue
        candidates, notes = _page_candidates(page)
        boxes = [(_displayed(c.rect, page, page_no), c) for c in candidates]
        group_ids: dict[tuple[str, int, int], str] = {}
        for index, (bbox, cand) in enumerate(_reading_order(boxes)):
            field_id = f"p{page_no}_f{index:03d}"
            group_id = None
            if cand.answer_group is not None:
                if cand.answer_group not in group_ids:
                    group_ids[cand.answer_group] = f"p{page_no}_g{len(group_ids):03d}"
                    kind = "choices" if cand.answer_group[0] == "choices" else "table_row"
                    groups.append(
                        FieldGroup(
                            id=group_ids[cand.answer_group],
                            kind=kind,
                            label=cand.answer_group_label,
                        )
                    )
                group_id = group_ids[cand.answer_group]
            fields.append(
                Field(
                    id=field_id,
                    kind=cand.kind,
                    native_name=None,
                    label_text=cand.label,
                    context_text=cand.context,
                    bbox=bbox,
                    max_chars=cand.max_chars,
                    validations=cand.validations,
                    no_fill_reason=cand.no_fill_reason,
                    uppercase=cand.case_hint is not None,
                    date_part=cand.date_part,
                    group_id=group_id,
                )
            )
            trace.append(
                TraceEvent(
                    pass_name=STAGE, field_id=field_id, change=f"detected {cand.source}", at=at
                )
            )
            if cand.no_fill_reason is not None:
                trace.append(
                    TraceEvent(
                        pass_name=STAGE,
                        field_id=field_id,
                        change="no_fill_reason office_use (inside an office-use box)",
                        at=at,
                    )
                )
            if cand.case_hint is not None:
                trace.append(
                    TraceEvent(
                        pass_name=STAGE,
                        field_id=field_id,
                        change=f"uppercase ({cand.case_hint} hint)",
                        at=at,
                    )
                )
        trace += [
            TraceEvent(pass_name=STAGE, field_id=None, change=f"page {page_no}: {note}", at=at)
            for note in notes
        ]

    return FormIR(
        document_id=document_id,
        source_kind=detection.source_kind,
        pages=detection.pages,
        fields=fields,
        groups=groups,
        trace=trace,
    )
