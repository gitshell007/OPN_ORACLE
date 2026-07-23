"""add tenant-scoped procurement search feedback

Revision ID: 20260723_0023
Revises: 20260723_0022
Create Date: 2026-07-23 23:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0023"
down_revision: str | None = "20260723_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "procurement_search_feedback",
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("folder_id", sa.String(length=240), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=True),
        sa.Column("note", sa.Text(), server_default="", nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("tender_title", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "tender_cpvs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(folder_id) BETWEEN 1 AND 240",
            name="procurement_search_feedback_folder",
        ),
        sa.CheckConstraint(
            "plan_version >= 1",
            name="procurement_search_feedback_plan_version",
        ),
        sa.CheckConstraint(
            "verdict IN ('relevant','not_relevant')",
            name="procurement_search_feedback_verdict",
        ),
        sa.CheckConstraint(
            "(verdict='relevant' AND reason IS NULL) OR "
            "(verdict='not_relevant' AND reason IN "
            "('wrong_sector','amount','region','buyer','other'))",
            name="procurement_search_feedback_reason",
        ),
        sa.CheckConstraint(
            "char_length(note) <= 2000",
            name="procurement_search_feedback_note",
        ),
        sa.CheckConstraint(
            "char_length(tender_title) <= 2000",
            name="procurement_search_feedback_title",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(tender_cpvs)='array'",
            name="procurement_search_feedback_cpvs",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "tenant_id"],
            [
                "procurement_search_profiles.id",
                "procurement_search_profiles.tenant_id",
            ],
            name="fk_procurement_search_feedback_profile_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_procurement_search_feedback_actor_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_procurement_search_feedback_id_tenant",
        ),
    )
    op.create_index(
        "uq_procurement_search_feedback_current",
        "procurement_search_feedback",
        ["tenant_id", "profile_id", "actor_user_id", "folder_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL AND withdrawn_at IS NULL"),
    )
    op.create_index(
        "ix_procurement_search_feedback_profile_updated",
        "procurement_search_feedback",
        ["tenant_id", "profile_id", "updated_at", "id"],
    )
    op.create_index(
        "ix_procurement_search_feedback_digest",
        "procurement_search_feedback",
        ["tenant_id", "profile_id", "plan_version", "verdict", "reason"],
        postgresql_where=sa.text("superseded_at IS NULL AND withdrawn_at IS NULL"),
    )
    op.execute("ALTER TABLE procurement_search_feedback ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE procurement_search_feedback FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON procurement_search_feedback "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON procurement_search_feedback TO oracle_app;
        END IF; END $$
        """
    )


def downgrade() -> None:
    op.drop_table("procurement_search_feedback")
