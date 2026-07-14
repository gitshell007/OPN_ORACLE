"""Allow retry audit history per AI job.

Revision ID: 20260714_0018
Revises: 20260714_0017
Create Date: 2026-07-14 12:38:00.000000
"""

from alembic import op

revision = "20260714_0018"
down_revision = "20260714_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ai_audit_logs DROP CONSTRAINT IF EXISTS uq_ai_audit_job_agent")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_audit_job_agent
        ON ai_audit_logs (tenant_id, background_job_id, agent, created_at)
        """
    )


def downgrade() -> None:
    # Do not delete immutable AI audit evidence to recreate the old uniqueness contract.
    # Once retries have produced multiple rows per (tenant, job, agent), the prior
    # constraint is not safely restorable. Keeping the lookup index preserves runtime
    # behavior and allows test/restore cycles to downgrade without data loss.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_ai_audit_job_agent
        ON ai_audit_logs (tenant_id, background_job_id, agent, created_at)
        """
    )
