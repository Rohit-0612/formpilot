import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.ir import MaskedFormIR
from app.db.models import DocumentStatus, JobStatus, JobType
from app.ir.models import SourceKind
from app.passes.answers import Answer
from app.passes.questions import Question
from app.services.review import MAX_VALUE_LENGTH


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID


class JobSummary(BaseModel):
    id: uuid.UUID
    # analyze runs on after the document is `ready` (understanding and filling); the web app
    # keeps polling while it is queued or running
    type: JobType
    status: JobStatus
    error_message: str | None  # readable, never a value


class DocumentResponse(BaseModel):
    id: uuid.UUID
    original_filename: str
    status: DocumentStatus
    source_kind: SourceKind | None
    page_count: int | None
    created_at: datetime
    expires_at: datetime
    job: JobSummary | None  # the latest job of this document


class JobResponse(BaseModel):
    id: uuid.UUID
    type: JobType
    status: JobStatus
    document_id: uuid.UUID | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None


class QuestionsResponse(BaseModel):
    """The questions for the fields that still need input (SPEC §6.4)."""

    questions: list[Question]
    fields_needing_input: int


class AnswersRequest(BaseModel):
    """Answers to the current questions (SPEC §6.5). `parts` keys are the parts' semantic types,
    or field ids for untyped parts (a section card); a sensitive value is saved to the profile
    only if its key is in `sensitive_opt_in`."""

    answers: list[Answer] = Field(min_length=1, max_length=200)


class JobAccepted(BaseModel):
    job_id: uuid.UUID


class FieldEdit(BaseModel):
    """A review action on one field (SPEC §6.8). `value`: the user's value; null or an empty
    string clears the field (it is asked again); left out: unchanged. `confirmed`: true confirms
    the field (also accepting a suggestion), false takes the confirm back; left out: unchanged."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = Field(default=None, max_length=MAX_VALUE_LENGTH)
    confirmed: bool | None = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if not self.model_fields_set & {"value", "confirmed"}:
            raise ValueError("send a value, confirmed, or both")
        return self


class ReviewResponse(BaseModel):
    """The form after a review action (values masked as in GET /ir) and how many fields the
    action changed (0: nothing to do)."""

    ir: MaskedFormIR
    changed: int
