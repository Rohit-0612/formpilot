"""Page images for the viewer, rendered in the worker (decision D3).

Each image shows the displayed page (after /Rotate), so IR boxes (points, top-left of the
displayed page) map onto it by scaling with dpi / 72.
"""

import pymupdf


def render_page(page: pymupdf.Page, dpi: int) -> bytes:
    return page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")


def render_pages(doc: pymupdf.Document, dpi: int) -> list[bytes]:
    return [render_page(page, dpi) for page in doc]
