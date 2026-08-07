"""expand dossier_memory_profiles + memory_retrieval_snapshots (MDEV-04)

Revision ID: 20260802_0029
Revises: 20260731_0028

Expand-only: new tenant-scoped tables with FORCE RLS + runtime grants.
Verified not applied on Dev (oracle_dev alembic at 20260726_0026) nor Prod
at the time of this REWORK-3 fix — safe to amend 0029 in place.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0029"
down_revision: str | None = "20260731_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "dossier_memory_profiles",
    "memory_retrieval_snapshots",
)


def _enable_rls(table: str) -> None:
    """Canonical tenant RLS + oracle_app DML grants (same pattern as 0028)."""
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


def _drop_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"""
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          REVOKE SELECT,INSERT,UPDATE,DELETE ON {table} FROM oracle_app;
        END IF; END $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "dossier_memory_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="disabled"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("etag", sa.String(length=80), nullable=False, server_default='W/"dmp-v1"'),
        sa.Column(
            "profile_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(length=40), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_dmp_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            ondelete="CASCADE",
            name="fk_dmp_dossier_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["integration_connections.id", "integration_connections.tenant_id"],
            ondelete="SET NULL",
            name="fk_dmp_connection_tenant",
        ),
        sa.CheckConstraint("mode IN ('disabled','shadow','augment')", name="dmp_mode_valid"),
        sa.CheckConstraint("version >= 1", name="dmp_version_positive"),
        sa.CheckConstraint("jsonb_typeof(profile_config) = 'object'", name="dmp_config_object"),
    )
    op.create_index("ix_dmp_tenant_dossier", "dossier_memory_profiles", ["tenant_id", "dossier_id"])
    op.create_index(
        "uq_dmp_scope_nulls",
        "dossier_memory_profiles",
        ["tenant_id", "dossier_id", "connection_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "memory_retrieval_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("correlation_id", sa.String(length=80), nullable=False),
        sa.Column("context_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("usage_log_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_mrs_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            ondelete="CASCADE",
            name="fk_mrs_dossier_tenant",
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="mrs_payload_object"),
        sa.CheckConstraint("octet_length(context_hash) = 32", name="mrs_hash_length"),
    )
    op.create_index(
        "ix_mrs_tenant_dossier", "memory_retrieval_snapshots", ["tenant_id", "dossier_id"]
    )

    for table in TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        _drop_rls(table)
    op.drop_index("ix_mrs_tenant_dossier", table_name="memory_retrieval_snapshots")
    op.drop_table("memory_retrieval_snapshots")
    op.drop_index(
        "uq_dmp_scope_nulls",
        table_name="dossier_memory_profiles",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index("ix_dmp_tenant_dossier", table_name="dossier_memory_profiles")
    op.drop_table("dossier_memory_profiles")
