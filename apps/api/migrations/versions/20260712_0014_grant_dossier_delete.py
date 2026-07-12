"""grant runtime deletion of strategic dossiers

Revision ID: 20260712_0014
Revises: 20260712_0013
Create Date: 2026-07-12 08:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260712_0014"
down_revision: str | None = "20260712_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The runtime role deliberately has only the privileges needed by the API.
    # Deletion was intentionally absent in the original core grant; it is now
    # required by the guarded dossier bulk-delete operation introduced in 0013.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
            GRANT DELETE ON strategic_dossiers TO oracle_app;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
            REVOKE DELETE ON strategic_dossiers FROM oracle_app;
          END IF;
        END $$;
        """
    )
