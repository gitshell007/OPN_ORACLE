"""G-19 materialización actor discovery · E2E ORM/HTTP + PostgreSQL desechable.

Reutiliza frontera G-18 (Evidence + link + AuditEvent). Cierra agent/endpoint:
competitor artifact no acepta por endpoint actor y viceversa.
"""

from __future__ import annotations

import hashlib
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
from opn_oracle.ai.citable_sources import (
    SOURCE_KIND_WEB_SEARCH,
    content_checksum,
    server_owned_candidate_id,
)
from opn_oracle.ai.market_materialize import MaterializeError, accept_and_materialize
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.extensions import db
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Evidence
from opn_oracle.platform.models import AuditEvent
from opn_oracle.tenants.context import TenantContext, tenant_context

ACTOR_ACCEPT_ACTION = "ai.market_actor_discovery.accept"

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
        detail = "TEST_DATABASE_URL required for G-19 materialization PG gates"
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


def _counts(tenant_id: uuid.UUID) -> tuple[int, int, int]:
    evidence_n = db.session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.tenant_id == tenant_id)
    )
    link_n = db.session.scalar(
        select(func.count())
        .select_from(EvidenceDossier)
        .where(EvidenceDossier.tenant_id == tenant_id)
    )
    audit_n = db.session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == ACTOR_ACCEPT_ACTION,
            AuditEvent.result == "success",
        )
    )
    return int(evidence_n or 0), int(link_n or 0), int(audit_n or 0)


@pytest.fixture
def g19_pg() -> Iterator[tuple[Any, dict[str, Any]]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG materialization gates")

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g19-actor-materializacion-secret-key-32b",
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
    audit_id = uuid.uuid4()
    actor_artifact_id = uuid.uuid4()
    competitor_artifact_id = uuid.uuid4()
    password = "g19-actor-materializacion-segura-2026"
    digest = hashlib.sha256(b"g19-actor-materializacion").digest()

    s1 = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://cnrs.example/graphene"))
    c1 = server_owned_candidate_id(
        execution_key=audit_id, name="Lab Graphene CNRS", evidence_ids=[s1]
    )
    actor_output = {
        "candidates": [
            {
                "candidate_id": c1,
                "actor_type": "research_group",
                "organization": "Lab Graphene CNRS",
                "affiliation": "CNRS",
                "country": "FR",
                "summary": "Grafeno en Francia",
                "rationale": "Grafeno en Francia",
                "evidence_ids": [s1],
                "confidence": 80,
                "citable_sources": [
                    {
                        "source_id": s1,
                        "title": "Lab Graphene CNRS",
                        "url": "https://cnrs.example/graphene",
                        "snippet": "snippet",
                        "domain": "cnrs.example",
                        "label": "Lab Graphene CNRS",
                        "origin": SOURCE_KIND_WEB_SEARCH,
                        "origin_label": "Fuente encontrada por búsqueda",
                    }
                ],
            }
        ],
        "warnings": [],
        "reserved_citable_sources": [
            _reserved(s1, title="Lab Graphene CNRS", url="https://cnrs.example/graphene"),
        ],
    }
    competitor_output = {
        "candidates": [
            {
                "candidate_id": c1,
                "name": "Lab Graphene CNRS",
                "country": "FR",
                "rationale": "as competitor",
                "evidence_ids": [s1],
                "confidence": 80,
            }
        ],
        "warnings": [],
        "reserved_citable_sources": [
            _reserved(s1, title="Lab Graphene CNRS", url="https://cnrs.example/graphene"),
        ],
    }

    engine = create_engine(migration_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES "
                "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
            ),
            {
                "id": tenant_id,
                "slug": f"g19-act-{tenant_id.hex[:8]}",
                "name": "G19 Actor",
            },
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
                "email": f"g19-act-{user_id.hex[:8]}@example.test",
                "dn": "G19 Owner",
                "ph": ph,
            },
        )
        conn.execute(
            text(
                "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                "settings, created_at, updated_at) VALUES "
                "(:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
            ),
            {
                "id": workspace_id,
                "t": tenant_id,
                "slug": f"ws-{workspace_id.hex[:6]}",
                "name": "WS",
            },
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
                "'[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, '{}'::jsonb, :u, 1, false, "
                "now(), now()"
                ")"
            ),
            {
                "id": dossier_id,
                "t": tenant_id,
                "w": workspace_id,
                "title": "Mercado G19",
                "u": user_id,
            },
        )
        now = datetime.now(UTC)
        import json as _json

        for aid, agent, schema_name, out in (
            (
                actor_artifact_id,
                "market_actor_discovery",
                "MarketActorDiscoveryOutput",
                actor_output,
            ),
            (
                competitor_artifact_id,
                "market_competitor_discovery",
                "MarketCompetitorDiscoveryOutput",
                competitor_output,
            ),
        ):
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
                    ":id, :t, NULL, NULL, :u, :agent, :agent, 'generate', 'mock', 'mock-v1', "
                    ":agent, 'v1', :h, :h, :schema, 'v1', :h, :h, '[]'::jsonb, "
                    "'succeeded', 'internal', false, '{}'::jsonb, 0, 0, 0, 'EUR', 1, "
                    ":now, :now, 'not_required', :now, :now"
                    ")"
                ),
                {
                    "id": audit_row,
                    "t": tenant_id,
                    "u": user_id,
                    "agent": agent,
                    "schema": schema_name,
                    "h": digest,
                    "now": now,
                },
            )
            target_type = (
                "market_actor_discovery"
                if agent == "market_actor_discovery"
                else "market_discovery"
            )
            # Actor artifacts are dossier-scoped (G-19 live); competitor stays pre-creation.
            art_dossier = dossier_id if agent == "market_actor_discovery" else None
            conn.execute(
                text(
                    "INSERT INTO ai_artifacts("
                    "id, tenant_id, audit_log_id, dossier_id, target_type, target_id, agent, "
                    "schema_name, schema_version, output, output_hash, status, version, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :audit, :did, :tt, :tid, :agent, :schema, 'v1', "
                    "CAST(:out AS jsonb), :h, 'candidate', 1, :now, :now"
                    ")"
                ),
                {
                    "id": aid,
                    "t": tenant_id,
                    "audit": audit_row,
                    "did": art_dossier,
                    "tt": target_type,
                    "tid": (dossier_id if agent == "market_actor_discovery" else tenant_id),
                    "agent": agent,
                    "schema": schema_name,
                    "out": _json.dumps(out),
                    "h": digest,
                    "now": now,
                },
            )

    env = {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "dossier_id": dossier_id,
        "actor_artifact_id": actor_artifact_id,
        "competitor_artifact_id": competitor_artifact_id,
        "c1": c1,
        "s1": s1,
        "password": password,
        "email": f"g19-act-{user_id.hex[:8]}@example.test",
    }
    yield app, env


def test_accept_actor_valid_1_1_1_and_retry(g19_pg: tuple[Any, dict[str, Any]]) -> None:
    app, env = g19_pg
    with (
        app.app_context(),
        tenant_context(
            TenantContext(
                tenant_id=env["tenant_id"],
                actor_id=env["user_id"],
                platform_access=False,
                access_reason="g19-test",
            )
        ),
    ):
        result = accept_and_materialize(
            artifact_id=env["actor_artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
            agent="market_actor_discovery",
        )
        assert result["count"] == 1
        assert _counts(env["tenant_id"]) == (1, 1, 1)
        # Retry identical → still 1/1/1
        result2 = accept_and_materialize(
            artifact_id=env["actor_artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
            agent="market_actor_discovery",
        )
        assert result2["count"] == 1
        assert _counts(env["tenant_id"]) == (1, 1, 1)
        event = db.session.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == env["tenant_id"],
                AuditEvent.action == ACTOR_ACCEPT_ACTION,
            )
        )
        assert event is not None
        assert event.actor_id == env["user_id"]
        assert (event.event_metadata or {}).get("agent") == "market_actor_discovery"


def test_cross_agent_accept_closed_zero_rows(g19_pg: tuple[Any, dict[str, Any]]) -> None:
    app, env = g19_pg
    with (
        app.app_context(),
        tenant_context(
            TenantContext(
                tenant_id=env["tenant_id"],
                actor_id=env["user_id"],
                platform_access=False,
                access_reason="g19-test",
            )
        ),
    ):
        # Actor endpoint path (agent=market_actor_discovery) cannot accept competitor.
        with pytest.raises(MaterializeError) as exc:
            accept_and_materialize(
                artifact_id=env["competitor_artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
                agent="market_actor_discovery",
            )
        assert exc.value.code == "artifact_not_found"
        assert _counts(env["tenant_id"]) == (0, 0, 0)

        # Competitor path cannot accept actor artifact.
        with pytest.raises(MaterializeError) as exc2:
            accept_and_materialize(
                artifact_id=env["actor_artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
                agent="market_competitor_discovery",
            )
        assert exc2.value.code == "artifact_not_found"
        assert _counts(env["tenant_id"]) == (0, 0, 0)


def test_service_rollback_zero_rows(g19_pg: tuple[Any, dict[str, Any]]) -> None:
    """Invalid selection fails closed with 0 Evidence / 0 link / 0 AuditEvent."""

    app, env = g19_pg
    with (
        app.app_context(),
        tenant_context(
            TenantContext(
                tenant_id=env["tenant_id"],
                actor_id=env["user_id"],
                platform_access=False,
                access_reason="g19-test",
            )
        ),
    ):
        with pytest.raises(MaterializeError):
            accept_and_materialize(
                artifact_id=env["actor_artifact_id"],
                dossier_id=env["dossier_id"],
                selected=[
                    {
                        "candidate_id": str(uuid.uuid4()),
                        "source_ids": [env["s1"]],
                    }
                ],
                agent="market_actor_discovery",
            )
        assert _counts(env["tenant_id"]) == (0, 0, 0)


def test_accept_actor_wrong_dossier_zero_rows(g19_pg: tuple[Any, dict[str, Any]]) -> None:
    """Accept A1 on D2 → 404 and 0 new rows; accept A1 on D1 → 1/1/1."""

    app, env = g19_pg
    d2 = uuid.uuid4()
    with app.app_context():
        # Second market dossier same tenant.
        db.session.execute(
            text(
                "INSERT INTO strategic_dossiers("
                "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                "strategic_goal, geography, sectors, languages, scoring_config, "
                "health_score, opportunity_score, risk_score, score_explanation, "
                "profile_config, owner_user_id, version, synthetic_data, "
                "created_at, updated_at"
                ") SELECT "
                ":id, tenant_id, workspace_id, 'Mercado D2', '', 'market', 'active', '', "
                "'[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 0, 0, 0, '{}'::jsonb, "
                "'{}'::jsonb, owner_user_id, 1, false, now(), now() "
                "FROM strategic_dossiers WHERE id = :d1"
            ),
            {"id": d2, "d1": env["dossier_id"]},
        )
        db.session.commit()

    with (
        app.app_context(),
        tenant_context(
            TenantContext(
                tenant_id=env["tenant_id"],
                actor_id=env["user_id"],
                platform_access=False,
                access_reason="g19-d1d2",
            )
        ),
    ):
        with pytest.raises(MaterializeError) as exc:
            accept_and_materialize(
                artifact_id=env["actor_artifact_id"],
                dossier_id=d2,
                selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
                agent="market_actor_discovery",
            )
        assert exc.value.status == 404
        assert exc.value.code == "artifact_dossier_mismatch"
        assert _counts(env["tenant_id"]) == (0, 0, 0)

        result = accept_and_materialize(
            artifact_id=env["actor_artifact_id"],
            dossier_id=env["dossier_id"],
            selected=[{"candidate_id": env["c1"], "source_ids": [env["s1"]]}],
            agent="market_actor_discovery",
        )
        assert result["count"] == 1
        assert _counts(env["tenant_id"]) == (1, 1, 1)
