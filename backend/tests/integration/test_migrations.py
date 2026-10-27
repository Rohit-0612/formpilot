from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import URL, CheckConstraint, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool

from app.db.base import Base
from tests.integration.db import alembic_config, drop_database, recreate_database

SCRATCH_DB_NAME = "formpilot_test_migrations"
EXPECTED_TABLES = {"users", "documents", "form_ir_versions", "jobs", "profiles", "audit_events"}


@pytest.fixture
def scratch_db_url() -> Iterator[URL]:
    url = recreate_database(SCRATCH_DB_NAME)
    yield url
    drop_database(SCRATCH_DB_NAME)


def _tables(url: URL) -> set[str]:
    engine = create_engine(url, poolclass=NullPool)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_round_trip(scratch_db_url: URL) -> None:
    config = alembic_config(scratch_db_url)

    command.upgrade(config, "head")
    assert _tables(scratch_db_url) == EXPECTED_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert _tables(scratch_db_url) == {"alembic_version"}

    command.upgrade(config, "head")
    assert _tables(scratch_db_url) == EXPECTED_TABLES | {"alembic_version"}


def _job_columns(url: URL) -> dict[str, bool]:
    """Column name -> nullable, for the jobs table."""
    engine = create_engine(url, poolclass=NullPool)
    try:
        return {
            column["name"]: column["nullable"] for column in inspect(engine).get_columns("jobs")
        }
    finally:
        engine.dispose()


def test_0002_adds_a_nullable_started_at_and_keeps_existing_jobs(scratch_db_url: URL) -> None:
    config = alembic_config(scratch_db_url)
    command.upgrade(config, "0001")
    assert "started_at" not in _job_columns(scratch_db_url)
    engine = create_engine(scratch_db_url, poolclass=NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO jobs (id, type, status)"
                    " VALUES (gen_random_uuid(), 'ping', 'running')"
                )
            )

        command.upgrade(config, "0002")
        assert _job_columns(scratch_db_url)["started_at"] is True
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT status, started_at FROM jobs")).all()
        assert [tuple(row) for row in rows] == [("running", None)]

        command.downgrade(config, "0001")
        assert "started_at" not in _job_columns(scratch_db_url)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 1
    finally:
        engine.dispose()


def test_models_match_migrations(migrated_db_url: URL) -> None:
    """Autogenerate against the migrated database must find nothing to do."""
    engine = create_engine(migrated_db_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == []


def test_check_constraints_match_models(migrated_db_url: URL) -> None:
    """Autogenerate does not compare CHECK constraints, so compare their names explicitly."""
    engine = create_engine(migrated_db_url, poolclass=NullPool)
    try:
        inspector = inspect(engine)
        for table in Base.metadata.sorted_tables:
            in_models = {
                str(constraint.name)
                for constraint in table.constraints
                if isinstance(constraint, CheckConstraint)
            }
            in_db = {check["name"] for check in inspector.get_check_constraints(table.name)}
            assert in_db == in_models, table.name
    finally:
        engine.dispose()


def test_0003_allows_profile_events_and_answers_jobs_and_downgrades(scratch_db_url: URL) -> None:
    config = alembic_config(scratch_db_url)
    command.upgrade(config, "0003")
    engine = create_engine(scratch_db_url, poolclass=NullPool)
    user = "INSERT INTO users (id, email, password_hash) VALUES (gen_random_uuid(), 'a@b.c', 'x')"
    try:
        with engine.begin() as conn:
            conn.execute(text(user))
            conn.execute(
                text(
                    "INSERT INTO audit_events (id, user_id, event, actor)"
                    " SELECT gen_random_uuid(), id, 'profile_updated', 'user' FROM users"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO jobs (id, type, status)"
                    " VALUES (gen_random_uuid(), 'answers', 'queued')"
                )
            )
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_events (id, event, actor)"
                    " VALUES (gen_random_uuid(), 'orphan', 'system')"
                )
            )

        command.downgrade(config, "0002")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
            assert conn.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
        command.upgrade(config, "head")
    finally:
        engine.dispose()
