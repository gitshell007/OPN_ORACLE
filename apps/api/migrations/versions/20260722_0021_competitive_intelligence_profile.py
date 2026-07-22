"""add competitive intelligence profile to dossiers

Revision ID: 20260722_0021
Revises: 20260717_0020
Create Date: 2026-07-22 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260722_0021"
down_revision: str | None = "20260717_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "strategic_dossiers",
        sa.Column(
            "profile_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_strategic_dossiers_dossier_profile_config"),
        "strategic_dossiers",
        "jsonb_typeof(profile_config)='object'",
    )
    op.add_column(
        "dossier_procurement_items",
        sa.Column("linked_opportunity_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_dossier_procurement_items_opportunity_tenant",
        "dossier_procurement_items",
        "opportunities",
        ["linked_opportunity_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_dossier_procurement_items_opportunity_tenant",
        "dossier_procurement_items",
        type_="foreignkey",
    )
    op.drop_column("dossier_procurement_items", "linked_opportunity_id")
    op.drop_constraint(
        op.f("ck_strategic_dossiers_dossier_profile_config"),
        "strategic_dossiers",
        type_="check",
    )
    op.drop_column("strategic_dossiers", "profile_config")
