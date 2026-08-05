"""MDEV-06 REWORK-2 · real PostgreSQL authority isolation (no fake session/SQL inspect)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from opn_oracle import create_app
from opn_oracle.integrations.memory_ask_dual import load_oracle_authority_from_session
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


def _require_urls() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url or not runtime_url:
        detail = (
            "real PG authority test requires TEST_DATABASE_URL and TEST_RUNTIME_DATABASE_URL "
            f"(migration={'set' if migration_url else 'missing'}, "
            f"runtime={'set' if runtime_url else 'missing'})"
        )
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if runtime_url.startswith("postgresql://"):
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return migration_url, runtime_url, redis_url


@pytest.fixture
def authority_pg() -> Iterator[tuple[Session, uuid.UUID, uuid.UUID, dict[str, uuid.UUID]]]:
    migration_url, runtime_url, redis_url = _require_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG authority gate")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "mdev06-authority-pg",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    migrator = create_engine(migration_url)
    runtime = create_engine(runtime_url)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    intent_a = uuid.uuid4()
    intent_b = uuid.uuid4()
    req_a = uuid.uuid4()
    req_b = uuid.uuid4()
    offering_a = uuid.uuid4()
    obj_a = uuid.uuid4()
    obj_b = uuid.uuid4()
    dec_a = uuid.uuid4()
    dec_b = uuid.uuid4()
    ev_a = uuid.uuid4()
    ev_b = uuid.uuid4()
    content_hash_a = "a" * 64
    content_hash_b = "b" * 64

    with migrator.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"mdev06-a-{tenant_a.hex[:8]}", "Tenant A MDEV06"),
            (tenant_b, f"mdev06-b-{tenant_b.hex[:8]}", "Tenant B MDEV06"),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES ("
                    ":id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now()"
                    ")"
                ),
                {"id": tid, "slug": slug, "name": name},
            )
        for wid, tid, slug in (
            (workspace_a, tenant_a, f"ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"ws-b-{workspace_b.hex[:6]}"),
        ):
            conn.execute(
                text(
                    "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                    "settings, created_at, updated_at) "
                    "VALUES (:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
                ),
                {"id": wid, "t": tid, "slug": slug, "name": f"WS {slug}"},
            )
        for did, tid, wid, title in (
            (dossier_a, tenant_a, workspace_a, "Dossier A"),
            (dossier_b, tenant_b, workspace_b, "Dossier B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO strategic_dossiers("
                    "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                    "strategic_goal, geography, sectors, languages, scoring_config, "
                    "health_score, opportunity_score, risk_score, score_explanation, "
                    "version, synthetic_data, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :w, :title, '', 'project', 'active', '', '[]'::jsonb, '[]'::jsonb, "
                    "'[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, 1, false, now(), now())"
                ),
                {"id": did, "t": tid, "w": wid, "title": title},
            )
        for iid, tid, did, chash, req in (
            (intent_a, tenant_a, dossier_a, content_hash_a, "comprar A"),
            (intent_b, tenant_b, dossier_b, content_hash_b, "comprar B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO dossier_intent_revisions("
                    "id, tenant_id, dossier_id, version, schema_key, schema_version, request_text, "
                    "structured_spec, status, content_hash, source_refs, row_version, "
                    "created_at, updated_at, accepted_at"
                    ") VALUES ("
                    ":id, :t, :d, 1, 'procurement', 'v1', :req, "
                    "'{\"cpv\":[\"35400000\"]}'::jsonb, 'accepted', :ch, '[]'::jsonb, 1, "
                    "now(), now(), now())"
                ),
                {"id": iid, "t": tid, "d": did, "req": req, "ch": chash},
            )
            conn.execute(
                text(
                    "UPDATE strategic_dossiers SET current_intent_revision_id=:i "
                    "WHERE id=:d AND tenant_id=:t"
                ),
                {"i": iid, "d": did, "t": tid},
            )
        for rid, tid, did, iid, question in (
            (req_a, tenant_a, dossier_a, intent_a, "quién gana en A?"),
            (req_b, tenant_b, dossier_b, intent_b, "quién gana en B?"),
        ):
            conn.execute(
                text(
                    "INSERT INTO intelligence_requirements("
                    "id, tenant_id, dossier_id, intent_revision_id, class, priority, question, "
                    "decision_to_support, scope, exclusions, success_criteria, status, "
                    "alignment_state, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :d, :i, 'procurement_fit', 'high', :q, 'bid', '{}'::jsonb, "
                    "'{}'::jsonb, '[]'::jsonb, 'active', 'aligned', now(), now())"
                ),
                {"id": rid, "t": tid, "d": did, "i": iid, "q": question},
            )
        conn.execute(
            text(
                "INSERT INTO dossier_offerings("
                "id, tenant_id, dossier_id, intent_revision_id, name, aliases, taxonomies, "
                "description, status, created_at, updated_at"
                ") VALUES ("
                ":id, :t, :d, :i, 'Offering A', '[]'::jsonb, '{}'::jsonb, 'oferta A', "
                "'active', now(), now())"
            ),
            {"id": offering_a, "t": tenant_a, "d": dossier_a, "i": intent_a},
        )
        for oid, tid, did, title, pos in (
            (obj_a, tenant_a, dossier_a, "objetivo A", 0),
            (obj_b, tenant_b, dossier_b, "objetivo B", 0),
        ):
            conn.execute(
                text(
                    "INSERT INTO dossier_objectives("
                    "id, tenant_id, dossier_id, title, description, priority, status, metrics, "
                    "position, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :d, :title, '', 'high', 'open', '{}'::jsonb, :pos, 1, now(), now())"
                ),
                {"id": oid, "t": tid, "d": did, "title": title, "pos": pos},
            )
        for didx, tid, did, title in (
            (dec_a, tenant_a, dossier_a, "decisión A"),
            (dec_b, tenant_b, dossier_b, "decisión B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO decisions("
                    "id, tenant_id, dossier_id, title, status, rationale, content, version, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :d, :title, 'proposed', 'porque', '{}'::jsonb, 1, now(), now())"
                ),
                {"id": didx, "t": tid, "d": did, "title": title},
            )
        for eid, tid, extract in (
            (ev_a, tenant_a, "evidencia tenant A del expediente"),
            (ev_b, tenant_b, "evidencia tenant B ajena — no debe aparecer"),
        ):
            conn.execute(
                text(
                    "INSERT INTO evidence("
                    "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                    "provenance, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, 'entity_intel', :extract, '{}'::jsonb, :checksum, 'internal', "
                    '\'{"source_kind":"entity_intel"}\'::jsonb, 1, now(), now())'
                ),
                {"id": eid, "t": tid, "extract": extract, "checksum": os.urandom(32)},
            )
        for eid, tid, did in ((ev_a, tenant_a, dossier_a), (ev_b, tenant_b, dossier_b)):
            conn.execute(
                text(
                    "INSERT INTO evidence_dossiers(tenant_id, evidence_id, dossier_id) "
                    "VALUES (:t, :e, :d)"
                ),
                {"t": tid, "e": eid, "d": did},
            )

    ids: dict[str, uuid.UUID] = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "dossier_a": dossier_a,
        "dossier_b": dossier_b,
        "intent_a": intent_a,
        "req_a": req_a,
        "offering_a": offering_a,
        "obj_a": obj_a,
        "dec_a": dec_a,
        "ev_a": ev_a,
        "ev_b": ev_b,
    }

    SessionLocal = sessionmaker(bind=runtime, autoflush=False, autocommit=False)
    try:
        yield SessionLocal, tenant_a, dossier_a, ids
    finally:
        runtime.dispose()
        migrator.dispose()


def test_load_oracle_authority_scopes_tenant_dossier_pg(
    authority_pg: tuple[sessionmaker, uuid.UUID, uuid.UUID, dict[str, uuid.UUID]],
) -> None:
    """Insert real tenant A/B rows; loader includes only A, excludes B/foreign dossier."""

    SessionLocal, tenant_a, dossier_a, ids = authority_pg
    actor = uuid.uuid4()

    # after_begin listener applies app.tenant_id from TenantContext (RLS runtime role).
    with (
        tenant_context(TenantContext(tenant_id=tenant_a, actor_id=actor)),
        SessionLocal() as session,
    ):
        block = load_oracle_authority_from_session(
            session,
            tenant_id=tenant_a,
            dossier_id=dossier_a,
            question="¿quién concentra el CPV?",
        )

        assert block["authority_loaded"] is True
        assert block["intent"]["content_hash"] == "a" * 64
        assert block["intent_hash"] == "a" * 64
        assert block["intent"]["id"] == str(ids["intent_a"])
        assert any(r["id"] == str(ids["req_a"]) for r in block["requirements"])
        assert block["offering"].get("id") == str(ids["offering_a"])
        assert any(o["id"] == str(ids["obj_a"]) for o in block["objectives"])
        assert any(d["id"] == str(ids["dec_a"]) for d in block["decisions"])
        evidence_ids = {str(e["id"]) for e in block["oracle_evidence"]}
        assert str(ids["ev_a"]) in evidence_ids
        assert str(ids["ev_b"]) not in evidence_ids
        # Foreign tenant / dossier must not leak into payload.
        blob = str(block)
        assert str(ids["tenant_b"]) not in blob
        assert str(ids["dossier_b"]) not in blob
        assert str(ids["ev_b"]) not in blob
        assert "evidencia tenant B" not in blob

        from sqlalchemy import func, select

        from opn_oracle.oracle.models import Evidence

        visible = session.scalar(select(func.count()).select_from(Evidence))
        assert visible is not None and int(visible) >= 1
