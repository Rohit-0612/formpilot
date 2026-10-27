"""Uploaded documents: the upload step, and reads checked against the owner (SPEC §8, D3, D7).

The API never opens a PDF (SPEC §11): it checks size and magic bytes, stores the bytes and
enqueues the analyze job; the worker does the rest (analysis.py).
Logging rule: document and job ids only, never file names or field values.
"""

import hashlib
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentStatus, Job, JobType
from app.ir.models import FormIR
from app.logging import get_logger
from app.passes.answers import Answer
from app.passes.questions import Question
from app.services import filling, ir_store
from app.services.analysis import original_key, page_key
from app.services.jobs import JobEnqueueError, JobQueue, JobService
from app.storage.base import ObjectNotFoundError, Storage
from app.vault.crypto import VaultCipher

log = get_logger(__name__)

PDF_MAGIC = b"%PDF-"
MAGIC_WINDOW = 1024  # the PDF header may follow some leading bytes
MAX_FILENAME_LENGTH = 255  # documents.original_filename
DEFAULT_FILENAME = "document.pdf"


def looks_like_pdf(head: bytes) -> bool:
    return PDF_MAGIC in head[:MAGIC_WINDOW]


def clean_filename(name: str | None) -> str:
    """The base name without control characters, at most 255 characters. Display only."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    printable = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip()
    return printable[:MAX_FILENAME_LENGTH] or DEFAULT_FILENAME


# Job error codes (exception class names, see analysis.py and jobs.py) -> readable messages.
_JOB_ERROR_MESSAGES = {
    "TooManyPages": "The PDF has more than {max_pages} pages.",
    "EncryptedPdf": "The PDF is password-protected. Upload a copy without a password.",
    "UnreadablePdf": "The file could not be read as a PDF.",
    "Stale": "The analysis was interrupted. Please upload the file again.",
    "Cancelled": "The analysis took too long or was interrupted. Please upload the file again.",
    "AnswersNotFoundError": "These answers were already used. Please answer the questions again.",
}
_ENQUEUE_FAILED = "The analysis could not be started. Please upload the file again."
_GENERIC = "The analysis failed."


def job_error_message(error: str | None, *, max_pages: int) -> str | None:
    if error is None:
        return None
    if error.startswith("EnqueueFailed"):
        return _ENQUEUE_FAILED
    template = _JOB_ERROR_MESSAGES.get(error)
    return template.format(max_pages=max_pages) if template else _GENERIC


class UnknownQuestionsError(Exception):
    def __init__(self, question_ids: list[str]) -> None:
        super().__init__(", ".join(question_ids))
        self.question_ids = question_ids


class DocumentService:
    def __init__(
        self, session: AsyncSession, storage: Storage, file_ttl_hours: int, cipher: VaultCipher
    ) -> None:
        self._session = session
        self._storage = storage
        self._ttl = timedelta(hours=file_ttl_hours)
        self._cipher = cipher

    async def upload(
        self, owner_id: uuid.UUID, filename: str, data: bytes, queue: JobQueue
    ) -> tuple[Document, Job]:
        """Store the original, insert the document, enqueue the analyze job.

        A storage failure leaves nothing behind; a database failure removes the stored file. If
        enqueueing fails, the document is `failed` and JobEnqueueError propagates.
        """
        document = Document(
            id=uuid.uuid4(),
            owner_id=owner_id,
            original_filename=clean_filename(filename),
            sha256=hashlib.sha256(data).hexdigest(),
            expires_at=datetime.now(UTC) + self._ttl,
        )
        await self._storage.put(original_key(document.id), data)
        self._session.add(document)
        try:
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            await self._storage.delete_prefix(f"documents/{document.id}")
            raise
        try:
            job = await JobService(self._session, queue).create_job(JobType.ANALYZE, document.id)
        except JobEnqueueError:
            document.status = DocumentStatus.FAILED.value
            await self._session.commit()
            raise
        log.info(
            "document_uploaded", document_id=str(document.id), job_id=str(job.id), bytes=len(data)
        )
        return document, job

    async def get(self, document_id: uuid.UUID, owner_id: uuid.UUID) -> Document | None:
        """None if the document does not exist or belongs to someone else (both answer 404)."""
        document = await self._session.get(Document, document_id)
        if document is None or document.owner_id != owner_id:
            return None
        return document

    async def latest_job(self, document_id: uuid.UUID) -> Job | None:
        return await self._session.scalar(
            select(Job)
            .where(Job.document_id == document_id)
            .order_by(Job.created_at.desc(), Job.id)
            .limit(1)
        )

    async def latest_ir(self, document_id: uuid.UUID) -> dict[str, Any] | None:
        """The latest IR JSON, values decrypted; callers mask it before it leaves the API."""
        return await ir_store.latest_data(self._session, document_id, self._cipher)

    async def latest_form(self, document_id: uuid.UUID) -> FormIR | None:
        """The latest IR with its values decrypted (never returned to the client unmasked)."""
        return await ir_store.latest(self._session, document_id, self._cipher)

    async def submit_answers(
        self, document: Document, given: list[Answer], questions: list[Question], queue: JobQueue
    ) -> Job:
        """Stores the answers encrypted under the job's id, then enqueues the answers job.

        Raises UnknownQuestionsError if an answer is for a question that is not asked now."""
        asked = {q.id for q in questions}
        unknown = sorted({a.question_id for a in given} - asked)
        if unknown:
            raise UnknownQuestionsError(unknown)
        job_id = uuid.uuid4()
        await filling.store_answers(self._storage, self._cipher, document.id, job_id, given)
        try:
            return await JobService(self._session, queue).create_job(
                JobType.ANSWERS, document.id, job_id=job_id
            )
        except JobEnqueueError:
            await self._storage.delete(filling.answers_key(document.id, job_id))
            raise

    async def page_image(self, document: Document, page: int) -> bytes | None:
        if document.page_count is None or not 0 <= page < document.page_count:
            return None
        try:
            return await self._storage.get(page_key(document.id, page))
        except ObjectNotFoundError:
            return None

    async def get_job(self, job_id: uuid.UUID, owner_id: uuid.UUID) -> Job | None:
        """None unless the job belongs to a document of this owner (jobs without one: None)."""
        job = await self._session.get(Job, job_id)
        if job is None or job.document_id is None:
            return None
        if await self.get(job.document_id, owner_id) is None:
            return None
        return job
