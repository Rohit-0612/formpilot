"""Profile audit events and the answers job (Phase 4, docs/decisions/phase-4.md)

- audit_events.user_id (cascade with the user) and a nullable document_id: a profile event has
  no document. One of the two must be set.
- jobs.type allows 'answers'.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_audit_events_user_id_users"),
        "audit_events",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_audit_events_user_id"), "audit_events", ["user_id"], unique=False)
    op.alter_column("audit_events", "document_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f("ck_audit_events_document_or_user"),
        "audit_events",
        "document_id IS NOT NULL OR user_id IS NOT NULL",
    )
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_type_valid"), "jobs", "type IN ('analyze', 'render', 'ping', 'answers')"
    )


def downgrade() -> None:
    # Rows that only the new schema allows go first: answers jobs and profile events.
    op.execute("DELETE FROM jobs WHERE type = 'answers'")
    op.drop_constraint(op.f("ck_jobs_type_valid"), "jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_jobs_type_valid"), "jobs", "type IN ('analyze', 'render', 'ping')"
    )
    op.execute("DELETE FROM audit_events WHERE document_id IS NULL")
    op.drop_constraint(op.f("ck_audit_events_document_or_user"), "audit_events", type_="check")
    op.alter_column("audit_events", "document_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_index(op.f("ix_audit_events_user_id"), table_name="audit_events")
    op.drop_constraint(op.f("fk_audit_events_user_id_users"), "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "user_id")
