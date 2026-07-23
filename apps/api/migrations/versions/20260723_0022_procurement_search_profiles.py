"""add tenant-scoped procurement search profiles

Revision ID: 20260723_0022
Revises: 20260722_0021
Create Date: 2026-07-23 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260723_0022"
down_revision: str | None = "20260722_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A tenant-level wizard has no dossier. Composite FKs remain tenant-safe:
    # PostgreSQL simply does not check them when dossier_id is NULL.
    op.alter_column("ai_artifacts", "dossier_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("ai_context_snapshots", "dossier_id", existing_type=sa.UUID(), nullable=True)

    op.create_table(
        "procurement_search_profiles",
        sa.Column("original_description", sa.Text(), nullable=False),
        sa.Column(
            "comparables",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("accepted_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("accepted_plan_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ai_artifact_id", sa.UUID(), nullable=False),
        sa.Column("tender_search_id", sa.String(length=120), nullable=True),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "last_accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            "char_length(original_description) BETWEEN 2 AND 5000",
            name="procurement_search_profile_description",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(comparables)='array'",
            name="procurement_search_profile_comparables",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(accepted_plan)='object'",
            name="procurement_search_profile_plan",
        ),
        sa.CheckConstraint(
            "octet_length(accepted_plan_hash)=32",
            name="procurement_search_profile_hash",
        ),
        sa.CheckConstraint("version >= 1", name="procurement_search_profile_version"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["ai_artifact_id", "tenant_id"],
            ["ai_artifacts.id", "ai_artifacts.tenant_id"],
            name="fk_procurement_search_profiles_artifact_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "accepted_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_procurement_search_profiles_acceptor_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            name="uq_procurement_search_profiles_id_tenant",
        ),
    )
    op.create_index(
        "ix_procurement_search_profiles_tenant_accepted",
        "procurement_search_profiles",
        ["tenant_id", "last_accepted_at"],
    )
    op.execute("ALTER TABLE procurement_search_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE procurement_search_profiles FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON procurement_search_profiles "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON procurement_search_profiles TO oracle_app;
        END IF; END $$
        """
    )


def downgrade() -> None:
    op.drop_table("procurement_search_profiles")
    # A downgrade must not manufacture dossier ownership. Fail clearly if rows
    # created by the tenant-level wizard would violate the old contract.
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM ai_artifacts WHERE dossier_id IS NULL)
             OR EXISTS (SELECT 1 FROM ai_context_snapshots WHERE dossier_id IS NULL)
          THEN
            RAISE EXCEPTION
              'Cannot downgrade: dossierless AI rows exist; remove them through an audited process';
          END IF;
        END $$
        """
    )
    op.alter_column("ai_context_snapshots", "dossier_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("ai_artifacts", "dossier_id", existing_type=sa.UUID(), nullable=False)
