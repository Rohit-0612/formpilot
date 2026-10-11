from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api import API_PREFIX
from app.api.deps import get_health_service
from app.api.schemas.health import HealthResponse
from app.services.health import HealthService

router = APIRouter(prefix=API_PREFIX, tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(
    response: Response,
    service: Annotated[HealthService, Depends(get_health_service)],
) -> HealthResponse:
    report = await service.check()
    if not report.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if report.ok else "degraded",
        db=report.db,
        redis=report.redis,
    )
