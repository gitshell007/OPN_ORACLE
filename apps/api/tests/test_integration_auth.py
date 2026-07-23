from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.low_level import Type
from flask_migrate import downgrade, upgrade
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from opn_oracle import create_app
from opn_oracle.ai.policy_defaults import default_ai_policy
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.jobs.tasks import dispatch_queued_jobs
from opn_oracle.notifications.email import CaptureEmailSender
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def auth_stack() -> Iterator[tuple[Any, dict[str, uuid.UUID], str]]:
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
            "AUTH_MAX_FAILURES": 2,
            "AUTH_LOCK_SECONDS": 30,
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
            "tenant",
            "tenant_b",
            "user",
            "super",
            "membership",
            "membership_b",
            "role",
            "viewer_role",
            "analyst_role",
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
                "(:t,'auth-tenant','Auth Tenant','active','es-ES','UTC','{}',now(),now()),"
                "(:b,'other-tenant','Other Tenant','active','es-ES','UTC','{}',now(),now())"
            ),
            {"t": ids["tenant"], "b": ids["tenant_b"]},
        )
        connection.execute(
            text(
                "INSERT INTO users (id,email,display_name,password_hash,status,platform_role,"
                "email_verified_at,created_at,updated_at) VALUES "
                "(:u,'owner@example.test','Owner',:p,'active',NULL,now(),now(),now()),"
                "(:s,'super@example.test','Super',:p,'active','super_admin',now(),now(),now())"
            ),
            {"u": ids["user"], "s": ids["super"], "p": encoded},
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships "
                "(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (:m,:t,:u,'active',now(),'{}',now(),now()),"
                "(:mb,:b,:u,'active',now(),'{}',now(),now())"
            ),
            {
                "m": ids["membership"],
                "mb": ids["membership_b"],
                "t": ids["tenant"],
                "b": ids["tenant_b"],
                "u": ids["user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO roles "
                "(id,tenant_id,key,name,description,is_system,created_at,updated_at) VALUES "
                "(:r,:t,'owner','Propietario','Owner',true,now(),now()),"
                "(:v,:t,'viewer','Lector','Viewer',true,now(),now()),"
                "(:a,:t,'analyst','Analista','Analyst',true,now(),now())"
            ),
            {
                "r": ids["role"],
                "v": ids["viewer_role"],
                "a": ids["analyst_role"],
                "t": ids["tenant"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO membership_roles (tenant_id,membership_id,role_id) VALUES (:t,:m,:r)"
            ),
            {"t": ids["tenant"], "m": ids["membership"], "r": ids["role"]},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions (tenant_id,role_id,permission_key) "
                "SELECT :t,:r,key FROM permissions"
            ),
            {"t": ids["tenant"], "r": ids["role"]},
        )
    yield app, ids, password
    redis.flushdb()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")


@pytest.fixture(autouse=True)
def reset_auth_state(auth_stack: tuple[Any, dict[str, uuid.UUID], str]) -> Iterator[None]:
    _, ids, password = auth_stack
    Redis.from_url(os.environ["TEST_REDIS_URL"]).flushdb()
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(text("DELETE FROM platform_backup_operations"))
        connection.execute(text("DELETE FROM platform_backup_artifacts"))
        connection.execute(text("DELETE FROM user_sessions"))
        connection.execute(text("DELETE FROM password_reset_tokens"))
        connection.execute(
            text("UPDATE users SET password_hash=:password,status='active' WHERE id=:id"),
            {"password": PasswordHasher().hash(password), "id": ids["user"]},
        )
        connection.execute(
            text("UPDATE tenants SET status='active' WHERE id=:id"), {"id": ids["tenant"]}
        )
        connection.execute(
            text("UPDATE tenant_memberships SET status='active' WHERE id=:id"),
            {"id": ids["membership"]},
        )
    migrator.dispose()
    yield


def _csrf(client: Any) -> str:
    return str(client.get("/api/v1/auth/csrf").get_json()["csrf_token"])


def _login(client: Any, email: str, password: str, tenant_id: uuid.UUID | None = None) -> Any:
    token = _csrf(client)
    payload: dict[str, Any] = {"email": email, "password": password}
    if tenant_id:
        payload["tenant_id"] = str(tenant_id)
    return client.post("/api/v1/auth/login", json=payload, headers={"X-CSRF-Token": token})


def _dispatch_password_reset(app: Any) -> None:
    with app.app_context():
        assert dispatch_queued_jobs.run() >= 1


def test_login_session_rotation_me_and_durable_hash(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    _csrf(client)
    before = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    response = _login(client, "owner@example.test", password, ids["tenant"])
    assert response.status_code == 200
    after = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    assert before and after and before.value != after.value
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.get_json()["active_tenant_id"] == str(ids["tenant"])
    assert "tenant.users.manage" in me.get_json()["permissions"]
    session_id = uuid.UUID(response.get_json()["session_id"])
    raw_sid = after.value.split(".", 1)[0]
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.connect() as connection:
        stored = connection.scalar(
            text("SELECT session_hash FROM user_sessions WHERE id=:id"), {"id": session_id}
        )
    migrator.dispose()
    assert stored == hashlib.sha256(raw_sid.encode()).digest()


def test_repeated_csrf_reads_do_not_invalidate_first_token_for_mutation(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    first_token = _csrf(client)
    second_token = _csrf(client)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "owner@example.test",
            "password": password,
            "tenant_id": str(ids["tenant"]),
        },
        headers={"X-CSRF-Token": first_token},
    )

    assert response.status_code == 200
    assert second_token == first_token


def test_csrf_rotates_on_login_and_password_change(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    anonymous_token = _csrf(client)
    assert _login(client, "owner@example.test", password, ids["tenant"]).status_code == 200
    login_token = _csrf(client)
    assert login_token != anonymous_token

    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "contraseña rotada segura 2026"},
        headers={"X-CSRF-Token": login_token},
    )

    assert changed.status_code == 204
    assert _csrf(client) != login_token


def test_login_with_multiple_memberships_returns_safe_choices(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    response = _login(client, "owner@example.test", password)
    assert response.status_code == 409
    problem = response.get_json()
    assert problem["code"] == "tenant_selection_required"
    assert problem["errors"]["memberships"] == [
        {
            "tenant_id": str(ids["tenant"]),
            "tenant_slug": "auth-tenant",
            "tenant_name": "Auth Tenant",
        },
        {
            "tenant_id": str(ids["tenant_b"]),
            "tenant_slug": "other-tenant",
            "tenant_name": "Other Tenant",
        },
    ]
    assert _login(client, "owner@example.test", password, ids["tenant_b"]).status_code == 200
    assert client.get("/api/v1/auth/me").get_json()["active_tenant_id"] == str(ids["tenant_b"])


def test_login_rehashes_legacy_argon2_parameters(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    legacy_hash = Argon2PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID
    ).hash(password)
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE users SET password_hash=:hash WHERE id=:id"),
            {"hash": legacy_hash, "id": ids["user"]},
        )
    assert (
        _login(app.test_client(), "owner@example.test", password, ids["tenant"]).status_code == 200
    )
    with migrator.connect() as connection:
        upgraded = connection.scalar(
            text("SELECT password_hash FROM users WHERE id=:id"), {"id": ids["user"]}
        )
    migrator.dispose()
    assert upgraded != legacy_hash
    assert PasswordHasher().needs_rehash(str(upgraded)) is False


def test_login_anti_enumeration_lock_and_retry_after(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = auth_stack
    client = app.test_client()
    wrong = _login(client, "owner@example.test", "equivocada", ids["tenant"])
    missing = _login(client, "missing@example.test", "equivocada", ids["tenant"])
    assert wrong.status_code == missing.status_code == 401
    assert wrong.get_json()["detail"] == missing.get_json()["detail"]
    _login(client, "owner@example.test", "equivocada", ids["tenant"])
    locked = _login(client, "owner@example.test", "equivocada", ids["tenant"])
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0


def test_session_list_reauth_revoke_others_and_switch_denied(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    first, second = app.test_client(), app.test_client()
    assert _login(first, "owner@example.test", password, ids["tenant"]).status_code == 200
    assert _login(second, "owner@example.test", password, ids["tenant"]).status_code == 200
    csrf = _csrf(first)
    denied = first.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403
    with first.session_transaction() as browser_session:
        browser_session["reauthenticated_at"] = 0
    stale_csrf = _csrf(first)
    stale = first.post(
        "/api/v1/auth/sessions/revoke-others",
        headers={"X-CSRF-Token": stale_csrf},
    )
    assert stale.status_code == 401
    reauth = first.post(
        "/api/v1/auth/reauthenticate",
        json={"password": password},
        headers={"X-CSRF-Token": stale_csrf},
    )
    assert reauth.status_code == 200
    csrf = _csrf(first)
    assert (
        first.post(
            "/api/v1/auth/sessions/revoke-others", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    assert second.get("/api/v1/auth/me").status_code == 401
    sessions = first.get("/api/v1/auth/sessions").get_json()["items"]
    assert any(
        item["current"] and item["active_tenant_id"] == str(ids["tenant"]) for item in sessions
    )
    before = first.get_cookie(app.config["SESSION_COOKIE_NAME"])
    csrf = _csrf(first)
    switched = first.post(
        "/api/v1/auth/switch-tenant",
        json={"tenant_id": str(ids["tenant_b"])},
        headers={"X-CSRF-Token": csrf},
    )
    after = first.get_cookie(app.config["SESSION_COOKIE_NAME"])
    assert switched.status_code == 200
    assert before and after and before.value != after.value


def test_forgot_reset_is_one_time_and_revokes_sessions(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    assert _login(client, "owner@example.test", password, ids["tenant"]).status_code == 200
    token = _csrf(client)
    sender = app.extensions["email_sender"]
    assert isinstance(sender, CaptureEmailSender)
    previous_messages = len(sender.messages)
    assert (
        client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "owner@example.test"},
            headers={"X-CSRF-Token": token},
        ).status_code
        == 204
    )
    assert len(sender.messages) == previous_messages
    _dispatch_password_reset(app)
    url = sender.messages[-1].body.splitlines()[0].split(": ", 1)[1]
    raw = parse_qs(urlparse(url).query)["token"][0]
    anonymous = app.test_client()
    csrf = _csrf(anonymous)
    reset_payload = {"token": raw, "new_password": "otra frase segura distinta 2026"}
    assert (
        anonymous.post(
            "/api/v1/auth/reset-password", json=reset_payload, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    assert (
        anonymous.post(
            "/api/v1/auth/reset-password", json=reset_payload, headers={"X-CSRF-Token": csrf}
        ).status_code
        == 400
    )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_superadmin_platform_tenant_lifecycle_and_global_audit(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, _, password = auth_stack
    client = app.test_client()
    assert _login(client, "super@example.test", password).status_code == 200
    csrf = _csrf(client)
    created = client.post(
        "/api/v1/platform/tenants",
        json={"name": "Nuevo Tenant", "slug": "nuevo-tenant"},
        headers={"X-CSRF-Token": csrf},
    )
    assert created.status_code == 201
    tenant_id = created.get_json()["id"]
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as connection:
        policy_count = connection.scalar(
            text("SELECT count(*) FROM ai_tenant_policies WHERE tenant_id=:tenant_id"),
            {"tenant_id": tenant_id},
        )
    engine.dispose()
    assert policy_count == 1
    assert client.get("/api/v1/platform/tenants").status_code == 200
    assert client.get(f"/api/v1/platform/tenants/{tenant_id}").status_code == 200
    assert client.get("/api/v1/platform/audit").status_code == 200
    assert (
        client.post(
            f"/api/v1/platform/tenants/{tenant_id}/suspend", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    assert (
        client.post(
            f"/api/v1/platform/tenants/{tenant_id}/reactivate", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )


def test_superadmin_backup_queue_host_agent_and_restore_gate(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    ordinary = app.test_client()
    assert _login(ordinary, "owner@example.test", password, ids["tenant"]).status_code == 200
    assert ordinary.get("/api/v1/platform/backups").status_code == 403

    client = app.test_client()
    assert _login(client, "super@example.test", password).status_code == 200
    csrf = _csrf(client)
    with client.session_transaction() as browser_session:
        browser_session["reauthenticated_at"] = 0
    stale = client.post(
        "/api/v1/platform/backups",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "manual-backup-20260711"},
    )
    assert stale.status_code == 401
    assert stale.get_json()["code"] == "recent_auth_required"
    assert (
        client.post(
            "/api/v1/auth/reauthenticate",
            json={"password": password},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    csrf = _csrf(client)
    created = client.post(
        "/api/v1/platform/backups",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "manual-backup-20260711"},
    )
    assert created.status_code == 202
    operation_id = created.get_json()["operation_id"]
    replay = client.post(
        "/api/v1/platform/backups",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "manual-backup-20260711"},
    )
    assert replay.status_code == 200
    assert replay.get_json()["operation_id"] == operation_id

    runner = app.test_cli_runner()
    claim = runner.invoke(args=["backup-agent", "claim-next", "--worker-id", "test-host"])
    assert claim.exit_code == 0, claim.output
    assert json.loads(claim.output)["operation"]["operation_id"] == operation_id
    artifact_metadata = {
        "backup_name": "20260711T180000Z-manual",
        "relative_path": "20260711T180000Z-manual",
        "size_bytes": 12345,
        "sha256": "a" * 64,
        "backup_created_at": "2026-07-11T18:00:00+00:00",
        "verified_at": "2026-07-11T18:01:00+00:00",
        "expires_at": "2026-08-10T18:00:00+00:00",
        "origin": "manual",
    }
    complete = runner.invoke(
        args=[
            "backup-agent",
            "complete",
            "--operation-id",
            operation_id,
            "--worker-id",
            "test-host",
            "--status",
            "succeeded",
            "--artifact-json-stdin",
        ],
        input=json.dumps(artifact_metadata),
    )
    assert complete.exit_code == 0, complete.output

    catalogue = client.get("/api/v1/platform/backups")
    assert catalogue.status_code == 200
    assert catalogue.get_json()["retention_days"] == 30
    assert catalogue.get_json()["storage_path"] == "/var/backups/opn-oracle"
    artifact = catalogue.get_json()["items"][0]
    bad_confirmation = client.post(
        f"/api/v1/platform/backups/{artifact['id']}/restore",
        json={"confirmation": "RECUPERAR"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "restore-backup-20260711"},
    )
    assert bad_confirmation.status_code == 422
    restore = client.post(
        f"/api/v1/platform/backups/{artifact['id']}/restore",
        json={"confirmation": f"RECUPERAR {artifact['backup_name']}"},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "restore-backup-20260711"},
    )
    assert restore.status_code == 202
    restore_id = restore.get_json()["operation_id"]
    assert restore.get_json()["status"] == "awaiting_approval"
    empty_claim = runner.invoke(args=["backup-agent", "claim-next", "--worker-id", "test-host"])
    assert empty_claim.exit_code == 0
    assert json.loads(empty_claim.output) == {"operation": None}
    approved = runner.invoke(
        args=[
            "backup-agent",
            "claim-restore",
            "--operation-id",
            restore_id,
            "--worker-id",
            "test-host",
        ]
    )
    assert approved.exit_code == 0, approved.output
    assert json.loads(approved.output)["operation"]["operation_type"] == "restore"
    restore_complete = runner.invoke(
        args=[
            "backup-agent",
            "complete",
            "--operation-id",
            restore_id,
            "--worker-id",
            "test-host",
            "--status",
            "succeeded",
        ]
    )
    assert restore_complete.exit_code == 0, restore_complete.output
    expired = runner.invoke(
        args=[
            "backup-agent",
            "mark-expired",
            "--backup-name",
            artifact["backup_name"],
        ]
    )
    assert expired.exit_code == 0, expired.output
    assert json.loads(expired.output)["transitioned"] is True
    replay_expired = runner.invoke(
        args=[
            "backup-agent",
            "mark-expired",
            "--backup-name",
            artifact["backup_name"],
        ]
    )
    assert replay_expired.exit_code == 0, replay_expired.output
    assert json.loads(replay_expired.output) == {
        **json.loads(expired.output),
        "transitioned": False,
    }
    missing_expired = runner.invoke(
        args=["backup-agent", "mark-expired", "--backup-name", "unknown-backup"]
    )
    assert missing_expired.exit_code == 0
    assert json.loads(missing_expired.output) == {
        "backup_name": "unknown-backup",
        "transitioned": False,
        "reason": "not_catalogued",
    }


def test_tenant_admin_invite_roles_last_owner_and_audit(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = auth_stack
    client = app.test_client()
    assert _login(client, "owner@example.test", auth_stack[2], ids["tenant"]).status_code == 200
    csrf = _csrf(client)
    invited = client.post(
        "/api/v1/tenant-admin/members",
        json={"email": "analyst@example.test", "name": "Analyst", "role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invited.status_code == 201
    member_id = invited.get_json()["id"]
    members = client.get("/api/v1/tenant-admin/members")
    assert members.status_code == 200
    invited_member = next(item for item in members.get_json()["items"] if item["id"] == member_id)
    assert invited_member["roles"] == ["viewer"]
    assert client.get("/api/v1/tenant-admin/roles").status_code == 200
    assert (
        client.patch(
            f"/api/v1/tenant-admin/members/{member_id}/roles",
            json={"roles": ["analyst"]},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 200
    )
    members = client.get("/api/v1/tenant-admin/members").get_json()["items"]
    assert next(item for item in members if item["id"] == member_id)["roles"] == ["analyst"]
    assert (
        client.post(
            f"/api/v1/tenant-admin/members/{member_id}/resend-invite",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/tenant-admin/members/{ids['membership']}", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/api/v1/tenant-admin/members/{ids['membership']}",
            json={"status": "suspended"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 409
    )
    assert client.get("/api/v1/tenant-admin/audit").status_code == 200


def test_tenant_owner_can_inspect_and_check_provisioned_ai_policy(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        db.session.add(
            default_ai_policy(
                ids["tenant"],
                {"AI_ENABLED": True, "AI_MODE": "mock", "AI_DEFAULT_MODEL": "mock-oracle-v1"},
            )
        )
        db.session.commit()

    client = app.test_client()
    assert _login(client, "owner@example.test", password, ids["tenant"]).status_code == 200
    response = client.get("/api/v1/tenant-admin/ai-policy")
    assert response.status_code == 200
    assert response.get_json() == {
        "enabled": True,
        "provider": "mock",
        "allowed_models": ["mock-oracle-v1"],
        "kill_switch": False,
        "max_classification": "public",
        "limits": {
            "daily_calls": 100,
            "max_concurrency": 2,
            "max_context_tokens": 8000,
            "max_output_tokens": 6500,
            "monthly_soft_budget_micros": 0,
            "monthly_hard_budget_micros": 0,
        },
        "routing_authority": "oracle",
        "last_run": None,
        "last_error": None,
    }
    tested = client.post(
        "/api/v1/tenant-admin/ai-policy/test",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert tested.status_code == 200
    assert tested.get_json()["status"] == "disabled"


def test_permission_revocation_is_effective_for_an_open_session(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    assert _login(client, "owner@example.test", password, ids["tenant"]).status_code == 200
    assert "tenant.users.manage" in client.get("/api/v1/auth/me").get_json()["permissions"]

    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        with migrator.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM role_permissions "
                    "WHERE tenant_id=:tenant AND role_id=:role "
                    "AND permission_key='tenant.users.manage'"
                ),
                {"tenant": ids["tenant"], "role": ids["role"]},
            )

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert "tenant.users.manage" not in me.get_json()["permissions"]
        denied = client.get("/api/v1/tenant-admin/members")
        assert denied.status_code == 403
        assert denied.get_json()["code"] == "permission_denied"
    finally:
        with migrator.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO role_permissions (tenant_id,role_id,permission_key) "
                    "VALUES (:tenant,:role,'tenant.users.manage') "
                    "ON CONFLICT DO NOTHING"
                ),
                {"tenant": ids["tenant"], "role": ids["role"]},
            )
        migrator.dispose()


def test_invitation_acceptance_is_one_time_and_enables_login(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    owner = app.test_client()
    assert _login(owner, "owner@example.test", password, ids["tenant"]).status_code == 200
    csrf = _csrf(owner)
    invited = owner.post(
        "/api/v1/tenant-admin/members",
        json={"email": "new-member@example.test", "name": "New Member", "role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invited.status_code == 201
    sender = app.extensions["email_sender"]
    url = sender.messages[-1].body.splitlines()[0].split(": ", 1)[1]
    raw = parse_qs(urlparse(url).query)["token"][0]
    newcomer = app.test_client()
    csrf = _csrf(newcomer)
    payload = {"token": raw, "new_password": "frase segura del nuevo miembro 2026"}
    assert (
        newcomer.post(
            "/api/v1/auth/accept-invitation",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 204
    )
    assert (
        newcomer.post(
            "/api/v1/auth/accept-invitation",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 400
    )
    assert (
        _login(
            newcomer,
            "new-member@example.test",
            "frase segura del nuevo miembro 2026",
            ids["tenant"],
        ).status_code
        == 200
    )


def test_change_password_logout_and_suspended_tenant_expire_session(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    assert _login(client, "owner@example.test", password, ids["tenant"]).status_code == 200
    csrf = _csrf(client)
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": password, "new_password": "contraseña renovada segura 2026"},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 204
    csrf = _csrf(client)
    assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        _login(
            client, "owner@example.test", "contraseña renovada segura 2026", ids["tenant"]
        ).status_code
        == 200
    )
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE tenants SET status='suspended' WHERE id=:id"), {"id": ids["tenant"]}
        )
    migrator.dispose()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_invitation_and_reset_are_rejected_without_side_effects(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    owner = app.test_client()
    assert _login(owner, "owner@example.test", password, ids["tenant"]).status_code == 200
    csrf = _csrf(owner)
    response = owner.post(
        "/api/v1/tenant-admin/members",
        json={"email": "expired-invite@example.test", "name": "Expired", "role": "viewer"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201
    sender = app.extensions["email_sender"]
    invitation_url = sender.messages[-1].body.splitlines()[0].split(": ", 1)[1]
    invitation_token = parse_qs(urlparse(invitation_url).query)["token"][0]

    assert (
        owner.post(
            "/api/v1/auth/forgot-password",
            json={"email": "owner@example.test"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 204
    )
    _dispatch_password_reset(app)
    reset_url = sender.messages[-1].body.splitlines()[0].split(": ", 1)[1]
    reset_token = parse_qs(urlparse(reset_url).query)["token"][0]

    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text(
                "UPDATE invitations SET expires_at=now()-interval '1 second' "
                "WHERE token_hash=:digest"
            ),
            {"digest": hashlib.sha256(invitation_token.encode()).digest()},
        )
        connection.execute(
            text(
                "UPDATE password_reset_tokens SET expires_at=now()-interval '1 second' "
                "WHERE token_hash=:digest"
            ),
            {"digest": hashlib.sha256(reset_token.encode()).digest()},
        )
    migrator.dispose()

    anonymous = app.test_client()
    csrf = _csrf(anonymous)
    assert (
        anonymous.post(
            "/api/v1/auth/accept-invitation",
            json={"token": invitation_token, "new_password": "frase que no debe aplicarse 2026"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 400
    )
    assert (
        anonymous.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "frase que tampoco debe aplicarse 2026"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 400
    )
    assert (
        _login(app.test_client(), "owner@example.test", password, ids["tenant"]).status_code == 200
    )


def test_platform_patch_invite_owner_users_and_cli_bootstrap(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    client = app.test_client()
    assert _login(client, "super@example.test", password).status_code == 200
    csrf = _csrf(client)
    patched = client.patch(
        f"/api/v1/platform/tenants/{ids['tenant']}",
        json={"name": "Auth Tenant Renombrado", "plan": "enterprise"},
        headers={"X-CSRF-Token": csrf},
    )
    assert patched.status_code == 200
    invited = client.post(
        f"/api/v1/platform/tenants/{ids['tenant']}/invite-owner",
        json={"email": "platform-owner@example.test", "name": "Platform Owner"},
        headers={"X-CSRF-Token": csrf},
    )
    assert invited.status_code == 201
    assert client.get("/api/v1/platform/users").status_code == 200

    runner = app.test_cli_runner()
    secret = "frase bootstrap segura 2026"
    result = runner.invoke(
        args=[
            "admin",
            "bootstrap-superadmin",
            "--email",
            "bootstrap@example.test",
            "--name",
            "Bootstrap",
        ],
        input=f"{secret}\n{secret}\n",
    )
    assert result.exit_code == 0
    assert secret not in result.output
    duplicate = runner.invoke(
        args=[
            "admin",
            "bootstrap-superadmin",
            "--email",
            "bootstrap@example.test",
            "--name",
            "Bootstrap",
        ]
    )
    assert duplicate.exit_code != 0


def test_idle_absolute_expiry_current_revoke_disabled_user_and_global_audit_boundary(
    auth_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, password = auth_stack
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    for expiry_column in ("idle_expires_at", "absolute_expires_at"):
        client = app.test_client()
        login = _login(client, "owner@example.test", password, ids["tenant"])
        assert login.status_code == 200
        with migrator.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE user_sessions SET {expiry_column}=now()-interval '1 second' "
                    "WHERE id=:id"
                ),
                {"id": uuid.UUID(login.get_json()["session_id"])},
            )
        assert client.get("/api/v1/auth/me").status_code == 401

    client = app.test_client()
    login = _login(client, "owner@example.test", password, ids["tenant"])
    current_id = login.get_json()["session_id"]
    csrf = _csrf(client)
    assert (
        client.delete(
            f"/api/v1/auth/sessions/{current_id}", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401

    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE users SET status='disabled' WHERE id=:id"), {"id": ids["user"]}
        )
    assert (
        _login(app.test_client(), "owner@example.test", password, ids["tenant"]).status_code == 401
    )
    migrator.dispose()

    runtime = create_engine(os.environ["TEST_RUNTIME_DATABASE_URL"])
    with pytest.raises(DBAPIError), runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.actor_id',:actor,true)"),
            {"actor": str(ids["user"])},
        )
        connection.execute(text("SELECT * FROM oracle_read_global_audit(10)"))
    with pytest.raises(DBAPIError), runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.actor_id',:actor,true)"),
            {"actor": str(ids["user"])},
        )
        connection.execute(
            text(
                "SELECT oracle_append_global_audit('auth.test','authentication','failure',"
                ":spoof,NULL,'{}'::jsonb,NULL,NULL)"
            ),
            {"spoof": ids["super"]},
        )
    with pytest.raises(DBAPIError), runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.actor_id',:actor,true)"),
            {"actor": str(ids["user"])},
        )
        connection.execute(
            text(
                "SELECT oracle_append_global_audit('auth.test','authentication','failure',"
                "NULL,NULL,'{}'::jsonb,NULL,NULL)"
            )
        )
    runtime.dispose()
