"""HTTP + PostgreSQL real for opportunity offer lifecycle (SV2-G10).

Covers migration FKs/RLS, auth, audit, tenant isolation, CAS race, and CRM
status separation. Requires disposable local PG:

  ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL
  TEST_REDIS_URL
"""

from __future__ import annotations

import os
import threading
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
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from opn_oracle import create_app
from opn_oracle.auth import permissions
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.oracle import offer_lifecycle_routes
from opn_oracle.oracle.models import Opportunity
from opn_oracle.oracle.offer_lifecycle import OpportunityOfferLifecycle
from opn_oracle.platform.models import AuditEvent
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci")
TABLE = "opportunity_offer_lifecycles"


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
        detail = "TEST_DATABASE_URL required for offer-lifecycle PG HTTP gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    migration_url = _assert_disposable(migration_url, env_name="TEST_DATABASE_URL")
    runtime_url = _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL")
    return migration_url, runtime_url, redis_url


@contextmanager
def _authenticated_http(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    perms: frozenset[str] | None = None,
) -> Iterator[None]:
    """Install server-owned identity without login rate limits (HTTP still real)."""

    granted = perms or frozenset(
        {
            "opportunity.read",
            "opportunity.write",
            "dossier.read",
            "dossier.write",
        }
    )
    principal = type("Principal", (), {"id": user_id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(offer_lifecycle_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: granted,
    )
    before = app.before_request_funcs.get(None, [])
    index = next(
        i
        for i, function in enumerate(before)
        if function.__name__ == "protect_csrf_and_install_identity"
    )
    original = before[index]

    def install_identity() -> None:
        g.active_tenant_id = tenant_id
        manager = tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id))
        manager.__enter__()
        g.auth_tenant_context_manager = manager

    before[index] = install_identity
    try:
        yield
    finally:
        before[index] = original


def _count_rows(migration_url: str, tenant_id: uuid.UUID) -> int:
    engine = create_engine(migration_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text(f"SELECT count(*) FROM {TABLE} WHERE tenant_id = :t"),
                    {"t": tenant_id},
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _count_audits(migration_url: str, tenant_id: uuid.UUID) -> int:
    engine = create_engine(migration_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM audit_events "
                        "WHERE tenant_id = :t "
                        "AND resource_type = 'opportunity_offer_lifecycle'"
                    ),
                    {"t": tenant_id},
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _json_headers() -> dict[str, str]:
    return {"Content-Type": "application/json"}


@pytest.fixture
def offer_lifecycle_pg() -> Iterator[tuple[Any, dict[str, Any]]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG offer-lifecycle gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g10-offer-lifecycle-secret-key-32bxx",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "OPENAPI_ENABLED": False,
        }
    )
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
    opp_a = uuid.uuid4()
    opp_b = uuid.uuid4()
    password = "g10-offer-lifecycle-2026"
    ph = PasswordHasher().hash(password)
    now = datetime.now(UTC)

    engine = create_engine(migration_url, poolclass=NullPool)
    with engine.begin() as conn:
        # Migration applied: table + FKs present (never drop constraints).
        fks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    f"WHERE conrelid = '{TABLE}'::regclass AND contype = 'f'"
                )
            )
        }
        for required in (
            "fk_ool_tenant",
            "fk_ool_dossier_tenant",
            "fk_ool_opportunity_tenant",
            "fk_ool_editor_membership",
        ):
            assert required in fks, f"missing FK {required} after migration"

        checks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    f"WHERE conrelid = '{TABLE}'::regclass AND contype = 'c'"
                )
            )
        }
        for required in (
            "ool_status",
            "ool_importe_non_negative",
            "ool_baja_range",
            "ool_motivo_exclusion",
        ):
            assert any(required in name for name in checks), f"missing check {required} in {checks}"

        rls = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                f"WHERE relname = '{TABLE}'"
            )
        ).one()
        assert rls[0] is True and rls[1] is True

        for tid, slug, name in (
            (tenant_a, f"g10-a-{tenant_a.hex[:8]}", "G10 A"),
            (tenant_b, f"g10-b-{tenant_b.hex[:8]}", "G10 B"),
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
            (user_a, f"g10-a-{user_a.hex[:8]}@example.test", "G10 Owner A"),
            (user_b, f"g10-b-{user_b.hex[:8]}@example.test", "G10 Owner B"),
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
        for tid, mid, rid in (
            (tenant_a, membership_a, role_a),
            (tenant_b, membership_b, role_b),
        ):
            conn.execute(
                text(
                    "INSERT INTO membership_roles(tenant_id, membership_id, role_id) "
                    "VALUES (:t, :m, :r)"
                ),
                {"t": tid, "m": mid, "r": rid},
            )
            conn.execute(
                text(
                    "INSERT INTO role_permissions(tenant_id, role_id, permission_key) "
                    "SELECT :t, :r, key FROM permissions ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "r": rid},
            )
        for did, tid, wid, uid, title in (
            (dossier_a, tenant_a, workspace_a, user_a, "Expediente G10 A"),
            (dossier_b, tenant_b, workspace_b, user_b, "Expediente G10 B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO strategic_dossiers("
                    "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                    "strategic_goal, geography, sectors, languages, scoring_config, "
                    "health_score, opportunity_score, risk_score, score_explanation, "
                    "profile_config, owner_user_id, version, synthetic_data, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :w, :title, '', 'opportunity', 'active', '', '[]'::jsonb, "
                    "'[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, "
                    "'{}'::jsonb, :u, 1, false, now(), now()"
                    ")"
                ),
                {"id": did, "t": tid, "w": wid, "title": title, "u": uid},
            )
        # Opportunities with CRM status identified (must stay untouched by offer lifecycle).
        for oid, tid, did, title in (
            (opp_a, tenant_a, dossier_a, "Licitación G10 A"),
            (opp_b, tenant_b, dossier_b, "Licitación G10 B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO opportunities("
                    "id, tenant_id, dossier_id, opportunity_type, status, title, description, "
                    "strategic_fit, urgency, expected_value, actionability, relationship_leverage, "
                    "timing, effort, blocking_risk, confidence, overall_score, score_details, "
                    "next_action, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :d, 'tender', 'identified', :title, '', "
                    "50, 50, 50, 50, 50, 50, 50, 50, 50, 50, '{}'::jsonb, "
                    "'', 1, :now, :now"
                    ")"
                ),
                {"id": oid, "t": tid, "d": did, "title": title, "now": now},
            )
    engine.dispose()

    ctx = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "dossier_a": dossier_a,
        "dossier_b": dossier_b,
        "opp_a": opp_a,
        "opp_b": opp_b,
        "email_a": f"g10-a-{user_a.hex[:8]}@example.test",
        "email_b": f"g10-b-{user_b.hex[:8]}@example.test",
        "password": password,
        "migration_url": migration_url,
    }
    yield app, ctx

    cleanup = create_engine(migration_url, poolclass=NullPool)
    with cleanup.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {TABLE} WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM audit_events WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM opportunities WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM strategic_dossiers WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM membership_roles WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM role_permissions WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM roles WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM tenant_memberships WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM workspaces WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"),
            {"a": user_a, "b": user_b},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
    cleanup.dispose()


def _path(dossier_id: uuid.UUID, opp_id: uuid.UUID) -> str:
    return f"/api/v1/dossiers/{dossier_id}/opportunities/{opp_id}/offer-lifecycle"


def test_read_only_get_is_safe_no_row_no_audit(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1: opportunity.read only, missing row → 200 virtual, zero rows/audits."""

    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    before_rows = _count_rows(ctx["migration_url"], ctx["tenant_a"])
    before_audits = _count_audits(ctx["migration_url"], ctx["tenant_a"])
    assert before_rows == 0
    assert before_audits == 0

    read_only = frozenset({"opportunity.read", "dossier.read"})
    with _authenticated_http(
        app,
        monkeypatch,
        user_id=ctx["user_a"],
        tenant_id=ctx["tenant_a"],
        perms=read_only,
    ):
        get_resp = client.get(path)
        assert get_resp.status_code == 200, get_resp.get_data(as_text=True)
        body = get_resp.get_json()
        assert body["materialized"] is False
        life = body["lifecycle"]
        assert life["materialized"] is False
        assert life["version"] == 0
        assert life["id"] is None
        assert life["last_edited_by_user_id"] is None
        assert life["created_at"] is None
        assert life["updated_at"] is None
        assert life["status"] == "preparando"
        assert life["importe_ofertado"] is None
        assert life["lotes"] == []
        assert "CRM" in life["crm_status_note"] or "crm" in life["crm_status_note"].lower()

        # Repeated GET still zero writes.
        assert client.get(path).status_code == 200
        assert client.get(path).get_json()["materialized"] is False

        # Concurrent GETs still zero writes.
        results: list[int] = []
        barrier = threading.Barrier(2, timeout=30)

        def worker() -> None:
            barrier.wait()
            resp = client.get(path)
            results.append(resp.status_code)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert results == [200, 200]

    assert _count_rows(ctx["migration_url"], ctx["tenant_a"]) == 0
    assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == 0


def test_first_write_materializes_once_and_crm_isolation(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3+R6: first write version=0 materializes one row + create audit; CRM intact."""

    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])

    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        get_resp = client.get(path)
        assert get_resp.status_code == 200
        assert get_resp.get_json()["materialized"] is False
        assert get_resp.get_json()["lifecycle"]["version"] == 0
        assert _count_rows(ctx["migration_url"], ctx["tenant_a"]) == 0

        with app.app_context(), tenant_context(
            TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])
        ):
            opp = db.session.get(Opportunity, ctx["opp_a"])
            assert opp is not None
            assert opp.status == "identified"

        # First write with logical version 0 materialises.
        patch = client.patch(
            path,
            json={
                "version": 0,
                "status": "presentada",
                "importe_ofertado": "125000.50",
                "baja_porcentaje": "3.25",
                "lotes": ["Lote 1", "Lote 2"],
                "garantia_provisional": "2500",
                "fecha_mesa": "2026-10-15",
            },
            headers=_json_headers(),
        )
        assert patch.status_code == 200, patch.get_data(as_text=True)
        body = patch.get_json()
        assert body["materialized"] is True
        saved = body["lifecycle"]
        assert saved["materialized"] is True
        assert saved["status"] == "presentada"
        assert saved["status_label"] == "Presentada"
        assert saved["importe_ofertado"] == "125000.5"
        assert saved["baja_porcentaje"] == "3.25"
        assert saved["lotes"] == ["Lote 1", "Lote 2"]
        assert saved["garantia_provisional"] == "2500"
        assert saved["fecha_mesa"] == "2026-10-15"
        assert saved["version"] == 1
        assert saved["id"] is not None
        assert saved["last_edited_by_user_id"] == str(ctx["user_a"])

        assert _count_rows(ctx["migration_url"], ctx["tenant_a"]) == 1
        assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == 1

        # Subsequent commercial edit uses CAS version=1.
        patch2 = client.patch(
            path,
            json={
                "version": 1,
                "status": "en_evaluacion",
                "importe_ofertado": "130000",
            },
            headers=_json_headers(),
        )
        assert patch2.status_code == 200, patch2.get_data(as_text=True)
        assert patch2.get_json()["lifecycle"]["version"] == 2
        assert patch2.get_json()["lifecycle"]["status"] == "en_evaluacion"

        with app.app_context(), tenant_context(
            TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])
        ):
            opp = db.session.get(Opportunity, ctx["opp_a"])
            assert opp is not None
            assert opp.status == "identified", "CRM must not be mapped from offer lifecycle"
            audits = db.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == ctx["tenant_a"],
                    AuditEvent.resource_type == "opportunity_offer_lifecycle",
                )
            ).all()
            actions = {a.action for a in audits}
            assert "opportunity.offer_lifecycle.create" in actions
            assert "opportunity.offer_lifecycle.update" in actions
            create_events = [
                a for a in audits if a.action == "opportunity.offer_lifecycle.create"
            ]
            assert len(create_events) == 1
            assert create_events[0].actor_id == ctx["user_a"]
            update_events = [
                a for a in audits if a.action == "opportunity.offer_lifecycle.update"
            ]
            assert update_events
            meta = update_events[-1].event_metadata or {}
            assert meta.get("crm_status") == "identified"
            assert meta.get("crm_status_untouched") is True
            assert update_events[-1].actor_id == ctx["user_a"]


def test_concurrent_first_writers_one_wins_one_409(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4: two first writes concurrent → one success, one 409; single row + single create audit."""

    from decimal import Decimal

    from opn_oracle.oracle.offer_lifecycle import materialize_offer_lifecycle
    from opn_oracle.oracle.service import VersionConflict

    app, ctx = offer_lifecycle_pg
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    client = app.test_client()

    # HTTP sequential proof: second first-write with version=0 loses after peer materialised.
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        assert client.get(path).get_json()["materialized"] is False

    outcomes: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2, timeout=30)

    def worker(amount: str) -> None:
        with app.app_context():
            manager = tenant_context(
                TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])
            )
            manager.__enter__()
            try:
                barrier.wait()
                try:
                    materialize_offer_lifecycle(
                        db.session(),
                        dossier_id=ctx["dossier_a"],
                        opportunity_id=ctx["opp_a"],
                        payload={
                            "status": "presentada",
                            "importe_ofertado": Decimal(amount),
                        },
                        actor_id=ctx["user_a"],
                        expected_version=0,
                        partial=True,
                    )
                    with lock:
                        outcomes.append("ok")
                except VersionConflict:
                    with lock:
                        outcomes.append("conflict")
            finally:
                manager.__exit__(None, None, None)

    t1 = threading.Thread(target=worker, args=("111",))
    t2 = threading.Thread(target=worker, args=("222",))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert sorted(outcomes) == ["conflict", "ok"], outcomes
    assert _count_rows(ctx["migration_url"], ctx["tenant_a"]) == 1
    assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == 1

    # HTTP: further version=0 write is 409 (already materialised).
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        again = client.patch(
            path,
            json={"version": 0, "status": "en_evaluacion"},
            headers=_json_headers(),
        )
        assert again.status_code == 409
        assert again.get_json()["code"] == "version_conflict"
        final = client.get(path)
        assert final.status_code == 200
        assert final.get_json()["materialized"] is True
        assert final.get_json()["lifecycle"]["version"] == 1
        assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == 1


def test_strict_patch_unknown_and_version_only_noop(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5: unknown/typo and version-only → 422; same version/timestamp; zero new audit."""

    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])

    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        first = client.patch(
            path,
            json={"version": 0, "status": "preparando", "importe_ofertado": "50"},
            headers=_json_headers(),
        )
        assert first.status_code == 200, first.get_data(as_text=True)
        life = first.get_json()["lifecycle"]
        version_before = life["version"]
        updated_before = life["updated_at"]
        audits_before = _count_audits(ctx["migration_url"], ctx["tenant_a"])

        typo = client.patch(
            path,
            json={
                "version": version_before,
                "importe_ofertad": "99",  # typo of importe_ofertado
            },
            headers=_json_headers(),
        )
        assert typo.status_code == 422
        assert typo.get_json()["code"] == "unknown_fields"

        version_only = client.patch(
            path,
            json={"version": version_before},
            headers=_json_headers(),
        )
        assert version_only.status_code == 422
        assert version_only.get_json()["code"] == "patch_no_commercial_fields"

        unknown_plus_version = client.patch(
            path,
            json={"version": version_before, "foo_bar": "x"},
            headers=_json_headers(),
        )
        assert unknown_plus_version.status_code == 422

        after = client.get(path)
        assert after.status_code == 200
        life_after = after.get_json()["lifecycle"]
        assert life_after["version"] == version_before
        assert life_after["updated_at"] == updated_before
        assert life_after["importe_ofertado"] == "50"
        assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == audits_before


def test_excluida_requires_motivo_and_clears_outside(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        # Materialise first with version=0.
        seed = client.patch(
            path,
            json={"version": 0, "status": "preparando"},
            headers=_json_headers(),
        )
        assert seed.status_code == 200
        bad = client.patch(
            path,
            json={"version": 1, "status": "excluida"},
            headers=_json_headers(),
        )
        assert bad.status_code == 422
        problem = bad.get_json()
        assert problem["code"] in {"offer_lifecycle_validation", "validation_error"}

        ok = client.patch(
            path,
            json={
                "version": 1,
                "status": "excluida",
                "motivo_exclusion": "Documentación incompleta en el sobre 1.",
            },
            headers=_json_headers(),
        )
        assert ok.status_code == 200, ok.get_data(as_text=True)
        assert ok.get_json()["lifecycle"]["motivo_exclusion"].startswith("Documentación")

        leave = client.patch(
            path,
            json={"version": 2, "status": "perdida"},
            headers=_json_headers(),
        )
        assert leave.status_code == 200
        assert leave.get_json()["lifecycle"]["motivo_exclusion"] is None
        assert leave.get_json()["lifecycle"]["status"] == "perdida"


def test_tenant_isolation(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = offer_lifecycle_pg
    path_a = _path(ctx["dossier_a"], ctx["opp_a"])
    path_b = _path(ctx["dossier_b"], ctx["opp_b"])

    client_a = app.test_client()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        assert client_a.get(path_a).status_code == 200
        assert client_a.get(path_a).get_json()["materialized"] is False
        assert (
            client_a.patch(
                path_a,
                json={"version": 0, "status": "presentada", "importe_ofertado": "10"},
                headers=_json_headers(),
            ).status_code
            == 200
        )

    client_b = app.test_client()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_b"], tenant_id=ctx["tenant_b"]
    ):
        cross = client_b.get(path_a)
        assert cross.status_code in {403, 404}
        own = client_b.get(path_b)
        assert own.status_code == 200
        assert own.get_json()["materialized"] is False
        assert own.get_json()["lifecycle"]["status"] == "preparando"
        assert own.get_json()["lifecycle"]["version"] == 0


def test_cas_conflict_and_concurrent_race(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from decimal import Decimal

    from opn_oracle.oracle.offer_lifecycle import cas_update_offer_lifecycle_sql

    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        first = client.patch(
            path,
            json={"version": 0, "status": "presentada", "importe_ofertado": "100"},
            headers=_json_headers(),
        )
        assert first.status_code == 200
        assert first.get_json()["lifecycle"]["version"] == 1
        stale = client.patch(
            path,
            json={"version": 0, "status": "en_evaluacion"},
            headers=_json_headers(),
        )
        assert stale.status_code == 409
        assert stale.get_json()["code"] == "version_conflict"
        stale2 = client.patch(
            path,
            json={"version": 1, "status": "en_evaluacion"},
            headers=_json_headers(),
        )
        assert stale2.status_code == 200
        # Now at version 2; concurrent CAS race on version 2.
        results: list[int] = []
        barrier = threading.Barrier(2, timeout=30)
        lock = threading.Lock()

        def worker(amount: str) -> None:
            with app.app_context():
                manager = tenant_context(
                    TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])
                )
                manager.__enter__()
                try:
                    barrier.wait()
                    matched = cas_update_offer_lifecycle_sql(
                        db.session(),
                        tenant_id=ctx["tenant_a"],
                        opportunity_id=ctx["opp_a"],
                        expected_version=2,
                        fields={
                            "status": "presentada",
                            "importe_ofertado": Decimal(amount),
                            "baja_porcentaje": None,
                            "lotes": [],
                            "garantia_provisional": None,
                            "fecha_mesa": None,
                            "motivo_exclusion": None,
                        },
                        actor_id=ctx["user_a"],
                    )
                    if matched == 1:
                        db.session.commit()
                    else:
                        db.session.rollback()
                    with lock:
                        results.append(matched)
                finally:
                    manager.__exit__(None, None, None)

        t1 = threading.Thread(target=worker, args=("111",))
        t2 = threading.Thread(target=worker, args=("222",))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
        assert sorted(results) == [0, 1], results

        final = client.get(path)
        assert final.status_code == 200
        assert final.get_json()["lifecycle"]["version"] == 3
        assert final.get_json()["lifecycle"]["importe_ofertado"] in {"111", "222"}
        assert final.get_json()["materialized"] is True


def test_rejects_client_owned_actor_id(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        resp = client.patch(
            path,
            json={
                "version": 0,
                "status": "presentada",
                "actor_id": str(uuid.uuid4()),
            },
            headers=_json_headers(),
        )
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "actor_not_client_owned"
        assert _count_rows(ctx["migration_url"], ctx["tenant_a"]) == 0


def test_negative_amounts_rejected(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        seed = client.patch(
            path,
            json={"version": 0, "status": "preparando"},
            headers=_json_headers(),
        )
        assert seed.status_code == 200
        resp = client.patch(
            path,
            json={"version": 1, "importe_ofertado": "-5"},
            headers=_json_headers(),
        )
        assert resp.status_code == 422
        # Invalid PATCH must not bump version or audit.
        assert client.get(path).get_json()["lifecycle"]["version"] == 1
        assert _count_audits(ctx["migration_url"], ctx["tenant_a"]) == 1


def test_crm_status_not_accepted_as_offer_status(
    offer_lifecycle_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: no silent mapping between CRM and offer lifecycle enums."""

    app, ctx = offer_lifecycle_pg
    client = app.test_client()
    path = _path(ctx["dossier_a"], ctx["opp_a"])
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]
    ):
        seed = client.patch(
            path,
            json={"version": 0, "status": "preparando"},
            headers=_json_headers(),
        )
        assert seed.status_code == 200
        for crm_value in ("identified", "qualified", "pursuing", "won", "lost", "dismissed"):
            resp = client.patch(
                path,
                json={"version": 1, "status": crm_value},
                headers=_json_headers(),
            )
            assert resp.status_code in {422, 400}, crm_value
        with app.app_context(), tenant_context(
            TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])
        ):
            opp = db.session.get(Opportunity, ctx["opp_a"])
            assert opp is not None and opp.status == "identified"
            row = db.session.scalar(
                select(OpportunityOfferLifecycle).where(
                    OpportunityOfferLifecycle.opportunity_id == ctx["opp_a"]
                )
            )
            assert row is not None
            assert row.status == "preparando"
            assert row.version == 1
