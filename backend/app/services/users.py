"""User registration and authentication.

Logging rule [A5]: log user ids only, never email addresses or passwords.
"""

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.logging import get_logger
from app.security import burn_verify_time, hash_password, verify_password

log = get_logger(__name__)


class EmailAlreadyRegisteredError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(self, email: str, password: str) -> User:
        # Argon2 is deliberately slow and CPU-bound: keep it off the event loop.
        password_hash = await asyncio.to_thread(hash_password, password)
        user = User(email=normalize_email(email), password_hash=password_hash)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if "uq_users_email" in str(exc.orig):
                log.info("registration_rejected", reason="email_taken")
                raise EmailAlreadyRegisteredError from None
            raise
        log.info("user_registered", user_id=str(user.id))
        return user

    async def authenticate(self, email: str, password: str) -> User | None:
        user = await self._session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None:
            await asyncio.to_thread(burn_verify_time, password)
            log.info("login_failed")
            return None
        if not await asyncio.to_thread(verify_password, user.password_hash, password):
            log.info("login_failed")
            return None
        log.info("user_logged_in", user_id=str(user.id))
        return user

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)
