"""add dossier procurement pinned items

Revision ID: 20260714_0018
Revises: 20260714_0017
Create Date: 2026-07-14 18:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260714_0018"
down_revision: str | None = "20260714_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dossier_procurement_items",
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("folder_id", sa.String(length=240), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_url", sa.String(length=1500), nullable=True),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pinned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
        sa.CheckConstraint("kind IN ('tender','award')", name="dossier_procurement_item_kind"),
        sa.CheckConstraint("jsonb_typeof(snapshot)='object'", name="procurement_snapshot_object"),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dossier_procurement_items_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "tenant_id"],
            ["evidence.id", "evidence.tenant_id"],
            name="fk_dossier_procurement_items_evidence_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "pinned_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_dossier_procurement_items_pinner_membership",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dossier_procurement_items_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "kind",
            "folder_id",
            name="uq_dossier_procurement_item_folder",
        ),
    )
    op.create_index(
        "ix_dossier_procurement_items_dossier",
        "dossier_procurement_items",
        ["tenant_id", "dossier_id"],
    )
    op.execute("ALTER TABLE dossier_procurement_items ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE dossier_procurement_items FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON dossier_procurement_items "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON dossier_procurement_items TO oracle_app;
        END IF; END $$
        """
    )


def downgrade() -> None:
    op.drop_index("ix_dossier_procurement_items_dossier", table_name="dossier_procurement_items")
    op.drop_table("dossier_procurement_items")
