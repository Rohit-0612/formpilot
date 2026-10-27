import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.db.models import DocumentStatus, JobStatus, JobType
from app.ir.models import SourceKind
from app.passes.answers import Answer
from app.passes.questions import Question


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
    """Answers to the current questions (SPEC §6.5). `parts` keys are semantic types; a
    sensitive value is saved to the profile only if its key is in `sensitive_opt_in`."""

    answers: list[Answer] = Field(min_length=1, max_length=200)


class JobAccepted(BaseModel):
    job_id: uuid.UUID
