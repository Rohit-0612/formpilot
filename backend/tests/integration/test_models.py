import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import (
    SOURCE_KINDS,
    AuditEvent,
    Document,
    DocumentStatus,
    FormIRVersion,
    Job,
    JobStatus,
    JobType,
    Profile,
    User,
)
from app.db.session import make_sessionmaker
from tests.integration.db import savepoint_session, truncate_all_tables

# Synthetic data only.
FAKE_HASH = "$argon2id$not-a-real-hash"


def _user(email: str = "asha@example.com") -> User:
    return User(email=email, password_hash=FAKE_HASH)


def _document(owner: User, **overrides: object) -> Document:
    values: dict[str, object] = {
        "owner_id": owner.id,
        "original_filename": "blank-scholarship-form.pdf",
        "sha256": "0" * 64,
        "expires_at": datetime.now(UTC) + timedelta(hours=24),
    }
    values.update(overrides)
    return Document(**values)


async def _count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model)) or 0


async def _assert_rejected(session: AsyncSession, obj: object, constraint: str) -> None:
    session.add(obj)
    with pytest.raises(IntegrityError) as excinfo:
        await session.flush()
    assert constraint in str(excinfo.value)
    await session.rollback()


# --- users -------------------------------------------------------------------


async def test_email_is_unique(db_session: AsyncSession) -> None:
    db_session.add(_user())
    await db_session.flush()

    await _assert_rejected(db_session, _user(), "uq_users_email")


async def test_email_must_be_stored_lowercase(db_session: AsyncSession) -> None:
    await _assert_rejected(db_session, _user("Asha@Example.com"), "ck_users_email_lowercase")


# --- documents ---------------------------------------------------------------


async def test_document_defaults_to_uploaded(db_session: AsyncSession) -> None:
    owner = _user()
    db_session.add(owner)
    await db_session.flush()
    document = _document(owner)
    db_session.add(document)
    await db_session.flush()
    await db_session.refresh(document)

    assert document.status == "uploaded"
    assert document.source_kind is None
    assert document.created_at.tzinfo is not None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "archived"}, "ck_documents_status_valid"),
        ({"source_kind": "docx"}, "ck_documents_source_kind_valid"),
        ({"sha256": "abc"}, "ck_documents_sha256_length"),
        ({"page_count": 0}, "ck_documents_page_count_positive"),
    ],
)
async def test_document_check_constraints(
    db_session: AsyncSession, overrides: dict, constraint: str
) -> None:
    owner = _user()
    db_session.add(owner)
    await db_session.flush()

    await _assert_rejected(db_session, _document(owner, **overrides), constraint)


# --- jobs --------------------------------------------------------------------


async def test_ping_job_needs_no_document_and_starts_queued(db_session: AsyncSession) -> None:
    job = Job(type="ping")
    db_session.add(job)
    await db_session.flush()
    await db_session.refresh(job)

    assert job.document_id is None
    assert job.status == "queued"
    assert job.finished_at is None


@pytest.mark.parametrize(
    ("job", "constraint"),
    [
        (Job(type="ping", status="paused"), "ck_jobs_status_valid"),
        (Job(type="ocr"), "ck_jobs_type_valid"),
    ],
)
async def test_job_check_constraints(db_session: AsyncSession, job: Job, constraint: str) -> None:
    await _assert_rejected(db_session, job, constraint)


# --- form IR versions --------------------------------------------------------


async def test_ir_version_is_unique_per_document_and_positive(db_session: AsyncSession) -> None:
    owner = _user()
    db_session.add(owner)
    await db_session.flush()
    document = _document(owner)
    db_session.add(document)
    await db_session.flush()
    db_session.add(FormIRVersion(document_id=document.id, version=1, ir_json={"fields": []}))
    await db_session.flush()

    await _assert_rejected(
        db_session,
        FormIRVersion(document_id=document.id, version=1, ir_json={"fields": []}),
        "uq_form_ir_versions_document_version",
    )
    await _assert_rejected(
        db_session,
        FormIRVersion(document_id=document.id, version=0, ir_json={"fields": []}),
        "ck_form_ir_versions_version_positive",
    )


# --- cascades ----------------------------------------------------------------


async def test_deleting_a_user_cascades_to_everything_they_own(db_session: AsyncSession) -> None:
    owner = _user()
    db_session.add(owner)
    await db_session.flush()
    document = _document(owner)
    db_session.add(document)
    await db_session.flush()
    db_session.add_all(
        [
            Job(document_id=document.id, type="analyze"),
            FormIRVersion(document_id=document.id, version=1, ir_json={"fields": []}),
            AuditEvent(document_id=document.id, event="field_confirmed", actor=f"user:{owner.id}"),
            Profile(user_id=owner.id, encrypted_blob=b"not-really-encrypted"),
        ]
    )
    await db_session.flush()

    await db_session.delete(owner)
    await db_session.flush()
    db_session.expunge_all()

    for model in (User, Document, Job, FormIRVersion, AuditEvent, Profile):
        assert await _count(db_session, model) == 0, model.__tablename__


async def test_deleting_a_document_keeps_the_ping_jobs(db_session: AsyncSession) -> None:
    owner = _user()
    db_session.add(owner)
    await db_session.flush()
    document = _document(owner)
    db_session.add_all([document, Job(type="ping")])
    await db_session.flush()
    db_session.add(Job(document_id=document.id, type="analyze"))
    await db_session.flush()

    await db_session.delete(document)
    await db_session.flush()
    db_session.expunge_all()

    remaining = (await db_session.scalars(select(Job.type))).all()
    assert remaining == ["ping"]


# --- the test isolation itself [A1] ------------------------------------------


async def test_commit_inside_a_savepoint_session_is_rolled_back(engine: AsyncEngine) -> None:
    email = f"rollback-{uuid.uuid4().hex}@example.com"

    async with savepoint_session(engine) as session:
        session.add(_user(email))
        await session.commit()  # what service code does
        visible_inside = await session.scalar(select(func.count()).where(User.email == email))

    async with engine.connect() as conn:
        visible_after = await conn.scalar(select(func.count()).where(User.email == email))

    assert visible_inside == 1
    assert visible_after == 0


async def test_truncate_all_tables_removes_really_committed_rows(engine: AsyncEngine) -> None:
    async with make_sessionmaker(engine)() as session:
        session.add(_user(f"truncate-{uuid.uuid4().hex}@example.com"))
        await session.commit()

    await truncate_all_tables(engine)

    async with engine.connect() as conn:
        assert await conn.scalar(select(func.count()).select_from(User)) == 0


# --- Python enums vs database CHECK constraints ------------------------------


async def test_every_python_enum_value_is_accepted_by_the_database(
    db_session: AsyncSession,
) -> None:
    """Catches a value added to a Python enum without a migration that updates the CHECK."""
    owner = _user()
    db_session.add(owner)
    await db_session.flush()

    for status in DocumentStatus:
        db_session.add(_document(owner, status=status.value))
    for kind in SOURCE_KINDS:
        db_session.add(_document(owner, source_kind=kind))
    for job_type in JobType:
        for job_status in JobStatus:
            db_session.add(Job(type=job_type.value, status=job_status.value))

    await db_session.flush()  # raises IntegrityError if any value is missing from a CHECK
