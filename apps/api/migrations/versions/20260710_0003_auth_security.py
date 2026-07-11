"""Narrow global audit boundary for authentication.

Revision ID: 20260710_0003
Revises: 20260710_0002
Create Date: 2026-07-10 15:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260710_0003"
down_revision: str | None = "20260710_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION oracle_append_global_audit(
          p_action varchar, p_resource_type varchar, p_result varchar,
          p_actor_id uuid, p_resource_id uuid, p_metadata jsonb,
          p_request_id varchar, p_correlation_id varchar
        ) RETURNS void
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
          IF p_action NOT LIKE 'auth.%' AND p_action NOT LIKE 'platform.bootstrap.%' THEN
            RAISE EXCEPTION 'global audit action not allowed';
          END IF;
          IF p_result NOT IN ('success','denied','failure') THEN
            RAISE EXCEPTION 'invalid audit result';
          END IF;
          IF p_actor_id IS DISTINCT FROM
             NULLIF(current_setting('app.actor_id', true), '')::uuid THEN
            RAISE EXCEPTION 'audit actor mismatch';
          END IF;
          INSERT INTO public.audit_events
            (id, tenant_id, actor_type, actor_id, action, resource_type, resource_id,
             result, request_id, correlation_id, metadata, created_at)
          VALUES
            (gen_random_uuid(), NULL, CASE WHEN p_actor_id IS NULL THEN 'service' ELSE 'user' END,
             p_actor_id, left(p_action,150), left(p_resource_type,100), p_resource_id,
             p_result, left(p_request_id,100), left(p_correlation_id,100),
             COALESCE(p_metadata,'{}'::jsonb), now());
        END $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION oracle_read_global_audit(p_limit integer)
        RETURNS TABLE(id uuid, action varchar, result varchar, created_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.users u
            WHERE u.id = NULLIF(current_setting('app.actor_id', true), '')::uuid
              AND u.status = 'active' AND u.platform_role = 'super_admin'
          ) THEN
            RAISE EXCEPTION 'platform audit access denied';
          END IF;
          RETURN QUERY
            SELECT a.id, a.action, a.result, a.created_at
            FROM public.audit_events a WHERE a.tenant_id IS NULL
            ORDER BY a.created_at DESC LIMIT LEAST(GREATEST(p_limit,1),200);
        END
        $$
        """
    )
    op.execute("ALTER FUNCTION oracle_read_global_audit(integer) OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION oracle_read_global_audit(integer) FROM PUBLIC")
    op.execute(
        """
        CREATE FUNCTION oracle_resolve_invitation(p_token_hash bytea)
        RETURNS TABLE(invitation_id uuid, tenant_id uuid, membership_id uuid)
        LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT i.id, i.tenant_id, i.membership_id FROM public.invitations i
          WHERE i.token_hash = p_token_hash AND i.used_at IS NULL AND i.revoked_at IS NULL
            AND i.expires_at > now() LIMIT 1
        $$
        """
    )
    op.execute("ALTER FUNCTION oracle_resolve_invitation(bytea) OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION oracle_resolve_invitation(bytea) FROM PUBLIC")
    op.execute(
        "ALTER FUNCTION oracle_append_global_audit(varchar,varchar,varchar,uuid,uuid,jsonb,varchar,varchar) OWNER TO oracle_migrator"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION oracle_append_global_audit(varchar,varchar,varchar,uuid,uuid,jsonb,varchar,varchar) FROM PUBLIC"
    )
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
            GRANT EXECUTE ON FUNCTION oracle_append_global_audit(varchar,varchar,varchar,uuid,uuid,jsonb,varchar,varchar) TO oracle_app;
            GRANT EXECUTE ON FUNCTION oracle_read_global_audit(integer) TO oracle_app;
            GRANT EXECUTE ON FUNCTION oracle_resolve_invitation(bytea) TO oracle_app;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS oracle_resolve_invitation(bytea)")
    op.execute("DROP FUNCTION IF EXISTS oracle_read_global_audit(integer)")
    op.execute(
        "DROP FUNCTION IF EXISTS oracle_append_global_audit(varchar,varchar,varchar,uuid,uuid,jsonb,varchar,varchar)"
    )
