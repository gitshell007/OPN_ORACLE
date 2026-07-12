"""preserve audit events when a dossier is permanently deleted

Revision ID: 20260712_0013
Revises: 20260711_0012
Create Date: 2026-07-12 02:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260712_0013"
down_revision: str | None = "20260711_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_audit_events_dossier_tenant", "audit_events", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_events_dossier_tenant",
        "audit_events",
        "strategic_dossiers",
        ["dossier_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="SET NULL (dossier_id)",
    )


def downgrade() -> None:
    op.drop_constraint("fk_audit_events_dossier_tenant", "audit_events", type_="foreignkey")
    op.create_foreign_key(
        "fk_audit_events_dossier_tenant",
        "audit_events",
        "strategic_dossiers",
        ["dossier_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
