import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status

from app.api import API_PREFIX
from app.api.deps import (
    CurrentUser,
    get_app_settings,
    get_document_service,
    get_queue,
    get_review_service,
)
from app.api.schemas.documents import (
    AnswersRequest,
    DocumentResponse,
    FieldEdit,
    JobAccepted,
    JobSummary,
    QuestionsResponse,
    ReviewResponse,
    UploadResponse,
)
from app.api.schemas.ir import MaskedFormIR
from app.api.uploads import InvalidUploadError, UploadTooLargeError, read_upload
from app.config import Settings
from app.db.models import Document
from app.services import filling
from app.services.documents import (
    DocumentService,
    UnknownQuestionsError,
    job_error_message,
    looks_like_pdf,
)
from app.services.jobs import JobEnqueueError, JobQueue
from app.services.review import (
    DocumentBusyError,
    FieldNotFoundError,
    ReviewError,
    ReviewService,
    Transform,
    confirm_all,
    edit_field,
    review_context,
)

router = APIRouter(prefix=f"{API_PREFIX}/documents", tags=["documents"])

Documents = Annotated[DocumentService, Depends(get_document_service)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Queue = Annotated[JobQueue, Depends(get_queue)]
Review = Annotated[ReviewService, Depends(get_review_service)]
DocumentId = Annotated[uuid.UUID, Path()]
FieldId = Annotated[str, Path(min_length=1, max_length=64)]

_NOT_FOUND = "Document not found"
_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": _NOT_FOUND}
}

# The body is read by read_upload (size cap while reading), not by a File() parameter, so the
# multipart schema is declared here for the OpenAPI document and the generated web types.
_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResponse,
    openapi_extra=_UPLOAD_BODY,
    responses={
        status.HTTP_413_CONTENT_TOO_LARGE: {"description": "The file is too large"},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"description": "The file is not a PDF"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "No single file in field 'file'"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The analysis could not be started"},
    },
)
async def upload_document(
    request: Request, user: CurrentUser, documents: Documents, settings: AppSettings, queue: Queue
) -> UploadResponse:
    try:
        upload = await read_upload(request, settings.max_upload_mb * 1024 * 1024)
    except UploadTooLargeError:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"The file is larger than {settings.max_upload_mb} MB.",
        ) from None
    except InvalidUploadError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Send one PDF file in the multipart field 'file'.",
        ) from None
    if not looks_like_pdf(upload.data):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="The file is not a PDF.")
    try:
        document, job = await documents.upload(user.id, upload.filename, upload.data, queue)
    except JobEnqueueError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis could not be started. Please try again.",
        ) from None
    return UploadResponse(document_id=document.id, job_id=job.id)


async def _owned(documents: DocumentService, document_id: uuid.UUID, user: CurrentUser) -> Document:
    document = await documents.get(document_id, user.id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    return document


@router.get("/{document_id}", response_model=DocumentResponse, responses=_NOT_FOUND_RESPONSE)
async def get_document(
    document_id: DocumentId, user: CurrentUser, documents: Documents, settings: AppSettings
) -> DocumentResponse:
    document = await _owned(documents, document_id, user)
    job = await documents.latest_job(document.id)
    return DocumentResponse.model_validate(
        {
            "id": document.id,
            "original_filename": document.original_filename,
            "status": document.status,
            "source_kind": document.source_kind,
            "page_count": document.page_count,
            "created_at": document.created_at,
            "expires_at": document.expires_at,
            "job": None
            if job is None
            else JobSummary.model_validate(
                {
                    "id": job.id,
                    "type": job.type,
                    "status": job.status,
                    "error_message": job_error_message(job.error, max_pages=settings.max_pages),
                }
            ),
        }
    )


@router.get(
    "/{document_id}/ir",
    response_model=MaskedFormIR,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Not found or not analysed yet"}},
)
async def get_ir(document_id: DocumentId, user: CurrentUser, documents: Documents) -> MaskedFormIR:
    document = await _owned(documents, document_id, user)
    ir_json = await documents.latest_ir(document.id)
    if ir_json is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The document is not analysed yet")
    return MaskedFormIR.model_validate(ir_json)  # sensitive values masked (SPEC §8)


@router.get(
    "/{document_id}/questions",
    response_model=QuestionsResponse,
    responses={status.HTTP_404_NOT_FOUND: {"description": "Not found or not analysed yet"}},
)
async def get_questions(
    document_id: DocumentId, user: CurrentUser, documents: Documents, settings: AppSettings
) -> QuestionsResponse:
    document = await _owned(documents, document_id, user)
    ir = await documents.latest_form(document.id)
    if ir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The document is not analysed yet")
    return QuestionsResponse(
        questions=filling.questions_for(ir, settings),
        fields_needing_input=filling.counts(ir)["needs_input"],
    )


@router.post(
    "/{document_id}/answers",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAccepted,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Not found or not analysed yet"},
        status.HTTP_409_CONFLICT: {"description": "Answers for questions that are not asked now"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "The job could not be queued"},
    },
)
async def post_answers(
    document_id: DocumentId,
    body: AnswersRequest,
    user: CurrentUser,
    documents: Documents,
    settings: AppSettings,
    queue: Queue,
) -> JobAccepted:
    document = await _owned(documents, document_id, user)
    ir = await documents.latest_form(document.id)
    if ir is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="The document is not analysed yet")
    try:
        job = await documents.submit_answers(
            document, body.answers, filling.questions_for(ir, settings), queue
        )
    except UnknownQuestionsError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"These questions are not asked now: {', '.join(exc.question_ids)}",
        ) from None
    except JobEnqueueError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="The answers could not be queued"
        ) from None
    return JobAccepted(job_id=job.id)


@router.get(
    "/{document_id}/pages/{page}.png",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {"image/png": {}}, "description": "The page image"},
        status.HTTP_404_NOT_FOUND: {"description": "Not found, no such page, or not rendered"},
    },
)
async def get_page_image(
    document_id: DocumentId,
    page: Annotated[int, Path(ge=0, description="0-based, like BBox.page")],
    user: CurrentUser,
    documents: Documents,
) -> Response:
    document = await _owned(documents, document_id, user)
    image = await documents.page_image(document, page)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page image not found")
    return Response(
        content=image, media_type="image/png", headers={"Cache-Control": "private, no-store"}
    )


_REVIEW_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": "Not found, not analysed yet, or no such field"},
    status.HTTP_409_CONFLICT: {
        "description": "Not possible now: a job is running, the field is never filled, or it "
        "has no value to confirm"
    },
}


async def _review(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentService, review: ReviewService,
    transform: Transform,
) -> ReviewResponse:  # fmt: skip
    document = await _owned(documents, document_id, user)
    try:
        ir, changes = await review.apply(document, user.id, transform)
    except FieldNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except ReviewError as exc:  # busy, never filled, nothing to confirm: messages hold no value
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    return ReviewResponse(
        ir=MaskedFormIR.model_validate(ir.model_dump(mode="json")), changed=len(changes)
    )


@router.patch(
    "/{document_id}/fields/{field_id}",
    response_model=ReviewResponse,
    responses=_REVIEW_RESPONSES,
)
async def patch_field(
    document_id: DocumentId,
    field_id: FieldId,
    body: FieldEdit,
    user: CurrentUser,
    documents: Documents,
    review: Review,
    settings: AppSettings,
) -> ReviewResponse:
    """Edit, clear, confirm or unconfirm one field (SPEC §6.8)."""
    ctx = review_context(lambda: datetime.now(UTC), settings)
    value = {"value": body.value} if "value" in body.model_fields_set else {}
    return await _review(
        document_id, user, documents, review,
        lambda ir: edit_field(ir, field_id, ctx, confirmed=body.confirmed, **value),
    )  # fmt: skip


@router.post(
    "/{document_id}/confirm-all",
    response_model=ReviewResponse,
    responses=_REVIEW_RESPONSES,
)
async def post_confirm_all(
    document_id: DocumentId,
    user: CurrentUser,
    documents: Documents,
    review: Review,
    settings: AppSettings,
) -> ReviewResponse:
    """Confirm every filled field whose checks passed and whose value is not the LLM's
    (decision P5-D7); suggestions and fields with a warning need their own confirm."""
    ctx = review_context(lambda: datetime.now(UTC), settings)
    return await _review(document_id, user, documents, review, lambda ir: confirm_all(ir, ctx))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": _NOT_FOUND},
        status.HTTP_409_CONFLICT: {"description": "A job of the document is running"},
    },
)
async def delete_document(document_id: DocumentId, user: CurrentUser, documents: Documents) -> None:
    """Delete the document now: the upload, page images, filled PDF, IR versions and jobs."""
    document = await _owned(documents, document_id, user)
    try:
        await documents.delete(document)
    except DocumentBusyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
