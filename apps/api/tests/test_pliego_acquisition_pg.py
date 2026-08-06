"""HTTP + PostgreSQL real for G-11 pliego acquisition / manual PCAP.

Requires disposable local PG:

  ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL
  TEST_REDIS_URL
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from flask import g
from flask_migrate import upgrade
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from opn_oracle import create_app
from opn_oracle.auth import permissions
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.documents.storage import LocalObjectStorage
from opn_oracle.oracle import pliego_acquisition_routes
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci")


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
    redis_url = os.getenv("TEST_REDIS_URL") or "redis://127.0.0.1:6379/15"
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url:
        detail = "TEST_DATABASE_URL required for pliego-acquisition PG HTTP gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    return (
        _assert_disposable(migration_url, env_name="TEST_DATABASE_URL"),
        _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL"),
        redis_url,
    )


@contextmanager
def _authenticated_http(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    perms: frozenset[str] | None = None,
) -> Iterator[None]:
    granted = perms or frozenset(
        {
            "documents.read",
            "documents.manage",
            "dossier.read",
            "dossier.write",
            "opportunity.read",
            "opportunity.write",
        }
    )
    principal = type("Principal", (), {"id": user_id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(pliego_acquisition_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda _user_id, _active_tenant_id: granted,
    )
    before = app.before_request_funcs.get(None, [])
    index = next(
        (
            i
            for i, function in enumerate(before)
            if getattr(function, "__name__", "") == "protect_csrf_and_install_identity"
        ),
        None,
    )
    original = before[index] if index is not None else None

    def install_identity() -> None:
        g.active_tenant_id = tenant_id
        manager = tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id))
        manager.__enter__()
        g.auth_tenant_context_manager = manager

    if index is not None:
        before[index] = install_identity
    else:
        app.before_request_funcs[None] = [install_identity, *before]
    try:
        yield
    finally:
        if index is not None and original is not None:
            before[index] = original
        else:
            app.before_request_funcs[None] = before


@pytest.fixture
def pliego_pg(tmp_path: Path) -> Iterator[tuple[Any, dict[str, uuid.UUID]]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG pliego gates")
    migration_url, runtime_url, redis_url = _require_pg_urls()
    storage = tmp_path / "docs"
    storage.mkdir()

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g11-pliego-acquisition-secret-key-32bx",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "OPENAPI_ENABLED": False,
            "DOCUMENTS_ENABLED": True,
            "DOCUMENT_STORAGE_BACKEND": "local",
            "DOCUMENT_LOCAL_ROOT": str(storage),
            "DOCUMENT_SCANNER_MODE": "noop",
            "DOCUMENT_MAX_BYTES": 5 * 1024 * 1024,
            "DOCUMENT_TENANT_QUOTA_BYTES": 50 * 1024 * 1024,
            "CELERY_TASK_ALWAYS_EAGER": True,
            "RATELIMIT_ENABLED": False,
        }
    )
    app.extensions["object_storage"] = LocalObjectStorage(storage)
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    membership_a = uuid.uuid4()
    membership_b = uuid.uuid4()
    role_a = uuid.uuid4()
    role_b = uuid.uuid4()
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    password = "g11-pliego-2026!!"
    ph = PasswordHasher().hash(password)
    now = datetime.now(UTC)

    engine = create_engine(migration_url, poolclass=NullPool)
    with engine.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"g11-a-{tenant_a.hex[:8]}", "G11 A"),
            (tenant_b, f"g11-b-{tenant_b.hex[:8]}", "G11 B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES "
                    "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
                ),
                {"id": tid, "slug": slug, "name": name},
            )
        for uid, email, display in (
            (user_a, f"g11-a-{user_a.hex[:8]}@example.test", "G11 Owner A"),
            (user_b, f"g11-b-{user_b.hex[:8]}@example.test", "G11 Owner B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO users(id, email, display_name, password_hash, status, "
                    "email_verified_at, created_at, updated_at) VALUES "
                    "(:id, :email, :dn, :ph, 'active', now(), now(), now())"
                ),
                {"id": uid, "email": email, "dn": display, "ph": ph},
            )
        for wid, tid, slug in (
            (workspace_a, tenant_a, f"ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"ws-b-{workspace_b.hex[:6]}"),
        ):
            conn.execute(
                text(
                    "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                    "settings, created_at, updated_at) VALUES "
                    "(:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
                ),
                {"id": wid, "t": tid, "slug": slug, "name": f"WS {slug}"},
            )
        for mid, tid, uid in (
            (membership_a, tenant_a, user_a),
            (membership_b, tenant_b, user_b),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenant_memberships(id, tenant_id, user_id, status, accepted_at, "
                    "settings, created_at, updated_at) VALUES "
                    "(:id, :t, :u, 'active', now(), '{}'::jsonb, now(), now())"
                ),
                {"id": mid, "t": tid, "u": uid},
            )
        for rid, tid in ((role_a, tenant_a), (role_b, tenant_b)):
            conn.execute(
                text(
                    "INSERT INTO roles(id, tenant_id, key, name, description, is_system, "
                    "created_at, updated_at) VALUES "
                    "(:id, :t, 'owner', 'Owner', 'Owner', true, now(), now())"
                ),
                {"id": rid, "t": tid},
            )
            conn.execute(
                text(
                    "INSERT INTO membership_roles(tenant_id, membership_id, role_id) "
                    "VALUES (:t, :m, :r)"
                ),
                {
                    "t": tid,
                    "m": membership_a if tid == tenant_a else membership_b,
                    "r": rid,
                },
            )
            # Grant all permissions if table is populated by migrations/seed
            conn.execute(
                text(
                    "INSERT INTO role_permissions(tenant_id, role_id, permission_key) "
                    "SELECT :t, :r, key FROM permissions ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "r": rid},
            )
        for did, tid, wid, uid, title in (
            (dossier_a, tenant_a, workspace_a, user_a, "G11 dossier A"),
            (dossier_b, tenant_b, workspace_b, user_b, "G11 dossier B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO strategic_dossiers("
                    "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                    "strategic_goal, geography, sectors, languages, owner_user_id, "
                    "scoring_config, profile_config, health_score, opportunity_score, "
                    "risk_score, score_explanation, version, synthetic_data, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :w, :title, '', 'procurement', 'active', '', '[]'::jsonb, "
                    "'[]'::jsonb, '[]'::jsonb, :u, '{}'::jsonb, '{}'::jsonb, 50, 0, 0, "
                    "'{}'::jsonb, 1, false, :now, :now)"
                ),
                {
                    "id": did,
                    "t": tid,
                    "w": wid,
                    "title": title,
                    "u": uid,
                    "now": now,
                },
            )
    engine.dispose()

    ids = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "dossier_a": dossier_a,
        "dossier_b": dossier_b,
    }
    yield app, ids


def test_pg_no_pins_no_disponible_and_manual_upload(
    pliego_pg: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = pliego_pg
    client = app.test_client()
    dossier_id = ids["dossier_a"]
    tenant_id = ids["tenant_a"]
    user_id = ids["user_a"]

    with app.app_context(), _authenticated_http(
        app, monkeypatch, user_id=user_id, tenant_id=tenant_id
    ):
        resp = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["overall_status"] == "no_disponible"
        assert body["manual_upload_offered"] is True
        assert body["cta"]["label"] == "Subir PCAP"
        assert body["overall_reason_code"] in {"no_pins", "signal_documents_empty"}

        # Manual PCAP as text (pipeline real processes text cleanly)
        payload = (
            "EXTRACTO DEL PCAP · CONTR 2026 G11\n"
            "Criterios de adjudicacion y solvencia tecnica.\n"
        ).encode()
        up = client.post(
            f"/api/v1/dossiers/{dossier_id}/pliego-pcap",
            data={
                "classification": "internal",
                "file": (io.BytesIO(payload), "PCAP_G11_manual.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        assert up.status_code == 202, up.get_data(as_text=True)
        up_body = up.get_json()
        assert up_body["acquisition_status"] == "subido"
        assert up_body["document"]["filename"] == "PCAP_G11_manual.txt"
        assert up_body["job_id"]

        # Inspección vía migrator (BYPASSRLS) para no pelear con el contexto
        # de la sesión HTTP residual.
        migration_url, _, _ = _require_pg_urls()
        engine = create_engine(migration_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                audit_n = int(
                    conn.execute(
                        text(
                            "SELECT count(*) FROM audit_events "
                            "WHERE tenant_id = :t AND action = :a"
                        ),
                        {"t": tenant_id, "a": "document.pcap_manual_upload"},
                    ).scalar_one()
                )
                assert audit_n == 1
                meta_row = conn.execute(
                    text(
                        "SELECT metadata FROM audit_events "
                        "WHERE tenant_id = :t AND action = :a LIMIT 1"
                    ),
                    {"t": tenant_id, "a": "document.pcap_manual_upload"},
                ).scalar_one()
                assert meta_row.get("acquisition_status") == "subido"
                assert meta_row.get("priority") == "manual_over_auto"
                doc_n = int(
                    conn.execute(
                        text(
                            "SELECT count(*) FROM documents "
                            "WHERE tenant_id = :t AND dossier_id = :d"
                        ),
                        {"t": tenant_id, "d": dossier_id},
                    ).scalar_one()
                )
                assert doc_n == 1
                doc_meta = conn.execute(
                    text(
                        "SELECT metadata FROM documents "
                        "WHERE tenant_id = :t AND dossier_id = :d LIMIT 1"
                    ),
                    {"t": tenant_id, "d": dossier_id},
                ).scalar_one()
                assert doc_meta.get("source") == "manual_pcap"
                assert doc_meta.get("manual_pcap") is True
                assert (doc_meta.get("pliego_acquisition") or {}).get("status") == "subido"
        finally:
            engine.dispose()

        # No duplicate row on second check — same document
        resp2 = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert resp2.status_code == 200
        body2 = resp2.get_json()
        assert any(
            a.get("reason_code") == "manual_upload" or a.get("status") == "subido"
            for a in body2["acquisitions"]
        )


def test_pg_tenant_isolation_and_permission(
    pliego_pg: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids = pliego_pg
    client = app.test_client()

    with app.app_context():
        with _authenticated_http(
            app,
            monkeypatch,
            user_id=ids["user_b"],
            tenant_id=ids["tenant_b"],
        ):
            resp = client.get(
                f"/api/v1/dossiers/{ids['dossier_a']}/pliego-acquisition"
            )
            assert resp.status_code == 404

        with _authenticated_http(
            app,
            monkeypatch,
            user_id=ids["user_a"],
            tenant_id=ids["tenant_a"],
            perms=frozenset({"documents.read", "dossier.read"}),
        ):
            up = client.post(
                f"/api/v1/dossiers/{ids['dossier_a']}/pliego-pcap",
                data={
                    "file": (io.BytesIO(b"hola PCAP"), "x.txt", "text/plain"),
                },
                content_type="multipart/form-data",
            )
            assert up.status_code in {403, 401}
