"""Create platform identity, RBAC and tenant isolation.

Revision ID: 20260710_0002
Revises: 20260710_0001
Create Date: 2026-07-10 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0002"
down_revision: str | None = "20260710_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "workspaces",
    "tenant_memberships",
    "roles",
    "role_permissions",
    "membership_roles",
    "invitations",
    "audit_events",
    "integration_connections",
    "api_credentials",
)

PERMISSIONS = (
    ("dossier.read", "Consultar expedientes y sus recursos."),
    ("dossier.write", "Crear y modificar expedientes."),
    ("dossier.delete", "Archivar o eliminar expedientes según política."),
    ("signal.review", "Revisar y clasificar señales."),
    ("report.generate", "Solicitar informes y briefings."),
    ("tenant.users.manage", "Gestionar usuarios, memberships y roles."),
    ("tenant.settings.manage", "Gestionar configuración del tenant."),
    ("tenant.integrations.manage", "Gestionar integraciones y credenciales."),
    ("audit.read", "Consultar la auditoría autorizada."),
)


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
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
    )


def _uuid_pk() -> sa.Column[postgresql.UUID]:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF current_user <> 'oracle_migrator' THEN
            RAISE EXCEPTION 'phase 03 migrations require oracle_migrator';
          END IF;
          IF NOT EXISTS (
            SELECT 1 FROM pg_roles
            WHERE rolname = 'oracle_migrator' AND rolbypassrls AND NOT rolsuper
          ) THEN
            RAISE EXCEPTION 'oracle_migrator must be a non-superuser with BYPASSRLS';
          END IF;
        END $$
        """
    )
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")

    op.create_table(
        "tenants",
        _uuid_pk(),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("plan", sa.String(50)),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_tenants_tenant_slug_format",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'archived')",
            name="ck_tenants_tenant_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'", name="ck_tenants_tenant_settings_object"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(512)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("platform_role", sa.String(30)),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'locked', 'disabled')",
            name="ck_users_user_status",
        ),
        sa.CheckConstraint(
            "platform_role IS NULL OR platform_role = 'super_admin'",
            name="ck_users_user_platform_role",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "permissions",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_permissions"),
    )
    permissions = sa.table(
        "permissions", sa.column("key", sa.String()), sa.column("description", sa.String())
    )
    op.bulk_insert(
        permissions, [{"key": key, "description": description} for key, description in PERMISSIONS]
    )

    op.create_table(
        "workspaces",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "slug = lower(slug) AND slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_workspaces_workspace_slug_format",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_workspaces_workspace_status"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'",
            name="ck_workspaces_workspace_settings_object",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_workspaces_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspaces_tenant_slug"),
    )
    op.create_index(
        "uq_workspaces_one_default_per_tenant",
        "workspaces",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "user_settings",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("locale", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "preferences", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "digest_preferences",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_user_settings_user_settings_schema_version"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(preferences) = 'object'",
            name="ck_user_settings_user_settings_preferences_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(digest_preferences) = 'object'",
            name="ck_user_settings_user_settings_digest_object",
        ),
        sa.ForeignKeyConstraint(
            ("user_id",), ("users.id",), ondelete="CASCADE", name="fk_user_settings_user_id_users"
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_settings"),
    )
    op.create_table(
        "tenant_memberships",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "settings", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'revoked')",
            name="ck_tenant_memberships_membership_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(settings) = 'object'",
            name="ck_tenant_memberships_membership_settings_object",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_tenant_memberships_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            ondelete="CASCADE",
            name="fk_tenant_memberships_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_memberships"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_membership_id_tenant"),
    )
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])
    op.create_table(
        "roles",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "key = lower(key) AND key ~ '^[a-z][a-z0-9_]*$'",
            name="ck_roles_role_key_format",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",), ("tenants.id",), ondelete="CASCADE", name="fk_roles_tenant_id_tenants"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_roles_tenant_key"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_roles_id_tenant"),
    )
    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_key", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(
            ("permission_key",),
            ("permissions.key",),
            ondelete="CASCADE",
            name="fk_role_permissions_permission_key_permissions",
        ),
        sa.ForeignKeyConstraint(
            ("role_id", "tenant_id"),
            ("roles.id", "roles.tenant_id"),
            ondelete="CASCADE",
            name="fk_role_permissions_role_tenant",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "role_id", "permission_key", name="pk_role_permissions"
        ),
    )
    op.create_table(
        "membership_roles",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ("membership_id", "tenant_id"),
            ("tenant_memberships.id", "tenant_memberships.tenant_id"),
            ondelete="CASCADE",
            name="fk_membership_roles_membership_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("role_id", "tenant_id"),
            ("roles.id", "roles.tenant_id"),
            ondelete="CASCADE",
            name="fk_membership_roles_role_tenant",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "membership_id", "role_id", name="pk_membership_roles"
        ),
    )
    op.create_table(
        "invitations",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("invited_by_user_id", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name="ck_invitations_invitation_token_hash_size"
        ),
        sa.ForeignKeyConstraint(
            ("membership_id", "tenant_id"),
            ("tenant_memberships.id", "tenant_memberships.tenant_id"),
            ondelete="CASCADE",
            name="fk_invitations_membership_tenant",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_invitations_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ("invited_by_user_id",),
            ("users.id",),
            ondelete="SET NULL",
            name="fk_invitations_invited_by_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_membership_id", "invitations", ["membership_id"])
    op.create_table(
        "password_reset_tokens",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name="ck_password_reset_tokens_reset_token_hash_size"
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="SET NULL",
            name="fk_password_reset_tokens_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ("user_id",),
            ("users.id",),
            ondelete="CASCADE",
            name="fk_password_reset_tokens_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])
    op.create_table(
        "user_sessions",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_tenant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("session_hash", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("user_agent_summary", sa.String(255)),
        sa.Column("ip_address", postgresql.INET()),
        sa.CheckConstraint(
            "octet_length(session_hash) = 32", name="ck_user_sessions_session_hash_size"
        ),
        sa.ForeignKeyConstraint(
            ("active_tenant_id",),
            ("tenants.id",),
            ondelete="SET NULL",
            name="fk_user_sessions_active_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ("user_id",), ("users.id",), ondelete="CASCADE", name="fk_user_sessions_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint("session_hash", name="uq_user_sessions_session_hash"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "audit_events",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(150), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("request_id", sa.String(100)),
        sa.Column("correlation_id", sa.String(100)),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_type IN ('user', 'service')", name="ck_audit_events_audit_actor_type"
        ),
        sa.CheckConstraint(
            "result IN ('success', 'denied', 'failure')", name="ck_audit_events_audit_result"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'", name="ck_audit_events_audit_metadata_object"
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="SET NULL",
            name="fk_audit_events_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"])
    op.create_table(
        "integration_connections",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'error', 'disabled')",
            name="ck_integration_connections_integration_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object'",
            name="ck_integration_connections_integration_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_integration_connections_tenant_id_tenants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_integration_connections"),
        sa.UniqueConstraint(
            "tenant_id", "provider", "name", name="uq_integration_tenant_provider_name"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_integration_id_tenant"),
    )
    op.create_table(
        "api_credentials",
        _uuid_pk(),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "credential_version >= 1", name="ck_api_credentials_credential_version_positive"
        ),
        sa.CheckConstraint(
            "key_version >= 1", name="ck_api_credentials_credential_key_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="CASCADE",
            name="fk_api_credentials_connection_tenant",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_api_credentials"),
        sa.UniqueConstraint(
            "connection_id", "credential_version", name="uq_credential_connection_version"
        ),
    )

    op.execute(
        """
        CREATE FUNCTION oracle_current_tenant() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE
        AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$
        """
    )
    op.execute("ALTER FUNCTION oracle_current_tenant() OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION oracle_current_tenant() FROM PUBLIC")
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (tenant_id = oracle_current_tenant()) "
            "WITH CHECK (tenant_id = oracle_current_tenant())"
        )

    op.execute(
        """
        CREATE FUNCTION protect_system_roles() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF current_user = 'oracle_app' AND OLD.is_system THEN
            IF TG_OP = 'DELETE' OR NEW.key <> OLD.key OR NOT NEW.is_system THEN
              RAISE EXCEPTION 'system roles cannot be removed or demoted';
            END IF;
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END $$
        """
    )
    op.execute("ALTER FUNCTION protect_system_roles() OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION protect_system_roles() FROM PUBLIC")
    op.execute(
        "CREATE TRIGGER trg_roles_protect_system BEFORE UPDATE OR DELETE ON roles "
        "FOR EACH ROW EXECUTE FUNCTION protect_system_roles()"
    )
    op.execute(
        """
        CREATE FUNCTION oracle_actor_memberships(p_actor_id uuid)
        RETURNS TABLE(membership_id uuid, tenant_id uuid, tenant_slug varchar, tenant_name varchar,
                      membership_status varchar)
        LANGUAGE sql SECURITY DEFINER STABLE
        SET search_path = pg_catalog, public
        AS $$
          SELECT m.id, m.tenant_id, t.slug, t.name, m.status
          FROM public.tenant_memberships m
          JOIN public.tenants t ON t.id = m.tenant_id
          WHERE p_actor_id = NULLIF(current_setting('app.actor_id', true), '')::uuid
            AND m.user_id = p_actor_id
            AND m.status IN ('invited', 'active')
            AND t.status = 'active'
        $$
        """
    )
    op.execute("ALTER FUNCTION oracle_actor_memberships(uuid) OWNER TO oracle_migrator")
    op.execute("REVOKE ALL ON FUNCTION oracle_actor_memberships(uuid) FROM PUBLIC")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'oracle_app') THEN
            GRANT USAGE ON SCHEMA public TO oracle_app;
            GRANT SELECT ON system_metadata, permissions TO oracle_app;
            GRANT SELECT, INSERT, UPDATE ON tenants, users, user_settings,
              tenant_memberships, roles, role_permissions, membership_roles,
              invitations, password_reset_tokens, user_sessions,
              integration_connections, api_credentials TO oracle_app;
            GRANT SELECT, INSERT, UPDATE, DELETE ON workspaces TO oracle_app;
            GRANT DELETE ON invitations, password_reset_tokens, user_sessions,
              roles, role_permissions, membership_roles,
              integration_connections, api_credentials TO oracle_app;
            GRANT SELECT, INSERT ON audit_events TO oracle_app;
            GRANT EXECUTE ON FUNCTION oracle_current_tenant() TO oracle_app;
            GRANT EXECUTE ON FUNCTION oracle_actor_memberships(uuid) TO oracle_app;
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS oracle_actor_memberships(uuid)")
    op.execute("DROP TRIGGER IF EXISTS trg_roles_protect_system ON roles")
    op.execute("DROP FUNCTION IF EXISTS protect_system_roles()")
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS oracle_current_tenant()")
    op.drop_table("api_credentials")
    op.drop_table("integration_connections")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("user_sessions")
    op.drop_table("password_reset_tokens")
    op.drop_table("invitations")
    op.drop_table("membership_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("tenant_memberships")
    op.drop_table("user_settings")
    op.drop_index("uq_workspaces_one_default_per_tenant", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("tenants")
    # citext and the hardened public schema are intentionally retained: later revisions may
    # depend on both and downgrade must never reopen CREATE to every database user.
