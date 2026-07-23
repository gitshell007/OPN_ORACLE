"""add deterministic procurement-search watch memory

Revision ID: 20260724_0024
Revises: 20260723_0023
Create Date: 2026-07-24 01:15:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260724_0024"
down_revision: str | None = "20260723_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rls(table: str) -> None:
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
        "procurement_search_watches",
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("tender_search_id", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "notifications_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("cadence_seconds", sa.Integer(), server_default="900", nullable=False),
        sa.Column("notification_user_id", sa.UUID(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("cadence_seconds >= 900", name="procurement_search_watch_cadence"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["profile_id", "tenant_id"],
            ["procurement_search_profiles.id", "procurement_search_profiles.tenant_id"],
            name="fk_procurement_search_watches_profile_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notification_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_procurement_search_watches_notification_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_procurement_search_watches_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "profile_id", name="uq_procurement_search_watches_profile_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id", "tender_search_id", name="uq_procurement_search_watches_search_tenant"
        ),
    )
    op.create_index(
        "ix_procurement_search_watches_tenant_active",
        "procurement_search_watches",
        ["tenant_id", "enabled", "deleted_at"],
    )
    op.create_table(
        "procurement_search_watch_items",
        sa.Column("watch_id", sa.UUID(), nullable=False),
        sa.Column("folder_id", sa.String(length=300), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_change_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
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
        sa.CheckConstraint(
            "octet_length(content_hash)=32", name="procurement_search_watch_item_hash"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot)='object'", name="procurement_search_watch_item_snapshot"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(last_change_fields)='array'",
            name="procurement_search_watch_item_change_fields",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["watch_id", "tenant_id"],
            ["procurement_search_watches.id", "procurement_search_watches.tenant_id"],
            name="fk_procurement_search_watch_items_watch_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_procurement_search_watch_items_reviewer_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_procurement_search_watch_items_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "watch_id", "folder_id", name="uq_procurement_search_watch_items_folder"
        ),
    )
    op.create_index(
        "ix_procurement_search_watch_items_unreviewed",
        "procurement_search_watch_items",
        ["tenant_id", "watch_id", "reviewed_at"],
    )
    op.create_index(
        "ix_procurement_search_watch_items_retention",
        "procurement_search_watch_items",
        ["tenant_id", "last_seen_at"],
    )
    _rls("procurement_search_watches")
    _rls("procurement_search_watch_items")
    # Existing saved Signal searches become inactive Oracle watches.  They remain silent until a
    # person explicitly enables vigilance, preserving Prompt 78's no-auto-watch boundary.
    op.execute(
        """
        INSERT INTO procurement_search_watches (
          id, tenant_id, profile_id, tender_search_id, name, enabled,
          notifications_enabled, cadence_seconds, created_at, updated_at
        )
        SELECT gen_random_uuid(), p.tenant_id, p.id, p.tender_search_id,
          'Vigilancia guardada', false, false, 900, now(), now()
        FROM procurement_search_profiles p
        WHERE p.tender_search_id IS NOT NULL AND p.tender_search_id <> ''
        """
    )


def downgrade() -> None:
    op.drop_table("procurement_search_watch_items")
    op.drop_table("procurement_search_watches")
