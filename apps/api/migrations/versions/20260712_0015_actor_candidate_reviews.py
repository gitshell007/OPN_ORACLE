"""persist actor candidate reviews

Revision ID: 20260712_0015
Revises: 20260712_0014
Create Date: 2026-07-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260712_0015"
down_revision: str | None = "20260712_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "actor_candidate_reviews",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("canonical_key", sa.String(length=320), nullable=False),
        sa.Column("candidate_name", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_signal_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
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
            "status IN ('dismissed','imported')", name="actor_candidate_review_status"
        ),
        sa.CheckConstraint("version >= 1", name="actor_candidate_review_version_positive"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_actor_candidate_reviews_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_actor_candidate_reviews_reviewer_membership",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_actor_candidate_reviews_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "dossier_id", "canonical_key", name="uq_actor_candidate_review_key"
        ),
    )
    op.create_index(
        "ix_actor_candidate_reviews_dossier_status",
        "actor_candidate_reviews",
        ["tenant_id", "dossier_id", "status"],
    )
    op.execute("ALTER TABLE actor_candidate_reviews ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE actor_candidate_reviews FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON actor_candidate_reviews "
        "USING (tenant_id=oracle_current_tenant()) "
        "WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON actor_candidate_reviews TO oracle_app;
        END IF; END $$
        """
    )


def downgrade() -> None:
    op.drop_table("actor_candidate_reviews")
