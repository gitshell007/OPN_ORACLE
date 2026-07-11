"""platform backup control plane

Revision ID: 20260711_0011
Revises: 20260711_0010
Create Date: 2026-07-11 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_0011"
down_revision: str | None = "20260711_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_global_audit_guard(*, include_backups: bool) -> None:
    backup_clause = " AND p_action NOT LIKE 'platform.backup.%'" if include_backups else ""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION oracle_append_global_audit(
          p_action varchar, p_resource_type varchar, p_result varchar,
          p_actor_id uuid, p_resource_id uuid, p_metadata jsonb,
          p_request_id varchar, p_correlation_id varchar
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          IF p_action NOT LIKE 'auth.%'
             AND p_action NOT LIKE 'platform.bootstrap.%'{backup_clause} THEN
            RAISE EXCEPTION 'global audit action not allowed';
          END IF;
          IF p_result NOT IN ('success','denied','failure') THEN
            RAISE EXCEPTION 'invalid audit result';
          END IF;
          IF p_actor_id IS DISTINCT FROM
             NULLIF(current_setting('app.actor_id', true), '')::uuid THEN
            RAISE EXCEPTION 'audit actor mismatch';
          END IF;
          INSERT INTO public.audit_events
            (id, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
             result, request_id, correlation_id, metadata, created_at)
          VALUES
            (gen_random_uuid(), NULL, CASE WHEN p_actor_id IS NULL THEN 'service' ELSE 'user' END,
             p_actor_id, left(p_action,150), left(p_resource_type,100), p_resource_id,
             p_result, left(p_request_id,100), left(p_correlation_id,100),
             COALESCE(p_metadata,'{{}}'::jsonb), now());
        END $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "platform_backup_artifacts",
        sa.Column("backup_name", sa.String(length=200), nullable=False),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("backup_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "status IN ('available','expired','missing')",
            name="ck_platform_backup_artifacts_backup_status",
        ),
        sa.CheckConstraint(
            "origin IN ('manual','scheduled','imported')",
            name="ck_platform_backup_artifacts_backup_origin",
        ),
        sa.CheckConstraint("size_bytes >= 0", name="ck_platform_backup_artifacts_backup_size"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_platform_backup_artifacts_backup_sha256"
        ),
        sa.CheckConstraint(
            "relative_path !~ '(^/|(^|/)[.][.](/|$))'",
            name="ck_platform_backup_artifacts_backup_relative_path",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_backup_artifacts"),
        sa.UniqueConstraint("backup_name", name="uq_platform_backup_name"),
        sa.UniqueConstraint("relative_path", name="uq_platform_backup_relative_path"),
    )
    op.create_index(
        "ix_platform_backup_created", "platform_backup_artifacts", ["backup_created_at"]
    )
    op.create_table(
        "platform_backup_operations",
        sa.Column("operation_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=100)),
        sa.Column("correlation_id", sa.String(length=100)),
        sa.Column("worker_id", sa.String(length=100)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "result_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "operation_type IN ('manual_backup','scheduled_backup','restore')",
            name="ck_platform_backup_operations_backup_operation_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued','awaiting_approval','running','succeeded','failed','cancelled')",
            name="ck_platform_backup_operations_backup_operation_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= 20",
            name="ck_platform_backup_operations_backup_operation_attempts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_metadata)='object'",
            name="ck_platform_backup_operations_backup_result_object",
        ),
        sa.CheckConstraint(
            "(status='running') = (worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_platform_backup_operations_backup_operation_lease",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["platform_backup_artifacts.id"],
            name="fk_backup_ops_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"],
            ["users.id"],
            name="fk_backup_ops_requested_user",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_platform_backup_operations"),
        sa.UniqueConstraint("idempotency_key", name="uq_platform_backup_operation_idempotency"),
    )
    op.create_index(
        "ix_platform_backup_operation_queue",
        "platform_backup_operations",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_platform_backup_one_active_restore",
        "platform_backup_operations",
        ["operation_type"],
        unique=True,
        postgresql_where=sa.text(
            "operation_type='restore' AND status IN ('awaiting_approval','running')"
        ),
    )
    _replace_global_audit_guard(include_backups=True)
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE ON platform_backup_artifacts,
            platform_backup_operations TO oracle_app;
        END IF; END $$
        """
    )


def downgrade() -> None:
    _replace_global_audit_guard(include_backups=False)
    op.drop_index("uq_platform_backup_one_active_restore", table_name="platform_backup_operations")
    op.drop_index("ix_platform_backup_operation_queue", table_name="platform_backup_operations")
    op.drop_table("platform_backup_operations")
    op.drop_index("ix_platform_backup_created", table_name="platform_backup_artifacts")
    op.drop_table("platform_backup_artifacts")
