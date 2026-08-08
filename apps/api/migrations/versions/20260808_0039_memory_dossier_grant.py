"""Durable Signal memory dossier grant status (ORA-AUTOGRANT).

Revision ID: 20260808_0039
Revises: 20260808_0038
Create Date: 2026-08-08 12:00:00+00:00

Stores the last result of POST /memory/v1/dossiers/{id}/authorize
(SIG-AUTOGRANT) so Oracle can show honest «pendiente de autorización»
without re-hitting Signal on every read, and without inventing authorized.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260808_0039"
down_revision: str | None = "20260808_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dossier_memory_profiles",
        sa.Column("signal_grant_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "dossier_memory_profiles",
        sa.Column("signal_grant_code", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "dossier_memory_profiles",
        sa.Column("signal_grant_detail", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "dossier_memory_profiles",
        sa.Column("signal_grant_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "dossier_memory_profiles",
        sa.Column("signal_grant_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "dmp_signal_grant_status_valid",
        "dossier_memory_profiles",
        "signal_grant_status IS NULL OR signal_grant_status IN ("
        "'authorized','manual_required','rejected','unknown','no_connection')",
    )


def downgrade() -> None:
    op.drop_constraint("dmp_signal_grant_status_valid", "dossier_memory_profiles", type_="check")
    op.drop_column("dossier_memory_profiles", "signal_grant_connection_id")
    op.drop_column("dossier_memory_profiles", "signal_grant_at")
    op.drop_column("dossier_memory_profiles", "signal_grant_detail")
    op.drop_column("dossier_memory_profiles", "signal_grant_code")
    op.drop_column("dossier_memory_profiles", "signal_grant_status")
