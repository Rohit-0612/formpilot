"""The analyze job: uploaded PDF -> Form IR version 1 + page images, then the understanding pass
-> Form IR version 2, then filling from the owner's profile -> version 3 (worker only, SPEC §11).

Version 1 (detection) is stored and the document is `ready` before understanding starts, so a
slow or failing LLM never loses the detected fields. Understanding gets a deadline inside the
job timeout; LLM batches due after it are skipped (their fields stay unknown).

Errors are exception classes whose names become the job's error code (run_tracked records the
class name); GET /documents/{id} turns them into readable messages (documents.py).
Never logs file names or values.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pymupdf
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Document, DocumentStatus, Job
from app.frontends import acroform, flat
from app.frontends.detect import detect
from app.frontends.page_images import render_pages
from app.ir.models import FormIR, SourceKind
from app.llm.factory import provider_from_settings
from app.logging import get_logger
from app.passes import understand
from app.passes.context import PassContext
from app.pdf import PYMUPDF_LOCK
from app.services import filling, ir_store
from app.storage.base import Storage
from app.vault.crypto import VaultCipher

log = get_logger(__name__)

# Time kept free at the end of the job timeout for storing IR version 2.
UNDERSTAND_MARGIN = timedelta(seconds=30)


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
    with PYMUPDF_LOCK:
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
    cipher = VaultCipher(settings.vault_key)
    job_started = datetime.now(UTC)
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
            await ir_store.add_version(session, document_id, result.ir, cipher)
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

    deadline = job_started + timedelta(seconds=settings.job_timeout_seconds) - UNDERSTAND_MARGIN
    began = time.perf_counter()
    understood = await asyncio.to_thread(_understand, result.ir, settings, deadline)
    async with sessionmaker() as session:
        await ir_store.add_version(session, document_id, understood, cipher)
        await session.commit()
    doc_log.info(
        "document_understood",
        by_rule=sum(1 for f in understood.fields if f.semantic_method == "rule"),
        by_llm=sum(1 for f in understood.fields if f.semantic_method == "llm"),
        never_fill=sum(1 for f in understood.fields if f.no_fill_reason is not None),
        duration_ms=round((time.perf_counter() - began) * 1000, 1),
    )

    # Phase 4: fill from the owner's profile, validate, fit -> version 3.
    async with sessionmaker() as session:
        document = await session.get(Document, document_id)
        if document is None:  # deleted while the job ran
            raise DocumentNotAnalyzableError
        filled = await filling.fill_document(session, document, understood, settings, deadline)
        await session.commit()
    doc_log.info("document_filled", **filling.counts(filled))


def _understand(ir: FormIR, settings: Settings, deadline: datetime) -> FormIR:
    """Blocking (LLM calls): runs in a thread, outside the PyMuPDF lock."""
    provider = provider_from_settings(settings)
    try:
        ctx = PassContext(
            clock=lambda: datetime.now(UTC),
            provider=provider,
            review_threshold=settings.understand_review_threshold,
            deadline=deadline,
        )
        return understand.run(ir, ctx)
    finally:
        if provider is not None:
            provider.close()


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
