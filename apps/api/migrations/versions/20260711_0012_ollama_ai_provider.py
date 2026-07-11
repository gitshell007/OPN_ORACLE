"""allow local and Signal-governed providers in tenant AI policy

Revision ID: 20260711_0012
Revises: 20260711_0011
Create Date: 2026-07-11 22:15:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260711_0012"
down_revision: str | None = "20260711_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_ai_tenant_policies_ai_policy_provider", "ai_tenant_policies", type_="check"
    )
    op.create_check_constraint(
        "ck_ai_tenant_policies_ai_policy_provider",
        "ai_tenant_policies",
        "provider IN ('disabled','mock','ollama','signal')",
    )


def downgrade() -> None:
    op.execute(
        "UPDATE ai_tenant_policies SET provider='disabled' WHERE provider IN ('ollama','signal')"
    )
    op.drop_constraint(
        "ck_ai_tenant_policies_ai_policy_provider", "ai_tenant_policies", type_="check"
    )
    op.create_check_constraint(
        "ck_ai_tenant_policies_ai_policy_provider",
        "ai_tenant_policies",
        "provider IN ('disabled','mock')",
    )
