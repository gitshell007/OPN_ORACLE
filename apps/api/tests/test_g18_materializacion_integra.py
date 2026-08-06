"""G-18 materialización íntegra · E2E real ORM/HTTP + PostgreSQL desechable.

No usa _FakeArtifact para gates de BD. Si PostgreSQL local no está disponible
y ORACLE_RUN_INTEGRATION=1, falla cerrado (no PASS conceptual).
"""

from __future__ import annotations

import hashlib
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
from sqlalchemy import create_engine, func, select, text

from opn_oracle import create_app
from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.citable_sources import (
    SOURCE_KIND_WEB_SEARCH,
    content_checksum,
    deterministic_web_search_evidence_id,
    server_owned_candidate_id,
    stamp_server_owned_candidate_ids,
)
from opn_oracle.ai.market_materialize import (
    MaterializeError,
    accept_and_materialize,
    accept_and_materialize_with_fault,
    deterministic_accept_audit_event_id,
)
from opn_oracle.auth import permissions
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Evidence
from opn_oracle.platform.models import AuditEvent, User
from opn_oracle.tenants.context import TenantContext, tenant_context

ACCEPT_ACTION = "ai.market_competitor_discovery.accept"

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
        detail = "TEST_DATABASE_URL required for G-18 materialization PG gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    migration_url = _assert_disposable(migration_url, env_name="TEST_DATABASE_URL")
    runtime_url = _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL")
    return migration_url, runtime_url, redis_url


def _reserved(sid: str, *, title: str, url: str, snippet: str = "snippet") -> dict[str, Any]:
    return {
        "source_id": sid,
        "title": title,
        "url": url,
        "snippet": snippet,
        "provider": "brave",
        "rank": 1,
        "content_checksum": content_checksum(title=title, snippet=snippet, url=url),
        "origin": SOURCE_KIND_WEB_SEARCH,
        "domain": urlparse(url).hostname or "",
        "label": title,
        "origin_label": "Fuente encontrada por búsqueda",
    }


@pytest.fixture
def g18_pg() -> Iterator[tuple[Any, dict[str, Any]]]:
    """Disposable PostgreSQL app + seeded tenant/user/market dossier/artifact."""

    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG materialization gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g18-materializacion-integra-secret-key-32b",
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

    tenant_id = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_id = uuid.uuid4()
    user_b = uuid.uuid4()
    membership_id = uuid.uuid4()
    membership_b = uuid.uuid4()
    role_id = uuid.uuid4()
    role_b = uuid.uuid4()
    workspace_id = uuid.uuid4()
    workspace_b = uuid.uuid4()
    dossier_id = uuid.uuid4()
    dossier_b = uuid.uuid4()
    audit_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    password = "g18-materializacion-segura-2026"
    digest = hashlib.sha256(b"g18-materializacion-integra").digest()

    s1 = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://acme.example/about"))
    s2 = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://beta.example/about"))
    c1 = server_owned_candidate_id(
        execution_key=audit_id, name="Acme Sensors", evidence_ids=[s1]
    )
    c2 = server_owned_candidate_id(
        execution_key=audit_id, name="Beta Corp", evidence_ids=[s2]
    )
    output = {
        "candidates": [
            {
                "candidate_id": c1,
                "name": "Acme Sensors",
                "country": "DE",
                "rationale": "Sensores industriales",
                "evidence_ids": [s1],
                "confidence": 80,
                "citable_sources": [
                    {
                        "source_id": s1,
                        "title": "Acme Sensors",
                        "url": "https://acme.example/about",
                        "snippet": "snippet",
                        "domain": "acme.example",
                        "label": "Acme Sensors",
                        "origin": SOURCE_KIND_WEB_SEARCH,
                        "origin_label": "Fuente encontrada por búsqueda",
                    }
                ],
            },
            {
                "candidate_id": c2,
                "name": "Beta Corp",
                "country": "ES",
                "rationale": "Compite en grid",
                "evidence_ids": [s2],
                "confidence": 70,
                "citable_sources": [
                    {
                        "source_id": s2,
                        "title": "Beta Corp",
                        "url": "https://beta.example/about",
                        "snippet": "snippet",
                        "domain": "beta.example",
                        "label": "Beta Corp",
                        "origin": SOURCE_KIND_WEB_SEARCH,
                        "origin_label": "Fuente encontrada por búsqueda",
                    }
                ],
            },
        ],
        "warnings": [],
        "reserved_citable_sources": [
            _reserved(s1, title="Acme Sensors", url="https://acme.example/about"),
            _reserved(s2, title="Beta Corp", url="https://beta.example/about"),
        ],
    }

    engine = create_engine(migration_url)
    with engine.begin() as conn:
        for tid, slug, name in (
            (tenant_id, f"g18-mat-a-{tenant_id.hex[:8]}", "G18 Mat A"),
            (tenant_b, f"g18-mat-b-{tenant_b.hex[:8]}", "G18 Mat B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES "
                    "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
                ),
                {"id": tid, "slug": slug, "name": name},
            )
        ph = PasswordHasher().hash(password)
        for uid, email, display in (
            (user_id, f"g18-mat-{user_id.hex[:8]}@example.test", "G18 Owner A"),
            (user_b, f"g18-mat-{user_b.hex[:8]}@example.test", "G18 Owner B"),
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
            (workspace_id, tenant_id, f"ws-a-{workspace_id.hex[:6]}"),
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
            (membership_id, tenant_id, user_id),
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
        for rid, tid, key in (
            (role_id, tenant_id, "owner"),
            (role_b, tenant_b, "owner"),
        ):
            conn.execute(
                text(
                    "INSERT INTO roles(id, tenant_id, key, name, description, is_system, "
                    "created_at, updated_at) VALUES "
                    "(:id, :t, :key, 'Owner', 'Owner', true, now(), now())"
                ),
                {"id": rid, "t": tid, "key": key},
            )
        for tid, mid, rid in (
            (tenant_id, membership_id, role_id),
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
            (dossier_id, tenant_id, workspace_id, user_id, "Mercado G18 A"),
            (dossier_b, tenant_b, workspace_b, user_b, "Mercado G18 B"),
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
                    ":id, :t, :w, :title, '', 'market', 'active', '', '[]'::jsonb, '[]'::jsonb, "
                    "'[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, '{}'::jsonb, :u, 1, false, "
                    "now(), now()"
                    ")"
                ),
                {"id": did, "t": tid, "w": wid, "title": title, "u": uid},
            )
        now = datetime.now(UTC)
        conn.execute(
            text(
                "INSERT INTO ai_audit_logs("
                "id, tenant_id, dossier_id, background_job_id, requested_by_user_id, "
                "use_case, agent, action, provider, model, prompt_name, prompt_version, "
                "prompt_hash, context_hash, schema_name, schema_version, input_hash, "
                "output_hash, source_ids, status, data_classification, redaction_applied, "
                "redaction_summary, input_tokens, output_tokens, actual_cost_micros, currency, "
                "attempt_count, started_at, completed_at, human_review_state, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :t, NULL, NULL, :u, 'market_competitor_discovery', "
                "'market_competitor_discovery', 'generate', 'mock', 'mock-v1', "
                "'market_competitor_discovery', 'v1', :h, :h, "
                "'MarketCompetitorDiscoveryOutput', 'v1', :h, :h, '[]'::jsonb, "
                "'succeeded', 'internal', false, '{}'::jsonb, 0, 0, 0, 'EUR', 1, "
                ":now, :now, 'not_required', :now, :now"
                ")"
            ),
            {"id": audit_id, "t": tenant_id, "u": user_id, "h": digest, "now": now},
        )
        import json as _json

        conn.execute(
            text(
                "INSERT INTO ai_artifacts("
                "id, tenant_id, audit_log_id, dossier_id, target_type, target_id, agent, "
                "schema_name, schema_version, output, output_hash, status, version, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :t, :audit, NULL, 'market_discovery', :t, "
                "'market_competitor_discovery', 'MarketCompetitorDiscoveryOutput', 'v1', "
                "CAST(:output AS jsonb), :h, 'candidate', 1, :now, :now"
                ")"
            ),
            {
                "id": artifact_id,
                "t": tenant_id,
                "audit": audit_id,
                "output": _json.dumps(output),
                "h": digest,
                "now": now,
            },
        )
    engine.dispose()

    ctx = {
        "tenant_id": tenant_id,
        "tenant_b": tenant_b,
        "user_id": user_id,
        "user_b": user_b,
        "dossier_id": dossier_id,
        "dossier_b": dossier_b,
        "artifact_id": artifact_id,
        "audit_id": audit_id,
        "s1": s1,
        "s2": s2,
        "c1": c1,
        "c2": c2,
        "password": password,
        "migration_url": migration_url,
        "runtime_url": runtime_url,
        "output": output,
    }
    yield app, ctx

    # Cleanup seeded rows (leave schema; do not touch oracle_dev).
    cleanup = create_engine(migration_url)
    with cleanup.begin() as conn:
        conn.execute(
            text("DELETE FROM evidence_dossiers WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM evidence WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM audit_events WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM ai_human_reviews WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM ai_artifacts WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM ai_audit_logs WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM strategic_dossiers WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM membership_roles WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM role_permissions WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM roles WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM tenant_memberships WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM workspaces WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM users WHERE id IN (:a, :b)"),
            {"a": user_id, "b": user_b},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE id IN (:a, :b)"),
            {"a": tenant_id, "b": tenant_b},
        )
    cleanup.dispose()


def _count_evidence(
    app: Any, tenant_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> tuple[int, int]:
    with app.app_context(), tenant_context(
        TenantContext(tenant_id=tenant_id, actor_id=actor_id)
    ):
        n_ev = db.session.scalar(
            select(func.count())
            .select_from(Evidence)
            .where(
                Evidence.tenant_id == tenant_id,
                Evidence.source_kind == SOURCE_KIND_WEB_SEARCH,
            )
        )
        n_link = db.session.scalar(
            select(func.count())
            .select_from(EvidenceDossier)
            .where(EvidenceDossier.tenant_id == tenant_id)
        )
        return int(n_ev or 0), int(n_link or 0)


def _count_accept_audits(
    app: Any, tenant_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> int:
    with app.app_context(), tenant_context(
        TenantContext(tenant_id=tenant_id, actor_id=actor_id)
    ):
        n = db.session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.action == ACCEPT_ACTION,
                AuditEvent.result == "success",
            )
        )
        return int(n or 0)


def _list_accept_audits(
    app: Any, tenant_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> list[AuditEvent]:
    with app.app_context(), tenant_context(
        TenantContext(tenant_id=tenant_id, actor_id=actor_id)
    ):
        return list(
            db.session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == ACCEPT_ACTION,
                    AuditEvent.result == "success",
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        )


def _assert_sane_accept_metadata(meta: dict[str, Any]) -> None:
    blob = str(meta).casefold()
    for banned in (
        "snippet",
        "prompt",
        "system_prompt",
        "model_output",
        "password",
        "secret",
        "api_key",
        "reviewer_user_id_from_client",
        "actor_from_client",
    ):
        assert banned not in blob, f"metadata contains banned key/content: {banned}"
    assert "candidate_ids" in meta
    assert "source_ids" in meta
    assert "evidence_ids" in meta
    assert "artifact_id" in meta
    assert "dossier_id" in meta


def _is_contractual_retriable(exc: BaseException) -> bool:
    """Only concrete retriable/contractual failures are acceptable for a race loser."""

    if isinstance(exc, MaterializeError):
        return exc.code in {
            "audit_conflict",
            "evidence_conflict",
            "link_conflict",
            "artifact_version_drift",
            "artifact_not_found",
            "artifact_not_acceptable",
            "artifact_rejected",
            "artifact_superseded",
        }
    return False


@contextmanager
def _authenticated_http(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Iterator[None]:
    user = User(
        id=user_id,
        email="g18-mat@example.test",
        display_name="G18 Mat",
        status="active",
    )
    principal = type("Principal", (), {"id": user.id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(ai_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: frozenset(
            {"ai.execute", "dossier.write", "dossier.read"}
        ),
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


def test_http_accept_idempotent_and_partial(
    g18_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = g18_pg
    client = app.test_client()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_id"], tenant_id=ctx["tenant_id"]
    ):
        # Full accept of candidate A (source1)
        r1 = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_id"]),
                "selected": [
                    {
                        "candidate_id": ctx["c1"],
                        "source_ids": [ctx["s1"]],
                    }
                ],
                "expected_version": 1,
            },
        )
        assert r1.status_code == 200, r1.get_json()
        body1 = r1.get_json()
        assert body1["count"] == 1
        assert body1["materialized"][0]["source_kind"] == SOURCE_KIND_WEB_SEARCH
        eid1 = body1["materialized"][0]["evidence_id"]
        expected_eid = str(
            deterministic_web_search_evidence_id(
                tenant_id=ctx["tenant_id"],
                artifact_id=ctx["artifact_id"],
                source_id=ctx["s1"],
            )
        )
        assert eid1 == expected_eid

        # Human accept audit: 1 row, server-owned actor, reconstructible selection
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 1
        audits = _list_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"])
        a1 = audits[0]
        assert a1.actor_id == ctx["user_id"]
        assert a1.tenant_id == ctx["tenant_id"]
        assert a1.resource_id == ctx["artifact_id"]
        assert a1.dossier_id == ctx["dossier_id"]
        assert a1.created_at is not None
        expected_audit_id = deterministic_accept_audit_event_id(
            tenant_id=ctx["tenant_id"],
            artifact_id=ctx["artifact_id"],
            dossier_id=ctx["dossier_id"],
            candidate_ids=[ctx["c1"]],
            source_ids=[ctx["s1"]],
        )
        assert a1.id == expected_audit_id
        meta1 = dict(a1.event_metadata or {})
        _assert_sane_accept_metadata(meta1)
        assert meta1["artifact_id"] == str(ctx["artifact_id"])
        assert meta1["dossier_id"] == str(ctx["dossier_id"])
        assert meta1["expected_version"] == 1
        assert meta1["candidate_ids"] == [ctx["c1"]]
        assert meta1["source_ids"] == [ctx["s1"]]
        assert meta1["evidence_ids"] == [eid1]

        # Exact retry → same IDs, no new evidence rows, still 1 human audit
        r2 = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_id"]),
                "selected": [
                    {"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}
                ],
            },
        )
        assert r2.status_code == 200
        body2 = r2.get_json()
        assert body2["materialized"][0]["evidence_id"] == eid1
        assert body2["count"] == 1

        n_ev, n_link = _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"])
        assert n_ev == 1
        assert n_link == 1
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 1

        # Partial second selection: add source2 without duplicating source1
        r3 = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_id"]),
                "selected": [
                    {"candidate_id": ctx["c2"], "source_ids": [ctx["s2"]]}
                ],
            },
        )
        assert r3.status_code == 200, r3.get_json()
        body3 = r3.get_json()
        assert body3["count"] == 1
        eid2 = body3["materialized"][0]["evidence_id"]
        assert eid2 != eid1
        n_ev, n_link = _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"])
        assert n_ev == 2
        assert n_link == 2
        # Two distinguishable human accept records (different selection identity)
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 2
        audits = _list_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"])
        ids = {a.id for a in audits}
        assert len(ids) == 2
        expected_audit_id_2 = deterministic_accept_audit_event_id(
            tenant_id=ctx["tenant_id"],
            artifact_id=ctx["artifact_id"],
            dossier_id=ctx["dossier_id"],
            candidate_ids=[ctx["c2"]],
            source_ids=[ctx["s2"]],
        )
        assert expected_audit_id_2 in ids
        for audit in audits:
            assert audit.actor_id == ctx["user_id"]
            assert audit.created_at is not None
            _assert_sane_accept_metadata(dict(audit.event_metadata or {}))


def test_http_validation_and_state_closed(
    g18_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = g18_pg
    client = app.test_client()
    base = {
        "artifact_id": str(ctx["artifact_id"]),
        "dossier_id": str(ctx["dossier_id"]),
    }
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_id"], tenant_id=ctx["tenant_id"]
    ):
        # empty candidate_id
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={**base, "selected": [{"candidate_id": "", "source_ids": [ctx["s1"]]}]},
        )
        assert r.status_code in {422, 400}

        # invalid candidate_id
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [{"candidate_id": "not-a-uuid", "source_ids": [ctx["s1"]]}],
            },
        )
        assert r.status_code in {422, 400}

        # alien candidate_id
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [
                    {"candidate_id": str(uuid.uuid4()), "source_ids": [ctx["s1"]]}
                ],
            },
        )
        assert r.status_code == 422
        assert r.get_json()["code"] == "candidate_unknown"

        # source of B under candidate A
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [
                    {"candidate_id": ctx["c1"], "source_ids": [ctx["s2"]]}
                ],
            },
        )
        assert r.status_code == 422
        assert r.get_json()["code"] == "source_id_not_on_candidate"
        assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0

        # version drift
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [{"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}],
                "expected_version": 99,
            },
        )
        assert r.status_code == 409
        assert r.get_json()["code"] == "artifact_version_drift"
        assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0

    # rejected / superseded → 409
    engine = create_engine(ctx["migration_url"])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_artifacts SET status='rejected' WHERE id=:id"),
            {"id": ctx["artifact_id"]},
        )
    engine.dispose()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_id"], tenant_id=ctx["tenant_id"]
    ):
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [{"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}],
            },
        )
        assert r.status_code == 409
        assert r.get_json()["code"] == "artifact_rejected"
        assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0

    engine = create_engine(ctx["migration_url"])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_artifacts SET status='superseded' WHERE id=:id"),
            {"id": ctx["artifact_id"]},
        )
    engine.dispose()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_id"], tenant_id=ctx["tenant_id"]
    ):
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                **base,
                "selected": [{"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}],
            },
        )
        assert r.status_code == 409
        assert r.get_json()["code"] == "artifact_superseded"
        assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0

    # restore candidate for other tests sharing fixture? fixture is function-scoped.
    engine = create_engine(ctx["migration_url"])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_artifacts SET status='candidate' WHERE id=:id"),
            {"id": ctx["artifact_id"]},
        )
    engine.dispose()


def test_tenant_isolation(
    g18_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = g18_pg
    client = app.test_client()
    # Tenant B cannot accept artifact A
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_b"], tenant_id=ctx["tenant_b"]
    ):
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_b"]),
                "selected": [{"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}],
            },
        )
        assert r.status_code in {404, 422}
        assert _count_evidence(app, ctx["tenant_b"], actor_id=ctx["user_b"]) == (0, 0)
        assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
        assert _count_accept_audits(app, ctx["tenant_b"], actor_id=ctx["user_b"]) == 0
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0

        # Cannot bind to dossier of tenant A
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_id"]),
                "selected": [{"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}],
            },
        )
        assert r.status_code in {404, 422}
        assert _count_accept_audits(app, ctx["tenant_b"], actor_id=ctx["user_b"]) == 0
        assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0


def test_http_client_actor_payload_ignored(
    g18_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Client-supplied actor_id / reviewer_user_id must not become the stored actor."""

    app, ctx = g18_pg
    client = app.test_client()
    forged = uuid.uuid4()
    with _authenticated_http(
        app, monkeypatch, user_id=ctx["user_id"], tenant_id=ctx["tenant_id"]
    ):
        r = client.post(
            "/api/v1/ai/market-competitor-discovery/accept",
            json={
                "artifact_id": str(ctx["artifact_id"]),
                "dossier_id": str(ctx["dossier_id"]),
                "actor_id": str(forged),
                "reviewer_user_id": str(forged),
                "selected": [
                    {
                        "candidate_id": ctx["c1"],
                        "source_ids": [ctx["s1"]],
                        "actor_id": str(forged),
                        "reviewer_user_id": str(forged),
                    }
                ],
                "expected_version": 1,
            },
        )
        # Schema may reject unknown fields (422) or strip them and accept (200).
        assert r.status_code in {200, 422, 400}, r.get_json()
        if r.status_code == 200:
            audits = _list_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"])
            assert len(audits) == 1
            assert audits[0].actor_id == ctx["user_id"]
            assert audits[0].actor_id != forged
            meta = dict(audits[0].event_metadata or {})
            _assert_sane_accept_metadata(meta)
            assert str(forged) not in str(meta)
            assert str(forged) not in str(meta.get("candidate_ids"))
            assert str(forged) not in str(meta.get("source_ids"))
            assert str(forged) not in str(meta.get("evidence_ids"))
        else:
            assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
            assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0


def test_rollback_mid_materialize(g18_pg: tuple[Any, dict[str, Any]]) -> None:
    """Fault before audit is written → 0 Evidence, 0 links, 0 success audits."""

    app, ctx = g18_pg
    with app.app_context(), tenant_context(
        TenantContext(tenant_id=ctx["tenant_id"], actor_id=ctx["user_id"])
    ), pytest.raises(RuntimeError, match="injected_mid_materialize_failure"):
        accept_and_materialize_with_fault(
            artifact_id=ctx["artifact_id"],
            dossier_id=ctx["dossier_id"],
            selected=[
                {"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]},
                {"candidate_id": ctx["c2"], "source_ids": [ctx["s2"]]},
            ],
            actor_user_id=ctx["user_id"],
            fail_after_index=0,
        )
    assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
    assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0


def test_rollback_after_audit(g18_pg: tuple[Any, dict[str, Any]]) -> None:
    """Fault after audit row is staged → full rollback including the audit event."""

    app, ctx = g18_pg
    with app.app_context(), tenant_context(
        TenantContext(tenant_id=ctx["tenant_id"], actor_id=ctx["user_id"])
    ), pytest.raises(RuntimeError, match="injected_post_audit_failure"):
        accept_and_materialize_with_fault(
            artifact_id=ctx["artifact_id"],
            dossier_id=ctx["dossier_id"],
            selected=[
                {"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]},
            ],
            actor_user_id=ctx["user_id"],
            fail_after_audit=True,
        )
    assert _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == (0, 0)
    assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 0


def test_concurrent_accept_one_evidence(
    g18_pg: tuple[Any, dict[str, Any]],
) -> None:
    """Two threads accept same artifact/source; DB ends 1 Evidence + 1 link + 1 audit.

    Barrier for sync. Loser may only be a contractual/retriable MaterializeError —
    arbitrary BaseException is not green.
    """

    app, ctx = g18_pg
    barrier = threading.Barrier(2, timeout=30)
    results: list[dict[str, Any] | BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            with app.app_context(), tenant_context(
                TenantContext(tenant_id=ctx["tenant_id"], actor_id=ctx["user_id"])
            ):
                barrier.wait()
                out = accept_and_materialize(
                    artifact_id=ctx["artifact_id"],
                    dossier_id=ctx["dossier_id"],
                    selected=[
                        {"candidate_id": ctx["c1"], "source_ids": [ctx["s1"]]}
                    ],
                    actor_user_id=ctx["user_id"],
                )
                with lock:
                    results.append(out)
        except Exception as exc:
            # Capture only Exception (not BaseException) for contractual check.
            with lock:
                results.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)
    assert not t1.is_alive() and not t2.is_alive()
    assert len(results) == 2, f"expected 2 worker outcomes, got {results!r}"

    successes = [r for r in results if isinstance(r, dict)]
    errors = [r for r in results if not isinstance(r, dict)]
    # Both succeed with same result, OR any loser is a concrete retriable contract error.
    assert len(successes) >= 1, f"no success: {errors!r}"
    for err in errors:
        assert isinstance(err, Exception), f"non-Exception outcome not allowed: {err!r}"
        assert not isinstance(err, BaseException) or isinstance(err, Exception)
        assert _is_contractual_retriable(err), (
            f"non-contractual race loser is not green: {type(err).__name__}: {err!r}"
        )
    expected_eid = str(
        deterministic_web_search_evidence_id(
            tenant_id=ctx["tenant_id"],
            artifact_id=ctx["artifact_id"],
            source_id=ctx["s1"],
        )
    )
    for s in successes:
        assert s["count"] == 1
        assert s["materialized"][0]["evidence_id"] == expected_eid
    if len(successes) == 2:
        assert (
            successes[0]["materialized"][0]["evidence_id"]
            == successes[1]["materialized"][0]["evidence_id"]
        )
    n_ev, n_link = _count_evidence(app, ctx["tenant_id"], actor_id=ctx["user_id"])
    assert n_ev == 1
    assert n_link == 1
    assert _count_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"]) == 1
    audits = _list_accept_audits(app, ctx["tenant_id"], actor_id=ctx["user_id"])
    assert audits[0].actor_id == ctx["user_id"]
    assert audits[0].id == deterministic_accept_audit_event_id(
        tenant_id=ctx["tenant_id"],
        artifact_id=ctx["artifact_id"],
        dossier_id=ctx["dossier_id"],
        candidate_ids=[ctx["c1"]],
        source_ids=[ctx["s1"]],
    )


def test_candidate_id_not_from_model_json() -> None:
    planted = str(uuid.uuid4())
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    key = uuid.uuid4()
    stamped = stamp_server_owned_candidate_ids(
        {
            "candidates": [
                {
                    "candidate_id": planted,
                    "name": "Same",
                    "evidence_ids": [s1],
                },
                {
                    "candidate_id": planted,
                    "name": "Same",
                    "evidence_ids": [s2],
                },
            ]
        },
        execution_key=key,
    )
    ids = [c["candidate_id"] for c in stamped["candidates"]]
    assert planted not in ids
    assert ids[0] != ids[1]
    assert ids[0] == server_owned_candidate_id(
        execution_key=key, name="Same", evidence_ids=[s1]
    )
