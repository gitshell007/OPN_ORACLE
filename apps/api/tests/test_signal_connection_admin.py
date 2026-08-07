"""ORA-SIGNAL-SW: exclusive active Signal connections, reactivate, readiness, isolation."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from redis import Redis
from sqlalchemy import create_engine, text

from opn_oracle import create_app
from opn_oracle.ai.policy_defaults import default_ai_policy
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db, limiter
from opn_oracle.integrations import routes as signal_routes
from opn_oracle.platform.models import IntegrationConnection
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def signal_admin_stack() -> Iterator[tuple[Any, dict[str, uuid.UUID], str]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    migration_url = os.environ["TEST_DATABASE_URL"]
    runtime_url = os.environ["TEST_RUNTIME_DATABASE_URL"]
    redis_url = os.environ["TEST_REDIS_URL"]
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "integration-secret-key-at-least-32-characters",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "SIGNAL_AVANZA_ENABLED": True,
            "SIGNAL_AVANZA_CONTRACT_CONFIRMED": True,
            "SIGNAL_AVANZA_BASE_URL": "https://signal-test.local",
            "AI_ENABLED": True,
            "AI_MODE": "mock",
            "AI_DEFAULT_MODEL": "mock-oracle-v1",
        }
    )
    redis = Redis.from_url(redis_url)
    redis.flushdb()
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)
    ids = {
        name: uuid.uuid4()
        for name in (
            "tenant_a",
            "tenant_b",
            "user_a",
            "user_b",
            "user_super",
            "membership_a",
            "membership_b",
            "membership_super",
            "role_a",
            "role_b",
        )
    }
    password = "frase de integración segura 2026"
    encoded = PasswordHasher().hash(password)
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants "
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) VALUES "
                "(:a,'sig-a','Signal A','active','es-ES','UTC','{}',now(),now()),"
                "(:b,'sig-b','Signal B','active','es-ES','UTC','{}',now(),now())"
            ),
            {"a": ids["tenant_a"], "b": ids["tenant_b"]},
        )
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,password_hash,status,"
                "platform_role,email_verified_at,created_at,updated_at) VALUES "
                "(:ua,'sig-owner-a@example.test','Owner A',:p,'active',NULL,now(),now(),now()),"
                "(:ub,'sig-owner-b@example.test','Owner B',:p,'active',NULL,now(),now(),now()),"
                "(:us,'sig-super@example.test','Super Admin',:p,'active',"
                "'super_admin',now(),now(),now())"
            ),
            {
                "ua": ids["user_a"],
                "ub": ids["user_b"],
                "us": ids["user_super"],
                "p": encoded,
            },
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships"
                "(id,tenant_id,user_id,status,created_at,updated_at) VALUES "
                "(:ma,:a,:ua,'active',now(),now()),(:mb,:b,:ub,'active',now(),now()),"
                "(:ms,:a,:us,'active',now(),now())"
            ),
            {
                "ma": ids["membership_a"],
                "mb": ids["membership_b"],
                "ms": ids["membership_super"],
                "a": ids["tenant_a"],
                "b": ids["tenant_b"],
                "ua": ids["user_a"],
                "ub": ids["user_b"],
                "us": ids["user_super"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO roles(id,tenant_id,key,name,description,"
                "is_system,created_at,updated_at) VALUES "
                "(:ra,:a,'owner','Owner','Owner',true,now(),now()),"
                "(:rb,:b,'owner','Owner','Owner',true,now(),now())"
            ),
            {
                "ra": ids["role_a"],
                "rb": ids["role_b"],
                "a": ids["tenant_a"],
                "b": ids["tenant_b"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO membership_roles(tenant_id,membership_id,role_id) VALUES "
                "(:a,:ma,:ra),(:b,:mb,:rb),(:a,:ms,:ra)"
            ),
            {
                "a": ids["tenant_a"],
                "b": ids["tenant_b"],
                "ma": ids["membership_a"],
                "mb": ids["membership_b"],
                "ms": ids["membership_super"],
                "ra": ids["role_a"],
                "rb": ids["role_b"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :a,:ra,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"a": ids["tenant_a"], "ra": ids["role_a"]},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :b,:rb,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"b": ids["tenant_b"], "rb": ids["role_b"]},
        )
    migrator.dispose()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user_a"])),
    ):
        db.session.add(
            default_ai_policy(
                ids["tenant_a"],
                {"AI_ENABLED": True, "AI_MODE": "mock", "AI_DEFAULT_MODEL": "mock-oracle-v1"},
            )
        )
        db.session.commit()
    yield app, ids, password
    redis.flushdb()


def _csrf(client: Any) -> str:
    return client.get("/api/v1/auth/csrf").get_json()["csrf_token"]


def _login(client: Any, email: str, password: str, tenant_id: uuid.UUID) -> Any:
    csrf = _csrf(client)
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "tenant_id": str(tenant_id)},
        headers={"X-CSRF-Token": csrf},
    )


def _fresh_csrf(app: Any, client: Any, password: str) -> str:
    # /auth/reauthenticate está limitado a 5/minuto en el código (no es configurable),
    # y este fichero necesita más reautenticaciones que eso: sin reiniciar el contador
    # los últimos tests reciben 429 en vez de ejercer el endpoint que quieren probar.
    with app.app_context():
        limiter.reset()
    csrf = _csrf(client)
    reauth = client.post(
        "/api/v1/auth/reauthenticate",
        json={"password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert reauth.status_code == 200, reauth.get_json()
    return _csrf(client)


def test_activate_one_disables_previous_and_readiness_follows_active(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = signal_admin_stack
    client = app.test_client()
    assert _login(client, "sig-owner-a@example.test", password, ids["tenant_a"]).status_code == 200
    csrf = _fresh_csrf(app, client, password)
    first = client.post(
        "/api/v1/integrations/signal-avanza",
        json={"name": "alpha", "adapter_mode": "mock"},
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 201, first.get_json()
    first_id = first.get_json()["id"]
    csrf = _fresh_csrf(app, client, password)
    second = client.post(
        "/api/v1/integrations/signal-avanza",
        json={"name": "beta", "adapter_mode": "mock"},
        headers={"X-CSRF-Token": csrf},
    )
    assert second.status_code == 201, second.get_json()
    second_id = second.get_json()["id"]
    # Creating the second mock as active must have disabled the first.
    listed = client.get("/api/v1/integrations/signal-avanza").get_json()["items"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[first_id]["status"] == "disabled"
    assert by_id[second_id]["status"] == "active"

    readiness = client.get("/api/v1/dossiers/competitive-intelligence/readiness")
    assert readiness.status_code == 200
    signal_check = next(c for c in readiness.get_json()["checks"] if c["key"] == "signal")
    assert signal_check["ready"] is True

    csrf = _fresh_csrf(app, client, password)
    reactivated = client.post(
        f"/api/v1/integrations/signal-avanza/{first_id}/activate",
        headers={"X-CSRF-Token": csrf},
    )
    assert reactivated.status_code == 200, reactivated.get_json()
    assert reactivated.get_json()["status"] == "active"
    listed = client.get("/api/v1/integrations/signal-avanza").get_json()["items"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[first_id]["status"] == "active"
    assert by_id[second_id]["status"] == "disabled"

    # Disabled connection can be reactivated again via activate.
    csrf = _fresh_csrf(app, client, password)
    again = client.post(
        f"/api/v1/integrations/signal-avanza/{second_id}/activate",
        headers={"X-CSRF-Token": csrf},
    )
    assert again.status_code == 200
    listed = client.get("/api/v1/integrations/signal-avanza").get_json()["items"]
    by_id = {item["id"]: item for item in listed}
    assert by_id[second_id]["status"] == "active"
    assert by_id[first_id]["status"] == "disabled"


def test_tenant_cannot_touch_other_tenant_connection(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = signal_admin_stack
    foreign_id = uuid.uuid4()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_b"], actor_id=ids["user_b"])),
    ):
        db.session.add(
            IntegrationConnection(
                id=foreign_id,
                tenant_id=ids["tenant_b"],
                provider="signal-avanza",
                name="foreign",
                status="disabled",
                adapter_mode="mock",
            )
        )
        db.session.commit()

    client = app.test_client()
    assert _login(client, "sig-owner-a@example.test", password, ids["tenant_a"]).status_code == 200
    csrf = _fresh_csrf(app, client, password)
    activate = client.post(
        f"/api/v1/integrations/signal-avanza/{foreign_id}/activate",
        headers={"X-CSRF-Token": csrf},
    )
    assert activate.status_code == 404
    patch = client.patch(
        f"/api/v1/integrations/signal-avanza/{foreign_id}",
        json={"name": "hacked"},
        headers={"X-CSRF-Token": csrf},
    )
    assert patch.status_code == 404


def test_owner_cannot_point_signal_outside_configured_destination(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    """Propietario sin super_admin: 403 aunque confirme el entorno cruzado."""
    app, ids, password = signal_admin_stack
    client = app.test_client()
    assert _login(client, "sig-owner-a@example.test", password, ids["tenant_a"]).status_code == 200
    csrf = _fresh_csrf(app, client, password)
    created = client.post(
        "/api/v1/integrations/signal-avanza",
        json={"name": "editable", "adapter_mode": "mock"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    connection_id = created.get_json()["id"]
    csrf = _fresh_csrf(app, client, password)
    denied = client.patch(
        f"/api/v1/integrations/signal-avanza/{connection_id}",
        json={
            "base_url": "https://signal.prod.example/api",
            "confirm_cross_environment": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403
    assert denied.get_json()["code"] == "signal_cross_environment_platform_required"
    # Sin confirm también 403 (no 422): el inquilino no puede siquiera iniciar el cambio.
    csrf = _fresh_csrf(app, client, password)
    denied_plain = client.patch(
        f"/api/v1/integrations/signal-avanza/{connection_id}",
        json={"base_url": "https://signal.prod.example/api"},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied_plain.status_code == 403
    assert denied_plain.get_json()["code"] == "signal_cross_environment_platform_required"


def test_super_admin_can_point_signal_with_confirm_and_is_audited(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = signal_admin_stack
    client = app.test_client()
    assert _login(client, "sig-super@example.test", password, ids["tenant_a"]).status_code == 200
    csrf = _fresh_csrf(app, client, password)
    created = client.post(
        "/api/v1/integrations/signal-avanza",
        json={"name": "super-editable", "adapter_mode": "mock"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201, created.get_json()
    connection_id = created.get_json()["id"]
    csrf = _fresh_csrf(app, client, password)
    # Super_admin still needs explicit confirm.
    missing_confirm = client.patch(
        f"/api/v1/integrations/signal-avanza/{connection_id}",
        json={"base_url": "https://signal.prod.example/api", "adapter_mode": "http"},
        headers={"X-CSRF-Token": csrf},
    )
    assert missing_confirm.status_code == 422
    assert missing_confirm.get_json()["code"] == "signal_cross_environment_confirmation_required"
    csrf = _fresh_csrf(app, client, password)
    updated = client.patch(
        f"/api/v1/integrations/signal-avanza/{connection_id}",
        json={
            "base_url": "https://signal.prod.example/api",
            "api_version": "2026-08-01",
            "adapter_mode": "http",
            "confirm_cross_environment": True,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert updated.status_code == 200, updated.get_json()
    body = updated.get_json()
    assert body["base_url"] == "https://signal.prod.example/api"
    assert body["api_version"] == "2026-08-01"
    assert body["adapter_mode"] == "http"
    assert "api_token" not in body
    assert "webhook_secret" not in body
    assert "subscription_key" not in body

    # Audit records who authorized the cross-environment move.
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user_super"])),
    ):
        events = (
            db.session.execute(
                text(
                    "SELECT actor_id, metadata FROM audit_events "
                    "WHERE tenant_id=:t AND action='integration.signal.update' "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"t": ids["tenant_a"]},
            )
            .mappings()
            .all()
        )
    assert events
    meta = events[0]["metadata"]
    if isinstance(meta, str):
        import json

        meta = json.loads(meta)
    assert meta["cross_environment_confirmed"] is True
    assert meta["authorized_by"]["user_id"] == str(ids["user_super"])
    assert meta["authorized_by"]["platform_role"] == "super_admin"
    assert meta["actor_platform_role"] == "super_admin"
    assert str(events[0]["actor_id"]) == str(ids["user_super"])


def test_owner_can_toggle_enabled_but_not_kill_switch(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = signal_admin_stack
    client = app.test_client()
    assert _login(client, "sig-owner-a@example.test", password, ids["tenant_a"]).status_code == 200
    before = client.get("/api/v1/tenant-admin/ai-policy")
    assert before.status_code == 200
    assert before.get_json()["enabled"] is True
    assert before.get_json()["kill_switch"] is False

    csrf = _fresh_csrf(app, client, password)
    kill_denied = client.patch(
        "/api/v1/tenant-admin/ai-policy",
        json={"kill_switch": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert kill_denied.status_code == 403
    assert kill_denied.get_json()["code"] == "ai_kill_switch_platform_required"

    # Kill switch untouched after denied attempt.
    still = client.get("/api/v1/tenant-admin/ai-policy").get_json()
    assert still["kill_switch"] is False
    assert still["enabled"] is True

    csrf = _fresh_csrf(app, client, password)
    disabled = client.patch(
        "/api/v1/tenant-admin/ai-policy",
        json={"enabled": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert disabled.status_code == 200, disabled.get_json()
    assert disabled.get_json()["enabled"] is False
    assert disabled.get_json()["kill_switch"] is False

    readiness = client.get("/api/v1/dossiers/competitive-intelligence/readiness")
    ai_check = next(c for c in readiness.get_json()["checks"] if c["key"] == "ai")
    assert ai_check["ready"] is False

    csrf = _fresh_csrf(app, client, password)
    enabled = client.patch(
        "/api/v1/tenant-admin/ai-policy",
        json={"enabled": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert enabled.status_code == 200
    assert enabled.get_json()["enabled"] is True
    audit = client.get("/api/v1/tenant-admin/audit").get_json()["items"]
    actions = [item["action"] for item in audit]
    assert "tenant.ai_policy.updated" in actions


def test_super_admin_can_toggle_kill_switch(
    signal_admin_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = signal_admin_stack
    client = app.test_client()
    assert _login(client, "sig-super@example.test", password, ids["tenant_a"]).status_code == 200
    csrf = _fresh_csrf(app, client, password)
    toggled = client.patch(
        "/api/v1/tenant-admin/ai-policy",
        json={"kill_switch": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert toggled.status_code == 200, toggled.get_json()
    assert toggled.get_json()["kill_switch"] is True
    assert toggled.get_json()["enabled"] is True


def test_cross_environment_helper_unit() -> None:
    from flask import Flask

    app = Flask("cross-env")
    app.config["APP_ENV"] = "development"
    app.config["SIGNAL_AVANZA_BASE_URL"] = "https://signal-dev.example"
    with app.app_context():
        assert signal_routes._requires_cross_environment_confirmation("https://signal.prod.example")
        assert not signal_routes._requires_cross_environment_confirmation("http://localhost:8080")
        # El destino configurado del propio despliegue no es entorno cruzado.
        assert not signal_routes._requires_cross_environment_confirmation(
            "https://signal-dev.example"
        )
    # oracle-dev corre con APP_ENV=production (DEV_NATIVE_DEPLOY.md): el guardián
    # NO puede depender del entorno, o queda inerte justo donde hace falta.
    app.config["APP_ENV"] = "production"
    with app.app_context():
        assert signal_routes._requires_cross_environment_confirmation("https://signal.prod.example")
        assert not signal_routes._requires_cross_environment_confirmation(
            "https://signal-dev.example"
        )

    # Sin destino configurado, cualquier https remoto pide confirmación.
    bare = Flask("cross-env-bare")
    bare.config["APP_ENV"] = "production"
    with bare.app_context():
        assert signal_routes._requires_cross_environment_confirmation("https://signal.prod.example")
