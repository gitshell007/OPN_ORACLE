"""report_ai_usage_bindings durable links (MDEV-08)

Revision ID: 20260802_0032
Revises: 20260802_0031
Create Date: 2026-08-02 05:00:00.000000

Expand-only: writer/review usage bindings with tenant unique (report, phase, run_id).
FORCE RLS + grants for oracle_app. Downgrade drops table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0032"
down_revision: str | None = "20260802_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "report_ai_usage_bindings"


def _enable_rls(table: str) -> None:
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
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("task_key", sa.String(length=100), nullable=False),
        sa.Column("runtime_id", sa.String(length=20), nullable=False),
        sa.Column("run_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=150), nullable=False),
        sa.Column(
            "fallback_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("validated_output_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "usage_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attempts_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("null"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["reports.id", "reports.tenant_id"],
            name="fk_report_ai_usage_report_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            name="fk_report_ai_usage_job_tenant",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_report_ai_usage_bindings_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "report_id",
            "phase",
            "run_id",
            name="uq_report_ai_usage_binding_run",
        ),
        sa.CheckConstraint("phase IN ('writer','review','plan')", name="report_ai_usage_phase"),
        sa.CheckConstraint("char_length(run_id) BETWEEN 1 AND 200", name="report_ai_usage_run_id"),
        sa.CheckConstraint(
            "jsonb_typeof(usage_payload)='object'", name="report_ai_usage_payload_object"
        ),
    )
    op.create_index(
        "ix_report_ai_usage_bindings_report",
        TABLE,
        ["tenant_id", "report_id", "phase", "created_at"],
    )
    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_report_ai_usage_bindings_report", table_name=TABLE)
    op.drop_table(TABLE)
