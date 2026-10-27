"""Review (SPEC §6.8, Phase 5): the user's edits and confirms on the latest Form IR.

The rules are pure functions on a FormIR; `ReviewService` stores the result as the next IR
version with an audit event per field (never a value).

- **Edit** a value: the value is the user's (`USER_EDIT`), validated and fitted again, status
  FILLED (NEEDS_REVIEW if a check fails). An empty value clears the field: NEEDS_INPUT, asked
  again. Editing a suggested value replaces the suggestion; clearing it rejects it.
- **Confirm** a field that has a value (or a checkbox answered "no"): CONFIRMED, also despite a
  warning, since the user decides. A suggestion is accepted this way only (P5-D1).
- **Unconfirm**: back to FILLED, or NEEDS_REVIEW if a check failed.
- **Confirm all** (decision P5-D7): every FILLED field whose checks all passed and whose value
  did not come from the LLM. Never a suggestion, a field with a warning, or an address part the
  LLM split from free text (`LLM_INFERRED`): those need a look of their own.

Fields FormPilot never fills (`no_fill_reason`) cannot be edited or confirmed. While a job of
the document is queued or running, the IR may change underneath, so review actions are refused.
Any change removes an earlier filled PDF: the output always matches the confirmed fields.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import AuditEvent, Document, DocumentStatus, Job, JobStatus
from app.ir.models import Field, FieldStatus, FormIR, TraceEvent, ValueSource
from app.logging import get_logger
from app.passes import fit, validate
from app.passes.context import PassContext
from app.services import ir_store
from app.storage.base import Storage
from app.vault.crypto import VaultCipher

log = get_logger(__name__)

STAGE = "review"
MAX_VALUE_LENGTH = 500


class ReviewError(Exception):
    """A review action that cannot be applied; the message is readable and holds no value."""


class FieldNotFoundError(ReviewError):
    pass


class NeverFilledError(ReviewError):
    pass


class NothingToConfirmError(ReviewError):
    pass


class DocumentBusyError(ReviewError):
    pass


def output_key(document_id: uuid.UUID) -> str:
    return f"documents/{document_id}/output.pdf"


@dataclass(frozen=True)
class Change:
    field_id: str
    event: str  # the audit event, e.g. "field_confirmed"


_UNSET = object()


def _checked(field: Field, ir: FormIR, ctx: PassContext) -> Field:
    """The field after the validate and fit passes (only this field)."""
    single = ir.model_copy(update={"fields": [field], "trace": []})
    return fit.run(validate.run(single, ctx), ctx).fields[0]


def _settled(field: Field) -> FieldStatus:
    return (
        FieldStatus.NEEDS_REVIEW if any(not v.ok for v in field.validations) else FieldStatus.FILLED
    )


def _event(field_id: str, change: str, ctx: PassContext) -> TraceEvent:
    return TraceEvent(pass_name=STAGE, field_id=field_id, change=change, at=ctx.clock())


def edit_field(
    ir: FormIR,
    field_id: str,
    ctx: PassContext,
    *,
    value: object = _UNSET,
    confirmed: bool | None = None,
) -> tuple[FormIR, list[Change]]:
    """A new value (None or blank clears it) and / or a confirm or unconfirm of one field."""
    fields = {f.id: f for f in ir.fields}
    field = fields.get(field_id)
    if field is None:
        raise FieldNotFoundError("This field is not on the form.")
    if field.no_fill_reason is not None:
        raise NeverFilledError("FormPilot never fills this field.")
    changes: list[Change] = []
    trace: list[TraceEvent] = []
    was_suggested = field.status is FieldStatus.SUGGESTED
    if value is not _UNSET:
        text = " ".join(str(value).split()) if value is not None else ""
        if not text:
            field = field.model_copy(
                update={
                    "value": None, "value_source": ValueSource.NONE, "validations": [],
                    "font_size": None, "status": FieldStatus.NEEDS_INPUT,
                }
            )  # fmt: skip
            changes.append(
                Change(field_id, "suggestion_rejected" if was_suggested else "field_cleared")
            )
            trace.append(_event(field_id, "cleared by the user", ctx))
        else:
            field = field.model_copy(
                update={
                    "value": text, "value_source": ValueSource.USER_EDIT, "validations": [],
                    "status": FieldStatus.FILLED,
                }
            )  # fmt: skip
            field = _checked(field, ir, ctx)
            field = field.model_copy(update={"status": _settled(field)})
            changes.append(Change(field_id, "field_edited"))
            trace.append(_event(field_id, "value edited by the user", ctx))
    if confirmed is True:
        answered_no = field.value is None and field.status is FieldStatus.FILLED
        if field.value is None and not answered_no:
            raise NothingToConfirmError("This field has no value to confirm.")
        if field.status is not FieldStatus.CONFIRMED:
            accepted = field.status is FieldStatus.SUGGESTED
            field = field.model_copy(update={"status": FieldStatus.CONFIRMED})
            changes.append(
                Change(field_id, "suggestion_accepted" if accepted else "field_confirmed")
            )
            trace.append(_event(field_id, "confirmed by the user", ctx))
    elif confirmed is False and field.status is FieldStatus.CONFIRMED:
        field = field.model_copy(update={"status": _settled(field)})
        changes.append(Change(field_id, "field_unconfirmed"))
        trace.append(_event(field_id, "unconfirmed by the user", ctx))
    fields[field_id] = field
    return (
        ir.model_copy(
            update={"fields": [fields[f.id] for f in ir.fields], "trace": ir.trace + trace}
        ),
        changes,
    )


def bulk_confirmable(field: Field) -> bool:
    """P5-D7: FILLED, every check passed, and the value is not the LLM's."""
    return (
        field.status is FieldStatus.FILLED
        and field.no_fill_reason is None
        and all(v.ok for v in field.validations)
        and field.value_source is not ValueSource.LLM_INFERRED
    )


def confirm_all(ir: FormIR, ctx: PassContext) -> tuple[FormIR, list[Change]]:
    changes = [Change(f.id, "field_confirmed_in_bulk") for f in ir.fields if bulk_confirmable(f)]
    ids = {c.field_id for c in changes}
    fields = [
        f.model_copy(update={"status": FieldStatus.CONFIRMED}) if f.id in ids else f
        for f in ir.fields
    ]
    trace = [_event(c.field_id, "confirmed by the user (confirm all)", ctx) for c in changes]
    return ir.model_copy(update={"fields": fields, "trace": ir.trace + trace}), changes


def renderable(ir: FormIR) -> list[Field]:
    """The fields a filled PDF shows (invariant 7): confirmed, with a value, never-fill excluded."""
    return [
        f
        for f in ir.fields
        if f.status is FieldStatus.CONFIRMED and f.value and f.no_fill_reason is None
    ]


# --- storing ---------------------------------------------------------------------------------


type Transform = Callable[[FormIR], tuple[FormIR, list[Change]]]


async def job_running(session: AsyncSession, document_id: uuid.UUID) -> bool:
    running = await session.scalar(
        select(Job.id)
        .where(
            Job.document_id == document_id,
            Job.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        )
        .limit(1)
    )
    return running is not None


class ReviewService:
    def __init__(self, session: AsyncSession, storage: Storage, cipher: VaultCipher) -> None:
        self._session = session
        self._storage = storage
        self._cipher = cipher

    def audit(
        self, document: Document, user_id: uuid.UUID, event: str, field_id: str | None = None
    ) -> None:
        """Adds an audit event to the session (committed by the caller). Never a value."""
        self._session.add(
            AuditEvent(
                document_id=document.id, user_id=user_id, field_id=field_id, event=event,
                actor=f"user:{user_id}",
            )
        )  # fmt: skip

    async def apply(
        self, document: Document, user_id: uuid.UUID, transform: Transform
    ) -> tuple[FormIR, list[Change]]:
        """Runs a review rule on the latest IR and stores the next version (committed).

        Raises DocumentBusyError while a job runs, or if another change was stored first."""
        if await job_running(self._session, document.id):
            raise DocumentBusyError("The form is still being processed. Try again in a moment.")
        ir = await ir_store.latest(self._session, document.id, self._cipher)
        if ir is None:
            raise FieldNotFoundError("The form is not analysed yet.")
        changed, changes = transform(ir)
        if not changes:
            return ir, []
        await ir_store.add_version(self._session, document.id, changed, self._cipher)
        for change in changes:
            self.audit(document, user_id, change.event, change.field_id)
        await self._session.execute(
            update(Document)
            .where(Document.id == document.id, Document.status == DocumentStatus.DONE.value)
            .values(status=DocumentStatus.READY.value)
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise DocumentBusyError(
                "The form changed meanwhile. Reload it and try again."
            ) from None
        await self._storage.delete(output_key(document.id))  # the filled PDF is out of date
        log.info(
            "document_reviewed",
            document_id=str(document.id),
            changes=len(changes),
            events=sorted({c.event for c in changes}),
        )
        return changed, changes


def review_context(clock: Callable[[], datetime], settings: Settings) -> PassContext:
    """The validate and fit settings for re-checking an edited value."""
    return PassContext(
        clock=clock, fit_font_size=settings.fit_font_size,
        fit_min_font_size=settings.fit_min_font_size,
    )  # fmt: skip
