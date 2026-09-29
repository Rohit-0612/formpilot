from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import URL, CheckConstraint, create_engine, inspect
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
