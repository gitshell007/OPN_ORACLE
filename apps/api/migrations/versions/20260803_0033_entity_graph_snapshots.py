"""entity_graph_snapshots durable memory for ficha 360 graph

Revision ID: 20260803_0033
Revises: 20260802_0032
Create Date: 2026-08-03 16:20:00.000000

Persist the societal graph already computed by entity-intel so a tenant can
re-open the last map with a capture date without re-hitting Signal. Incomplete
graphs (truncated / depth-capped) are stored with an explicit completeness flag.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0033"
down_revision: str | None = "20260802_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "entity_graph_snapshots"


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
        sa.Column("entity_name", sa.String(length=300), nullable=False),
        sa.Column("entity_kind", sa.String(length=20), nullable=False),
        sa.Column("normalized_name", sa.String(length=300), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column(
            "active_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("completeness", sa.String(length=20), nullable=False),
        sa.Column(
            "incompleteness_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="signal_live"),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_entity_graph_snapshots_id_tenant"),
        sa.CheckConstraint(
            "entity_kind IN ('company','person')",
            name="entity_graph_snapshot_kind",
        ),
        sa.CheckConstraint("depth BETWEEN 1 AND 2", name="entity_graph_snapshot_depth"),
        sa.CheckConstraint(
            "completeness IN ('complete','incomplete')",
            name="entity_graph_snapshot_completeness",
        ),
        sa.CheckConstraint("node_count >= 0", name="entity_graph_snapshot_nodes"),
        sa.CheckConstraint("edge_count >= 0", name="entity_graph_snapshot_edges"),
        sa.CheckConstraint(
            "octet_length(content_hash)=32",
            name="entity_graph_snapshot_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload)='object'",
            name="entity_graph_snapshot_payload",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(incompleteness_reasons)='array'",
            name="entity_graph_snapshot_reasons",
        ),
    )
    op.create_index(
        "ix_entity_graph_snapshots_lookup",
        TABLE,
        ["tenant_id", "normalized_name", "entity_kind", "captured_at"],
    )
    op.create_index(
        "ix_entity_graph_snapshots_hash",
        TABLE,
        ["tenant_id", "content_hash"],
    )
    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_entity_graph_snapshots_hash", table_name=TABLE)
    op.drop_index("ix_entity_graph_snapshots_lookup", table_name=TABLE)
    op.drop_table(TABLE)
