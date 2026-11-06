"""The 24 h expiry (SPEC §11): documents past expires_at are deleted with their files.

Runs when the worker starts and then every hour (app/jobs/tasks.py). Free-tier hosts sleep and
can miss a cron run, so the start-up sweep catches up; between sweeps the API already refuses an
expired document (410, DocumentService.get).

Deleting the document row removes its IR versions, jobs and audit events (ON DELETE CASCADE),
as the user's own delete does. Each expired document leaves one audit event on its owner,
"document_expired" by "system", with no document id, file name or value, so the events count
expiries and nothing else. Logs hold counts only.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AuditEvent, Document
from app.logging import get_logger
from app.services.review import job_running
from app.storage.base import Storage

log = get_logger(__name__)

EXPIRED_EVENT = "document_expired"


@dataclass(frozen=True)
class SweepResult:
    deleted: int  # documents deleted by this sweep
    busy: int  # expired, but a job of the document is queued or running; tried again next sweep


def is_expired(document: Document, now: datetime | None = None) -> bool:
    return document.expires_at <= (now or datetime.now(UTC))


async def _delete_one(
    session: AsyncSession, storage: Storage, document_id: uuid.UUID, owner_id: uuid.UUID
) -> bool:
    """Files first, then the row: a failure in between leaves a row the next sweep retries."""
    await storage.delete_prefix(f"documents/{document_id}")
    deleted = await session.execute(delete(Document).where(Document.id == document_id))
    if deleted.rowcount != 1:  # type: ignore[attr-defined]  # deleted meanwhile (user or sweep)
        await session.rollback()
        return False
    session.add(AuditEvent(user_id=owner_id, event=EXPIRED_EVENT, actor="system"))
    await session.commit()
    return True


async def sweep(
    sessionmaker: async_sessionmaker[AsyncSession], storage: Storage, now: datetime | None = None
) -> SweepResult:
    """Deletes every expired document whose jobs have all ended. Running it again is a no-op."""
    now = now or datetime.now(UTC)
    deleted = busy = 0
    async with sessionmaker() as session:
        expired = (
            await session.execute(
                select(Document.id, Document.owner_id)
                .where(Document.expires_at <= now)
                .order_by(Document.expires_at)
            )
        ).all()
        for document_id, owner_id in expired:
            # A running job could write files again after they are deleted.
            if await job_running(session, document_id):
                busy += 1
            elif await _delete_one(session, storage, document_id, owner_id):
                deleted += 1
    log.info("expired_documents_swept", deleted=deleted, busy=busy)
    return SweepResult(deleted=deleted, busy=busy)
