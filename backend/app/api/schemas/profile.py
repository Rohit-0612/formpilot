from datetime import datetime

from pydantic import BaseModel, Field

from app.services.masking import mask_value
from app.vault.fields import BY_KEY, PROFILE_FIELDS
from app.vault.service import ProfileData


class ProfileFieldInfo(BaseModel):
    key: str
    label: str
    group: str
    sensitive: bool


class ProfileResponse(BaseModel):
    """Sensitive values are masked (SPEC §8); dates are ISO (YYYY-MM-DD)."""

    values: dict[str, str]
    sensitive_opt_in: list[str]
    fields: list[ProfileFieldInfo]
    updated_at: datetime | None

    @classmethod
    def masked(cls, profile: ProfileData) -> "ProfileResponse":
        return cls(
            values={
                key: mask_value(value) if BY_KEY[key].sensitive else value
                for key, value in sorted(profile.values.items())
                if key in BY_KEY
            },
            sensitive_opt_in=sorted(profile.sensitive_opt_in),
            fields=[
                ProfileFieldInfo(key=f.key, label=f.label, group=f.group, sensitive=f.sensitive)
                for f in PROFILE_FIELDS
            ],
            updated_at=profile.updated_at,
        )


class ProfileUpdate(BaseModel):
    """Values to set (null deletes) and per-field opt-ins for sensitive values. A sensitive value
    is saved only with its opt-in (in this request or earlier); opting out deletes it."""

    values: dict[str, str | None] = Field(default_factory=dict)
    sensitive_opt_in: dict[str, bool] = Field(default_factory=dict)


class ProfileProblem(BaseModel):
    key: str
    message: str  # never contains the value
