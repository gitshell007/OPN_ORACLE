"""platform source activity log for official gazettes

Revision ID: 20260726_0026
Revises: 20260725_0025
Create Date: 2026-07-26 13:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260726_0026"
down_revision: str | None = "20260725_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_source_activity",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("source_key", sa.String(length=40), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "section_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("official_identifier", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            "source_key IN ('borme', 'boe')",
            name="platform_source_activity_source",
        ),
        sa.CheckConstraint(
            "status IN ('published', 'not_published', 'error')",
            name="platform_source_activity_status",
        ),
        sa.CheckConstraint("item_count >= 0", name="platform_source_activity_item_count"),
        sa.UniqueConstraint(
            "source_key",
            "activity_date",
            name="uq_platform_source_activity_day",
        ),
    )
    op.create_index(
        "ix_platform_source_activity_checked",
        "platform_source_activity",
        ["checked_at"],
    )
    op.create_index(
        "ix_platform_source_activity_source_date",
        "platform_source_activity",
        ["source_key", "activity_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_source_activity_source_date", table_name="platform_source_activity")
    op.drop_index("ix_platform_source_activity_checked", table_name="platform_source_activity")
    op.drop_table("platform_source_activity")
