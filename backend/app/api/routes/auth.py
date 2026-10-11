from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api import API_PREFIX
from app.api.deps import SESSION_COOKIE, CurrentUser, get_app_settings, get_user_service
from app.api.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.config import Settings
from app.security import create_access_token
from app.services.users import EmailAlreadyRegisteredError, UserService

router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=["auth"])

Users = Annotated[UserService, Depends(get_user_service)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]

_INVALID_LOGIN = "Invalid email or password"


def _cookie_options(settings: Settings) -> dict[str, object]:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
    }


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={status.HTTP_409_CONFLICT: {"description": "Email already registered"}},
)
async def register(body: RegisterRequest, users: Users) -> UserResponse:
    try:
        user = await users.register(body.email, body.password)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered") from None
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=UserResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": _INVALID_LOGIN}},
)
async def login(
    body: LoginRequest, users: Users, settings: AppSettings, response: Response
) -> UserResponse:
    user = await users.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=_INVALID_LOGIN)
    ttl = timedelta(minutes=settings.jwt_ttl_minutes)
    token = create_access_token(user.id, settings.jwt_secret.get_secret_value(), ttl)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        **_cookie_options(settings),  # type: ignore[arg-type]
    )
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(settings: AppSettings, response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, **_cookie_options(settings))  # type: ignore[arg-type]


@router.get(
    "/me",
    response_model=UserResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Not authenticated"}},
)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
