"""G-20-B corrective · PostgreSQL disposable identity-first accept gates.

Requires ORACLE_RUN_INTEGRATION=1 + TEST_DATABASE_URL disposable.
"""
from __future__ import annotations

import hashlib
import json
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

from opn_oracle import create_app
from opn_oracle.ai.citable_sources import content_checksum, server_owned_candidate_id
from opn_oracle.ai.market_materialize import MaterializeError, accept_and_materialize
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Actor, DossierActor, Evidence
from opn_oracle.platform.models import AuditEvent
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci")
ACTOR_ACCEPT_ACTION = "ai.market_actor_discovery.accept"


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
        detail = "TEST_DATABASE_URL required for G-20-B identity PG gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    return (
        _assert_disposable(migration_url, env_name="TEST_DATABASE_URL"),
        _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL"),
        redis_url,
    )


def _reserved(sid: str, *, title: str, url: str, snippet: str = "snippet") -> dict[str, Any]:
    return {
        "source_id": sid,
        "title": title,
        "url": url,
        "snippet": snippet,
        "provider": "hal_structure",
        "rank": 1,
        "content_checksum": content_checksum(title=title, snippet=snippet, url=url),
        "origin": "structured",
        "domain": urlparse(url).hostname or "",
        "label": title,
        "origin_label": "Fuente estructurada",
    }


def _counts(tenant_id: uuid.UUID) -> dict[str, int]:
    return {
        "evidence": int(
            db.session.scalar(
                select(func.count()).select_from(Evidence).where(Evidence.tenant_id == tenant_id)
            )
            or 0
        ),
        "links": int(
            db.session.scalar(
                select(func.count())
                .select_from(EvidenceDossier)
                .where(EvidenceDossier.tenant_id == tenant_id)
            )
            or 0
        ),
        "actors": int(
            db.session.scalar(
                select(func.count()).select_from(Actor).where(Actor.tenant_id == tenant_id)
            )
            or 0
        ),
        "dossier_actors": int(
            db.session.scalar(
                select(func.count())
                .select_from(DossierActor)
                .where(DossierActor.tenant_id == tenant_id)
            )
            or 0
        ),
        "audit": int(
            db.session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == ACTOR_ACCEPT_ACTION,
                    AuditEvent.result == "success",
                )
            )
            or 0
        ),
    }


@pytest.fixture
def g20b_pg() -> Iterator[tuple[Any, dict[str, Any]]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG identity gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g20b-identity-materializacion-secret-key-32b",
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
    user_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    role_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    digest = hashlib.sha256(b"g20b-identity").digest()
    password = "g20b-identity-segura-2026"

    s_a = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://neel.example/a"))
    s_b = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://neel.example/b"))
    s_c = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://neel.example/c"))
    c_a = server_owned_candidate_id(
        execution_key="g20b-a", name="Institut Néel", evidence_ids=[s_a]
    )
    c_b = server_owned_candidate_id(
        execution_key="g20b-b", name="Institut Néel", evidence_ids=[s_b]
    )
    c_alias = server_owned_candidate_id(
        execution_key="g20b-alias", name="NEEL Institute", evidence_ids=[s_c]
    )

    # Artifact with three candidates: ROR A, ROR B (homonym), same ROR A with alias name.
    candidates = [
        {
            "candidate_id": c_a,
            "actor_type": "research_group",
            "organization": "Institut Néel",
            "affiliation": "CNRS",
            "country": "FR",
            "summary": "Lab ROR A",
            "evidence_ids": [s_a],
            "confidence": 90,
            "ids": {"ror": "04dbzz632", "rnsr": "200717524X"},
            "identity_status": "validated",
            "score_breakdown": {"identity": 40.0},
            "ranking_reasons": ["identity_validated"],
        },
        {
            "candidate_id": c_b,
            "actor_type": "research_group",
            "organization": "Institut Néel",
            "country": "FR",
            "summary": "Homonym ROR B",
            "evidence_ids": [s_b],
            "confidence": 40,
            "ids": {"ror": "05neelt99"},
            "identity_status": "unresolved",
        },
        {
            "candidate_id": c_alias,
            "actor_type": "research_group",
            "organization": "NEEL Institute",
            "country": "FR",
            "summary": "Alias same ROR A",
            "evidence_ids": [s_c],
            "confidence": 85,
            "ids": {"ror": "04dbzz632"},
            "identity_status": "validated",
        },
    ]
    reserved = [
        _reserved(s_a, title="Néel A", url="https://neel.example/a"),
        _reserved(s_b, title="Néel B", url="https://neel.example/b"),
        _reserved(s_c, title="NEEL alias", url="https://neel.example/c"),
    ]
    output = {"candidates": candidates, "warnings": [], "reserved_citable_sources": reserved}
    artifact_id = uuid.uuid4()

    engine = create_engine(migration_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES "
                "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
            ),
            {"id": tenant_id, "slug": f"g20b-id-{tenant_id.hex[:8]}", "name": "G20B Identity"},
        )
        ph = PasswordHasher().hash(password)
        conn.execute(
            text(
                "INSERT INTO users(id, email, display_name, password_hash, status, "
                "email_verified_at, created_at, updated_at) VALUES "
                "(:id, :email, :dn, :ph, 'active', now(), now(), now())"
            ),
            {
                "id": user_id,
                "email": f"g20b-id-{user_id.hex[:8]}@example.test",
                "dn": "G20B Owner",
                "ph": ph,
            },
        )
        conn.execute(
            text(
                "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                "settings, created_at, updated_at) VALUES "
                "(:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
            ),
            {"id": workspace_id, "t": tenant_id, "slug": f"ws-{workspace_id.hex[:6]}", "name": "WS"},
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
                "'[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, "
                "CAST(:profile AS jsonb), :u, 1, false, now(), now()"
                ")"
            ),
            {
                "id": dossier_id,
                "t": tenant_id,
                "w": workspace_id,
                "title": "Mercado G20B identity",
                "u": user_id,
                "profile": json.dumps(
                    {
                        "discovery_intent": "grupos de investigación en Francia grafeno",
                        "discovery_actor_type": "research_group",
                    }
                ),
            },
        )
        now = datetime.now(UTC)
        audit_row = uuid.uuid4()
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
                ":id, :t, :did, NULL, :u, 'market_actor_discovery', 'market_actor_discovery', "
                "'generate', 'mock', 'mock-v1', 'market_actor_discovery', 'v1', :h, :h, "
                "'MarketActorDiscoveryOutput', 'v1', :h, :h, '[]'::jsonb, "
                "'succeeded', 'internal', false, '{}'::jsonb, 0, 0, 0, 'EUR', 1, "
                ":now, :now, 'not_required', :now, :now"
                ")"
            ),
            {
                "id": audit_row,
                "t": tenant_id,
                "did": dossier_id,
                "u": user_id,
                "h": digest,
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO ai_artifacts("
                "id, tenant_id, audit_log_id, dossier_id, target_type, target_id, agent, "
                "schema_name, schema_version, output, output_hash, status, version, "
                "created_at, updated_at"
                ") VALUES ("
                ":id, :t, :audit, :did, 'market_actor_discovery', :did, "
                "'market_actor_discovery', 'MarketActorDiscoveryOutput', 'v1', "
                "CAST(:out AS jsonb), :h, 'candidate', 1, :now, :now"
                ")"
            ),
            {
                "id": artifact_id,
                "t": tenant_id,
                "audit": audit_row,
                "did": dossier_id,
                "out": json.dumps(output),
                "h": digest,
                "now": now,
            },
        )

    env = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "dossier_id": dossier_id,
        "artifact_id": artifact_id,
        "c_a": c_a,
        "c_b": c_b,
        "c_alias": c_alias,
        "s_a": s_a,
        "s_b": s_b,
        "s_c": s_c,
        "password": password,
        "email": f"g20b-id-{user_id.hex[:8]}@example.test",
        "migration_url": migration_url,
        "runtime_url": runtime_url,
    }
    yield app, env


def test_pg_accept_subset_and_same_id_idempotent(g20b_pg: tuple[Any, dict[str, Any]]) -> None:
    app, env = g20b_pg
    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=env["tenant_id"],
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-pg",
        )
    ):
        before = _counts(env["tenant_id"])
        assert before == {
            "evidence": 0,
            "links": 0,
            "actors": 0,
            "dossier_actors": 0,
            "audit": 0,
        }
        r1 = accept_and_materialize(
            artifact_id=env["artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
            expected_version=1,
            agent="market_actor_discovery",
        )
        assert r1["count"] == 1
        assert r1["actors_count"] == 1
        assert r1["actors"][0]["identity_resolution"] == "create"
        # Strong-ID priority: rnsr before ror when both present.
        assert r1["actors"][0]["canonical_key"] == "rnsr:200717524x"
        after1 = _counts(env["tenant_id"])
        assert after1["evidence"] == 1
        assert after1["actors"] == 1
        assert after1["dossier_actors"] == 1
        assert after1["audit"] == 1

        # Double-click / exact retry
        r2 = accept_and_materialize(
            artifact_id=env["artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
            expected_version=1,
            agent="market_actor_discovery",
        )
        assert r2["actors"][0]["actor_id"] == r1["actors"][0]["actor_id"]
        after2 = _counts(env["tenant_id"])
        assert after2["actors"] == 1
        assert after2["evidence"] == 1
        assert after2["audit"] == 1

        # Alias same ROR → reuse
        r3 = accept_and_materialize(
            artifact_id=env["artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c_alias"], "source_ids": [env["s_c"]]}],
            expected_version=1,
            agent="market_actor_discovery",
        )
        assert r3["actors"][0]["actor_id"] == r1["actors"][0]["actor_id"]
        assert r3["actors"][0]["identity_resolution"] == "reuse_by_id"
        after3 = _counts(env["tenant_id"])
        assert after3["actors"] == 1
        assert after3["evidence"] == 2  # new source
        assert after3["audit"] == 2  # different selection → new audit


def test_pg_homonym_incompatible_ids_separate_no_mutate(
    g20b_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, env = g20b_pg
    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=env["tenant_id"],
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-pg",
        )
    ):
        r_a = accept_and_materialize(
            artifact_id=env["artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
            agent="market_actor_discovery",
        )
        actor_a_id = uuid.UUID(r_a["actors"][0]["actor_id"])
        a_before = db.session.get(Actor, actor_a_id)
        assert a_before is not None
        version_before = int(a_before.version)
        ids_before = dict(a_before.identifiers or {})

        r_b = accept_and_materialize(
            artifact_id=env["artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c_b"], "source_ids": [env["s_b"]]}],
            agent="market_actor_discovery",
        )
        actor_b_id = uuid.UUID(r_b["actors"][0]["actor_id"])
        assert actor_b_id != actor_a_id
        assert r_b["actors"][0]["canonical_key"] == "ror:05neelt99"
        assert "identifier_conflicts" not in (r_b["actors"][0].get("identifiers") or {})

        a_after = db.session.get(Actor, actor_a_id)
        assert a_after is not None
        assert int(a_after.version) == version_before
        assert dict(a_after.identifiers or {}) == ids_before
        assert _counts(env["tenant_id"])["actors"] == 2


def test_pg_cas_stale_and_reject_and_other_tenant(
    g20b_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, env = g20b_pg
    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=env["tenant_id"],
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-pg",
        )
    ):
        with pytest.raises(MaterializeError) as exc:
            accept_and_materialize(
                artifact_id=env["artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
                expected_version=99,
                agent="market_actor_discovery",
            )
        assert exc.value.status == 409
        assert exc.value.code == "artifact_version_drift"
        assert _counts(env["tenant_id"])["actors"] == 0
        assert _counts(env["tenant_id"])["evidence"] == 0

    # Other tenant context → artifact not found, no leak
    other_tenant = uuid.uuid4()
    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=other_tenant,
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-other",
        )
    ):
        with pytest.raises(MaterializeError) as exc2:
            accept_and_materialize(
                artifact_id=env["artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
                agent="market_actor_discovery",
            )
        assert exc2.value.status == 404
        # No actors in other tenant
        assert (
            db.session.scalar(
                select(func.count()).select_from(Actor).where(Actor.tenant_id == other_tenant)
            )
            or 0
        ) == 0


def test_pg_reject_artifact_zero_writes(g20b_pg: tuple[Any, dict[str, Any]]) -> None:
    app, env = g20b_pg
    # Bypass RLS with migrator URL so status flip is durable for the app role.
    engine = create_engine(env["migration_url"])
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE ai_artifacts SET status='rejected' WHERE id=:id"),
            {"id": env["artifact_id"]},
        )
    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=env["tenant_id"],
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-pg",
        )
    ):
        with pytest.raises(MaterializeError) as exc:
            accept_and_materialize(
                artifact_id=env["artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": env["c_a"], "source_ids": [env["s_a"]]}],
                agent="market_actor_discovery",
            )
        assert exc.value.status == 409
        assert exc.value.code in {"artifact_rejected", "artifact_not_acceptable"}
        assert _counts(env["tenant_id"])["actors"] == 0
        assert _counts(env["tenant_id"])["evidence"] == 0


def test_pg_identity_split_409_zero_writes(g20b_pg: tuple[Any, dict[str, Any]]) -> None:
    """Pre-seed two actors; candidate claims both IDs → 409, no new rows."""

    app, env = g20b_pg
    engine = create_engine(env["migration_url"])
    s_split = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://neel.example/split"))
    c_split = server_owned_candidate_id(
        execution_key="g20b-split", name="Split Org", evidence_ids=[s_split]
    )
    with engine.begin() as conn:
        a1 = uuid.uuid4()
        a2 = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO actors(id, tenant_id, actor_type, canonical_name, canonical_key, "
                "aliases, identifiers, metadata, provenance, version, created_at, updated_at) "
                "VALUES "
                "(:id, :t, 'institution', 'A1', 'ror:aaaa1111', '[]'::jsonb, "
                "CAST(:ids AS jsonb), '{}'::jsonb, '{}'::jsonb, 1, now(), now())"
            ),
            {
                "id": a1,
                "t": env["tenant_id"],
                "ids": json.dumps({"ror": "aaaa1111"}),
            },
        )
        conn.execute(
            text(
                "INSERT INTO actors(id, tenant_id, actor_type, canonical_name, canonical_key, "
                "aliases, identifiers, metadata, provenance, version, created_at, updated_at) "
                "VALUES "
                "(:id, :t, 'institution', 'A2', 'rnsr:bbbb2222', '[]'::jsonb, "
                "CAST(:ids AS jsonb), '{}'::jsonb, '{}'::jsonb, 1, now(), now())"
            ),
            {
                "id": a2,
                "t": env["tenant_id"],
                "ids": json.dumps({"rnsr": "bbbb2222"}),
            },
        )
        # Patch artifact output to add split candidate
        conn.execute(
            text(
                """
                UPDATE ai_artifacts SET output = jsonb_set(
                  jsonb_set(
                    output,
                    '{candidates}',
                    output->'candidates' || CAST(:cand AS jsonb)
                  ),
                  '{reserved_citable_sources}',
                  output->'reserved_citable_sources' || CAST(:src AS jsonb)
                )
                WHERE id = :id
                """
            ),
            {
                "id": env["artifact_id"],
                "cand": json.dumps(
                    [
                        {
                            "candidate_id": c_split,
                            "actor_type": "research_group",
                            "organization": "Split Org",
                            "country": "FR",
                            "summary": "split brain",
                            "evidence_ids": [s_split],
                            "confidence": 50,
                            "ids": {"ror": "aaaa1111", "rnsr": "bbbb2222"},
                            "identity_status": "validated",
                        }
                    ]
                ),
                "src": json.dumps(
                    [
                        _reserved(
                            s_split, title="Split", url="https://neel.example/split"
                        )
                    ]
                ),
            },
        )

    with app.app_context(), tenant_context(
        TenantContext(
            tenant_id=env["tenant_id"],
            actor_id=env["user_id"],
            platform_access=False,
            access_reason="g20b-pg",
        )
    ):
        before = _counts(env["tenant_id"])
        assert before["actors"] == 2
        with pytest.raises(MaterializeError) as exc:
            accept_and_materialize(
                artifact_id=env["artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": c_split, "source_ids": [s_split]}],
                agent="market_actor_discovery",
            )
        assert exc.value.status == 409
        assert exc.value.code == "identity_conflict"
        after = _counts(env["tenant_id"])
        assert after["actors"] == 2
        assert after["evidence"] == 0
        assert after["dossier_actors"] == 0
        assert after["audit"] == 0
