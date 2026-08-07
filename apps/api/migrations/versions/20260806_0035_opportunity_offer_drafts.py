"""opportunity_offer_drafts durable editable offer draft (G-09-A)

Revision ID: 20260806_0035
Revises: 20260806_0034
Create Date: 2026-08-06 12:00:00.000000

Persist one human-editable offer draft per tenant+dossier, seeded from the
calculated opportunity ``draft_offer``. Recalculation of analysis never
overwrites this row; optimistic concurrency via version/etag.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0035"
down_revision: str | None = "20260806_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "opportunity_offer_drafts"


def _enable_rls(table: str) -> None:
    """Match canonical tenant-table pattern (ENABLE+FORCE RLS, policy, oracle_app grants)."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        f"""
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO oracle_app;
        END IF; END $$
        """
    )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("etag", sa.String(length=80), nullable=False, server_default='W/"ood-v1"'),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_edited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_ood_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            ondelete="CASCADE",
            name="fk_ood_dossier_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id", "tenant_id"],
            ["ai_artifacts.id", "ai_artifacts.tenant_id"],
            ondelete="RESTRICT",
            name="fk_ood_source_artifact_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "last_edited_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_ood_editor_membership",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_opportunity_offer_drafts_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "dossier_id", name="uq_opportunity_offer_drafts_tenant_dossier"
        ),
        sa.CheckConstraint("version >= 1", name="ood_version_positive"),
        sa.CheckConstraint("jsonb_typeof(content) = 'object'", name="ood_content_object"),
    )
    op.create_index("ix_ood_tenant_dossier", TABLE, ["tenant_id", "dossier_id"])
    op.create_index("ix_ood_tenant_artifact", TABLE, ["tenant_id", "source_artifact_id"])
    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_ood_tenant_artifact", table_name=TABLE)
    op.drop_index("ix_ood_tenant_dossier", table_name=TABLE)
    op.drop_table(TABLE)
