"""expand dossier_memory_profiles + memory_retrieval_snapshots (MDEV-04)

Revision ID: 20260802_0029
Revises: 20260731_0028
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_dmp_tenant"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["integration_connections.id", "integration_connections.tenant_id"],
            ondelete="SET NULL",
            name="fk_dmp_connection_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "dossier_id", "connection_id", name="uq_dossier_memory_profile_scope"
        ),
        sa.CheckConstraint("mode IN ('disabled','shadow','augment')", name="dmp_mode_valid"),
        sa.CheckConstraint("version >= 1", name="dmp_version_positive"),
        sa.CheckConstraint("jsonb_typeof(profile_config) = 'object'", name="dmp_config_object"),
    )
    op.create_index("ix_dmp_tenant_dossier", "dossier_memory_profiles", ["tenant_id", "dossier_id"])

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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE", name="fk_mrs_tenant"),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name="mrs_payload_object"),
        sa.CheckConstraint("octet_length(context_hash) = 32", name="mrs_hash_length"),
    )
    op.create_index(
        "ix_mrs_tenant_dossier", "memory_retrieval_snapshots", ["tenant_id", "dossier_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_mrs_tenant_dossier", table_name="memory_retrieval_snapshots")
    op.drop_table("memory_retrieval_snapshots")
    op.drop_index("ix_dmp_tenant_dossier", table_name="dossier_memory_profiles")
    op.drop_table("dossier_memory_profiles")
