"""Durable Celery jobs and database schedules.

Revision ID: 20260710_0006
Revises: 20260710_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0006"
down_revision: str | None = "20260710_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("password_reset_tokens", sa.Column("delivery_key", sa.String(200)))
    op.add_column("password_reset_tokens", sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.add_column(
        "password_reset_tokens", sa.Column("delivery_started_at", sa.DateTime(timezone=True))
    )
    op.create_unique_constraint(
        "uq_password_reset_tokens_delivery_key", "password_reset_tokens", ["delivery_key"]
    )
    columns = (
        sa.Column("stage", sa.String(100), nullable=False, server_default="queued"),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column(
            "payload_hash",
            sa.LargeBinary(32),
            nullable=False,
            server_default=sa.text("decode(repeat('00',32),'hex')"),
        ),
        sa.Column(
            "input_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_publish_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_lease_id", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("background_jobs", column)
    op.execute(
        "UPDATE background_jobs SET status=CASE "
        "WHEN status='pending' THEN 'queued' "
        "WHEN status='completed' THEN 'succeeded' ELSE status END"
    )
    op.create_check_constraint(
        "background_job_progress", "background_jobs", "progress BETWEEN 0 AND 100"
    )
    op.create_check_constraint(
        "background_job_attempts", "background_jobs", "attempts >= 0 AND max_attempts >= 1"
    )
    op.create_check_constraint("background_job_version", "background_jobs", "version >= 1")
    op.create_check_constraint(
        "background_job_input_object", "background_jobs", "jsonb_typeof(input_payload) = 'object'"
    )
    op.create_check_constraint(
        "background_job_result_object", "background_jobs", "jsonb_typeof(result_ref) = 'object'"
    )
    op.create_check_constraint(
        "background_job_lease_pair",
        "background_jobs",
        "(execution_lease_id IS NULL) = (lease_expires_at IS NULL)",
    )
    op.create_foreign_key(
        "fk_background_job_requester_membership",
        "background_jobs",
        "tenant_memberships",
        ["tenant_id", "requested_by_user_id"],
        ["tenant_id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "background_job_status",
        "background_jobs",
        "status IN ('queued','running','retrying','succeeded','failed','cancelled')",
    )
    op.create_index(
        "ix_background_jobs_celery_task_id",
        "background_jobs",
        ["celery_task_id"],
        unique=True,
    )
    op.create_index("ix_background_jobs_not_before", "background_jobs", ["status", "not_before"])
    op.create_index("ix_background_jobs_heartbeat", "background_jobs", ["status", "heartbeat_at"])
    op.create_index(
        "ix_background_jobs_lease_expiry",
        "background_jobs",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "job_schedules",
        sa.Column("schedule_key", sa.String(150), nullable=False),
        sa.Column("task_name", sa.String(150), nullable=False),
        sa.Column("queue", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cadence_seconds", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="UTC"),
        sa.Column("schedule_kind", sa.String(20), nullable=False, server_default="interval"),
        sa.Column("local_time", sa.Time(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_job_schedules_id_tenant"),
        sa.UniqueConstraint("tenant_id", "schedule_key", name="uq_job_schedule_key"),
        sa.CheckConstraint("cadence_seconds >= 60", name="job_schedule_cadence"),
        sa.CheckConstraint(
            "schedule_kind IN ('interval','daily','weekly')", name="job_schedule_kind"
        ),
        sa.CheckConstraint(
            "(schedule_kind='interval' AND local_time IS NULL AND weekday IS NULL) OR "
            "(schedule_kind='daily' AND local_time IS NOT NULL AND weekday IS NULL) OR "
            "(schedule_kind='weekly' AND local_time IS NOT NULL AND weekday BETWEEN 0 AND 6)",
            name="job_schedule_wall_clock",
        ),
    )
    op.create_index("ix_job_schedules_due", "job_schedules", ["enabled", "next_run_at"])
    op.execute("ALTER TABLE job_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE job_schedules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON job_schedules USING "
        "(tenant_id=oracle_current_tenant()) WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON job_schedules TO oracle_app;
      END IF; END $$
    """)


def downgrade() -> None:
    op.drop_table("job_schedules")
    op.drop_index("ix_background_jobs_heartbeat", table_name="background_jobs")
    op.drop_index("ix_background_jobs_lease_expiry", table_name="background_jobs")
    op.drop_index("ix_background_jobs_not_before", table_name="background_jobs")
    op.drop_index("ix_background_jobs_celery_task_id", table_name="background_jobs")
    op.drop_constraint(
        "fk_background_job_requester_membership", "background_jobs", type_="foreignkey"
    )
    op.drop_constraint("background_job_attempts", "background_jobs", type_="check")
    op.drop_constraint("background_job_version", "background_jobs", type_="check")
    op.drop_constraint("background_job_input_object", "background_jobs", type_="check")
    op.drop_constraint("background_job_result_object", "background_jobs", type_="check")
    op.drop_constraint("background_job_lease_pair", "background_jobs", type_="check")
    op.drop_constraint("background_job_status", "background_jobs", type_="check")
    op.drop_constraint("background_job_progress", "background_jobs", type_="check")
    for name in (
        "cancel_requested",
        "cancel_requested_at",
        "publish_attempts",
        "last_publish_attempt_at",
        "published_at",
        "execution_lease_id",
        "lease_expires_at",
        "request_id",
        "requested_by_user_id",
        "error_message",
        "heartbeat_at",
        "finished_at",
        "started_at",
        "max_attempts",
        "attempts",
        "not_before",
        "retryable",
        "version",
        "payload_hash",
        "input_payload",
        "celery_task_id",
        "resource_id",
        "resource_type",
        "stage",
    ):
        op.drop_column("background_jobs", name)
    op.drop_constraint(
        "uq_password_reset_tokens_delivery_key", "password_reset_tokens", type_="unique"
    )
    op.drop_column("password_reset_tokens", "delivered_at")
    op.drop_column("password_reset_tokens", "delivery_started_at")
    op.drop_column("password_reset_tokens", "delivery_key")
