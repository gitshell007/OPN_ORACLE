"""Opt-in tests that exercise PostgreSQL RLS using the real runtime role."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from opn_oracle import create_app
from opn_oracle.extensions import TenantContextChanged
from opn_oracle.platform.access import PlatformAccessDenied, authorize_platform_tenant_access
from opn_oracle.platform.models import (
    Invitation,
    PasswordResetToken,
    Role,
    RolePermission,
    User,
    Workspace,
)
from opn_oracle.platform.rbac import ROLE_DEFINITIONS, seed_system_roles
from opn_oracle.platform.security import generate_opaque_token, hash_opaque_token
from opn_oracle.tenants.context import TenantContext, actor_context, tenant_context
from opn_oracle.tenants.repository import ActiveTenantResolver, TenantScopedRepository

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class SeededTenants:
    tenant_a: uuid.UUID
    tenant_b: uuid.UUID
    actor: uuid.UUID
    superadmin: uuid.UUID
    membership_a: uuid.UUID
    membership_b: uuid.UUID
    workspace_a: uuid.UUID
    workspace_b: uuid.UUID
    connection_a: uuid.UUID
    connection_b: uuid.UUID


@pytest.fixture(scope="module")
def multitenant_database() -> Iterator[tuple[Engine, Engine, SeededTenants]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 para ejecutar integración local")
    migration_url = os.environ.get("TEST_DATABASE_URL")
    runtime_url = os.environ.get("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not migration_url or not runtime_url or not redis_url:
        pytest.skip("RLS requiere TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL")
    if "test" not in migration_url.lower() or "test" not in runtime_url.lower():
        pytest.fail("Las URLs de integración RLS deben apuntar a una base desechable con 'test'")

    app = create_app(
        {
            "APP_ENV": "test",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)

    migrator = create_engine(migration_url)
    runtime = create_engine(
        runtime_url,
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_reset_on_return="rollback",
    )
    tenant_a, tenant_b, actor, superadmin = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    membership_a, membership_b = uuid.uuid4(), uuid.uuid4()
    workspace_a, workspace_b = uuid.uuid4(), uuid.uuid4()
    connection_a, connection_b = uuid.uuid4(), uuid.uuid4()
    now = "2026-07-10T10:00:00+00:00"
    with migrator.begin() as connection:
        bypass = connection.scalar(
            text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        if not bypass:
            pytest.fail("La URL migradora debe usar un rol BYPASSRLS separado del runtime")
        connection.execute(
            text(
                "INSERT INTO tenants "
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) "
                "VALUES (:a,'tenant-a','Tenant A','active','es-ES','UTC','{}',:now,:now),"
                "(:b,'tenant-b','Tenant B','active','es-ES','UTC','{}',:now,:now)"
            ),
            {"a": tenant_a, "b": tenant_b, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO users "
                "(id,email,display_name,status,platform_role,created_at,updated_at) VALUES "
                "(:id,'actor@example.test','Actor','active',NULL,:now,:now),"
                "(:admin,'admin@example.test','Admin','active','super_admin',:now,:now)"
            ),
            {"id": actor, "admin": superadmin, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships "
                "(id,tenant_id,user_id,status,settings,created_at,updated_at) VALUES "
                "(:ma,:a,:u,'active','{}',:now,:now),(:mb,:b,:u,'active','{}',:now,:now)"
            ),
            {
                "ma": membership_a,
                "mb": membership_b,
                "a": tenant_a,
                "b": tenant_b,
                "u": actor,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) VALUES "
                "(:wa,:a,'main','A','active',true,'{}',:now,:now),"
                "(:wb,:b,'main','B','active',true,'{}',:now,:now)"
            ),
            {
                "wa": workspace_a,
                "wb": workspace_b,
                "a": tenant_a,
                "b": tenant_b,
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO integration_connections "
                "(id,tenant_id,provider,name,status,metadata,created_at,updated_at) VALUES "
                "(:ca,:a,'signal','default','active','{}',:now,:now),"
                "(:cb,:b,'signal','default','active','{}',:now,:now)"
            ),
            {
                "ca": connection_a,
                "cb": connection_b,
                "a": tenant_a,
                "b": tenant_b,
                "now": now,
            },
        )
    seeded = SeededTenants(
        tenant_a,
        tenant_b,
        actor,
        superadmin,
        membership_a,
        membership_b,
        workspace_a,
        workspace_b,
        connection_a,
        connection_b,
    )
    yield migrator, runtime, seeded
    runtime.dispose()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")


def _set_tenant(connection: object, tenant_id: uuid.UUID) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
    )


def test_runtime_role_is_minimal_and_schema_is_hardened(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, _ = multitenant_database
    with runtime.begin() as connection:
        assert (
            connection.scalar(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user"))
            is False
        )
        assert (
            connection.scalar(text("SELECT rolinherit FROM pg_roles WHERE rolname=current_user"))
            is False
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM pg_auth_members m "
                    "JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=current_user"
                )
            )
            == 0
        )
        assert (
            connection.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')"))
            is False
        )
        public_execute_grants = connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc p "
                "CROSS JOIN LATERAL aclexplode(p.proacl) acl "
                "WHERE p.proname IN ('oracle_current_tenant','oracle_actor_memberships',"
                "'protect_system_roles') AND acl.grantee = 0 "
                "AND acl.privilege_type = 'EXECUTE'"
            )
        )
        assert public_execute_grants == 0
        functions = connection.execute(
            text(
                "SELECT p.proname, owner.rolname, p.prosecdef, p.proconfig "
                "FROM pg_proc p JOIN pg_roles owner ON owner.oid=p.proowner "
                "WHERE p.proname IN ('oracle_current_tenant','oracle_actor_memberships',"
                "'protect_system_roles')"
            )
        ).all()
        assert {owner for _, owner, _, _ in functions} == {"oracle_migrator"}
        actor_function = next(row for row in functions if row[0] == "oracle_actor_memberships")
        assert actor_function[2] is True
        assert actor_function[3] == ["search_path=pg_catalog, public"]
        with pytest.raises(ProgrammingError):
            connection.execute(text("CREATE TABLE forbidden_runtime_ddl (id integer)"))


def test_every_tenant_table_has_forced_rls_and_is_closed_without_context(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    """Fail the release when a new tenant-scoped table is added without RLS."""

    migrator, runtime, _ = multitenant_database
    with migrator.connect() as connection:
        tenant_tables = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND column_name='tenant_id'"
                )
            ).scalars()
        )
        protected = {
            row.relname
            for row in connection.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p')"
                )
            )
            if row.relrowsecurity and row.relforcerowsecurity
        }
    # Password reset is intentionally resolved before authentication from a
    # high-entropy token hash. Its tenant_id is attribution, not tenant scope.
    global_identity_tables = {"password_reset_tokens"}
    assert tenant_tables
    assert tenant_tables - protected == global_identity_tables

    with runtime.begin() as connection:
        for table in sorted(tenant_tables - global_identity_tables):
            count = connection.scalar(text(f'SELECT count(*) FROM "{table}"'))
            assert count == 0, f"{table} expone filas sin app.tenant_id"


def test_rls_denies_cross_tenant_and_pool_does_not_leak(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    with runtime.begin() as connection:
        _set_tenant(connection, seeded.tenant_a)
        assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 1
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) "
                    "VALUES (:id,:tenant,'forbidden','Forbidden','active',false,'{}',now(),now())"
                ),
                {"id": uuid.uuid4(), "tenant": seeded.tenant_b},
            )
    with runtime.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 0
    with runtime.begin() as connection:
        _set_tenant(connection, seeded.tenant_b)
        assert connection.scalar(text("SELECT count(*) FROM workspaces")) == 1


def test_rls_rejects_cross_tenant_update(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    with pytest.raises(DBAPIError), runtime.begin() as connection:
        _set_tenant(connection, seeded.tenant_a)
        connection.execute(
            text("UPDATE workspaces SET tenant_id=:tenant_b WHERE id=:workspace_a"),
            {"tenant_b": seeded.tenant_b, "workspace_a": seeded.workspace_a},
        )


def test_real_repository_prevents_idor(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    with (
        tenant_context(TenantContext(tenant_id=seeded.tenant_a, actor_id=seeded.actor)),
        Session(runtime) as session,
    ):
        repository = TenantScopedRepository(session, Workspace)
        assert repository.get(seeded.workspace_a) is not None
        assert repository.get(seeded.workspace_b) is None
        tenant_repository = ActiveTenantResolver(session).repository
        assert tenant_repository.get_active_by_id(seeded.tenant_a) is not None
        assert tenant_repository.get_active_by_id(seeded.tenant_b) is None
        assert tenant_repository.get_active_by_slug("TENANT-A") is not None
        session.rollback()


def test_context_guard_requires_transaction_boundary_and_resolver_provides_it(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    with Session(runtime) as session, actor_context(seeded.actor):
        resolver = ActiveTenantResolver(session)
        resolved = resolver.resolve(actor_id=seeded.actor, slug="tenant-a")
        assert not session.in_transaction()
        with tenant_context(resolved):
            assert session.scalar(select(Workspace.id)) == seeded.workspace_a
            session.rollback()

    with Session(runtime) as session, actor_context(seeded.actor):
        session.execute(
            text("SELECT * FROM oracle_actor_memberships(:actor)"), {"actor": seeded.actor}
        ).all()
        with (
            tenant_context(TenantContext(seeded.tenant_a, seeded.actor)),
            pytest.raises(TenantContextChanged),
        ):
            session.scalar(select(Workspace.id))
        session.rollback()

    with Session(runtime) as session, tenant_context(TenantContext(seeded.tenant_a, seeded.actor)):
        session.scalar(select(Workspace.id))
        with (
            tenant_context(TenantContext(seeded.tenant_b, seeded.actor)),
            pytest.raises(TenantContextChanged),
        ):
            session.scalar(select(Workspace.id))
        with (
            tenant_context(TenantContext(seeded.tenant_b, seeded.actor)),
            pytest.raises(TenantContextChanged),
            session.begin_nested(),
        ):
            session.scalar(select(Workspace.id))
        session.rollback()


def test_security_definer_lists_only_authenticated_actor_memberships(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    with runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.actor_id', :actor, true)"),
            {"actor": str(seeded.actor)},
        )
        rows = connection.execute(
            text("SELECT tenant_id FROM oracle_actor_memberships(:actor)"),
            {"actor": seeded.actor},
        ).scalars()
        assert set(rows) == {seeded.tenant_a, seeded.tenant_b}
        assert (
            connection.scalar(
                text("SELECT count(*) FROM oracle_actor_memberships(:actor)"),
                {"actor": uuid.uuid4()},
            )
            == 0
        )


def test_composite_credential_fk_rejects_cross_tenant_connection(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    migrator, _, seeded = multitenant_database
    with pytest.raises(IntegrityError), migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO api_credentials "
                "(id,tenant_id,connection_id,ciphertext,nonce,key_version,credential_version,"
                "fingerprint,is_active,created_at,updated_at) VALUES "
                "(:id,:tenant,:connection,'x','n',1,1,'f',true,now(),now())"
            ),
            {
                "id": uuid.uuid4(),
                "tenant": seeded.tenant_a,
                "connection": seeded.connection_b,
            },
        )


def test_email_is_case_insensitive_and_audit_is_append_only(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    migrator, runtime, seeded = multitenant_database
    with pytest.raises(IntegrityError), migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id,email,display_name,status,created_at,updated_at) "
                "VALUES (:id,'ACTOR@example.test','Duplicate','active',now(),now())"
            ),
            {"id": uuid.uuid4()},
        )
    event_id = uuid.uuid4()
    with runtime.begin() as connection:
        _set_tenant(connection, seeded.tenant_a)
        connection.execute(
            text(
                "INSERT INTO audit_events "
                "(id,tenant_id,actor_type,actor_id,action,resource_type,result,metadata,"
                "created_at) "
                "VALUES (:id,:tenant,'user',:actor,'test','workspace','success','{}',now())"
            ),
            {"id": event_id, "tenant": seeded.tenant_a, "actor": seeded.actor},
        )
    with pytest.raises(ProgrammingError), runtime.begin() as connection:
        _set_tenant(connection, seeded.tenant_a)
        connection.execute(
            text("UPDATE audit_events SET action='tampered' WHERE id=:id"), {"id": event_id}
        )


def test_system_role_seed_is_idempotent_with_runtime_context(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    migrator, runtime, seeded = multitenant_database
    with tenant_context(TenantContext(tenant_id=seeded.tenant_a, actor_id=seeded.actor)):
        with Session(runtime) as session:
            first = seed_system_roles(session, seeded.tenant_a)
            session.commit()
        with migrator.begin() as connection:
            connection.execute(
                text(
                    "UPDATE roles SET name='Corrupto', description='Corrupta', is_system=false "
                    "WHERE tenant_id=:tenant AND key='viewer'"
                ),
                {"tenant": seeded.tenant_a},
            )
        with Session(runtime) as session:
            second = seed_system_roles(session, seeded.tenant_a)
            session.commit()
            assert session.scalar(text("SELECT count(*) FROM roles")) == 6
            assert session.scalar(text("SELECT count(*) FROM role_permissions")) > 0
            viewer = session.scalar(select(Role).where(Role.key == "viewer"))
            assert viewer is not None
            assert (viewer.name, viewer.description) == ROLE_DEFINITIONS["viewer"]
            assert viewer.is_system is True
            grants = {
                key: set(
                    session.scalars(
                        select(RolePermission.permission_key)
                        .join(Role, Role.id == RolePermission.role_id)
                        .where(Role.key == key)
                    )
                )
                for key in ROLE_DEFINITIONS
            }
            assert {"ai.execute", "ai.review", "documents.read", "documents.manage"} <= grants[
                "owner"
            ]
            assert {"ai.execute", "ai.review", "documents.read", "documents.manage"} <= grants[
                "editor"
            ]
            assert {"ai.execute", "ai.review", "documents.read", "documents.manage"} <= grants[
                "analyst"
            ]
            assert "documents.read" in grants["viewer"]
            assert {"documents.read", "audit.read", "audit.export", "export.create"} <= grants[
                "auditor"
            ]
    assert set(first) == set(second) == {"owner", "admin", "editor", "analyst", "viewer", "auditor"}


def test_invitation_and_reset_persist_only_token_hashes(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    _, runtime, seeded = multitenant_database
    invitation_token = generate_opaque_token()
    reset_token = generate_opaque_token()
    with tenant_context(TenantContext(seeded.tenant_a, seeded.actor)), Session(runtime) as session:
        invitation = Invitation(
            tenant_id=seeded.tenant_a,
            membership_id=seeded.membership_a,
            token_hash=hash_opaque_token(invitation_token),
            expires_at=datetime.fromisoformat("2026-07-11T10:00:00+00:00"),
        )
        reset = PasswordResetToken(
            user_id=seeded.actor,
            tenant_id=seeded.tenant_a,
            token_hash=hash_opaque_token(reset_token),
            expires_at=datetime.fromisoformat("2026-07-11T10:00:00+00:00"),
        )
        session.add_all([invitation, reset])
        session.commit()
        invitation_hash = session.scalar(
            select(Invitation.token_hash).where(Invitation.id == invitation.id)
        )
        reset_hash = session.scalar(
            select(PasswordResetToken.token_hash).where(PasswordResetToken.id == reset.id)
        )
        assert invitation_hash == hash_opaque_token(invitation_token)
        assert reset_hash == hash_opaque_token(reset_token)
        assert invitation_token.encode() != invitation_hash
        assert reset_token.encode() != reset_hash
        session.rollback()


def test_superadmin_access_requires_active_role_reason_and_clean_session(
    multitenant_database: tuple[Engine, Engine, SeededTenants],
) -> None:
    migrator, runtime, seeded = multitenant_database
    with Session(runtime) as session, actor_context(seeded.superadmin):
        context = authorize_platform_tenant_access(
            session,
            actor_id=seeded.superadmin,
            target_tenant_id=seeded.tenant_b,
            reason="Revisión operativa autorizada",
        )
        assert context.platform_access is True
        assert context.tenant_id == seeded.tenant_b
    with migrator.begin() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM audit_events WHERE tenant_id=:tenant "
                    "AND actor_id=:actor AND action='platform.tenant_access.authorized'"
                ),
                {"tenant": seeded.tenant_b, "actor": seeded.superadmin},
            )
            == 1
        )

    with (
        Session(runtime) as session,
        actor_context(seeded.actor),
        pytest.raises(PlatformAccessDenied),
    ):
        authorize_platform_tenant_access(
            session,
            actor_id=seeded.actor,
            target_tenant_id=seeded.tenant_a,
            reason="Revisión operativa autorizada",
        )
    with Session(runtime) as session, actor_context(seeded.superadmin):
        with pytest.raises(PlatformAccessDenied):
            authorize_platform_tenant_access(
                session,
                actor_id=seeded.superadmin,
                target_tenant_id=seeded.tenant_a,
                reason="corto",
            )
        pending_id = uuid.uuid4()
        session.add(
            User(
                id=pending_id,
                email="pending@example.test",
                display_name="Pending",
                status="invited",
            )
        )
        with pytest.raises(PlatformAccessDenied, match="Session limpia"):
            authorize_platform_tenant_access(
                session,
                actor_id=seeded.superadmin,
                target_tenant_id=seeded.tenant_a,
                reason="Revisión operativa autorizada",
            )
        session.rollback()
    with migrator.begin() as connection:
        assert (
            connection.scalar(text("SELECT count(*) FROM users WHERE id=:id"), {"id": pending_id})
            == 0
        )
