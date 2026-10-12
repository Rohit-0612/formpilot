"""Decide a document's SourceKind and each page's text-layer quality (SPEC §6.1, decision D1).

Per page:
- NONE: fewer than NONE_MAX_CHARS non-space characters AND images cover most of the page
  (more than IMAGE_COVERAGE_FOR_NONE of its area). A sparse page without significant images
  (e.g. a signature page) is OK, not routed to OCR.
- GARBLED: the text looks like a legacy non-Unicode Hindi font (heuristics below).
- OK: otherwise.

Per document: FILLABLE if any page has a widget; else FLAT_TEXT if more than half of the pages
are OK; else SCANNED.

The garbled-text heuristics and thresholds are ported unchanged from the Phase 0 classifier
(scripts/classify_forms.py), which applied them per document; here they run per page. They are
heuristics: e.g. Unicode Devanagari with wrongly extracted vowel signs (#30) is not detected.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

import pymupdf

from app.ir.models import PageInfo, SourceKind, TextLayer

NONE_MAX_CHARS = 50
IMAGE_COVERAGE_FOR_NONE = 0.5

# Letters from Latin-1 Supplement / Latin Extended-A/B (U+00C0-U+024F): legacy Hindi fonts map
# Devanagari glyphs onto these.
MOJIBAKE_MIN_CHARS = 20
MOJIBAKE_MIN_SHARE = 0.02
# Kruti Dev-style tokens: ASCII letters with punctuation inside a word ("[kkrk", "gsrq%"),
# because those fonts map Devanagari glyphs onto ASCII punctuation.
KRUTI_TOKEN = re.compile(r"[A-Za-z]*[\[\]{};%`~|][A-Za-z]+|[A-Za-z]+[\[\]{}%`~|]")
KRUTI_MIN_TOKENS = 15
KRUTI_MIN_SHARE = 0.03

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class PageDiagnostics:
    """Why a page got its text layer. Counts and reasons only, never text."""

    chars: int  # non-space characters in the text layer
    image_coverage: float  # share of the page area covered by images, 0..1
    garbled_reasons: tuple[str, ...]


@dataclass(frozen=True)
class Detection:
    source_kind: SourceKind
    pages: list[PageInfo]
    diagnostics: list[PageDiagnostics]


# --- pure functions -----------------------------------------------------------------------


def _is_mojibake_letter(char: str) -> bool:
    return 0x00C0 <= ord(char) <= 0x024F and unicodedata.category(char).startswith("L")


def garbled_reasons(text: str) -> list[str]:
    """Reasons the text looks like a legacy-font text layer; empty if it looks like real text."""
    reasons: list[str] = []
    letters = [c for c in text if c.isalpha()]
    if letters:
        mojibake = sum(1 for c in letters if _is_mojibake_letter(c))
        if mojibake >= MOJIBAKE_MIN_CHARS and mojibake / len(letters) >= MOJIBAKE_MIN_SHARE:
            reasons.append(f"{mojibake} Latin-extended letters mixed into the text")
    tokens = text.split()
    if tokens:
        kruti = sum(1 for token in tokens if KRUTI_TOKEN.search(token))
        if kruti >= KRUTI_MIN_TOKENS and kruti / len(tokens) >= KRUTI_MIN_SHARE:
            reasons.append(f"{kruti} words with punctuation inside (Kruti Dev-style)")
    return reasons


def text_layer_quality(chars: int, image_coverage: float, reasons: Sequence[str]) -> TextLayer:
    if chars < NONE_MAX_CHARS and image_coverage > IMAGE_COVERAGE_FOR_NONE:
        return TextLayer.NONE
    if reasons:
        return TextLayer.GARBLED
    return TextLayer.OK


def source_kind(has_widgets: bool, layers: Sequence[TextLayer]) -> SourceKind:
    if not layers:
        raise ValueError("a document has at least one page")
    if has_widgets:
        return SourceKind.FILLABLE
    ok_pages = sum(1 for layer in layers if layer is TextLayer.OK)
    return SourceKind.FLAT_TEXT if ok_pages * 2 > len(layers) else SourceKind.SCANNED


def union_area(rects: Iterable[Rect], clip: Rect) -> float:
    """Exact area of the union of rectangles, clipped to `clip` (coordinate compression)."""
    cx0, cy0, cx1, cy1 = clip
    clipped = [(max(x0, cx0), max(y0, cy0), min(x1, cx1), min(y1, cy1)) for x0, y0, x1, y1 in rects]
    clipped = [r for r in clipped if r[0] < r[2] and r[1] < r[3]]
    if not clipped:
        return 0.0
    xs = sorted({v for r in clipped for v in (r[0], r[2])})
    ys = sorted({v for r in clipped for v in (r[1], r[3])})
    area = 0.0
    for left, right in pairwise(xs):
        for top, bottom in pairwise(ys):
            if any(
                r[0] <= left and right <= r[2] and r[1] <= top and bottom <= r[3] for r in clipped
            ):
                area += (right - left) * (bottom - top)
    return area


# --- PyMuPDF ------------------------------------------------------------------------------


def image_coverage(page: pymupdf.Page) -> float:
    """Share of the page covered by images (placed or inline), overlaps counted once."""
    # Image boxes are reported on the unrotated page; compare with the unrotated page rect.
    page_rect = page.rect * page.derotation_matrix
    page_rect.normalize()
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return 0.0
    rects = [tuple(info["bbox"]) for info in page.get_image_info()]
    clip = (page_rect.x0, page_rect.y0, page_rect.x1, page_rect.y1)
    return min(union_area(rects, clip) / page_area, 1.0)


def diagnose_page(page: pymupdf.Page) -> PageDiagnostics:
    text = page.get_text()
    return PageDiagnostics(
        chars=sum(1 for c in text if not c.isspace()),
        image_coverage=image_coverage(page),
        garbled_reasons=tuple(garbled_reasons(text)),
    )


def detect(doc: pymupdf.Document) -> Detection:
    """Classify an open, unencrypted PDF. Reads only; never modifies the document."""
    pages: list[PageInfo] = []
    diagnostics: list[PageDiagnostics] = []
    has_widgets = False
    for page in doc:
        has_widgets = has_widgets or page.first_widget is not None
        diag = diagnose_page(page)
        layer = text_layer_quality(diag.chars, diag.image_coverage, diag.garbled_reasons)
        pages.append(PageInfo(width=page.rect.width, height=page.rect.height, text_layer=layer))
        diagnostics.append(diag)
    kind = source_kind(has_widgets, [page.text_layer for page in pages])
    return Detection(source_kind=kind, pages=pages, diagnostics=diagnostics)
