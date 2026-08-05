"""expand dossier_surveillance_actions (MDEV-07 provisional)

Revision ID: 20260802_0031
Revises: 20260802_0030
Create Date: 2026-08-02 03:40:00.000000

Expand-only: table for human-confirmed surveillance actions with cadence,
provenance and alignment. FORCE RLS + grants for oracle_app.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260802_0031"
down_revision: str | None = "20260802_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "dossier_surveillance_actions"


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
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("alignment_state", sa.String(length=20), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("offering_id", sa.UUID(), nullable=True),
        sa.Column("requirement_id", sa.UUID(), nullable=True),
        sa.Column("intent_revision_id", sa.UUID(), nullable=True),
        sa.Column("effective_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("confirmed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "manual_overrides",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("watchlist_id", sa.UUID(), nullable=True),
        sa.Column("signal_monitor_id", sa.UUID(), nullable=True),
        sa.Column("procurement_watch_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("degraded_reason", sa.String(length=200), nullable=True),
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
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dsa_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "tenant_id"],
            ["actors.id", "actors.tenant_id"],
            name="fk_dsa_actor_tenant",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dsa_id_tenant"),
        sa.UniqueConstraint("tenant_id", "dossier_id", "dedupe_key", name="uq_dsa_dedupe"),
        sa.CheckConstraint(
            "action_type IN ("
            "'news_mentions','official_publications','actor_tenders',"
            "'offering_tenders','research_digest','no_follow')",
            name="dsa_action_type",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'prepared','active','paused','pending','running','retrying',"
            "'needs_attention','retired')",
            name="dsa_status",
        ),
        sa.CheckConstraint(
            "alignment_state IN ('aligned','needs_review','overridden')",
            name="dsa_alignment",
        ),
        sa.CheckConstraint(
            "cadence IN ('manual','hourly','daily','weekly')",
            name="dsa_cadence",
        ),
        sa.CheckConstraint(
            "origin IN ('user','intake','assistant','signal','system')",
            name="dsa_origin",
        ),
        sa.CheckConstraint("row_version >= 1", name="dsa_row_version_positive"),
        sa.CheckConstraint("retry_count >= 0", name="dsa_retry_nonneg"),
    )
    op.create_index("ix_dsa_tenant_dossier", TABLE, ["tenant_id", "dossier_id"])
    op.create_index("ix_dsa_tenant_next_run", TABLE, ["tenant_id", "next_run_at"])
    op.create_index("ix_dsa_tenant_actor", TABLE, ["tenant_id", "actor_id"])
    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_dsa_tenant_actor", table_name=TABLE)
    op.drop_index("ix_dsa_tenant_next_run", table_name=TABLE)
    op.drop_index("ix_dsa_tenant_dossier", table_name=TABLE)
    op.drop_table(TABLE)
