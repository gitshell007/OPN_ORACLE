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
    op.drop_constraint("uq_ai_audit_job_agent", "ai_audit_logs", type_="unique")
    op.create_index(
        "ix_ai_audit_job_agent",
        "ai_audit_logs",
        ["tenant_id", "background_job_id", "agent", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_audit_job_agent", table_name="ai_audit_logs")
    op.create_unique_constraint(
        "uq_ai_audit_job_agent",
        "ai_audit_logs",
        ["tenant_id", "background_job_id", "agent"],
    )
