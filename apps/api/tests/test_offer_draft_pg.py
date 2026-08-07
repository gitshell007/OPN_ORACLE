"""HTTP + PostgreSQL real for opportunity offer drafts (SV2-G09-A rework).

Uses the full migration (FKs intact), app test client, real AuditEvent rows,
and concurrent sessions for CAS / POST idempotency races.

Requires disposable local PG:
  ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL
  TEST_REDIS_URL
"""

from __future__ import annotations

import io
import json
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
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from opn_oracle import create_app
from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.models import OpportunityOfferDraft
from opn_oracle.ai.offer_draft import (
    cas_update_offer_draft_sql,
    make_etag,
    materialize_content_from_calculated,
    utc_now,
)
from opn_oracle.auth import permissions
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.platform.models import AuditEvent, User
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci")
TABLE = "opportunity_offer_drafts"


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
        detail = "TEST_DATABASE_URL required for offer-draft PG HTTP gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    migration_url = _assert_disposable(migration_url, env_name="TEST_DATABASE_URL")
    runtime_url = _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL")
    return migration_url, runtime_url, redis_url


def _sample_draft_offer() -> dict[str, Any]:
    return {
        "banner": "BORRADOR COMERCIAL — no es documento presentable.",
        "human_gate": "draft_requires_human_edit",
        "statement": "Introducción base del borrador G09 rework.",
        "tender_ref": "CONTR-G09-RW",
        "sections": [
            {
                "key": "award_economic",
                "title": "Oferta económica",
                "requirement": "[oficial] Criterio económico",
                "our_response_draft": "[borrador declarado — no es hecho] Semilla A.",
            },
            {
                "key": "award_technical",
                "title": "Oferta técnica",
                "requirement": "[oficial] Criterio técnico",
                "our_response_draft": "[borrador declarado — no es hecho] Semilla B.",
            },
        ],
        "origin": "declared_draft",
        "based_on_verdict": "go_conditioned",
    }


@pytest.fixture
def offer_draft_pg() -> Iterator[tuple[Any, dict[str, Any]]]:
    """Disposable PostgreSQL app + full graph (tenant/user/dossier/artifact)."""

    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG offer-draft gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g09-offer-draft-rework-secret-key-32b",
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
    dossier_a2 = uuid.uuid4()
    audit_a = uuid.uuid4()
    audit_b = uuid.uuid4()
    artifact_a = uuid.uuid4()
    artifact_b = uuid.uuid4()
    password = "g09-offer-draft-rework-2026"
    digest = b"\x11" * 32
    now = datetime.now(UTC)
    draft_offer = _sample_draft_offer()
    output = {
        "title": "Licitación G09 rework",
        "summary": "Resumen",
        "draft_offer": draft_offer,
        "fit_assessment": {
            "statement": "Encaje demo",
            "verdict": {"recommendation": "go_conditioned"},
        },
    }

    engine = create_engine(migration_url)
    with engine.begin() as conn:
        # Ensure FKs of the real migration are present (never drop them).
        fks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'opportunity_offer_drafts'::regclass "
                    "AND contype = 'f'"
                )
            )
        }
        for required in (
            "fk_ood_tenant",
            "fk_ood_dossier_tenant",
            "fk_ood_source_artifact_tenant",
            "fk_ood_editor_membership",
        ):
            assert required in fks, f"missing FK {required} after migration"

        ph = PasswordHasher().hash(password)
        for tid, slug, name in (
            (tenant_a, f"g09rw-a-{tenant_a.hex[:8]}", "G09RW A"),
            (tenant_b, f"g09rw-b-{tenant_b.hex[:8]}", "G09RW B"),
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
            (user_a, f"g09rw-a-{user_a.hex[:8]}@example.test", "G09RW Owner A"),
            (user_b, f"g09rw-b-{user_b.hex[:8]}@example.test", "G09RW Owner B"),
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
            (dossier_a, tenant_a, workspace_a, user_a, "Expediente G09 A"),
            (dossier_a2, tenant_a, workspace_a, user_a, "Expediente G09 A2"),
            (dossier_b, tenant_b, workspace_b, user_b, "Expediente G09 B"),
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
        for aid, tid, uid in ((audit_a, tenant_a, user_a), (audit_b, tenant_b, user_b)):
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
                    ":id, :t, :d, NULL, :u, 'opportunity', 'opportunity', 'generate', "
                    "'mock', 'mock-v1', 'opportunity', 'v1', :h, :h, 'opportunity', 'v1', "
                    ":h, :h, '[]'::jsonb, 'succeeded', 'internal', false, '{}'::jsonb, "
                    "0, 0, 0, 'EUR', 1, :now, :now, 'not_required', :now, :now"
                    ")"
                ),
                {
                    "id": aid,
                    "t": tid,
                    "d": dossier_a if tid == tenant_a else dossier_b,
                    "u": uid,
                    "h": digest,
                    "now": now,
                },
            )
        for art_id, tid, audit, did in (
            (artifact_a, tenant_a, audit_a, dossier_a),
            (artifact_b, tenant_b, audit_b, dossier_b),
        ):
            conn.execute(
                text(
                    "INSERT INTO ai_artifacts("
                    "id, tenant_id, audit_log_id, dossier_id, target_type, target_id, agent, "
                    "schema_name, schema_version, output, output_hash, status, version, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :audit, :d, 'strategic_dossier', :d, 'opportunity', "
                    "'opportunity', 'v1', CAST(:output AS jsonb), :h, 'candidate', 1, "
                    ":now, :now"
                    ")"
                ),
                {
                    "id": art_id,
                    "t": tid,
                    "audit": audit,
                    "d": did,
                    "output": json.dumps(output),
                    "h": digest,
                    "now": now,
                },
            )
    engine.dispose()

    ctx = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "dossier_a": dossier_a,
        "dossier_a2": dossier_a2,
        "dossier_b": dossier_b,
        "artifact_a": artifact_a,
        "artifact_b": artifact_b,
        "password": password,
        "migration_url": migration_url,
        "runtime_url": runtime_url,
        "draft_offer": draft_offer,
    }
    yield app, ctx

    cleanup = create_engine(migration_url)
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
            text("DELETE FROM ai_artifacts WHERE tenant_id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )
        conn.execute(
            text("DELETE FROM ai_audit_logs WHERE tenant_id IN (:a, :b)"),
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
        email=f"g09rw-{user_id.hex[:8]}@example.test",
        display_name="G09RW",
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


def _path(dossier_id: uuid.UUID) -> str:
    return f"/api/v1/ai/dossiers/{dossier_id}/opportunity/offer-draft"


def test_migration_fks_and_rls_intact(offer_draft_pg: tuple[Any, dict[str, Any]]) -> None:
    _, ctx = offer_draft_pg
    engine = create_engine(ctx["migration_url"])
    with engine.begin() as conn:
        cols = {
            row[0]
            for row in conn.execute(
                text(
                    f"SELECT column_name FROM information_schema.columns WHERE table_name='{TABLE}'"
                )
            )
        }
        for required in (
            "id",
            "tenant_id",
            "dossier_id",
            "source_artifact_id",
            "version",
            "etag",
            "content",
            "last_edited_by_user_id",
        ):
            assert required in cols
        rls = conn.execute(
            text(
                f"SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='{TABLE}'"
            )
        ).one()
        assert rls[0] is True
        assert rls[1] is True
        fks = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    f"WHERE conrelid = '{TABLE}'::regclass AND contype = 'f'"
                )
            )
        }
        assert "fk_ood_dossier_tenant" in fks
        assert "fk_ood_source_artifact_tenant" in fks
        assert "fk_ood_editor_membership" in fks
    engine.dispose()


def test_http_post_get_patch_get_audit_and_isolation(
    offer_draft_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, ctx = offer_draft_pg
    client = app.test_client()
    path_a = _path(ctx["dossier_a"])
    path_b = _path(ctx["dossier_b"])
    path_a2 = _path(ctx["dossier_a2"])

    with _authenticated_http(app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]):
        # POST materialize
        created = client.post(path_a, json={})
        assert created.status_code == 201, created.get_json()
        body = created.get_json()
        assert body["created"] is True
        draft = body["draft"]
        assert draft["version"] == 1
        assert draft["last_edited_by_user_id"] == str(ctx["user_a"])
        assert "tenant_id" not in draft
        assert draft["statement"].startswith("Introducción base")
        assert created.headers.get("ETag") == make_etag(1)

        # 428 without precondition (draft exists; version / If-Match missing)
        missing = client.patch(path_a, json={"statement": "sin versión"})
        assert missing.status_code == 428, missing.get_json()
        assert missing.get_json()["code"] == "precondition_required"

        # Idempotent second prepare
        again = client.post(path_a, json={})
        assert again.status_code == 200
        assert again.get_json()["created"] is False
        assert again.get_json()["draft"]["id"] == draft["id"]

        # GET
        got = client.get(path_a)
        assert got.status_code == 200
        assert got.get_json()["draft"]["id"] == draft["id"]

        # Reject client-owned actor/tenant
        rejected = client.patch(
            path_a,
            json={
                "version": 1,
                "statement": "hack",
                "tenant_id": str(ctx["tenant_b"]),
                "last_edited_by_user_id": str(ctx["user_b"]),
            },
        )
        assert rejected.status_code == 422
        assert rejected.get_json()["code"] == "forbidden_field"

        # PATCH win
        patched = client.patch(
            path_a,
            json={
                "version": 1,
                "statement": "Introducción editada por el comercial A.",
                "sections": [
                    {
                        "key": "award_economic",
                        "our_response_draft": (
                            "[borrador declarado — no es hecho] Económica editada A."
                        ),
                    }
                ],
            },
            headers={"If-Match": make_etag(1)},
        )
        assert patched.status_code == 200, patched.get_json()
        saved = patched.get_json()["draft"]
        assert saved["version"] == 2
        assert saved["statement"] == "Introducción editada por el comercial A."
        assert saved["last_edited_by_user_id"] == str(ctx["user_a"])
        assert "Económica editada A." in saved["sections"][0]["our_response_draft"]

        # Stale version → 409
        conflict = client.patch(
            path_a,
            json={"version": 1, "statement": "PISADO concurrente"},
        )
        assert conflict.status_code == 409
        assert conflict.get_json()["code"] == "version_conflict"
        assert conflict.get_json()["errors"]["current_version"] == 2

        # GET keeps winner
        final = client.get(path_a)
        assert final.get_json()["draft"]["statement"] == "Introducción editada por el comercial A."
        assert "PISADO" not in final.get_json()["draft"]["statement"]

        # Dossier A does not mix with A2 (no draft yet)
        empty_a2 = client.get(path_a2)
        assert empty_a2.status_code == 404
        assert empty_a2.get_json()["code"] == "offer_draft_not_found"

    # Tenant B cannot see tenant A draft
    with _authenticated_http(app, monkeypatch, user_id=ctx["user_b"], tenant_id=ctx["tenant_b"]):
        cross = client.get(path_a)
        assert cross.status_code == 404
        own = client.post(path_b, json={})
        assert own.status_code == 201, own.get_json()
        assert own.get_json()["draft"]["dossier_id"] == str(ctx["dossier_b"])
        assert own.get_json()["draft"]["last_edited_by_user_id"] == str(ctx["user_b"])

    # Audit events: create + update for tenant A, actor server-owned
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])),
    ):
        creates = list(
            db.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == ctx["tenant_a"],
                    AuditEvent.action == "opportunity.offer_draft.create",
                    AuditEvent.result == "success",
                )
            )
        )
        updates = list(
            db.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == ctx["tenant_a"],
                    AuditEvent.action == "opportunity.offer_draft.update",
                    AuditEvent.result == "success",
                )
            )
        )
        assert len(creates) == 1
        assert creates[0].actor_id == ctx["user_a"]
        assert creates[0].tenant_id == ctx["tenant_a"]
        assert creates[0].dossier_id == ctx["dossier_a"]
        assert len(updates) == 1
        assert updates[0].actor_id == ctx["user_a"]
        meta = dict(updates[0].event_metadata or {})
        assert meta["before_version"] == 1
        assert meta["after_version"] == 2

        n_rows = db.session.scalar(
            select(func.count())
            .select_from(OpportunityOfferDraft)
            .where(
                OpportunityOfferDraft.tenant_id == ctx["tenant_a"],
                OpportunityOfferDraft.dossier_id == ctx["dossier_a"],
            )
        )
        assert int(n_rows or 0) == 1


def test_cas_race_two_sessions_one_winner(
    offer_draft_pg: tuple[Any, dict[str, Any]],
) -> None:
    """Real concurrent CAS: two sessions start from v1; exactly one wins."""

    _, ctx = offer_draft_pg
    migration_url = ctx["migration_url"]
    content = materialize_content_from_calculated(ctx["draft_offer"])
    draft_id = uuid.uuid4()
    now = utc_now()

    # Seed v1 with migrator (bypasses RLS); keep all FKs valid.
    mig = create_engine(migration_url, poolclass=NullPool)
    with mig.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {TABLE} (
                  id, tenant_id, dossier_id, source_artifact_id, version, etag,
                  content, last_edited_by_user_id, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :dossier, :artifact, 1, :etag,
                  CAST(:content AS jsonb), :actor, :now, :now
                )
                """
            ),
            {
                "id": draft_id,
                "tenant": ctx["tenant_a"],
                "dossier": ctx["dossier_a2"],
                "artifact": ctx["artifact_a"],
                "etag": make_etag(1),
                "content": json.dumps(content),
                "actor": ctx["user_a"],
                "now": now,
            },
        )
    mig.dispose()

    barrier = threading.Barrier(2, timeout=30)
    results: list[tuple[str, int]] = []
    lock = threading.Lock()
    runtime_url = ctx["runtime_url"]

    def worker(label: str, statement: str) -> None:
        engine: Engine = create_engine(runtime_url, poolclass=NullPool)
        try:
            with engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(ctx["tenant_a"])},
                )
                conn.execute(
                    text("SELECT set_config('app.actor_id', :a, true)"),
                    {"a": str(ctx["user_a"])},
                )
                # Materialize next content from v1 base (both race from same expected).
                next_content = {**content, "statement": statement}
                barrier.wait()
                result = conn.execute(
                    cas_update_offer_draft_sql(
                        tenant_id=ctx["tenant_a"],
                        dossier_id=ctx["dossier_a2"],
                        expected_version=1,
                        next_content=next_content,
                        actor_id=ctx["user_a"],
                        new_version=2,
                        new_etag=make_etag(2),
                        updated_at=utc_now(),
                    )
                )
                rowcount = int(result.rowcount or 0)
                conn.commit()
                with lock:
                    results.append((label, rowcount))
        finally:
            engine.dispose()

    t1 = threading.Thread(target=worker, args=("A", "Texto concurrente A — único ganador."))
    t2 = threading.Thread(target=worker, args=("B", "Texto concurrente B — único ganador."))
    t1.start()
    t2.start()
    t1.join(timeout=45)
    t2.join(timeout=45)
    assert not t1.is_alive() and not t2.is_alive()

    wins = [label for label, rc in results if rc == 1]
    losses = [label for label, rc in results if rc == 0]
    assert len(results) == 2
    assert len(wins) == 1, f"expected exactly one CAS winner, got {results}"
    assert len(losses) == 1, f"expected exactly one CAS loser, got {results}"
    winner = wins[0]
    loser = losses[0]

    # Winner text remains at version 2; loser never applied.
    verify = create_engine(runtime_url, poolclass=NullPool)
    with verify.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(ctx["tenant_a"])},
        )
        row = conn.execute(
            text(
                f"SELECT version, content->>'statement' FROM {TABLE} "
                "WHERE tenant_id=:t AND dossier_id=:d"
            ),
            {"t": ctx["tenant_a"], "d": ctx["dossier_a2"]},
        ).one()
        conn.rollback()
    verify.dispose()
    assert int(row[0]) == 2
    assert f"Texto concurrente {winner}" in str(row[1])
    assert f"Texto concurrente {loser}" not in str(row[1])


def test_http_post_concurrent_idempotent(
    offer_draft_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two simultaneous prepares: no 500, exactly one row, both usable responses."""

    app, ctx = offer_draft_pg
    migration_url = ctx["migration_url"]
    mig = create_engine(migration_url, poolclass=NullPool)
    with mig.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {TABLE} WHERE tenant_id=:t AND dossier_id=:d"),
            {"t": ctx["tenant_a"], "d": ctx["dossier_a"]},
        )
        conn.execute(
            text(
                "DELETE FROM audit_events WHERE tenant_id=:t "
                "AND action LIKE 'opportunity.offer_draft.%'"
            ),
            {"t": ctx["tenant_a"]},
        )
    mig.dispose()

    path = _path(ctx["dossier_a"])
    barrier = threading.Barrier(2, timeout=30)
    outcomes: list[tuple[int, dict[str, Any]]] = []
    lock = threading.Lock()

    # Shared identity for both workers (same tenant/actor); install once.
    with _authenticated_http(app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]):

        def worker() -> None:
            client = app.test_client()
            barrier.wait()
            response = client.post(path, json={})
            with lock:
                outcomes.append((response.status_code, response.get_json() or {}))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=45)
        t2.join(timeout=45)
        assert not t1.is_alive() and not t2.is_alive()

    assert len(outcomes) == 2
    statuses = sorted(code for code, _ in outcomes)
    assert all(code in {200, 201} for code in statuses), outcomes
    assert 500 not in statuses
    draft_ids = {body["draft"]["id"] for _, body in outcomes if "draft" in body}
    assert len(draft_ids) == 1

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])),
    ):
        n = db.session.scalar(
            select(func.count())
            .select_from(OpportunityOfferDraft)
            .where(
                OpportunityOfferDraft.tenant_id == ctx["tenant_a"],
                OpportunityOfferDraft.dossier_id == ctx["dossier_a"],
            )
        )
        assert int(n or 0) == 1


def _export_path(dossier_id: uuid.UUID) -> str:
    return f"/api/v1/ai/dossiers/{dossier_id}/opportunity/offer-draft/export.docx"


def test_http_export_docx_version_isolation_and_audit(
    offer_draft_pg: tuple[Any, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DOCX export: durable only, version gate, tenant isolation, server-owned audit."""

    app, ctx = offer_draft_pg
    client = app.test_client()
    path_a = _path(ctx["dossier_a"])
    export_a = _export_path(ctx["dossier_a"])
    export_b = _export_path(ctx["dossier_b"])
    export_a2 = _export_path(ctx["dossier_a2"])

    with _authenticated_http(app, monkeypatch, user_id=ctx["user_a"], tenant_id=ctx["tenant_a"]):
        # No durable draft → honest 404 (never regenerates from artifact).
        missing = client.get(f"{export_a}?version=1")
        assert missing.status_code == 404, missing.get_json()
        assert missing.get_json()["code"] == "offer_draft_not_found"

        # Materialize durable draft
        created = client.post(path_a, json={})
        assert created.status_code == 201, created.get_json()
        draft = created.get_json()["draft"]
        assert draft["version"] == 1

        # Precondition required
        need_version = client.get(export_a)
        assert need_version.status_code == 428
        assert need_version.get_json()["code"] == "precondition_required"

        # Happy path export v1
        ok = client.get(f"{export_a}?version=1")
        assert ok.status_code == 200, ok.headers
        assert ok.headers.get("Content-Type", "").startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        disposition = ok.headers.get("Content-Disposition", "")
        assert "attachment" in disposition
        assert ".docx" in disposition.casefold()
        assert "\r" not in disposition and "\n" not in disposition
        payload = ok.data
        assert payload.startswith(b"PK")
        assert b"<!DOCTYPE html" not in payload[:200].lower()
        assert b"<html" not in payload[:200].lower()

        from opn_oracle.documents.parsers import DOCXParser

        parsed = DOCXParser().parse(io.BytesIO(payload))
        text_joined = "\n".join(block.text for block in parsed.blocks)
        assert "Borrador de oferta" in text_joined
        assert "Expediente G09 A" in text_joined
        assert draft["statement"][:40] in text_joined
        assert "tenant_id" not in text_joined.casefold()
        assert str(ctx["tenant_a"]) not in text_joined
        assert str(ctx["user_a"]) not in text_joined

        # Bump to v2
        patched = client.patch(
            path_a,
            json={
                "version": 1,
                "statement": "Introducción exportable v2 del comercial.",
            },
        )
        assert patched.status_code == 200, patched.get_json()
        assert patched.get_json()["draft"]["version"] == 2

        # Stale export of v1 → 409
        stale = client.get(f"{export_a}?version=1")
        assert stale.status_code == 409, stale.get_json()
        assert stale.get_json()["code"] == "version_conflict"
        assert stale.get_json()["errors"]["current_version"] == 2

        # Correct version works
        ok2 = client.get(f"{export_a}?version=2", headers={"If-Match": make_etag(2)})
        assert ok2.status_code == 200
        parsed2 = DOCXParser().parse(io.BytesIO(ok2.data))
        joined2 = "\n".join(block.text for block in parsed2.blocks)
        assert "Introducción exportable v2 del comercial." in joined2
        assert "Introducción base del borrador G09 rework." not in joined2

        # Other dossier without draft
        empty = client.get(f"{export_a2}?version=1")
        assert empty.status_code == 404

    # Tenant B cannot export tenant A draft
    with _authenticated_http(app, monkeypatch, user_id=ctx["user_b"], tenant_id=ctx["tenant_b"]):
        cross = client.get(f"{export_a}?version=2")
        assert cross.status_code == 404
        # B has no draft yet
        own_missing = client.get(f"{export_b}?version=1")
        assert own_missing.status_code == 404

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ctx["tenant_a"], actor_id=ctx["user_a"])),
    ):
        exports = list(
            db.session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == ctx["tenant_a"],
                    AuditEvent.action == "opportunity.offer_draft.export",
                    AuditEvent.dossier_id == ctx["dossier_a"],
                )
            )
        )
        assert len(exports) >= 2  # at least success + conflict
        successes = [e for e in exports if e.result == "success"]
        failures = [e for e in exports if e.result == "failure"]
        assert successes
        assert failures
        assert any(dict(e.event_metadata or {}).get("result") == "conflict" for e in failures)
        for event in successes:
            assert event.actor_id == ctx["user_a"]
            assert event.tenant_id == ctx["tenant_a"]
            meta = dict(event.event_metadata or {})
            assert meta.get("format") == "docx"
            assert meta.get("version") in {1, 2}
            assert meta.get("result") == "success"
            assert "statement" not in meta
            assert "content" not in meta
            assert "sections" not in meta
            # Body must not be dumped into metadata
            blob = json.dumps(meta, ensure_ascii=False)
            assert "Introducción exportable" not in blob
            assert "Semilla" not in blob
