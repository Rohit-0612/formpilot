import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import API_PREFIX
from app.api.deps import CurrentUser, get_app_settings, get_document_service
from app.api.schemas.documents import JobResponse
from app.config import Settings
from app.services.documents import DocumentExpiredError, DocumentService, job_error_message

router = APIRouter(prefix=f"{API_PREFIX}/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Job not found"},
        status.HTTP_410_GONE: {"description": "The job's document expired and is being deleted"},
    },
)
async def get_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    documents: Annotated[DocumentService, Depends(get_document_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> JobResponse:
    try:
        job = await documents.get_job(job_id, user.id)
    except DocumentExpiredError as exc:
        raise HTTPException(status.HTTP_410_GONE, detail=str(exc)) from None
    if job is None:  # missing, another user's, or a job without a document (ping)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobResponse.model_validate(
        {
            "id": job.id,
            "type": job.type,
            "status": job.status,
            "document_id": job.document_id,
            "error_message": job_error_message(job.error, max_pages=settings.max_pages),
            "created_at": job.created_at,
            "finished_at": job.finished_at,
        }
    )
