"""The analyze job: uploaded PDF -> Form IR version 1 + page images (worker only, SPEC §11).

Errors are exception classes whose names become the job's error code (run_tracked records the
class name); GET /documents/{id} turns them into readable messages (documents.py).
Never logs file names or values.
"""

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pymupdf
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Document, DocumentStatus, FormIRVersion, Job
from app.frontends import acroform, flat
from app.frontends.detect import detect
from app.frontends.page_images import render_pages
from app.ir.models import FormIR, SourceKind
from app.logging import get_logger
from app.storage.base import Storage

log = get_logger(__name__)

# PyMuPDF is not thread-safe, even across documents: one PDF at a time per worker process. The
# work runs in a thread so the event loop (and arq's health check) stays responsive.
_PYMUPDF_LOCK = threading.Lock()


class AnalysisError(Exception):
    """Base of the errors that end an analysis; the subclass name is the job error code."""


class DocumentNotAnalyzableError(AnalysisError):
    """The job has no document, or the document is not waiting for analysis."""


class EncryptedPdf(AnalysisError):  # noqa: N818 - the name is the job error code (D3)
    pass


class UnreadablePdf(AnalysisError):  # noqa: N818 - the name is the job error code (D3)
    pass


class TooManyPages(AnalysisError):  # noqa: N818 - the name is the job error code (D3)
    pass


def original_key(document_id: uuid.UUID) -> str:
    return f"documents/{document_id}/original.pdf"


def page_key(document_id: uuid.UUID, page: int) -> str:
    return f"documents/{document_id}/pages/{page}.png"


@dataclass(frozen=True)
class Analysis:
    ir: FormIR
    page_images: list[bytes]


def analyze_pdf(
    data: bytes, document_id: uuid.UUID, *, max_pages: int, dpi: int, at: datetime
) -> Analysis:
    """Pure and blocking: detect, run the frontend for the source kind, render the pages."""
    with _PYMUPDF_LOCK:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            raise UnreadablePdf from None
        with doc:
            if doc.needs_pass:
                raise EncryptedPdf
            if doc.page_count == 0:
                raise UnreadablePdf
            if doc.page_count > max_pages:
                raise TooManyPages
            detection = detect(doc)
            if detection.source_kind is SourceKind.FILLABLE:
                # Widgets only; printed blanks of a hybrid document are not detected (Step 9).
                ir = acroform.run(doc, detection, document_id, at)
            else:
                # flat_text and scanned alike: fields on pages with a usable text layer, a
                # "needs OCR" trace event for the others (OCR is Phase 6).
                ir = flat.run(doc, detection, document_id, at)
            images = render_pages(doc, dpi)
    return Analysis(ir, images)


async def analyze_document(
    job_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
) -> None:
    """uploaded -> analyzing -> ready (IR v1 + page images stored) | failed."""
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        document_id = job.document_id if job is not None else None
        if document_id is None:
            raise DocumentNotAnalyzableError
        started = await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.UPLOADED.value)
            .values(status=DocumentStatus.ANALYZING.value)
        )
        await session.commit()
    if started.rowcount != 1:  # type: ignore[attr-defined]
        raise DocumentNotAnalyzableError

    doc_log = log.bind(document_id=str(document_id), job_id=str(job_id))
    began = time.perf_counter()
    try:
        data = await storage.get(original_key(document_id))
        result = await asyncio.to_thread(
            analyze_pdf,
            data,
            document_id,
            max_pages=settings.max_pages,
            dpi=settings.page_image_dpi,
            at=datetime.now(UTC),
        )
        for page, image in enumerate(result.page_images):
            await storage.put(page_key(document_id, page), image)
        async with sessionmaker() as session:
            session.add(
                FormIRVersion(
                    document_id=document_id, version=1, ir_json=result.ir.model_dump(mode="json")
                )
            )
            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(
                    status=DocumentStatus.READY.value,
                    source_kind=result.ir.source_kind.value,
                    page_count=len(result.ir.pages),
                )
            )
            await session.commit()
    except BaseException:
        # Includes cancellation (job timeout): the document must not stay `analyzing`.
        await asyncio.shield(_mark_failed(sessionmaker, document_id))
        raise
    doc_log.info(
        "document_analyzed",
        source_kind=result.ir.source_kind.value,
        pages=len(result.ir.pages),
        fields=len(result.ir.fields),
        duration_ms=round((time.perf_counter() - began) * 1000, 1),
    )


async def _mark_failed(
    sessionmaker: async_sessionmaker[AsyncSession], document_id: uuid.UUID
) -> None:
    async with sessionmaker() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == DocumentStatus.ANALYZING.value)
            .values(status=DocumentStatus.FAILED.value)
        )
        await session.commit()
