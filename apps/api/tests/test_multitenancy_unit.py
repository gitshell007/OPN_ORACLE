from __future__ import annotations

import uuid
from typing import Any

import pytest
from apiflask import APIFlask

from opn_oracle.config import ConfigError, Settings
from opn_oracle.extensions import (
    SESSION_CONTEXT_KEY,
    TenantContextChanged,
    clear_transaction_context,
    guard_flush,
    set_postgres_transaction_context,
)
from opn_oracle.platform.access import PlatformAccessDenied, authorize_platform_tenant_access
from opn_oracle.platform.audit import append_audit_event, sanitize_audit_metadata
from opn_oracle.platform.models import Permission, Workspace
from opn_oracle.platform.rbac import PERMISSIONS, seed_permission_catalog, seed_system_roles
from opn_oracle.platform.security import generate_opaque_token, hash_opaque_token
from opn_oracle.tenants.context import (
    TenantContext,
    TenantContextMissing,
    actor_context,
    get_tenant_context,
    require_tenant_id,
    tenant_context,
)
from opn_oracle.tenants.repository import (
    ActiveTenantResolver,
    PermissionRepository,
    TenantRepository,
    TenantResolutionError,
    TenantScopedRepository,
)


def test_tenant_context_is_nested_and_restored() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    with tenant_context(TenantContext(tenant_id=tenant_a, actor_id=uuid.uuid4())):
        assert require_tenant_id() == tenant_a
        with tenant_context(TenantContext(tenant_id=tenant_b, actor_id=uuid.uuid4())):
            assert require_tenant_id() == tenant_b
        assert require_tenant_id() == tenant_a
    assert get_tenant_context(required=False) is None
    with pytest.raises(TenantContextMissing):
        require_tenant_id()


def test_opaque_token_is_random_and_only_hash_is_fixed_size() -> None:
    first = generate_opaque_token()
    second = generate_opaque_token()
    assert first != second
    assert len(hash_opaque_token(first)) == 32
    assert hash_opaque_token(first) == hash_opaque_token(first)
    assert first.encode() not in hash_opaque_token(first)
    with pytest.raises(ValueError):
        generate_opaque_token(bytes_length=16)


def test_audit_redacts_nested_keys_embedded_values_and_dsns() -> None:
    sanitized = sanitize_audit_metadata(
        {
            "password": "hunter2",
            "nested": {"note": "password=hunter2"},
            "dsn": "postgresql://oracle:hunter2@db/opn",
        }
    )
    assert sanitized == {
        "password": "[REDACTED]",
        "nested": {"note": "password=[REDACTED]"},
        "dsn": "postgresql://oracle:[REDACTED]@db/opn",
    }


def test_audit_event_requires_explicit_global_intent() -> None:
    class FakeSession:
        def add(self, value: object) -> None:
            raise AssertionError(f"No debe persistirse: {value!r}")

    with pytest.raises(TenantContextMissing):
        append_audit_event(  # type: ignore[arg-type]
            FakeSession(), action="test", resource_type="test", result="success"
        )


def test_audit_event_is_sanitized_and_bound_to_context() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        def get(self, model: object, key: str) -> Permission:
            del model
            return Permission(key=key, description="anterior")

    session = FakeSession()
    tenant_id, actor_id = uuid.uuid4(), uuid.uuid4()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        event = append_audit_event(  # type: ignore[arg-type]
            session,
            action="tenant.access",
            resource_type="tenant",
            result="success",
            metadata={"note": "token=canary"},
        )
    assert event.tenant_id == tenant_id
    assert event.actor_id == actor_id
    assert event.event_metadata == {"note": "token=[REDACTED]"}
    assert session.added == [event]


def test_production_requires_rls_and_normalizes_migration_url() -> None:
    with pytest.raises(ConfigError, match="RLS_ENABLED"):
        Settings.load(
            {
                "APP_ENV": "production",
                "FLASK_DEBUG": False,
                "SECRET_KEY": "x" * 32,
                "DATABASE_URL": "postgresql://app@db/oracle",
                "DATABASE_MIGRATION_URL": "postgresql://migrator@db/oracle",
                "REDIS_URL": "redis://redis/0",
                "FRONTEND_ORIGIN": "https://oracle.example",
                "RLS_ENABLED": False,
            }
        )
    settings = Settings.load(
        {
            "APP_ENV": "test",
            "DATABASE_URL": "postgresql://app@db/oracle",
            "DATABASE_MIGRATION_URL": "postgresql://migrator@db/oracle",
        }
    )
    assert settings.database_migration_url == "postgresql+psycopg://migrator@db/oracle"


def test_repository_helpers_require_scope_and_map_memberships() -> None:
    class Result:
        def mappings(self) -> list[dict[str, Any]]:
            return [
                {
                    "membership_id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "tenant_slug": "tenant-a",
                    "tenant_name": "Tenant A",
                    "membership_status": "active",
                }
            ]

    class FakeSession:
        def scalar(self, statement: object) -> object:
            del statement
            return marker

        def execute(self, statement: object, parameters: object = None) -> Result:
            del statement, parameters
            return Result()

    tenant_id = uuid.uuid4()
    marker = object()
    session = FakeSession()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=uuid.uuid4())):
        scoped = TenantScopedRepository(session, Workspace)  # type: ignore[arg-type]
        assert scoped.get(uuid.uuid4()) is marker
        assert TenantRepository(session).get_active() is marker  # type: ignore[arg-type]
        memberships = TenantRepository(session).memberships_for_authenticated_actor(  # type: ignore[arg-type]
            uuid.uuid4()
        )
        assert memberships[0].tenant_id == tenant_id
        assert PermissionRepository(session).has_permission(  # type: ignore[arg-type]
            uuid.uuid4(), "dossier.read"
        )


def test_permission_catalog_is_idempotent_and_role_seed_rejects_wrong_tenant() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def scalars(self, statement: object) -> list[str]:
            del statement
            return ["dossier.read"]

        def add(self, value: object) -> None:
            self.added.append(value)

        def get(self, model: object, key: str) -> Permission:
            del model
            return Permission(key=key, description="anterior")

    session = FakeSession()
    seed_permission_catalog(session)  # type: ignore[arg-type]
    keys = {item.key for item in session.added if isinstance(item, Permission)}
    assert keys == set(PERMISSIONS) - {"dossier.read"}
    with (
        tenant_context(TenantContext(tenant_id=uuid.uuid4(), actor_id=None)),
        pytest.raises(ValueError, match="tenant activo"),
    ):
        seed_system_roles(session, uuid.uuid4())  # type: ignore[arg-type]


def test_transaction_listener_sets_only_local_postgres_context() -> None:
    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def execute(self, statement: object, values: dict[str, str]) -> None:
            del statement
            self.calls.append(values)

    class FakeSession:
        def __init__(self) -> None:
            self.info: dict[str, object] = {}

    class Transaction:
        parent = None

    connection = Connection()
    tenant_id, actor_id = uuid.uuid4(), uuid.uuid4()
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=actor_id)):
        set_postgres_transaction_context(  # type: ignore[arg-type]
            FakeSession(), Transaction(), connection
        )
    assert connection.calls == [
        {"tenant_id": str(tenant_id)},
        {"actor_id": str(actor_id)},
    ]


def test_transaction_guard_rejects_context_change_and_clears_root() -> None:
    tenant_a, tenant_b, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    class FakeSession:
        def __init__(self) -> None:
            self.info: dict[str, object] = {SESSION_CONTEXT_KEY: (str(tenant_a), str(actor))}

    class RootTransaction:
        parent = None

    session = FakeSession()
    with (
        tenant_context(TenantContext(tenant_b, actor)),
        pytest.raises(TenantContextChanged),
    ):
        guard_flush(session, None, None)  # type: ignore[arg-type]
    clear_transaction_context(session, RootTransaction())  # type: ignore[arg-type]
    assert SESSION_CONTEXT_KEY not in session.info


def test_active_tenant_resolver_rolls_back_pretenant_lookup() -> None:
    actor_id, tenant_id = uuid.uuid4(), uuid.uuid4()

    class Result:
        def mappings(self) -> list[dict[str, Any]]:
            return [
                {
                    "membership_id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "tenant_slug": "tenant-a",
                    "tenant_name": "Tenant A",
                    "membership_status": "active",
                }
            ]

    class FakeSession:
        def __init__(self) -> None:
            self.new: set[object] = set()
            self.dirty: set[object] = set()
            self.deleted: set[object] = set()
            self.rollbacks = 0

        def execute(self, statement: object, parameters: object = None) -> Result:
            del statement, parameters
            return Result()

        def rollback(self) -> None:
            self.rollbacks += 1

    session = FakeSession()
    with actor_context(actor_id):
        resolved = ActiveTenantResolver(session).resolve(  # type: ignore[arg-type]
            actor_id=actor_id, slug="TENANT-A"
        )
    assert resolved == TenantContext(tenant_id=tenant_id, actor_id=actor_id)
    assert session.rollbacks == 1
    session.new = {object()}
    with actor_context(actor_id), pytest.raises(TenantResolutionError, match="Session limpia"):
        ActiveTenantResolver(session).resolve(actor_id=actor_id, tenant_id=tenant_id)  # type: ignore[arg-type]


def test_platform_access_is_explicit_audited_and_requires_clean_session() -> None:
    actor_id, tenant_id = uuid.uuid4(), uuid.uuid4()

    class FakeSession:
        def __init__(self) -> None:
            self.new: set[object] = set()
            self.dirty: set[object] = set()
            self.deleted: set[object] = set()
            self.scalar_results = [object(), object()]
            self.rollbacks = 0
            self.commits = 0
            self.added: list[object] = []

        def scalar(self, statement: object) -> object | None:
            del statement
            return self.scalar_results.pop(0)

        def rollback(self) -> None:
            self.rollbacks += 1

        def commit(self) -> None:
            self.commits += 1

        def add(self, value: object) -> None:
            self.added.append(value)

    session = FakeSession()
    with actor_context(actor_id):
        context = authorize_platform_tenant_access(  # type: ignore[arg-type]
            session,
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            reason="Revisión operativa autorizada",
        )
    assert context.platform_access is True
    assert session.rollbacks == 1
    assert session.commits == 1
    assert len(session.added) == 1

    session = FakeSession()
    session.new = {object()}
    with actor_context(actor_id), pytest.raises(PlatformAccessDenied, match="Session limpia"):
        authorize_platform_tenant_access(  # type: ignore[arg-type]
            session,
            actor_id=actor_id,
            target_tenant_id=tenant_id,
            reason="Revisión operativa autorizada",
        )


def test_create_dev_tenant_is_disabled_in_production(app: APIFlask) -> None:
    app.config["APP_ENV"] = "production"
    result = app.test_cli_runner().invoke(
        args=[
            "create-dev-tenant",
            "--slug",
            "tenant-test",
            "--name",
            "Tenant test",
            "--email",
            "owner@example.test",
            "--display-name",
            "Owner",
        ]
    )
    assert result.exit_code != 0
    assert "deshabilitado en producción" in result.output
