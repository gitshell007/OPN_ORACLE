"""expand dossier conversations and messages for Preguntar a Oracle

Revision ID: 20260731_0028
Revises: 20260731_0027
Create Date: 2026-07-31 20:00:00.000000

Expand-only (MEMSOL-06): new tables for durable Q&A. No data backfill.
Custom report briefs (MEMSOL-07) reuse existing reports table via options JSON.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0028"
down_revision: str | None = "20260731_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "dossier_conversations",
    "dossier_messages",
)


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
        "dossier_conversations",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("intent_revision_id", sa.UUID(), nullable=True),
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
            "status IN ('open','archived')",
            name="dossier_conversation_status",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 0 AND 300",
            name="dossier_conversation_title",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dossier_conversations_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_dossier_conversations_creator_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intent_revision_id", "tenant_id"],
            ["dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"],
            name="fk_dossier_conversations_intent_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dossier_conversations_id_tenant"),
        sa.UniqueConstraint(
            "id",
            "dossier_id",
            "tenant_id",
            name="uq_dossier_conversations_id_dossier_tenant",
        ),
    )
    op.create_index(
        "ix_dossier_conversations_dossier_updated",
        "dossier_conversations",
        ["tenant_id", "dossier_id", "updated_at"],
    )

    op.create_table(
        "dossier_messages",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "answer_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "coverage_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("background_job_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
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
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="dossier_message_status",
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant','system')",
            name="dossier_message_role",
        ),
        sa.CheckConstraint("sequence >= 1", name="dossier_message_sequence"),
        sa.CheckConstraint(
            "char_length(content_text) BETWEEN 0 AND 50000",
            name="dossier_message_content_text",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(coverage_manifest)='object'",
            name="dossier_message_coverage_manifest",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(answer_payload)='object'",
            name="dossier_message_answer_payload",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "dossier_id", "tenant_id"],
            [
                "dossier_conversations.id",
                "dossier_conversations.dossier_id",
                "dossier_conversations.tenant_id",
            ],
            name="fk_dossier_messages_conversation_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dossier_messages_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["background_job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            name="fk_dossier_messages_background_job_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_dossier_messages_creator_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dossier_messages_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "sequence",
            name="uq_dossier_messages_sequence",
        ),
    )
    op.create_index(
        "ix_dossier_messages_conversation_created",
        "dossier_messages",
        ["tenant_id", "conversation_id", "created_at"],
    )
    op.create_index(
        "ix_dossier_messages_status",
        "dossier_messages",
        ["tenant_id", "status", "updated_at"],
    )

    for table in TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.drop_index("ix_dossier_messages_status", table_name="dossier_messages")
    op.drop_index("ix_dossier_messages_conversation_created", table_name="dossier_messages")
    op.drop_table("dossier_messages")
    op.drop_index(
        "ix_dossier_conversations_dossier_updated",
        table_name="dossier_conversations",
    )
    op.drop_table("dossier_conversations")
