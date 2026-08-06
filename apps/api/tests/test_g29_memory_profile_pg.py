"""G-29 · PostgreSQL disposable gates for honest DossierMemoryProfile.

Requires ORACLE_RUN_INTEGRATION=1 + TEST_DATABASE_URL disposable.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from opn_oracle import create_app
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.integrations.models import DossierMemoryProfile
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.service import DOSSIER_TYPES, create_dossier
from opn_oracle.platform.models import AuditEvent, Tenant, User, Workspace
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci", "g29")


def _assert_disposable(url: str, *, env_name: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0]
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "postgres", "pg"}:
        raise RuntimeError(f"{env_name} host={host!r} not disposable")
    if not db_name or not any(m in db_name.lower() for m in _DISPOSABLE_MARKERS):
        raise RuntimeError(f"{env_name} database={db_name!r} not disposable")
    return url


def _require_pg_urls() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL") or migration_url
    redis_url = os.getenv("TEST_REDIS_URL") or "redis://127.0.0.1:6379/14"
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url:
        detail = "TEST_DATABASE_URL required for G-29 memory PG gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    return (
        _assert_disposable(migration_url, env_name="TEST_DATABASE_URL"),
        _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL"),
        redis_url,
    )


@pytest.fixture
def g29_pg() -> Iterator[tuple[Any, str]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG G-29 gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "TESTING": True,
            "SECRET_KEY": "g29-memory-honest-profile-secret-key-32b",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "MEMORY_CONTEXT_MODE": "disabled",
            "AI_MODE": "mock",
            "AI_ENABLED": False,
            "OPENAPI_ENABLED": False,
            "RLS_ENABLED": True,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")
        yield app, migration_url
        db.session.remove()


def _seed_tenant_user(migration_url: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed via migrator role (BYPASSRLS) with raw SQL — same pattern as G-20-B."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    role_id = uuid.uuid4()
    hasher = PasswordHasher()
    ph = hasher.hash("G29 Test Password 2026!")
    engine = create_engine(migration_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES "
                "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
            ),
            {"id": tenant_id, "slug": f"g29-{tenant_id.hex[:8]}", "name": f"G29 {tenant_id.hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO users(id, email, display_name, password_hash, status, "
                "email_verified_at, created_at, updated_at) VALUES "
                "(:id, :email, :dn, :ph, 'active', now(), now(), now())"
            ),
            {
                "id": user_id,
                "email": f"g29-{user_id.hex[:8]}@oracle-test.local",
                "dn": "G29 Owner",
                "ph": ph,
            },
        )
        conn.execute(
            text(
                "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                "settings, created_at, updated_at) VALUES "
                "(:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
            ),
            {"id": ws_id, "t": tenant_id, "slug": f"ws-{ws_id.hex[:6]}", "name": "Default"},
        )
        conn.execute(
            text(
                "INSERT INTO tenant_memberships(id, tenant_id, user_id, status, accepted_at, "
                "settings, created_at, updated_at) VALUES "
                "(:id, :t, :u, 'active', now(), '{}'::jsonb, now(), now())"
            ),
            {"id": membership_id, "t": tenant_id, "u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO roles(id, tenant_id, key, name, description, is_system, "
                "created_at, updated_at) VALUES "
                "(:id, :t, 'owner', 'Owner', 'Owner', true, now(), now())"
            ),
            {"id": role_id, "t": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO membership_roles(tenant_id, membership_id, role_id) "
                "VALUES (:t, :m, :r)"
            ),
            {"t": tenant_id, "m": membership_id, "r": role_id},
        )
        conn.execute(
            text(
                "INSERT INTO role_permissions(tenant_id, role_id, permission_key) "
                "SELECT :t, :r, key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"t": tenant_id, "r": role_id},
        )
    engine.dispose()
    return tenant_id, user_id, ws_id


def _create_under_tenant(
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
    dossier_type: str = "custom",
    extra: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Create dossier; return durable id (survive expire_on_commit + RLS)."""
    from sqlalchemy import inspect as sa_inspect

    payload = {
        "title": title,
        "type": dossier_type,
        "strategic_goal": "G-29 gate",
        "initial_status": "draft",
        **(extra or {}),
    }
    with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
        d = create_dossier(db.session(), payload, actor_id=user_id)
        # expire_on_commit clears attrs; identity remains without SELECT.
        ident = sa_inspect(d).identity
        assert ident is not None
        return uuid.UUID(str(ident[0]))


@pytest.mark.integration
def test_pg_alta_atomica_crea_exactamente_un_perfil(g29_pg: tuple[Any, str]) -> None:
    app, migration_url = g29_pg
    with app.app_context():
        tenant_id, user_id, _ws = _seed_tenant_user(migration_url)
        # Relevant product types (competitive_intelligence needs full profile_config; covered via custom/market/project).
        types = ["custom", "market", "project", "tender_or_grant", "strategic_account"]
        for t in types:
            assert t in DOSSIER_TYPES
            d_id = _create_under_tenant(
                tenant_id=tenant_id,
                user_id=user_id,
                title=f"G29 {t} {uuid.uuid4().hex[:6]}",
                dossier_type=t,
                extra={
                    "memory_mode": "augment",
                    "memory_profile": {"mode": "augment"},
                },
            )
            with tenant_context(
                TenantContext(tenant_id=tenant_id, actor_id=user_id)
            ):
                count = db.session.scalar(
                    select(func.count())
                    .select_from(DossierMemoryProfile)
                    .where(
                        DossierMemoryProfile.tenant_id == tenant_id,
                        DossierMemoryProfile.dossier_id == d_id,
                    )
                )
                assert count == 1
                row = db.session.scalar(
                    select(DossierMemoryProfile).where(
                        DossierMemoryProfile.tenant_id == tenant_id,
                        DossierMemoryProfile.dossier_id == d_id,
                    )
                )
                assert row is not None
                assert row.mode == "disabled"
                assert row.profile_config.get("config_source") == "server_policy"
                assert row.profile_config.get("provenance") == "server_policy_on_create"


@pytest.mark.integration
def test_pg_profile_failure_rolls_back_dossier(
    g29_pg: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, migration_url = g29_pg
    with app.app_context():
        tenant_id, user_id, _ws = _seed_tenant_user(migration_url)

        def boom(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("forced profile failure")

        monkeypatch.setattr(
            "opn_oracle.integrations.memory_profile.create_dossier_memory_profile",
            boom,
        )
        with tenant_context(
            TenantContext(tenant_id=tenant_id, actor_id=user_id)
        ):
            before = db.session.scalar(
                select(func.count())
                .select_from(StrategicDossier)
                .where(StrategicDossier.tenant_id == tenant_id)
            )
        with pytest.raises(RuntimeError, match="forced profile failure"):
            _create_under_tenant(
                tenant_id=tenant_id,
                user_id=user_id,
                title="Should not exist",
            )
        db.session.rollback()
        with tenant_context(
            TenantContext(tenant_id=tenant_id, actor_id=user_id)
        ):
            after = db.session.scalar(
                select(func.count())
                .select_from(StrategicDossier)
                .where(StrategicDossier.tenant_id == tenant_id)
            )
            assert after == before
            mem_count = db.session.scalar(
                select(func.count())
                .select_from(DossierMemoryProfile)
                .where(DossierMemoryProfile.tenant_id == tenant_id)
            )
            assert mem_count == 0


@pytest.mark.integration
def test_pg_unique_dossier_profile_and_tenant_isolation(g29_pg: tuple[Any, str]) -> None:
    app, migration_url = g29_pg
    with app.app_context():
        t_a, u_a, _ = _seed_tenant_user(migration_url)
        t_b, u_b, _ = _seed_tenant_user(migration_url)
        d_a_id = _create_under_tenant(tenant_id=t_a, user_id=u_a, title="Tenant A dossier")
        d_b_id = _create_under_tenant(tenant_id=t_b, user_id=u_b, title="Tenant B dossier")
        db.session.expunge_all()

        from opn_oracle.integrations.memory_profile import create_dossier_memory_profile

        with tenant_context(TenantContext(tenant_id=t_a, actor_id=u_a)):
            create_dossier_memory_profile(db.session(), tenant_id=t_a, dossier_id=d_a_id)
            with pytest.raises(IntegrityError):
                db.session.commit()
            db.session.rollback()
            db.session.expunge_all()

        with tenant_context(TenantContext(tenant_id=t_b, actor_id=u_b)):
            foreign = db.session.scalar(
                select(DossierMemoryProfile).where(
                    DossierMemoryProfile.tenant_id == t_b,
                    DossierMemoryProfile.dossier_id == d_a_id,
                )
            )
            assert foreign is None
            own_b = db.session.scalar(
                select(DossierMemoryProfile).where(
                    DossierMemoryProfile.tenant_id == t_b,
                    DossierMemoryProfile.dossier_id == d_b_id,
                )
            )
            assert own_b is not None


@pytest.mark.integration
def test_pg_legacy_materialize_cas_stale_and_tenant_404(
    g29_pg: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """legacy_missing GET no write; materialize audited; stale ETag 409; other tenant 404."""
    app, migration_url = g29_pg
    with app.app_context():
        tenant_id, user_id, ws_id = _seed_tenant_user(migration_url)
        legacy_id = uuid.uuid4()
        engine = create_engine(migration_url)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO strategic_dossiers("
                    "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                    "strategic_goal, geography, sectors, languages, scoring_config, "
                    "health_score, opportunity_score, risk_score, score_explanation, "
                    "profile_config, owner_user_id, version, synthetic_data, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :w, :title, '', 'custom', 'draft', 'legacy', "
                    "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, "
                    "0, 0, 0, '{}'::jsonb, '{}'::jsonb, :u, 1, false, now(), now())"
                ),
                {
                    "id": legacy_id,
                    "t": tenant_id,
                    "w": ws_id,
                    "title": "Legacy without memory",
                    "u": user_id,
                },
            )
        engine.dispose()

        actor = User(
            id=user_id,
            email=f"g29-actor-{user_id.hex[:8]}@oracle-test.local",
            display_name="G29 Actor",
            status="active",
        )

        from flask import g as flask_g

        from opn_oracle.auth import permissions
        from opn_oracle.integrations import memory_routes

        monkeypatch.setattr(permissions, "current_user", actor)
        monkeypatch.setattr(memory_routes, "current_user", actor)
        monkeypatch.setattr(
            permissions,
            "current_permissions",
            lambda *_a, **_k: frozenset({"dossier.read", "dossier.write"}),
        )
        monkeypatch.setattr(
            memory_routes,
            "dossier_accessible",
            lambda *_a, **_k: True,
        )

        active_tenant_holder: dict[str, uuid.UUID] = {"id": tenant_id}
        before_request_funcs = app.before_request_funcs.get(None, [])
        auth_index = next(
            i
            for i, fn in enumerate(before_request_funcs)
            if fn.__name__ == "protect_csrf_and_install_identity"
        )
        original_auth = before_request_funcs[auth_index]

        def _install_identity() -> None:
            flask_g.active_tenant_id = active_tenant_holder["id"]

        before_request_funcs[auth_index] = _install_identity

        def _status_and_json(result: Any) -> tuple[int, Any]:
            if isinstance(result, tuple):
                resp, status = result[0], int(result[1])
                return status, resp.get_json()
            return int(result.status_code), result.get_json()

        try:
            with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
                # GET legacy: no write
                with app.test_request_context(
                    f"/api/v1/dossiers/{legacy_id}/memory/profile"
                ):
                    flask_g.active_tenant_id = tenant_id
                    status, body = _status_and_json(
                        memory_routes.get_memory_profile(legacy_id)
                    )
                assert status == 200
                assert body["status"] == "legacy_missing"
                assert body["persisted"] is False
                count = db.session.scalar(
                    select(func.count())
                    .select_from(DossierMemoryProfile)
                    .where(DossierMemoryProfile.dossier_id == legacy_id)
                )
                assert count == 0

                with app.test_request_context(
                    f"/api/v1/dossiers/{legacy_id}/memory/profile/materialize",
                    method="POST",
                    json={"reason": "pg-gate"},
                ):
                    flask_g.active_tenant_id = tenant_id
                    status, mat_body = _status_and_json(
                        memory_routes.materialize_memory_profile(legacy_id)
                    )
                assert status == 201, mat_body
                assert mat_body["persisted"] is True
                assert mat_body["mode"] == "disabled"
                etag = mat_body["etag"]
                version = mat_body["version"]

                with app.test_request_context(
                    f"/api/v1/dossiers/{legacy_id}/memory/profile",
                    method="PUT",
                    json={"mode": "shadow", "expected_version": version},
                    headers={"If-Match": 'W/"stale"'},
                ):
                    flask_g.active_tenant_id = tenant_id
                    status, stale_body = _status_and_json(
                        memory_routes.put_memory_profile(legacy_id)
                    )
                assert status == 409, stale_body

                with app.test_request_context(
                    f"/api/v1/dossiers/{legacy_id}/memory/profile",
                    method="PUT",
                    json={"mode": "shadow", "expected_version": version, "reason": "pg-ok"},
                    headers={"If-Match": etag},
                ):
                    flask_g.active_tenant_id = tenant_id
                    status, ok_body = _status_and_json(
                        memory_routes.put_memory_profile(legacy_id)
                    )
                assert status == 200, ok_body
                assert ok_body["mode"] == "shadow"
                assert ok_body["version"] == version + 1

            # Close transaction before switching tenant context (RLS guard).
            db.session.rollback()
            db.session.remove()

            # Other tenant 404
            other_tenant = uuid.uuid4()
            with tenant_context(
                TenantContext(tenant_id=other_tenant, actor_id=user_id)
            ):
                with app.test_request_context(
                    f"/api/v1/dossiers/{legacy_id}/memory/profile"
                ):
                    flask_g.active_tenant_id = other_tenant
                    status, foreign_body = _status_and_json(
                        memory_routes.get_memory_profile(legacy_id)
                    )
                assert status == 404, foreign_body
        finally:
            before_request_funcs[auth_index] = original_auth

        engine = create_engine(migration_url)
        with engine.connect() as conn:
            actions = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT action FROM audit_events WHERE tenant_id = :t "
                        "AND resource_type = 'dossier_memory_profile'"
                    ),
                    {"t": tenant_id},
                )
            ]
        engine.dispose()
        assert "dossier.memory_profile.materialize" in actions
        assert "dossier.memory_profile.update" in actions
