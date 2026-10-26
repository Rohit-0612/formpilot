"""The analyze job's pure part (analyze_pdf) and the page images, on synthetic fixtures."""

import uuid
from datetime import UTC, datetime

import pymupdf
import pytest

from app.frontends.page_images import render_page
from app.ir.models import SourceKind, TextLayer
from app.services.analysis import (
    EncryptedPdf,
    TooManyPages,
    UnreadablePdf,
    analyze_pdf,
)
from tests.fixtures import pdfs

DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000025")
AT = datetime(2026, 10, 18, tzinfo=UTC)
DPI = 72


def _analyze(name: str, max_pages: int = 50):
    return analyze_pdf(pdfs.get(name).data, DOCUMENT_ID, max_pages=max_pages, dpi=DPI, at=AT)


def test_flat_pdf_gets_fields_and_one_image_per_page() -> None:
    fixture = pdfs.get("flat_boxes")

    result = _analyze("flat_boxes")

    assert result.ir.document_id == DOCUMENT_ID
    assert result.ir.source_kind is SourceKind.FLAT_TEXT
    assert len(result.ir.fields) == len(fixture.fields)
    assert len(result.page_images) == len(result.ir.pages)
    assert all(image.startswith(b"\x89PNG\r\n\x1a\n") for image in result.page_images)


def test_scanned_pdf_goes_through_the_flat_frontend() -> None:
    """Fields on the usable pages, a "needs OCR" trace event for the others (approved plan)."""
    result = _analyze("mixed_mostly_scanned")

    ir = result.ir
    assert ir.source_kind is SourceKind.SCANNED
    ok_pages = {i for i, page in enumerate(ir.pages) if page.text_layer is TextLayer.OK}
    other_pages = set(range(len(ir.pages))) - ok_pages
    assert ok_pages and other_pages
    assert {field.bbox.page for field in ir.fields} <= ok_pages
    assert sum("needs OCR" in event.change for event in ir.trace) == len(other_pages)


def test_fillable_pdf_goes_through_the_acroform_frontend() -> None:
    result = _analyze("fillable_basic")

    assert result.ir.source_kind is SourceKind.FILLABLE
    assert len(result.ir.fields) == len(pdfs.get("fillable_basic").fields)
    assert {event.pass_name for event in result.ir.trace} == {"frontend.acroform"}


def test_page_limit() -> None:
    assert len(_analyze("too_many_pages", max_pages=51).ir.pages) == 51
    with pytest.raises(TooManyPages):
        _analyze("too_many_pages", max_pages=50)


def test_encrypted_pdf() -> None:
    with pytest.raises(EncryptedPdf):
        _analyze("encrypted")


@pytest.mark.parametrize("data", [b"%PDF-1.7 but nothing else", b"not a pdf at all", b""])
def test_unreadable_pdf(data: bytes) -> None:
    with pytest.raises(UnreadablePdf):
        analyze_pdf(data, DOCUMENT_ID, max_pages=50, dpi=DPI, at=AT)


def test_error_class_names_are_the_job_error_codes() -> None:
    """GET /documents/{id} maps these names to messages (D3); renaming them breaks that."""
    assert [e.__qualname__ for e in (TooManyPages, EncryptedPdf, UnreadablePdf)] == [
        "TooManyPages",
        "EncryptedPdf",
        "UnreadablePdf",
    ]


@pytest.mark.parametrize("dpi", [72, 144])
def test_page_image_size_follows_the_displayed_page_and_the_dpi(dpi: int) -> None:
    """IR boxes map onto the image by scaling with dpi / 72, also on a rotated page."""
    with pymupdf.open("pdf", pdfs.get("flat_rotated").data) as doc:
        page = doc[0]
        image = pymupdf.Pixmap(render_page(page, dpi))

        assert page.rotation != 0
        assert (image.width, image.height) == (
            round(page.rect.width * dpi / 72),
            round(page.rect.height * dpi / 72),
        )
