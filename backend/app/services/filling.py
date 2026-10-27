"""Filling (Phase 4): the passes after understanding, and the answers job.

- `fill`: match (profile, fill policy) -> validate -> fit; run by the analyze job after
  understanding, with the document owner's profile (Form IR version 3).
- `answer_document`: the answers job. The answers were stored encrypted (vault key) under the
  document's prefix by the API, keyed by the job id, because job arguments are ids only; the job
  reads and deletes them, runs answers -> validate -> fit, stores the next IR version and saves
  the answers the user ticked to the profile.

Logs ids and counts only, never values.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.models import Document, Job
from app.ir.models import FieldStatus, FormIR
from app.llm.factory import provider_from_settings
from app.logging import get_logger
from app.passes import answers, fit, match, validate
from app.passes.answers import Answer
from app.passes.context import PassContext
from app.passes.questions import Question, plan
from app.services import ir_store
from app.storage.base import ObjectNotFoundError, Storage
from app.vault.crypto import VaultCipher
from app.vault.service import ProfileService, ProfileUpdateError, load_profile_values

log = get_logger(__name__)


class AnswersNotFoundError(Exception):
    """The answers job has no stored answers (already used, or the document was deleted)."""


class AnswersPayload(BaseModel):
    answers: list[Answer]


def answers_key(document_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return f"documents/{document_id}/answers/{job_id}.enc"


def fill_context(
    settings: Settings, profile: dict[str, str] | None = None, provider: object = None
) -> PassContext:
    return PassContext(
        clock=lambda: datetime.now(UTC),
        provider=provider,  # type: ignore[arg-type]
        review_threshold=settings.understand_review_threshold,
        profile=profile or {},
        fill_min_confidence=settings.fill_min_confidence,
        fill_once_per_form=settings.fill_once_per_form,
        suggest_min_confidence=settings.suggest_min_confidence,
        fit_font_size=settings.fit_font_size,
        fit_min_font_size=settings.fit_min_font_size,
    )


def fill(ir: FormIR, ctx: PassContext) -> FormIR:
    return fit.run(validate.run(match.run(ir, ctx), ctx), ctx)


def questions_for(ir: FormIR, settings: Settings) -> list[Question]:
    return plan(ir, match.policy_for(fill_context(settings)))


def counts(ir: FormIR) -> dict[str, int]:
    return {
        "filled": sum(f.status is FieldStatus.FILLED for f in ir.fields),
        "needs_input": sum(f.status is FieldStatus.NEEDS_INPUT for f in ir.fields),
        "needs_review": sum(f.status is FieldStatus.NEEDS_REVIEW for f in ir.fields),
        "suggested": sum(f.status is FieldStatus.SUGGESTED for f in ir.fields),
    }


async def fill_document(
    session: AsyncSession, document: Document, ir: FormIR, settings: Settings
) -> FormIR:
    """Fills from the owner's profile and adds the next IR version (not committed)."""
    cipher = VaultCipher(settings.vault_key)
    profile = await load_profile_values(session, document.owner_id, cipher)
    filled = fill(ir, fill_context(settings, profile))
    await ir_store.add_version(session, document.id, filled, cipher)
    return filled


def _apply(ir: FormIR, given: list[Answer], settings: Settings) -> FormIR:
    """Blocking (a free-text answer may call the LLM): runs in a thread."""
    provider = provider_from_settings(settings) if any(a.free_text for a in given) else None
    try:
        ctx = fill_context(settings, provider=provider)
        answered = answers.run(ir, ctx, given, questions_for(ir, settings))
        return fit.run(validate.run(answered, ctx), ctx)
    finally:
        if provider is not None:
            provider.close()


async def answer_document(
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
            raise AnswersNotFoundError
        key = answers_key(document.id, job_id)
        try:
            sealed = await storage.get(key)
        except ObjectNotFoundError:
            raise AnswersNotFoundError from None
        await storage.delete(key)
        payload = AnswersPayload.model_validate_json(cipher.decrypt(sealed.decode()))
        ir = await ir_store.latest(session, document.id, cipher)
        if ir is None:
            raise AnswersNotFoundError
        questions = questions_for(ir, settings)
        answered = await asyncio.to_thread(_apply, ir, payload.answers, settings)
        version = await ir_store.add_version(session, document.id, answered, cipher)
        await session.commit()
        changes = answers.profile_changes(payload.answers, questions, datetime.now(UTC).date())
        saved = 0
        if changes.values:
            try:
                await ProfileService(session, cipher).update(
                    document.owner_id, changes.values, changes.opt_in, datetime.now(UTC).date()
                )
                saved = len(changes.values)
            except ProfileUpdateError as exc:
                log.warning("profile_save_refused", keys=sorted(exc.problems))
    log.info(
        "document_answered",
        document_id=str(document.id),
        job_id=str(job_id),
        version=version,
        answers=len(payload.answers),
        saved_to_profile=saved,
        **counts(answered),
    )


async def store_answers(
    storage: Storage, cipher: VaultCipher, document_id: uuid.UUID, job_id: uuid.UUID,
    given: list[Answer],
) -> None:  # fmt: skip
    payload = AnswersPayload(answers=given).model_dump_json()
    await storage.put(answers_key(document_id, job_id), cipher.encrypt(payload).encode())
