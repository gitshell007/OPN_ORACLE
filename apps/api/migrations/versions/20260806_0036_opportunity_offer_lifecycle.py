"""opportunity_offer_lifecycles durable commercial offer tracking (G-10)

Revision ID: 20260806_0036
Revises: 20260806_0035
Create Date: 2026-08-06 13:30:00.000000

Persist the commercial offer lifecycle bound to an opportunity (CRM status remains
on opportunities.status). Tenant-scoped, RLS, optimistic concurrency via version.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260806_0036"
down_revision: str | None = "20260806_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "opportunity_offer_lifecycles"


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
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="preparando"),
        sa.Column("importe_ofertado", sa.Numeric(14, 2), nullable=True),
        sa.Column("baja_porcentaje", sa.Numeric(5, 2), nullable=True),
        sa.Column(
            "lotes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("garantia_provisional", sa.Numeric(14, 2), nullable=True),
        sa.Column("fecha_mesa", sa.Date(), nullable=True),
        sa.Column("motivo_exclusion", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_edited_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_ool_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            ondelete="CASCADE",
            name="fk_ool_dossier_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "tenant_id"],
            ["opportunities.id", "opportunities.tenant_id"],
            ondelete="CASCADE",
            name="fk_ool_opportunity_tenant",
        ),
        # dossier_id is denormalized for tenant queries; consistency with
        # opportunity.dossier_id is enforced in the service layer (no unique
        # constraint on opportunities(id,dossier_id,tenant_id) to reference).
        sa.ForeignKeyConstraint(
            ["tenant_id", "last_edited_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_ool_editor_membership",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_opportunity_offer_lifecycles_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "opportunity_id",
            name="uq_opportunity_offer_lifecycles_tenant_opportunity",
        ),
        sa.CheckConstraint("version >= 1", name="ool_version_positive"),
        sa.CheckConstraint(
            "status IN ("
            "'preparando','presentada','en_evaluacion','adjudicada','perdida','excluida'"
            ")",
            name="ool_status",
        ),
        sa.CheckConstraint(
            "importe_ofertado IS NULL OR importe_ofertado >= 0",
            name="ool_importe_non_negative",
        ),
        sa.CheckConstraint(
            "baja_porcentaje IS NULL OR (baja_porcentaje >= 0 AND baja_porcentaje <= 100)",
            name="ool_baja_range",
        ),
        sa.CheckConstraint(
            "garantia_provisional IS NULL OR garantia_provisional >= 0",
            name="ool_garantia_non_negative",
        ),
        sa.CheckConstraint("jsonb_typeof(lotes) = 'array'", name="ool_lotes_array"),
        sa.CheckConstraint(
            "("
            "status = 'excluida' AND motivo_exclusion IS NOT NULL "
            "AND char_length(btrim(motivo_exclusion)) >= 1"
            ") OR ("
            "status <> 'excluida' AND (motivo_exclusion IS NULL OR btrim(motivo_exclusion) = '')"
            ")",
            name="ool_motivo_exclusion_conditional",
        ),
    )
    op.create_index(
        "ix_ool_tenant_dossier",
        TABLE,
        ["tenant_id", "dossier_id"],
    )
    op.create_index(
        "ix_ool_tenant_opportunity",
        TABLE,
        ["tenant_id", "opportunity_id"],
    )
    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_ool_tenant_opportunity", table_name=TABLE)
    op.drop_index("ix_ool_tenant_dossier", table_name=TABLE)
    op.drop_table(TABLE)
