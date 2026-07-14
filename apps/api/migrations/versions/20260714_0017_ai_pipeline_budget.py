"""raise governed AI output budget for tuned local agents

Revision ID: 20260714_0017
Revises: 20260713_0016
Create Date: 2026-07-14 12:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260714_0017"
down_revision: str | None = "20260713_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "ai_tenant_policies",
        "max_output_tokens",
        existing_type=sa.Integer(),
        server_default=sa.text("6500"),
    )
    op.execute(
        sa.text(
            "UPDATE ai_tenant_policies "
            "SET max_output_tokens = 6500 "
            "WHERE enabled IS TRUE AND provider IN ('signal', 'ollama', 'mock') "
            "AND max_output_tokens < 6500"
        )
    )


def downgrade() -> None:
    op.alter_column(
        "ai_tenant_policies",
        "max_output_tokens",
        existing_type=sa.Integer(),
        server_default=sa.text("2000"),
    )
