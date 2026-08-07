"""Password-reset tenant resolver (SECURITY DEFINER) for pre-session RLS.

Revision ID: 20260808_0038
Revises: 20260806_0037
Create Date: 2026-08-08 00:00:00+00:00

``POST /auth/forgot-password`` runs without a tenant session. Direct SELECTs
on ``tenant_memberships`` are empty under FORCE RLS because
``oracle_current_tenant()`` is unset. Same pattern as
``oracle_resolve_invitation``: a narrow SECURITY DEFINER function owned by
``oracle_migrator`` that returns only the first active membership's
``tenant_id`` (nothing else).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260808_0038"
down_revision: str | None = "20260806_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION oracle_resolve_password_reset_tenant(p_user_id uuid)
        RETURNS uuid
        LANGUAGE sql
        SECURITY DEFINER
        STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT m.tenant_id
          FROM public.tenant_memberships m
          WHERE m.user_id = p_user_id
            AND m.status = 'active'
          ORDER BY m.created_at ASC, m.id ASC
          LIMIT 1
        $$
        """
    )
    op.execute("ALTER FUNCTION oracle_resolve_password_reset_tenant(uuid) OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION oracle_resolve_password_reset_tenant(uuid) FROM PUBLIC")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
            GRANT EXECUTE ON FUNCTION oracle_resolve_password_reset_tenant(uuid) TO oracle_app;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS oracle_resolve_password_reset_tenant(uuid)")
