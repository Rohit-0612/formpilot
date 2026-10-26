import pymupdf
import pytest

from app.frontends.detect import (
    IMAGE_COVERAGE_FOR_NONE,
    NONE_MAX_CHARS,
    detect,
    garbled_reasons,
    image_coverage,
    source_kind,
    text_layer_quality,
    union_area,
)
from app.ir.models import SourceKind, TextLayer
from tests.fixtures import pdfs
from tests.fixtures.pdfs import KRUTI_LINES, MOJIBAKE_LINES

ANALYSABLE = [name for name in pdfs.NAMES if not pdfs.get(name).encrypted]

CLEAN_ENGLISH = (
    "ACCOUNT OPENING FORM FOR RESIDENT INDIVIDUALS. Name of the applicant, Father's name, "
    "Date of birth (DD/MM/YYYY), Permanent address, PIN code, Mobile number, Email ID, "
    "PAN, Aadhaar number, Nominee details, Declaration: I hereby declare that the "
    "information given above is true and correct to the best of my knowledge. "
) * 4
CLEAN_DEVANAGARI = (
    "आवेदक का नाम पिता का नाम माता का नाम जन्म तिथि स्थायी पता पिन कोड मोबाइल नंबर "
    "घोषणा मैं घोषणा करता हूँ कि ऊपर दी गई जानकारी सही है। हस्ताक्षर दिनांक स्थान "
) * 4
BILINGUAL = (
    "नाम / Name : पिता का नाम / Father's name : जन्म तिथि / Date of birth : "
    "पता / Address : हस्ताक्षर / Signature : दिनांक / Date : "
) * 4


# --- garbled-text heuristics on text vectors ----------------------------------------------


@pytest.mark.parametrize("text", [CLEAN_ENGLISH, CLEAN_DEVANAGARI, BILINGUAL, ""])
def test_real_text_is_not_garbled(text: str) -> None:
    assert garbled_reasons(text) == []


def test_kruti_dev_text_is_garbled() -> None:
    reasons = garbled_reasons("\n".join(KRUTI_LINES * 3))

    assert len(reasons) == 1
    assert "Kruti Dev-style" in reasons[0]


def test_latin_extended_mojibake_is_garbled() -> None:
    reasons = garbled_reasons("\n".join(MOJIBAKE_LINES * 3))

    assert any("Latin-extended letters" in reason for reason in reasons)


def test_a_few_accented_letters_in_english_are_not_garbled() -> None:
    """Like form #1: a handful of mis-mapped glyphs in a long English text."""
    text = CLEAN_ENGLISH + " Tel. (Oģ) café naïve résumé Zürich"

    assert garbled_reasons(text) == []


def test_kruti_tokens_need_both_a_count_and_a_share() -> None:
    tokens = KRUTI_LINES[0].split()  # a few Kruti tokens only
    few = " ".join(tokens)
    diluted = few * 2 + " " + CLEAN_ENGLISH * 20  # many tokens, small share

    assert garbled_reasons(few) == []
    assert garbled_reasons(diluted) == []


def test_reasons_never_contain_the_text() -> None:
    reasons = garbled_reasons("\n".join(KRUTI_LINES * 3))

    assert all(line not in " ".join(reasons) for line in KRUTI_LINES)


# --- text-layer decision (D1) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("chars", "coverage", "reasons", "expected"),
    [
        (0, 1.0, (), TextLayer.NONE),  # scanned page
        (NONE_MAX_CHARS - 1, 0.9, (), TextLayer.NONE),  # a page number on a scan
        (45, 0.0, (), TextLayer.OK),  # sparse signature page, no image (D1 amendment)
        (13, 0.007, (), TextLayer.OK),  # sparse page with a small logo
        (0, 0.0, (), TextLayer.OK),  # blank page: nothing to OCR
        (0, IMAGE_COVERAGE_FOR_NONE, (), TextLayer.OK),  # exactly half is not "most"
        (NONE_MAX_CHARS, 1.0, (), TextLayer.OK),  # enough text: use the text layer
        (500, 0.0, ("x",), TextLayer.GARBLED),
        (500, 1.0, ("x",), TextLayer.GARBLED),
    ],
)
def test_text_layer_quality(
    chars: int, coverage: float, reasons: tuple[str, ...], expected: TextLayer
) -> None:
    assert text_layer_quality(chars, coverage, reasons) is expected


# --- source kind --------------------------------------------------------------------------

OK, GARBLED, NONE = TextLayer.OK, TextLayer.GARBLED, TextLayer.NONE


@pytest.mark.parametrize(
    ("has_widgets", "layers", "expected"),
    [
        (True, [NONE], SourceKind.FILLABLE),  # widgets win
        (False, [OK], SourceKind.FLAT_TEXT),
        (False, [OK, OK, GARBLED], SourceKind.FLAT_TEXT),
        (False, [OK, NONE], SourceKind.SCANNED),  # half is not "most"
        (False, [OK, NONE, GARBLED], SourceKind.SCANNED),
        (False, [GARBLED], SourceKind.SCANNED),
        (False, [NONE, NONE], SourceKind.SCANNED),
    ],
)
def test_source_kind(has_widgets: bool, layers: list[TextLayer], expected: SourceKind) -> None:
    assert source_kind(has_widgets, layers) is expected


def test_source_kind_needs_pages() -> None:
    with pytest.raises(ValueError):
        source_kind(False, [])


# --- union area ---------------------------------------------------------------------------

PAGE = (0.0, 0.0, 100.0, 100.0)


def test_union_area_counts_overlaps_once() -> None:
    assert union_area([(0, 0, 50, 50), (25, 25, 75, 75)], PAGE) == 2500 + 2500 - 625


def test_union_area_clips_to_the_page() -> None:
    assert union_area([(-50, -50, 50, 200)], PAGE) == 50 * 100


def test_union_area_of_nothing() -> None:
    assert union_area([], PAGE) == 0.0
    assert union_area([(200, 200, 300, 300)], PAGE) == 0.0


# --- detect() on the fixtures -------------------------------------------------------------


@pytest.mark.parametrize("name", ANALYSABLE)
def test_detect_matches_fixture_ground_truth(name: str) -> None:
    fixture = pdfs.get(name)
    with pymupdf.open("pdf", fixture.data) as doc:
        detection = detect(doc)
        displayed = [(page.rect.width, page.rect.height) for page in doc]

    assert detection.source_kind is fixture.source_kind
    assert tuple(page.text_layer for page in detection.pages) == fixture.text_layers
    assert [(page.width, page.height) for page in detection.pages] == displayed


def test_detect_reports_displayed_size_of_rotated_page() -> None:
    with pymupdf.open("pdf", pdfs.get("flat_rotated").data) as doc:
        detection = detect(doc)

    assert (detection.pages[0].width, detection.pages[0].height) == (842, 595)


def test_detect_reports_crop_box_size() -> None:
    with pymupdf.open("pdf", pdfs.get("fillable_basic").data) as doc:
        detection = detect(doc)

    assert (detection.pages[0].width, detection.pages[0].height) == (592, 762)


def test_diagnostics_explain_the_decision() -> None:
    with pymupdf.open("pdf", pdfs.get("mixed_mostly_scanned").data) as doc:
        diagnostics = detect(doc).diagnostics

    ok, image, garbled = diagnostics
    assert ok.garbled_reasons == () and ok.image_coverage == 0.0
    assert image.chars == 0 and image.image_coverage == pytest.approx(1.0)
    assert garbled.garbled_reasons and garbled.chars >= NONE_MAX_CHARS


def test_image_coverage_on_rotated_page() -> None:
    """Image boxes are unrotated; coverage must still be computed against the right rect."""
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=400)
    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 10, 10), False)
    page.insert_image(pymupdf.Rect(0, 0, 200, 300), pixmap=pix)  # 75% of the page
    page.set_rotation(90)

    assert image_coverage(page) == pytest.approx(0.75)


def test_detect_does_not_modify_the_document() -> None:
    data = pdfs.get("flat_underscores").data
    with pymupdf.open("pdf", data) as doc:
        detect(doc)
        assert not doc.is_dirty
