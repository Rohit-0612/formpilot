import uuid
from datetime import datetime

from pydantic import BaseModel

from app.db.models import DocumentStatus, JobStatus, JobType
from app.ir.models import SourceKind


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID


class JobSummary(BaseModel):
    id: uuid.UUID
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
