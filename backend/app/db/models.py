"""Database tables (SPEC §7). Schema changes need a decision record and a new Alembic migration.

Enum-like columns are VARCHAR + CHECK rather than native PostgreSQL enums, so new values can be
added by a later migration that replaces the CHECK constraint.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    READY = "ready"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


# Mirrors SourceKind in the Form IR (SPEC §4), which arrives with ir/models.py in Phase 2.
SOURCE_KINDS = ("fillable", "flat_text", "scanned", "photo")


class JobType(StrEnum):
    ANALYZE = "analyze"
    RENDER = "render"
    PING = "ping"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _one_of(column: str, values: Any, name: str) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _document_fk(nullable: bool = False, index: bool = True) -> Mapped[Any]:
    return mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=nullable, index=index
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        _one_of("status", DocumentStatus, "status_valid"),
        _one_of("source_kind", SOURCE_KINDS, "source_kind_valid"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint("page_count IS NULL OR page_count > 0", name="page_count_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Unknown until the analyze job has run detection.
    source_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DocumentStatus.UPLOADED.value
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    # Indexed for the expiry cleanup job.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class FormIRVersion(Base):
    """Append-only: a new row per IR change, never updated in place."""

    __tablename__ = "form_ir_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_form_ir_versions_document_version"),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # No separate index: the unique (document_id, version) index already starts with document_id.
    document_id: Mapped[uuid.UUID] = _document_fk(index=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ir_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        _one_of("type", JobType, "type_valid"),
        _one_of("status", JobStatus, "status_valid"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Nullable: a ping job has no document.
    document_id: Mapped[uuid.UUID | None] = _document_fk(nullable=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=JobStatus.QUEUED.value
    )
    # Error class / short reason only; never field values.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Profile(Base):
    """The user's profile vault, Fernet-encrypted as one blob (Phase 4)."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditEvent(Base):
    """What happened to which field, by whom. Never stores values."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = _document_fk()
    field_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    # "user:<uuid>" or "system"
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created_at()
