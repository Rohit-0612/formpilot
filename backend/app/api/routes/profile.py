from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder

from app.api import API_PREFIX
from app.api.deps import CurrentUser, get_profile_service
from app.api.schemas.profile import ProfileProblem, ProfileResponse, ProfileUpdate
from app.passes.context import INDIA
from app.vault.service import ProfileService, ProfileUpdateError

router = APIRouter(prefix=f"{API_PREFIX}/profile", tags=["profile"])

Profiles = Annotated[ProfileService, Depends(get_profile_service)]


@router.get("", response_model=ProfileResponse)
async def get_profile(user: CurrentUser, profiles: Profiles) -> ProfileResponse:
    return ProfileResponse.masked(await profiles.load(user.id))


@router.put(
    "",
    response_model=ProfileResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Unknown keys, invalid values or a sensitive value without opt-in"
        }
    },
)
async def put_profile(
    body: ProfileUpdate, user: CurrentUser, profiles: Profiles
) -> ProfileResponse:
    today = datetime.now(INDIA).date()
    try:
        profile = await profiles.update(user.id, body.values, body.sensitive_opt_in, today)
    except ProfileUpdateError as exc:
        detail: Any = jsonable_encoder(
            [ProfileProblem(key=k, message=m) for k, m in sorted(exc.problems.items())]
        )
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail) from None
    return ProfileResponse.masked(profile)
