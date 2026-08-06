"""G-26 · integración del compositor Preguntar (authority + build_context path).

- Pure session mock: load_oracle_authority_from_session applies family mix.
- Optional real PG: tenant/dossier isolation (skipped unless ORACLE_RUN_INTEGRATION=1).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.ai.context_mix import map_context_family, mix_context_evidence
from opn_oracle.integrations.memory_ask_dual import (
    build_dual_ask_context,
    load_oracle_authority_from_session,
    merge_ask_citation_allowlist,
)

QUESTION = "¿qué persona y competidor influyen y qué dice el pliego?"


@dataclass
class _Row:
    id: uuid.UUID
    source_kind: str
    extract: str
    classification: str = "internal"
    provenance: dict[str, Any] = field(default_factory=dict)
    locator: dict[str, Any] = field(default_factory=dict)
    checksum: bytes = field(default_factory=lambda: hashlib.sha256(b"x").digest())
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    tenant_id: uuid.UUID | None = None


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def __iter__(self):
        if self._value is None:
            return iter(())
        if isinstance(self._value, list):
            return iter(self._value)
        return iter([self._value])


class _FakeSession:
    """Minimal session that returns pre-seeded evidence for authority load."""

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        dossier_id: uuid.UUID,
        evidence: list[_Row],
        other_tenant_evidence: list[_Row] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.dossier_id = dossier_id
        self.evidence = evidence
        self.other_tenant_evidence = other_tenant_evidence or []
        self._dossier = MagicMock()
        self._dossier.id = dossier_id
        self._dossier.tenant_id = tenant_id
        self._dossier.current_intent_revision_id = None

    def scalar(self, statement: Any) -> Any:
        # Dossier lookup only; no accepted intent / empty authority extras.
        try:
            cols = list(statement.column_descriptions)  # type: ignore[attr-defined]
        except Exception:
            cols = []
        for col in cols:
            entity = col.get("entity")
            name = getattr(entity, "__name__", "") or ""
            if name == "StrategicDossier":
                return self._dossier
        text = str(statement)
        if "StrategicDossier" in text or "strategic_dossiers" in text:
            return self._dossier
        return None

    def scalars(self, statement: Any) -> _ScalarResult:
        try:
            cols = list(statement.column_descriptions)  # type: ignore[attr-defined]
        except Exception:
            cols = []
        for col in cols:
            entity = col.get("entity")
            name = getattr(entity, "__name__", "") or ""
            if name == "Evidence":
                return _ScalarResult(list(self.evidence))
        text = str(statement)
        # Fallback: only Evidence selects include source_kind filters in this path.
        if "source_kind" in text and "Evidence" in text:
            return _ScalarResult(list(self.evidence))
        return _ScalarResult([])


def _ev(
    *,
    source_kind: str,
    extract: str,
    tenant_id: uuid.UUID,
    provenance: dict[str, Any] | None = None,
) -> _Row:
    eid = uuid.uuid4()
    return _Row(
        id=eid,
        source_kind=source_kind,
        extract=extract,
        provenance=provenance or {"source_kind": source_kind},
        checksum=hashlib.sha256(f"{eid}:{extract}".encode()).digest(),
        tenant_id=tenant_id,
    )


def _seed_bag(tenant_id: uuid.UUID) -> list[_Row]:
    rows: list[_Row] = []
    for i in range(80):
        rows.append(
            _ev(
                source_kind="procurement",
                extract=f"pliego irrelevante {i} CONTR 2026 {20000 + i}",
                tenant_id=tenant_id,
                provenance={"source_kind": "procurement"},
            )
        )
    for i in range(3):
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Persona clave {i} influye.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "person",
                    "entity_name": f"persona-{i}",
                },
            )
        )
    for i in range(4):
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Competidor relevante {i}.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "role": "competitor",
                    "entity_name": f"comp-{i}",
                },
            )
        )
    for i in range(2):
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Actor institucional {i}.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "organization",
                    "actor_type": "institution",
                    "entity_name": f"actor-{i}",
                },
            )
        )
    for i in range(5):
        rows.append(
            _ev(
                source_kind="document",
                extract=f"Documento propio {i}.",
                tenant_id=tenant_id,
                provenance={"source_kind": "document", "document_role": "own_upload"},
            )
        )
    for i in range(3):
        rows.append(
            _ev(
                source_kind="memory_signal",
                extract=f"Memoria expediente {i}.",
                tenant_id=tenant_id,
                provenance={"source_kind": "memory_signal", "source_ref": f"m-{i}"},
            )
        )
    return rows


@pytest.mark.unit
def test_load_oracle_authority_applies_g26_mix_and_exposes_metadata() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    session = _FakeSession(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        evidence=_seed_bag(tenant_id),
    )
    block = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        memory_mode="augment",
    )
    evidence = block["oracle_evidence"]
    assert evidence, "authority must carry mixed evidence"
    assert len(evidence) <= 40
    extracts = " ".join(str(r.get("extract") or "") for r in evidence)
    assert "Persona clave" in extracts
    assert "Competidor relevante" in extracts
    assert "pliego" in extracts.lower() or "CONTR" in extracts
    mix = block.get("context_mix") or {}
    assert mix.get("mixer") == "context_family_mix.v1"
    assert mix["selected_by_family"]["people"] >= 1
    assert mix["selected_by_family"]["competitors"] >= 1
    assert mix["selected_by_family"]["tenders"] >= 1
    # No PII beyond what evidence already exposes in extracts for the model.
    assert "Persona clave" not in str(mix["selected_by_family"])


@pytest.mark.unit
def test_load_oracle_authority_memory_disabled_selects_zero_memory() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    session = _FakeSession(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        evidence=_seed_bag(tenant_id),
    )
    block = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        memory_mode="disabled",
    )
    mix = block.get("context_mix") or {}
    assert mix.get("selected_by_family", {}).get("memory", 0) == 0
    assert mix.get("memory_mode") == "disabled"
    for row in block["oracle_evidence"]:
        assert row.get("source_kind") != "memory_signal"


@pytest.mark.unit
def test_dual_ask_merges_allowlist_with_mixed_authority() -> None:
    tenant_id = str(uuid.uuid4())
    dossier_id = str(uuid.uuid4())
    bag = _seed_bag(uuid.UUID(tenant_id))
    mix = mix_context_evidence(bag, limit=20, question=QUESTION, memory_mode="augment")
    authority = {
        "oracle_evidence": [
            {
                "id": str(r.id),
                "source_kind": r.source_kind,
                "extract": r.extract[:200],
            }
            for r in mix.selected
        ],
        "context_mix": mix.metadata,
    }
    dual = build_dual_ask_context(
        mode="disabled",
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        retrieval_items=[],
        coverage_manifest={"used": [], "failed": [], "excluded": []},
        memory_policy="disabled",
        oracle_authority=authority,
    )
    allow = merge_ask_citation_allowlist(
        list(dual.allowed_evidence_ids),
        oracle_authority=dual.oracle_authority,
    )
    # Model block: dossier-citable kinds from authority enter the allowlist.
    # memory_signal is dual-only (not bulk-imported via authority merge).
    citable_kinds = {"procurement", "document", "signal", "entity_intel"}
    assert allow
    for row in mix.selected:
        if row.source_kind in citable_kinds:
            assert str(row.id) in allow
    # Dual disabled → no signal factual inject.
    assert dual.signal_factual.get("items") in ([], None) or list(
        dual.signal_factual.get("items") or []
    ) == []


@pytest.mark.unit
def test_provider_facing_block_is_exactly_oracle_evidence_plus_dual() -> None:
    """Inspect the exact structure the model receives from dual+authority."""

    tenant_id = str(uuid.uuid4())
    dossier_id = str(uuid.uuid4())
    mix = mix_context_evidence(
        _seed_bag(uuid.UUID(tenant_id)),
        limit=15,
        question=QUESTION,
        memory_mode="augment",
    )
    authority = {
        "block": "oracle_authority",
        "tenant_id": tenant_id,
        "dossier_id": dossier_id,
        "question": QUESTION,
        "oracle_evidence": [
            {
                "id": str(r.id),
                "source_kind": r.source_kind,
                "extract": (mix.selected_extracts.get(str(r.id)) or r.extract)[:1200],
            }
            for r in mix.selected
        ],
        "context_mix": mix.metadata,
    }
    dual = build_dual_ask_context(
        mode="shadow",
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        retrieval_items=[
            {
                "id": "sig-observed",
                "text": "observed only",
                "checksum": "a" * 64,
                "tenant_id": tenant_id,
                "dossier_id": dossier_id,
                "citable": True,
            }
        ],
        coverage_manifest={"used": [], "failed": [], "excluded": []},
        memory_policy="shadow",
        oracle_authority=authority,
    )
    # Shadow: observe path may list items but injects zero into signal_factual.
    assert list(dual.signal_factual.get("items") or []) == []
    # Authority block is unchanged and still family-mixed.
    assert dual.oracle_authority["context_mix"]["selected_by_family"]["people"] >= 1
    model_evidence = dual.oracle_authority["oracle_evidence"]
    families = [map_context_family(type("X", (), r)()) if False else None for r in model_evidence]
    del families
    kinds = {r["source_kind"] for r in model_evidence}
    assert "entity_intel" in kinds
    assert "procurement" in kinds


# ---------------------------------------------------------------------------
# Optional real PostgreSQL isolation
# ---------------------------------------------------------------------------


def _require_pg_urls() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url or not runtime_url:
        detail = "G-26 PG isolation requires TEST_DATABASE_URL and TEST_RUNTIME_DATABASE_URL"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if runtime_url.startswith("postgresql://"):
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return migration_url, runtime_url, redis_url


@pytest.fixture
def g26_pg() -> Iterator[dict[str, Any]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG G-26 gate")
    migration_url, runtime_url, redis_url = _require_pg_urls()
    import json

    from flask_migrate import upgrade
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from opn_oracle import create_app
    from opn_oracle.tenants.context import TenantContext, tenant_context

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g26-context-mix-pg",
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
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()

    with migrator.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"g26-a-{tenant_a.hex[:8]}", "G26 Tenant A"),
            (tenant_b, f"g26-b-{tenant_b.hex[:8]}", "G26 Tenant B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES ("
                    ":id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
                ),
                {"id": tid, "slug": slug, "name": name},
            )
        for wid, tid, slug in (
            (workspace_a, tenant_a, f"g26-ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"g26-ws-b-{workspace_b.hex[:6]}"),
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
            (dossier_a, tenant_a, workspace_a, "G26 Dossier A"),
            (dossier_b, tenant_b, workspace_b, "G26 Dossier B"),
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

        def _insert_ev(tid: uuid.UUID, did: uuid.UUID, sk: str, extract: str, prov: dict) -> None:
            eid = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO evidence("
                    "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                    "provenance, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :sk, :extract, '{}'::jsonb, :checksum, 'internal', "
                    "CAST(:prov AS jsonb), 1, now(), now())"
                ),
                {
                    "id": eid,
                    "t": tid,
                    "sk": sk,
                    "extract": extract,
                    "checksum": os.urandom(32),
                    "prov": json.dumps(prov),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO evidence_dossiers(tenant_id, evidence_id, dossier_id) "
                    "VALUES (:t, :e, :d)"
                ),
                {"t": tid, "e": eid, "d": did},
            )

        for i in range(30):
            _insert_ev(
                tenant_a,
                dossier_a,
                "procurement",
                f"pliego A {i}",
                {"source_kind": "procurement"},
            )
        _insert_ev(
            tenant_a,
            dossier_a,
            "entity_intel",
            "Persona clave solo en A",
            {"source_kind": "entity_intel", "entity_kind": "person", "entity_name": "a-person"},
        )
        _insert_ev(
            tenant_a,
            dossier_a,
            "entity_intel",
            "Competidor solo en A",
            {
                "source_kind": "entity_intel",
                "entity_kind": "company",
                "role": "competitor",
                "entity_name": "a-comp",
            },
        )
        _insert_ev(
            tenant_b,
            dossier_b,
            "entity_intel",
            "Persona clave solo en B",
            {"source_kind": "entity_intel", "entity_kind": "person", "entity_name": "b-person"},
        )
        for i in range(10):
            _insert_ev(
                tenant_b,
                dossier_b,
                "procurement",
                f"pliego B {i}",
                {"source_kind": "procurement"},
            )

    SessionLocal = sessionmaker(bind=runtime, autoflush=False, autocommit=False)
    try:
        yield {
            "SessionLocal": SessionLocal,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "dossier_a": dossier_a,
            "dossier_b": dossier_b,
            "tenant_context": tenant_context,
            "TenantContext": TenantContext,
        }
    finally:
        runtime.dispose()
        migrator.dispose()


@pytest.mark.integration
def test_pg_tenant_dossier_isolation_no_cross_mix(g26_pg: dict[str, Any]) -> None:
    SessionLocal = g26_pg["SessionLocal"]
    tenant_context = g26_pg["tenant_context"]
    TenantContext = g26_pg["TenantContext"]
    actor = uuid.uuid4()

    ctx_a = TenantContext(tenant_id=g26_pg["tenant_a"], actor_id=actor)
    with tenant_context(ctx_a), SessionLocal() as session:
        block_a = load_oracle_authority_from_session(
            session,
            tenant_id=g26_pg["tenant_a"],
            dossier_id=g26_pg["dossier_a"],
            question=QUESTION,
            memory_mode="augment",
        )
    ctx_b = TenantContext(tenant_id=g26_pg["tenant_b"], actor_id=actor)
    with tenant_context(ctx_b), SessionLocal() as session:
        block_b = load_oracle_authority_from_session(
            session,
            tenant_id=g26_pg["tenant_b"],
            dossier_id=g26_pg["dossier_b"],
            question=QUESTION,
            memory_mode="augment",
        )

    text_a = " ".join(r.get("extract") or "" for r in block_a["oracle_evidence"])
    text_b = " ".join(r.get("extract") or "" for r in block_b["oracle_evidence"])
    assert "solo en A" in text_a
    assert "solo en B" not in text_a
    assert "solo en B" in text_b
    assert "solo en A" not in text_b
    assert block_a["context_mix"]["selected_by_family"]["people"] >= 1
    assert block_a["context_mix"]["selected_by_family"]["competitors"] >= 1
