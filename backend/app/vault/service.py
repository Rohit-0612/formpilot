"""The profile vault (SPEC §6.3, §7, §11): one Fernet-encrypted JSON blob per user.

- Values are keyed by profile key (`vault/fields.py`), checked and normalised on the way in.
- Sensitive values (D2) are stored only for keys the user opted in to, one key at a time;
  opting out deletes the stored value.
- Every change writes an audit event with the key and what happened, never the value.
"""

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditEvent, Profile
from app.logging import get_logger
from app.validators.normalize import InvalidValueError, normalize
from app.vault.crypto import VaultCipher
from app.vault.fields import BY_KEY

log = get_logger(__name__)


class ProfileUpdateError(Exception):
    """Per-key problems with an update; messages never contain values."""

    def __init__(self, problems: dict[str, str]) -> None:
        super().__init__(", ".join(sorted(problems)))
        self.problems = problems


@dataclass
class ProfileData:
    values: dict[str, str] = field(default_factory=dict)
    sensitive_opt_in: set[str] = field(default_factory=set)
    updated_at: datetime | None = None

    def to_json(self) -> str:
        return json.dumps(
            {"values": self.values, "sensitive_opt_in": sorted(self.sensitive_opt_in)},
            ensure_ascii=False,
            sort_keys=True,
        )


class ProfileService:
    def __init__(self, session: AsyncSession, cipher: VaultCipher) -> None:
        self._session = session
        self._cipher = cipher

    async def load(self, user_id: uuid.UUID) -> ProfileData:
        row = await self._session.get(Profile, user_id)
        if row is None:
            return ProfileData()
        stored = json.loads(self._cipher.decrypt(row.encrypted_blob.decode()))
        return ProfileData(
            values=dict(stored["values"]),
            sensitive_opt_in=set(stored["sensitive_opt_in"]),
            updated_at=row.updated_at,
        )

    async def update(
        self,
        user_id: uuid.UUID,
        values: Mapping[str, str | None],
        sensitive_opt_in: Mapping[str, bool],
        today: date,
    ) -> ProfileData:
        """Applies the opt-in changes, then the values (None deletes). All or nothing."""
        profile = await self.load(user_id)
        problems: dict[str, str] = {}
        events: list[tuple[str, str]] = []
        for key in [*sensitive_opt_in, *values]:
            if key not in BY_KEY:
                problems[key] = "Unknown profile field."
        for key, on in sensitive_opt_in.items():
            if key in BY_KEY and not BY_KEY[key].sensitive:
                problems[key] = "Only sensitive fields need an opt-in."
            elif key in BY_KEY and on and key not in profile.sensitive_opt_in:
                profile.sensitive_opt_in.add(key)
                events.append((key, "profile_opt_in"))
            elif key in BY_KEY and not on and key in profile.sensitive_opt_in:
                profile.sensitive_opt_in.discard(key)
                if profile.values.pop(key, None) is not None:
                    events.append((key, "profile_value_removed"))
                events.append((key, "profile_opt_out"))
        for key, raw in values.items():
            spec = BY_KEY.get(key)
            if spec is None:
                continue
            if raw is None:
                if profile.values.pop(key, None) is not None:
                    events.append((key, "profile_value_removed"))
                continue
            if spec.sensitive and key not in profile.sensitive_opt_in:
                problems[key] = "Saving this sensitive value needs your opt-in for this field."
                continue
            try:
                value = normalize(spec.semantic_type, raw, today)
            except InvalidValueError as exc:
                problems[key] = str(exc)
                continue
            if profile.values.get(key) != value:
                profile.values[key] = value
                events.append((key, "profile_value_set"))
        if problems:
            raise ProfileUpdateError(problems)
        if events:
            await self._save(user_id, profile, events)
        return await self.load(user_id) if events else profile

    async def _save(
        self, user_id: uuid.UUID, profile: ProfileData, events: list[tuple[str, str]]
    ) -> None:
        blob = self._cipher.encrypt(profile.to_json()).encode()
        row = await self._session.get(Profile, user_id)
        if row is None:
            self._session.add(Profile(user_id=user_id, encrypted_blob=blob))
        else:
            row.encrypted_blob = blob
        for key, event in events:
            self._session.add(
                AuditEvent(user_id=user_id, field_id=key, event=event, actor=f"user:{user_id}")
            )
        await self._session.commit()
        log.info("profile_updated", user_id=str(user_id), changes=len(events))


async def load_profile_values(
    session: AsyncSession, user_id: uuid.UUID, cipher: VaultCipher
) -> dict[str, str]:
    """The decrypted values for the match pass (empty without a profile)."""
    return (await ProfileService(session, cipher).load(user_id)).values
