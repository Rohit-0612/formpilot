import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import API_PREFIX
from app.api.deps import CurrentUser, get_app_settings, get_document_service
from app.api.schemas.documents import JobResponse
from app.config import Settings
from app.services.documents import DocumentService, job_error_message

router = APIRouter(prefix=f"{API_PREFIX}/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Job not found"}},
)
async def get_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    documents: Annotated[DocumentService, Depends(get_document_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> JobResponse:
    job = await documents.get_job(job_id, user.id)
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
