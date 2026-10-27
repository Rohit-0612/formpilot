"""The render job (SPEC §6.9, Phase 5): the latest Form IR's confirmed fields drawn on the original
PDF by the overlay backend, stored as the document's output; the document is then `done`.

`POST /documents/{id}/render` checks that something is confirmed, sets the document `rendering`
and queues the job; review actions are refused while it runs (the output must match the
confirmed fields), and any later change deletes the output again (ReviewService). A failed job
puts the document back to `ready`. Logs ids and counts only, never values.
"""

import asyncio
import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backends import overlay
from app.config import Settings
from app.db.models import Document, DocumentStatus, Job
from app.ir.models import FormIR
from app.logging import get_logger
from app.pdf import PYMUPDF_LOCK
from app.services import ir_store
from app.services.analysis import original_key
from app.services.review import output_key, renderable
from app.storage.base import Storage
from app.vault.crypto import VaultCipher

log = get_logger(__name__)


class RenderError(Exception):
    """Base of the errors that end a render job; the subclass name is the job error code."""


class NothingToRenderError(RenderError):
    pass


def has_something_to_render(ir: FormIR) -> bool:
    return bool(renderable(ir))


def _render(original: bytes, ir: FormIR) -> overlay.Rendered:
    """Blocking: runs in a thread, holding the PyMuPDF lock."""
    with PYMUPDF_LOCK:
        return overlay.render(original, ir)


async def _set_status(
    sessionmaker: async_sessionmaker[AsyncSession], document_id: uuid.UUID,
    old: DocumentStatus, new: DocumentStatus,
) -> None:  # fmt: skip
    async with sessionmaker() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.status == old.value)
            .values(status=new.value)
        )
        await session.commit()


async def render_document(
    job_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: Storage,
    settings: Settings,
) -> None:
    cipher = VaultCipher(settings.vault_key)
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        document = await session.get(Document, job.document_id) if job and job.document_id else None
        if document is None:
            raise NothingToRenderError
        document_id = document.id
        ir = await ir_store.latest(session, document_id, cipher)
    try:
        if ir is None or not has_something_to_render(ir):
            raise NothingToRenderError
        original = await storage.get(original_key(document_id))
        out = await asyncio.to_thread(_render, original, ir)
        await storage.put(output_key(document_id), out.pdf)
    except BaseException:
        await asyncio.shield(
            _set_status(sessionmaker, document_id, DocumentStatus.RENDERING, DocumentStatus.READY)
        )
        raise
    await _set_status(sessionmaker, document_id, DocumentStatus.RENDERING, DocumentStatus.DONE)
    log.info(
        "document_rendered",
        document_id=str(document_id),
        job_id=str(job_id),
        drawn=len(out.drawn),
        skipped=len(out.skipped),
    )
