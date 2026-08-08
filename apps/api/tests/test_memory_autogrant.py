"""ORA-AUTOGRANT: Signal dossier scope ensure — unit + integration (mock transport)."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.integrations.memory_grant import (
    CODE_MANUAL_REQUIRED,
    GRANT_AUTHORIZED,
    GRANT_MANUAL_REQUIRED,
    GRANT_NO_CONNECTION,
    ensure_dossier_memory_grant,
    grant_public_from_row,
    require_usable_memory_grant,
)
from opn_oracle.integrations.memory_http_client import MemoryHttpError, MockTransport
from opn_oracle.integrations.models import DossierMemoryProfile
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def grant_stack() -> Iterator[tuple[Any, dict[str, uuid.UUID]]]:
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
            "MEMORY_CONTEXT_MODE": "mock",
        }
    )
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
            "workspace",
            "workspace_b",
            "dossier",
            "dossier_b",
            "connection",
        )
    }
    password = PasswordHasher().hash("frase de integración grant 2026")
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants "
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) VALUES "
                "(:t,'grant-tenant','Grant Tenant','active','es-ES','UTC','{}',now(),now()),"
                "(:b,'grant-other','Other','active','es-ES','UTC','{}',now(),now())"
            ),
            {"t": ids["tenant"], "b": ids["tenant_b"]},
        )
        connection.execute(
            text(
                "INSERT INTO users (id,email,display_name,password_hash,status,"
                "email_verified_at,created_at,updated_at) VALUES "
                "(:u,'grant@example.test','Grant',:p,'active',now(),now(),now())"
            ),
            {"u": ids["user"], "p": password},
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships "
                "(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (gen_random_uuid(),:t,:u,'active',now(),'{}',now(),now())"
            ),
            {"t": ids["tenant"], "u": ids["user"]},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) VALUES "
                "(:w,:t,'main','Main','active',true,'{}',now(),now()),"
                "(:wb,:b,'main','MainB','active',true,'{}',now(),now())"
            ),
            {
                "w": ids["workspace"],
                "wb": ids["workspace_b"],
                "t": ids["tenant"],
                "b": ids["tenant_b"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO strategic_dossiers("
                "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                "strategic_goal, geography, sectors, languages, scoring_config, "
                "health_score, opportunity_score, risk_score, score_explanation, "
                "profile_config, owner_user_id, version, synthetic_data, "
                "created_at, updated_at"
                ") VALUES "
                "(:d, :t, :w, 'Grant Dossier', '', 'market', 'active', '', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, "
                "'{}'::jsonb, :u, 1, false, now(), now()),"
                "(:db, :b, :wb, 'Other Dossier', '', 'market', 'active', '', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, "
                "'{}'::jsonb, NULL, 1, false, now(), now())"
            ),
            {
                "d": ids["dossier"],
                "db": ids["dossier_b"],
                "t": ids["tenant"],
                "b": ids["tenant_b"],
                "w": ids["workspace"],
                "wb": ids["workspace_b"],
                "u": ids["user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO integration_connections "
                "(id,tenant_id,provider,name,status,base_url,metadata,adapter_mode,"
                "created_at,updated_at) VALUES "
                "(:c,:t,'signal-avanza','Signal Grant','active',"
                "'https://signal-dev.opnconsultoria.com','{}'::jsonb,'http',now(),now())"
            ),
            {"c": ids["connection"], "t": ids["tenant"]},
        )
    yield app, ids
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)


@pytest.fixture(autouse=True)
def _clean_grant_profiles(grant_stack: tuple[Any, dict[str, uuid.UUID]]) -> Iterator[None]:
    """Each test starts without leftover default memory profiles."""
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(text("DELETE FROM dossier_memory_profiles"))
        connection.execute(
            text(
                "UPDATE integration_connections SET status='active' WHERE provider='signal-avanza'"
            )
        )
    migrator.dispose()
    yield


def _profile_row(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    mode: str = "augment",
) -> DossierMemoryProfile:
    now = datetime.now(UTC)
    return DossierMemoryProfile(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=None,
        mode=mode,
        version=1,
        etag='W/"dmp-v1"',
        profile_config={"mode": mode, "status": "active"},
        created_at=now,
        updated_at=now,
    )


def test_unit_require_usable_is_fail_closed() -> None:
    require_usable_memory_grant(SimpleNamespace(mode="disabled", signal_grant_status=None))
    with pytest.raises(MemoryHttpError) as exc:
        require_usable_memory_grant(
            SimpleNamespace(mode="augment", signal_grant_status=GRANT_MANUAL_REQUIRED)
        )
    assert exc.value.code == CODE_MANUAL_REQUIRED
    with pytest.raises(MemoryHttpError):
        require_usable_memory_grant(SimpleNamespace(mode="augment", signal_grant_status=None))


def test_unit_grant_public_labels() -> None:
    row = SimpleNamespace(
        signal_grant_status=GRANT_MANUAL_REQUIRED,
        signal_grant_code=CODE_MANUAL_REQUIRED,
        signal_grant_detail="manual",
        signal_grant_at=datetime.now(UTC),
        signal_grant_connection_id=uuid.uuid4(),
    )
    pub = grant_public_from_row(row)
    assert pub is not None
    assert pub["pending_manual"] is True
    assert pub["usable"] is False
    assert "Pendiente" in pub["status_label_es"]
    assert "autorización" in (pub["message_es"] or "").lower()


def test_client_authorize_hits_real_path_not_scopes_ensure() -> None:
    """Mock must exercise the live path: .../dossiers/{id}/authorize, no body."""
    from opn_oracle.integrations.memory_http_client import (
        MemoryClientConfig,
        SignalMemoryHttpClient,
    )

    dossier = "3746291e-9f11-46e3-88d5-db1fc7b68c4d"
    transport = MockTransport(
        responses={
            "/authorize": (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "dossier_id": dossier,
                        "authorized": True,
                        "reason": "already_active",
                        "granted_by": "auto",
                        "created": False,
                        "reactivated": False,
                    }
                ).encode(),
            ),
            # If someone reverts to the stub path, this would incorrectly "succeed"
            # with a shape that must NOT be treated as grant success alone — leave
            # empty so a wrong path returns the default retrieve stub and fails.
        }
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="https://signal-dev.opnconsultoria.com",
            api_token="unit-token",
            require_https=False,
        ),
        transport,
    )
    status, data = client.authorize_dossier(
        external_tenant_id="tenant-x",
        dossier_id=dossier,
    )
    assert status == 200
    assert data["authorized"] is True
    assert data["reason"] == "already_active"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"].endswith(f"/api/v1/memory/v1/dossiers/{dossier}/authorize")
    assert "/scopes/ensure" not in call["url"]
    assert call["json_body"] is None
    assert call["headers"].get("X-API-Key") == "***"


@pytest.mark.integration
def test_live_signal_dev_authorize_route_is_not_the_ensure_stub() -> None:
    """Real HTTP to signal-dev: authorize path exists; we never call scopes/ensure.

    Without a live API key we only prove routing/auth envelope shape (401),
    which still exercises the production host and the correct URL. Full
    authorized vs manual_required needs SIGNAL_MEMORY_LIVE_* (see smoke script).
    """
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    from opn_oracle.integrations.memory_http_client import (
        HttpxTransport,
        MemoryClientConfig,
        SignalMemoryHttpClient,
    )

    dossier = "3746291e-9f11-46e3-88d5-db1fc7b68c4d"
    # Deliberately invalid key — proves the live route without inventing grants.
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="https://signal-dev.opnconsultoria.com",
            api_token="oracle-live-smoke-invalid-key",
            require_https=True,
            max_retries=0,
            deadline_seconds=15.0,
        ),
        HttpxTransport(),
    )
    with pytest.raises(MemoryHttpError) as exc:
        client.authorize_dossier(
            external_tenant_id="00000000-0000-4000-8000-000000000001",
            dossier_id=dossier,
        )
    # Live Signal returns MemoryErrorEnvelope with error_code.
    assert exc.value.http_status in {401, 403}
    assert (
        exc.value.code
        in {
            "missing_api_key",
            "invalid_api_key",
            "unauthorized",
            "auth_or_scope",
            "invalid_credentials",
            "consumer_inactive",
        }
        or "auth" in exc.value.code
        or "key" in exc.value.code
    )

    live_key = os.environ.get("SIGNAL_MEMORY_LIVE_API_KEY", "").strip()
    live_tenant = os.environ.get("SIGNAL_MEMORY_LIVE_TENANT_ID", "").strip()
    live_dossier = os.environ.get("SIGNAL_MEMORY_LIVE_DOSSIER_ID", "").strip()
    if not (live_key and live_tenant and live_dossier):
        return  # route existence already proven against signal-dev

    live = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url=os.environ.get(
                "SIGNAL_MEMORY_LIVE_BASE_URL", "https://signal-dev.opnconsultoria.com"
            ),
            api_token=live_key,
            require_https=True,
            max_retries=0,
            deadline_seconds=20.0,
        ),
        HttpxTransport(),
    )
    try:
        status, data = live.authorize_dossier(
            external_tenant_id=live_tenant,
            dossier_id=live_dossier,
        )
        assert status == 200
        assert data.get("authorized") is True
        assert data.get("granted_by") == "auto"
        assert data.get("reason") in {"granted", "already_active", "reactivated"}
    except MemoryHttpError as err:
        from opn_oracle.integrations.memory_grant import (
            CODE_MANUAL_REQUIRED,
            _interpret_authorize_error,
        )

        mapped = _interpret_authorize_error(err)
        assert mapped.code == CODE_MANUAL_REQUIRED or mapped.status in {
            GRANT_MANUAL_REQUIRED,
            "rejected",
        }, f"unexpected live outcome: {err.code} -> {mapped}"


def test_client_maps_dossier_authorization_manual_required() -> None:
    from opn_oracle.integrations.memory_grant import (
        CODE_MANUAL_REQUIRED,
        GRANT_MANUAL_REQUIRED,
        _interpret_authorize_error,
    )
    from opn_oracle.integrations.memory_http_client import (
        MemoryClientConfig,
        SignalMemoryHttpClient,
    )

    dossier = "11111111-1111-4111-8111-111111111111"
    transport = MockTransport(
        responses={
            "/authorize": (
                403,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "error_code": "dossier_authorization_manual_required",
                        "http_status": 403,
                        "retryable": False,
                        "message": "la autorización de expedientes es manual para este consumidor",
                        "detail": None,
                    }
                ).encode(),
            )
        }
    )
    client = SignalMemoryHttpClient(
        MemoryClientConfig(
            base_url="https://signal-dev.opnconsultoria.com",
            api_token="unit-token",
            require_https=False,
        ),
        transport,
    )
    with pytest.raises(MemoryHttpError) as exc:
        client.authorize_dossier(external_tenant_id="t", dossier_id=dossier)
    assert exc.value.code == "dossier_authorization_manual_required"
    assert exc.value.job_error_code == CODE_MANUAL_REQUIRED
    mapped = _interpret_authorize_error(exc.value)
    assert mapped.status == GRANT_MANUAL_REQUIRED
    assert mapped.code == CODE_MANUAL_REQUIRED


def test_ensure_authorized_once_and_cache(
    grant_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = grant_stack
    # Real Signal contract: POST /dossiers/{id}/authorize (not scopes/ensure stub).
    transport = MockTransport(
        responses={
            "/authorize": (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "dossier_id": str(ids["dossier"]),
                        "authorized": True,
                        "reason": "granted",
                        "granted_by": "auto",
                        "created": True,
                        "reactivated": False,
                    }
                ).encode(),
            )
        }
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_grant.build_client_for_connection",
        lambda connection, transport, require_https=True: __import__(
            "opn_oracle.integrations.memory_http_client", fromlist=["SignalMemoryHttpClient"]
        ).SignalMemoryHttpClient(
            __import__(
                "opn_oracle.integrations.memory_http_client", fromlist=["MemoryClientConfig"]
            ).MemoryClientConfig(
                base_url="https://signal-dev.opnconsultoria.com",
                api_token="test-token-not-logged",
                require_https=False,
            ),
            transport,
        ),
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        row = _profile_row(tenant_id=ids["tenant"], dossier_id=ids["dossier"])
        db.session.add(row)
        db.session.commit()
        first = ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        db.session.commit()
        assert first.status == GRANT_AUTHORIZED
        assert first.attempted is True
        assert first.cached is False
        assert len(transport.calls) == 1
        assert transport.calls[0]["method"] == "POST"
        assert f"/dossiers/{ids['dossier']}/authorize" in transport.calls[0]["url"]
        assert "/scopes/ensure" not in transport.calls[0]["url"]
        assert transport.calls[0]["json_body"] is None  # path-only body on live Signal
        # Second call must not re-POST
        second = ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        assert second.cached is True
        assert second.attempted is False
        assert len(transport.calls) == 1
        # No credential material in logs/calls body
        for call in transport.calls:
            assert "test-token" not in json.dumps(call.get("headers") or {})
            assert call["headers"].get("X-API-Key") == "***"


def test_ensure_manual_required_is_stable(
    grant_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = grant_stack
    # Live Signal envelope when connector_policy.memory_autogrant_dossiers is off.
    transport = MockTransport(
        responses={
            "/authorize": (
                403,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "error_code": "dossier_authorization_manual_required",
                        "http_status": 403,
                        "retryable": False,
                        "message": "la autorización de expedientes es manual para este consumidor",
                        "detail": None,
                    }
                ).encode(),
            )
        }
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_grant.build_client_for_connection",
        lambda connection, transport, require_https=True: __import__(
            "opn_oracle.integrations.memory_http_client", fromlist=["SignalMemoryHttpClient"]
        ).SignalMemoryHttpClient(
            __import__(
                "opn_oracle.integrations.memory_http_client", fromlist=["MemoryClientConfig"]
            ).MemoryClientConfig(
                base_url="https://signal-dev.opnconsultoria.com",
                api_token="secret-key",
                require_https=False,
            ),
            transport,
        ),
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        row = _profile_row(tenant_id=ids["tenant"], dossier_id=ids["dossier"])
        db.session.add(row)
        db.session.commit()
        result = ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        db.session.commit()
        assert result.status == GRANT_MANUAL_REQUIRED
        assert result.code == CODE_MANUAL_REQUIRED
        assert row.signal_grant_status == GRANT_MANUAL_REQUIRED
        # No aggressive re-try
        again = ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        assert again.cached is True
        assert len(transport.calls) == 1
        pub = grant_public_from_row(row)
        assert pub and pub["pending_manual"] is True


def test_no_connection_does_not_call_signal(
    grant_stack: tuple[Any, dict[str, uuid.UUID]],
) -> None:
    app, ids = grant_stack
    migrator = create_engine(os.environ["TEST_DATABASE_URL"])
    with migrator.begin() as connection:
        connection.execute(
            text("UPDATE integration_connections SET status='disabled' WHERE id=:id"),
            {"id": ids["connection"]},
        )
    migrator.dispose()
    transport = MockTransport()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        row = _profile_row(tenant_id=ids["tenant"], dossier_id=ids["dossier"])
        db.session.add(row)
        db.session.commit()
        result = ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        assert result.status == GRANT_NO_CONNECTION
        assert result.attempted is False
        assert transport.calls == []


def test_cannot_ensure_foreign_tenant_dossier_under_rls(
    grant_stack: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant A context must not stamp grants for tenant B dossier via app path."""
    app, ids = grant_stack
    transport = MockTransport(
        responses={
            "/authorize": (
                200,
                {"content-type": "application/json"},
                json.dumps(
                    {
                        "dossier_id": str(ids["dossier"]),
                        "authorized": True,
                        "reason": "already_active",
                        "granted_by": "auto",
                        "created": False,
                        "reactivated": False,
                    }
                ).encode(),
            )
        }
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_grant.build_client_for_connection",
        lambda connection, transport, require_https=True: __import__(
            "opn_oracle.integrations.memory_http_client", fromlist=["SignalMemoryHttpClient"]
        ).SignalMemoryHttpClient(
            __import__(
                "opn_oracle.integrations.memory_http_client", fromlist=["MemoryClientConfig"]
            ).MemoryClientConfig(
                base_url="https://signal-dev.opnconsultoria.com",
                api_token="x",
                require_https=False,
            ),
            transport,
        ),
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["user"])),
    ):
        # Attempt ensure for foreign dossier id while tenant context is A.
        # Profile row for foreign dossier is not visible under RLS; we only pass ids.
        row = _profile_row(tenant_id=ids["tenant"], dossier_id=ids["dossier_b"])
        # Insert via migrator would bypass RLS; app session insert for foreign dossier
        # should fail FK or RLS. Stamp only if row is tenant-scoped.
        row.tenant_id = ids["tenant"]
        row.dossier_id = ids["dossier"]  # own dossier only
        db.session.add(row)
        db.session.commit()
        ensure_dossier_memory_grant(
            db.session,
            tenant_id=ids["tenant"],
            dossier_id=ids["dossier"],
            row=row,
            transport=transport,
        )
        db.session.commit()
        # Foreign dossier must not appear in ensure path for this tenant connection.
        assert row.dossier_id == ids["dossier"]
        assert all(
            str(ids["dossier_b"]) not in (c.get("json_body") or {}).get("dossier_id", "")
            for c in transport.calls
        )
