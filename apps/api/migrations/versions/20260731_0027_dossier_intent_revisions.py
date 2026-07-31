"""expand dossier intent revisions, requirements and offerings

Revision ID: 20260731_0027
Revises: 20260726_0026
Create Date: 2026-07-31 18:00:00.000000

Expand-only (MEMSOL-03): new tables + nullable current_intent_revision_id.
No backfill of profile_config in this revision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0027"
down_revision: str | None = "20260726_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLES = (
    "dossier_intent_revisions",
    "intelligence_requirements",
    "dossier_offerings",
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
        "dossier_intent_revisions",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_key", sa.String(length=40), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column(
            "structured_spec",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "source_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("proposed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("accepted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False),
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
            "status IN ('draft','accepted','superseded','rejected')",
            name="dossier_intent_revision_status",
        ),
        sa.CheckConstraint(
            "schema_key IN ('market','procurement','research','competitive-intelligence','custom')",
            name="dossier_intent_revision_schema_key",
        ),
        sa.CheckConstraint(
            "schema_version ~ '^v[0-9]+$'",
            name="dossier_intent_revision_schema_version",
        ),
        sa.CheckConstraint("version >= 1", name="dossier_intent_revision_version"),
        sa.CheckConstraint("row_version >= 1", name="dossier_intent_revision_row_version"),
        sa.CheckConstraint(
            "char_length(request_text) BETWEEN 1 AND 20000",
            name="dossier_intent_revision_request_text",
        ),
        sa.CheckConstraint(
            "char_length(content_hash)=64 AND content_hash ~ '^[a-f0-9]{64}$'",
            name="dossier_intent_revision_content_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(structured_spec)='object'",
            name="dossier_intent_revision_structured_spec",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_refs)='array'",
            name="dossier_intent_revision_source_refs",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dossier_intent_revisions_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dossier_intent_revisions_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "version",
            name="uq_dossier_intent_revisions_version",
        ),
    )
    op.create_index(
        "ix_dossier_intent_revisions_dossier_updated",
        "dossier_intent_revisions",
        ["tenant_id", "dossier_id", "updated_at"],
    )
    op.create_index(
        "uq_dossier_intent_revisions_one_accepted",
        "dossier_intent_revisions",
        ["tenant_id", "dossier_id"],
        unique=True,
        postgresql_where=sa.text("status = 'accepted'"),
    )

    op.create_table(
        "intelligence_requirements",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("intent_revision_id", sa.UUID(), nullable=True),
        sa.Column("class", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("decision_to_support", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exclusions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "success_criteria",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("alignment_state", sa.String(length=20), nullable=False),
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
            "class IN ("
            "'market_scan','competitive_watch','procurement_fit',"
            "'actor_monitor','research_question','risk_watch','custom'"
            ")",
            name="intelligence_requirement_class",
        ),
        sa.CheckConstraint(
            "priority IN ('low','medium','high','critical')",
            name="intelligence_requirement_priority",
        ),
        sa.CheckConstraint(
            "status IN ('active','paused','needs_review','retired')",
            name="intelligence_requirement_status",
        ),
        sa.CheckConstraint(
            "alignment_state IN ('aligned','needs_review','overridden')",
            name="intelligence_requirement_alignment",
        ),
        sa.CheckConstraint(
            "char_length(question) BETWEEN 1 AND 2000",
            name="intelligence_requirement_question",
        ),
        sa.CheckConstraint(
            "char_length(decision_to_support) <= 2000",
            name="intelligence_requirement_decision",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scope)='object'",
            name="intelligence_requirement_scope",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(exclusions)='object'",
            name="intelligence_requirement_exclusions",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(success_criteria)='array'",
            name="intelligence_requirement_success_criteria",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_intelligence_requirements_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["intent_revision_id", "tenant_id"],
            ["dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"],
            name="fk_intelligence_requirements_intent_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_intelligence_requirements_id_tenant"),
    )
    op.create_index(
        "ix_intelligence_requirements_dossier_status",
        "intelligence_requirements",
        ["tenant_id", "dossier_id", "status", "updated_at"],
    )

    op.create_table(
        "dossier_offerings",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("intent_revision_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "taxonomies",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False),
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
            "status IN ('active','retired')",
            name="dossier_offering_status",
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 300",
            name="dossier_offering_name",
        ),
        sa.CheckConstraint(
            "char_length(description) <= 5000",
            name="dossier_offering_description",
        ),
        sa.CheckConstraint("jsonb_typeof(aliases)='array'", name="dossier_offering_aliases"),
        sa.CheckConstraint(
            "jsonb_typeof(taxonomies)='object'",
            name="dossier_offering_taxonomies",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_dossier_offerings_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["intent_revision_id", "tenant_id"],
            ["dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"],
            name="fk_dossier_offerings_intent_tenant",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_dossier_offerings_id_tenant"),
    )
    op.create_index(
        "ix_dossier_offerings_dossier_status",
        "dossier_offerings",
        ["tenant_id", "dossier_id", "status", "updated_at"],
    )

    op.add_column(
        "strategic_dossiers",
        sa.Column("current_intent_revision_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_dossiers_current_intent_revision_tenant",
        "strategic_dossiers",
        "dossier_intent_revisions",
        ["current_intent_revision_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="SET NULL",
    )

    for table in TABLES:
        _enable_rls(table)


def downgrade() -> None:
    op.drop_constraint(
        "fk_dossiers_current_intent_revision_tenant",
        "strategic_dossiers",
        type_="foreignkey",
    )
    op.drop_column("strategic_dossiers", "current_intent_revision_id")
    op.drop_table("dossier_offerings")
    op.drop_table("intelligence_requirements")
    op.drop_index(
        "uq_dossier_intent_revisions_one_accepted",
        table_name="dossier_intent_revisions",
    )
    op.drop_index(
        "ix_dossier_intent_revisions_dossier_updated",
        table_name="dossier_intent_revisions",
    )
    op.drop_table("dossier_intent_revisions")
