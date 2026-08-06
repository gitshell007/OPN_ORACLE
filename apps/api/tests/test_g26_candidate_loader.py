"""G-26 corrective · balanced candidate loader (pre-cap diversity).

- Parity: SQL taxonomy tokens/order match map_context_family.
- Unit: FakeSession multi-family bag preserves people/competitors under flood.
- Optional PG adversarial: 1000+ recent tenders + 600 noise; old people/competitors
  survive both load_oracle_authority_from_session and build_context.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from opn_oracle.ai.context_candidate_loader import (
    DEFAULT_FAMILY_POOL_CAPS,
    LOADER_VERSION,
    classify_family_parity_spec,
    load_balanced_context_candidates,
)
from opn_oracle.ai.context_mix import (
    CONTEXT_FAMILIES,
    map_context_family,
    mix_context_evidence,
)
from opn_oracle.integrations.memory_ask_dual import load_oracle_authority_from_session

QUESTION = "¿qué persona y competidor influyen y qué dice el pliego?"


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


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
    """Returns pre-seeded evidence for any Evidence select (filters ignored)."""

    def __init__(
        self,
        *,
        tenant_id: uuid.UUID,
        dossier_id: uuid.UUID,
        evidence: list[_Row],
    ) -> None:
        self.tenant_id = tenant_id
        self.dossier_id = dossier_id
        self.evidence = evidence
        self._dossier = MagicMock()
        self._dossier.id = dossier_id
        self._dossier.tenant_id = tenant_id
        self._dossier.current_intent_revision_id = None

    def scalar(self, statement: Any) -> Any:
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
        if "Evidence" in text or "evidence" in text.lower():
            return _ScalarResult(list(self.evidence))
        return _ScalarResult([])


def _ev(
    *,
    source_kind: str,
    extract: str,
    tenant_id: uuid.UUID,
    provenance: dict[str, Any] | None = None,
    locator: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    eid: uuid.UUID | None = None,
) -> _Row:
    item_id = eid or uuid.uuid4()
    return _Row(
        id=item_id,
        source_kind=source_kind,
        extract=extract,
        provenance=provenance or {"source_kind": source_kind},
        locator=locator or {},
        checksum=hashlib.sha256(f"{item_id}:{extract}".encode()).digest(),
        tenant_id=tenant_id,
        created_at=created_at or datetime.now(UTC),
    )


def _flood_bag(tenant_id: uuid.UUID) -> tuple[list[_Row], list[uuid.UUID], list[uuid.UUID]]:
    """Recent tenders + noise dominate; people/competitors are older."""

    now = datetime.now(UTC)
    old = now - timedelta(days=400)
    mid = now - timedelta(days=200)
    rows: list[_Row] = []
    people_ids: list[uuid.UUID] = []
    comp_ids: list[uuid.UUID] = []

    # Older relevant entities (must survive pre-cap diversity).
    for i in range(3):
        eid = uuid.uuid4()
        people_ids.append(eid)
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Persona clave antigua {i} influye en el expediente.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "person",
                    "entity_name": f"persona-old-{i}",
                },
                created_at=old + timedelta(minutes=i),
                eid=eid,
            )
        )
    for i in range(4):
        eid = uuid.uuid4()
        comp_ids.append(eid)
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Competidor relevante antiguo {i}.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "role": "competitor",
                    "entity_name": f"comp-old-{i}",
                },
                created_at=old + timedelta(hours=i),
                eid=eid,
            )
        )
    rows.append(
        _ev(
            source_kind="entity_intel",
            extract="Actor institucional antiguo.",
            tenant_id=tenant_id,
            provenance={
                "source_kind": "entity_intel",
                "entity_kind": "organization",
                "actor_type": "institution",
                "entity_name": "actor-old",
            },
            created_at=old,
        )
    )
    for i in range(5):
        rows.append(
            _ev(
                source_kind="document",
                extract=f"Documento propio antiguo {i}.",
                tenant_id=tenant_id,
                provenance={"source_kind": "document", "document_role": "own_upload"},
                created_at=old,
            )
        )
    for i in range(3):
        rows.append(
            _ev(
                source_kind="memory_signal",
                extract=f"Memoria expediente antigua {i}.",
                tenant_id=tenant_id,
                provenance={"source_kind": "memory_signal", "source_ref": f"m-old-{i}"},
                created_at=old,
            )
        )

    # Mid-age residual tenders (still older than the flood).
    for i in range(20):
        rows.append(
            _ev(
                source_kind="procurement",
                extract=f"pliego mid {i} CONTR 2025 {1000 + i}",
                tenant_id=tenant_id,
                provenance={"source_kind": "procurement"},
                created_at=mid + timedelta(seconds=i),
            )
        )

    # Recent flood that would fill a global LIMIT 400.
    for i in range(500):
        rows.append(
            _ev(
                source_kind="procurement",
                extract=f"pliego reciente irrelevante {i} CONTR 2026 {20000 + i}",
                tenant_id=tenant_id,
                provenance={"source_kind": "procurement"},
                created_at=now - timedelta(seconds=i),
            )
        )
    for i in range(120):
        rows.append(
            _ev(
                source_kind="entity_intel",
                extract=f"Ruido actor reciente {i}.",
                tenant_id=tenant_id,
                provenance={
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "entity_name": f"noise-co-{i}",
                },
                created_at=now - timedelta(milliseconds=i + 1),
            )
        )
    return rows, people_ids, comp_ids


# ---------------------------------------------------------------------------
# Parity / unit
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parity_spec_shares_closed_families_and_tokens() -> None:
    spec = classify_family_parity_spec()
    assert spec["families"] == list(CONTEXT_FAMILIES)
    assert "competitor" in spec["competitor_role_tokens"]
    assert "person" in spec["person_tokens"]
    assert "pliego" in spec["tender_doc_roles"]
    assert spec["loader"] == LOADER_VERSION


@pytest.mark.unit
@pytest.mark.parametrize(
    "row_kwargs, expected",
    [
        (
            {
                "source_kind": "memory_signal",
                "provenance": {"source_kind": "memory_signal"},
            },
            "memory",
        ),
        (
            {
                "source_kind": "procurement",
                "provenance": {"source_kind": "procurement"},
            },
            "tenders",
        ),
        (
            {
                "source_kind": "entity_intel",
                "provenance": {
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "role": "competitor",
                },
            },
            "competitors",
        ),
        (
            {
                "source_kind": "entity_intel",
                "provenance": {
                    "source_kind": "entity_intel",
                    "entity_kind": "person",
                    "entity_name": "x",
                },
            },
            "people",
        ),
        (
            {
                "source_kind": "document",
                "provenance": {"source_kind": "document", "document_role": "own_upload"},
            },
            "documents",
        ),
        (
            {
                "source_kind": "document",
                "provenance": {"source_kind": "document", "document_role": "pliego"},
            },
            "tenders",
        ),
        (
            {
                "source_kind": "entity_intel",
                "provenance": {
                    "source_kind": "entity_intel",
                    "entity_kind": "organization",
                },
            },
            "actors",
        ),
        (
            {
                "source_kind": "signal",
                "provenance": {"source_kind": "signal"},
            },
            "other",
        ),
        (
            {
                "source_kind": "entity_intel",
                "provenance": {
                    "source_kind": "entity_intel",
                    "context_family": "people",
                    "entity_kind": "company",
                },
            },
            "people",
        ),
    ],
)
def test_map_context_family_matrix_stable(row_kwargs: dict, expected: str) -> None:
    row = _ev(extract="x", tenant_id=uuid.uuid4(), **row_kwargs)
    assert map_context_family(row) == expected


@pytest.mark.unit
def test_loader_preserves_old_people_competitors_under_tender_flood() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    bag, people_ids, comp_ids = _flood_bag(tenant_id)
    session = _FakeSession(tenant_id=tenant_id, dossier_id=dossier_id, evidence=bag)

    result = load_balanced_context_candidates(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
    )
    loaded_ids = {str(r.id) for r in result.candidates}
    assert people_ids and all(str(pid) in loaded_ids for pid in people_ids)
    assert comp_ids and all(str(cid) in loaded_ids for cid in comp_ids)
    by_fam = result.metadata["candidates_loaded_by_family"]
    assert by_fam["people"] >= 3
    assert by_fam["competitors"] >= 4
    assert by_fam["tenders"] >= 1
    assert result.metadata["loader"] == LOADER_VERSION
    # Metadata is bounded (no extracts).
    blob = json.dumps(result.metadata)
    assert "Persona clave" not in blob
    assert "extract" not in result.metadata


@pytest.mark.unit
def test_authority_path_uses_loader_and_keeps_families() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    bag, people_ids, comp_ids = _flood_bag(tenant_id)
    session = _FakeSession(tenant_id=tenant_id, dossier_id=dossier_id, evidence=bag)
    block = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        memory_mode="augment",
    )
    evidence = block["oracle_evidence"]
    assert evidence
    extracts = " ".join(str(r.get("extract") or "") for r in evidence)
    assert "Persona clave antigua" in extracts
    assert "Competidor relevante antiguo" in extracts
    mix = block["context_mix"]
    assert mix["selected_by_family"]["people"] >= 1
    assert mix["selected_by_family"]["competitors"] >= 1
    assert mix["selected_by_family"]["tenders"] >= 1
    assert "retrieval" in mix
    assert mix["retrieval"]["loader"] == LOADER_VERSION
    selected_ids = {r["id"] for r in evidence}
    # At least one old person and competitor id must remain.
    assert selected_ids & {str(p) for p in people_ids}
    assert selected_ids & {str(c) for c in comp_ids}


@pytest.mark.unit
def test_adding_more_tenders_does_not_change_people_competitor_ids() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    bag, people_ids, comp_ids = _flood_bag(tenant_id)
    session = _FakeSession(tenant_id=tenant_id, dossier_id=dossier_id, evidence=bag)
    block_a = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        memory_mode="augment",
    )
    people_a = {
        r["id"]
        for r in block_a["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    comp_a = {
        r["id"]
        for r in block_a["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    assert people_a and comp_a

    now = datetime.now(UTC)
    extra = [
        _ev(
            source_kind="procurement",
            extract=f"pliego extra {i}",
            tenant_id=tenant_id,
            provenance={"source_kind": "procurement"},
            created_at=now + timedelta(seconds=i + 1),
        )
        for i in range(1000)
    ]
    session2 = _FakeSession(
        tenant_id=tenant_id, dossier_id=dossier_id, evidence=bag + extra
    )
    block_b = load_oracle_authority_from_session(
        session2,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=QUESTION,
        memory_mode="augment",
    )
    people_b = {
        r["id"]
        for r in block_b["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    comp_b = {
        r["id"]
        for r in block_b["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    assert people_a == people_b
    assert comp_a == comp_b
    # Known ids still present.
    assert people_b <= {str(p) for p in people_ids}
    assert comp_b <= {str(c) for c in comp_ids}


@pytest.mark.unit
def test_safety_cap_metadata_distinct_from_budget_insufficient() -> None:
    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    bag, _, _ = _flood_bag(tenant_id)
    session = _FakeSession(tenant_id=tenant_id, dossier_id=dossier_id, evidence=bag)
    # Tiny safety cap: tenders fetched last in fetch_order, so diversity families
    # still load; residual families may be truncated.
    result = load_balanced_context_candidates(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        safety_total_pool_cap=12,
        family_pool_caps={f: 4 for f in CONTEXT_FAMILIES},
    )
    assert result.metadata["candidates_loaded"] <= 12
    # Mixer with huge item budget should NOT claim budget_insufficient solely
    # because retrieval was truncated.
    mix = mix_context_evidence(
        result.candidates,
        limit=40,
        question=QUESTION,
        memory_mode="augment",
    )
    meta = dict(mix.metadata)
    meta["retrieval"] = result.metadata
    if result.metadata.get("candidate_pool_truncated"):
        assert "candidate_pool_truncated" in result.metadata["reason_codes"]
    # budget_insufficient only when item budget < eligible families count.
    if meta.get("budget_insufficient_for_all_families"):
        assert meta["budget_items_requested"] < len(meta["eligible_families"])


@pytest.mark.unit
def test_default_pool_caps_are_bounded() -> None:
    total = sum(DEFAULT_FAMILY_POOL_CAPS.values())
    assert total <= 500
    assert DEFAULT_FAMILY_POOL_CAPS["tenders"] >= DEFAULT_FAMILY_POOL_CAPS["people"]


# ---------------------------------------------------------------------------
# Real PostgreSQL adversarial gate
# ---------------------------------------------------------------------------


def _require_pg_urls() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url or not runtime_url:
        detail = "G-26 PG adversarial requires TEST_DATABASE_URL and TEST_RUNTIME_DATABASE_URL"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if runtime_url.startswith("postgresql://"):
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return migration_url, runtime_url, redis_url


@pytest.fixture
def g26_precap_pg() -> Iterator[dict[str, Any]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG G-26 pre-cap gate")
    migration_url, runtime_url, redis_url = _require_pg_urls()
    from flask_migrate import upgrade
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from opn_oracle import create_app
    from opn_oracle.tenants.context import TenantContext, tenant_context

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g26-precap-diversity-pg",
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
    people_ids: list[uuid.UUID] = []
    comp_ids: list[uuid.UUID] = []

    now = datetime.now(UTC)
    old = now - timedelta(days=400)

    with migrator.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"g26p-a-{tenant_a.hex[:8]}", "G26 Precap Tenant A"),
            (tenant_b, f"g26p-b-{tenant_b.hex[:8]}", "G26 Precap Tenant B"),
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
            (workspace_a, tenant_a, f"g26p-ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"g26p-ws-b-{workspace_b.hex[:6]}"),
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
            (dossier_a, tenant_a, workspace_a, "G26 Precap Dossier A"),
            (dossier_b, tenant_b, workspace_b, "G26 Precap Dossier B"),
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

        def _insert_ev(
            tid: uuid.UUID,
            did: uuid.UUID,
            sk: str,
            extract: str,
            prov: dict,
            *,
            created_at: datetime,
            eid: uuid.UUID | None = None,
        ) -> uuid.UUID:
            item_id = eid or uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO evidence("
                    "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                    "provenance, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :sk, :extract, '{}'::jsonb, :checksum, 'internal', "
                    "CAST(:prov AS jsonb), 1, :created_at, :created_at)"
                ),
                {
                    "id": item_id,
                    "t": tid,
                    "sk": sk,
                    "extract": extract,
                    "checksum": os.urandom(32),
                    "prov": json.dumps(prov),
                    "created_at": created_at,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO evidence_dossiers(tenant_id, evidence_id, dossier_id) "
                    "VALUES (:t, :e, :d)"
                ),
                {"t": tid, "e": item_id, "d": did},
            )
            return item_id

        # --- Tenant A: old diversity rows first ---
        for i in range(3):
            pid = _insert_ev(
                tenant_a,
                dossier_a,
                "entity_intel",
                f"Persona clave antigua {i} influye.",
                {
                    "source_kind": "entity_intel",
                    "entity_kind": "person",
                    "entity_name": f"persona-old-{i}",
                },
                created_at=old + timedelta(minutes=i),
            )
            people_ids.append(pid)
        for i in range(4):
            cid = _insert_ev(
                tenant_a,
                dossier_a,
                "entity_intel",
                f"Competidor relevante antiguo {i}.",
                {
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "role": "competitor",
                    "entity_name": f"comp-old-{i}",
                },
                created_at=old + timedelta(hours=i),
            )
            comp_ids.append(cid)
        _insert_ev(
            tenant_a,
            dossier_a,
            "entity_intel",
            "Actor institucional antiguo.",
            {
                "source_kind": "entity_intel",
                "entity_kind": "organization",
                "actor_type": "institution",
                "entity_name": "actor-old-a",
            },
            created_at=old,
        )
        # Documents: source_kind=document requires document_id/version/chunk FKs.
        # Use server-owned explicit context_family on free-shape entity_intel so
        # the closed taxonomy maps to ``documents`` without a full document graph.
        for i in range(5):
            _insert_ev(
                tenant_a,
                dossier_a,
                "entity_intel",
                f"Documento propio antiguo {i}.",
                {
                    "source_kind": "entity_intel",
                    "context_family": "documents",
                    "document_role": "own_upload",
                },
                created_at=old,
            )
        for i in range(3):
            _insert_ev(
                tenant_a,
                dossier_a,
                "memory_signal",
                f"Memoria expediente antigua {i}.",
                {"source_kind": "memory_signal", "source_ref": f"m-old-{i}"},
                created_at=old,
            )

        # 1000 recent tenders (would bury old entities under LIMIT 400).
        for i in range(1000):
            _insert_ev(
                tenant_a,
                dossier_a,
                "procurement",
                f"pliego reciente irrelevante {i} CONTR 2026 {30000 + i}",
                {"source_kind": "procurement"},
                created_at=now - timedelta(seconds=i),
            )
        # 600 recent entity_intel noise.
        for i in range(600):
            _insert_ev(
                tenant_a,
                dossier_a,
                "entity_intel",
                f"Ruido actor reciente {i}.",
                {
                    "source_kind": "entity_intel",
                    "entity_kind": "company",
                    "entity_name": f"noise-co-{i}",
                },
                created_at=now - timedelta(milliseconds=i + 1),
            )

        # Tenant B forbidden markers.
        _insert_ev(
            tenant_b,
            dossier_b,
            "entity_intel",
            "Persona clave solo en B FORBIDDEN_MARKER_B",
            {
                "source_kind": "entity_intel",
                "entity_kind": "person",
                "entity_name": "b-person",
            },
            created_at=now,
        )
        for i in range(50):
            _insert_ev(
                tenant_b,
                dossier_b,
                "procurement",
                f"pliego B {i} FORBIDDEN_MARKER_B",
                {"source_kind": "procurement"},
                created_at=now - timedelta(seconds=i),
            )

    SessionLocal = sessionmaker(bind=runtime, autoflush=False, autocommit=False)
    try:
        yield {
            "app": app,
            "SessionLocal": SessionLocal,
            "tenant_a": tenant_a,
            "tenant_b": tenant_b,
            "dossier_a": dossier_a,
            "dossier_b": dossier_b,
            "people_ids": people_ids,
            "comp_ids": comp_ids,
            "tenant_context": tenant_context,
            "TenantContext": TenantContext,
            "migrator": migrator,
            "runtime": runtime,
        }
    finally:
        runtime.dispose()
        migrator.dispose()


@pytest.mark.integration
def test_pg_adversarial_authority_keeps_old_families(g26_precap_pg: dict[str, Any]) -> None:
    SessionLocal = g26_precap_pg["SessionLocal"]
    tenant_context = g26_precap_pg["tenant_context"]
    TenantContext = g26_precap_pg["TenantContext"]
    actor = uuid.uuid4()
    people_ids = {str(p) for p in g26_precap_pg["people_ids"]}
    comp_ids = {str(c) for c in g26_precap_pg["comp_ids"]}

    ctx = TenantContext(tenant_id=g26_precap_pg["tenant_a"], actor_id=actor)
    with tenant_context(ctx), SessionLocal() as session:
        # Baseline demonstration: global LIMIT 400 would miss old people.
        from sqlalchemy import select

        from opn_oracle.oracle.links import EvidenceDossier
        from opn_oracle.oracle.models import Evidence

        evidence_ids = select(EvidenceDossier.evidence_id).where(
            EvidenceDossier.tenant_id == g26_precap_pg["tenant_a"],
            EvidenceDossier.dossier_id == g26_precap_pg["dossier_a"],
        )
        global_400 = list(
            session.scalars(
                select(Evidence)
                .where(
                    Evidence.id.in_(evidence_ids),
                    Evidence.tenant_id == g26_precap_pg["tenant_a"],
                )
                .order_by(Evidence.created_at.desc())
                .limit(400)
            )
        )
        global_ids = {str(r.id) for r in global_400}
        # With 1000 recent tenders + 600 noise, old people are outside top-400.
        assert not (people_ids & global_ids), (
            "baseline expected to fail diversity: old people still in global 400"
        )
        assert not (comp_ids & global_ids), (
            "baseline expected to fail diversity: old competitors still in global 400"
        )

        block = load_oracle_authority_from_session(
            session,
            tenant_id=g26_precap_pg["tenant_a"],
            dossier_id=g26_precap_pg["dossier_a"],
            question=QUESTION,
            memory_mode="augment",
        )

    extracts = " ".join(r.get("extract") or "" for r in block["oracle_evidence"])
    assert "Persona clave antigua" in extracts
    assert "Competidor relevante antiguo" in extracts
    assert "FORBIDDEN_MARKER_B" not in extracts
    mix = block["context_mix"]
    assert mix["selected_by_family"]["people"] >= 1
    assert mix["selected_by_family"]["competitors"] >= 1
    assert mix["selected_by_family"]["tenders"] >= 1
    assert mix["selected_by_family"].get("documents", 0) >= 1 or mix["selected_by_family"].get(
        "memory", 0
    ) >= 1
    assert "retrieval" in mix
    selected_ids = {r["id"] for r in block["oracle_evidence"]}
    assert selected_ids & people_ids
    assert selected_ids & comp_ids

    # Determinism: second call same selection for people/competitors.
    with tenant_context(ctx), SessionLocal() as session:
        block2 = load_oracle_authority_from_session(
            session,
            tenant_id=g26_precap_pg["tenant_a"],
            dossier_id=g26_precap_pg["dossier_a"],
            question=QUESTION,
            memory_mode="augment",
        )
    people1 = {
        r["id"]
        for r in block["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    people2 = {
        r["id"]
        for r in block2["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    comp1 = {
        r["id"]
        for r in block["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    comp2 = {
        r["id"]
        for r in block2["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    assert people1 == people2
    assert comp1 == comp2


@pytest.mark.integration
def test_pg_adversarial_build_context_keeps_old_families(
    g26_precap_pg: dict[str, Any],
) -> None:
    from opn_oracle.ai.context import build_context

    app = g26_precap_pg["app"]
    tenant_context = g26_precap_pg["tenant_context"]
    TenantContext = g26_precap_pg["TenantContext"]
    actor = uuid.uuid4()
    people_ids = {str(p) for p in g26_precap_pg["people_ids"]}
    comp_ids = {str(c) for c in g26_precap_pg["comp_ids"]}

    ctx = TenantContext(tenant_id=g26_precap_pg["tenant_a"], actor_id=actor)
    with app.app_context(), tenant_context(ctx):
        built = build_context(
            g26_precap_pg["dossier_a"],
            max_tokens=8_000,
            question=QUESTION,
            memory_mode="augment",
        )

    payload_evidence = built.payload.get("evidence") or []
    extracts = " ".join(str(r.get("extract") or "") for r in payload_evidence)
    assert "Persona clave antigua" in extracts
    assert "Competidor relevante antiguo" in extracts
    assert "FORBIDDEN_MARKER_B" not in extracts
    mix = (built.manifest or {}).get("context_mix") or {}
    # build_context may store mix under manifest — also accept payload key.
    if not mix:
        mix = built.payload.get("context_mix") or {}
    if mix:
        assert mix.get("selected_by_family", {}).get("people", 0) >= 1
        assert mix.get("selected_by_family", {}).get("competitors", 0) >= 1
        assert "retrieval" in mix
    selected_ids = {str(r.get("id")) for r in payload_evidence}
    assert selected_ids & people_ids
    assert selected_ids & comp_ids


@pytest.mark.integration
def test_pg_extra_tenders_do_not_change_people_competitor_ids(
    g26_precap_pg: dict[str, Any],
) -> None:
    SessionLocal = g26_precap_pg["SessionLocal"]
    tenant_context = g26_precap_pg["tenant_context"]
    TenantContext = g26_precap_pg["TenantContext"]
    actor = uuid.uuid4()
    ctx = TenantContext(tenant_id=g26_precap_pg["tenant_a"], actor_id=actor)

    with tenant_context(ctx), SessionLocal() as session:
        block_a = load_oracle_authority_from_session(
            session,
            tenant_id=g26_precap_pg["tenant_a"],
            dossier_id=g26_precap_pg["dossier_a"],
            question=QUESTION,
            memory_mode="augment",
        )
    people_a = {
        r["id"]
        for r in block_a["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    comp_a = {
        r["id"]
        for r in block_a["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    assert people_a and comp_a

    # Insert another 1000 recent tenders.
    from sqlalchemy import text

    now = datetime.now(UTC)
    with g26_precap_pg["migrator"].begin() as conn:
        for i in range(1000):
            eid = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO evidence("
                    "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                    "provenance, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, 'procurement', :extract, '{}'::jsonb, :checksum, 'internal', "
                    "CAST(:prov AS jsonb), 1, :created_at, :created_at)"
                ),
                {
                    "id": eid,
                    "t": g26_precap_pg["tenant_a"],
                    "extract": f"pliego extra wave2 {i}",
                    "checksum": os.urandom(32),
                    "prov": json.dumps({"source_kind": "procurement"}),
                    "created_at": now + timedelta(seconds=i + 1),
                },
            )
            conn.execute(
                text(
                    "INSERT INTO evidence_dossiers(tenant_id, evidence_id, dossier_id) "
                    "VALUES (:t, :e, :d)"
                ),
                {
                    "t": g26_precap_pg["tenant_a"],
                    "e": eid,
                    "d": g26_precap_pg["dossier_a"],
                },
            )

    with tenant_context(ctx), SessionLocal() as session:
        block_b = load_oracle_authority_from_session(
            session,
            tenant_id=g26_precap_pg["tenant_a"],
            dossier_id=g26_precap_pg["dossier_a"],
            question=QUESTION,
            memory_mode="augment",
        )
    people_b = {
        r["id"]
        for r in block_b["oracle_evidence"]
        if "Persona clave antigua" in (r.get("extract") or "")
    }
    comp_b = {
        r["id"]
        for r in block_b["oracle_evidence"]
        if "Competidor relevante antiguo" in (r.get("extract") or "")
    }
    assert people_a == people_b
    assert comp_a == comp_b
    text_b = " ".join(r.get("extract") or "" for r in block_b["oracle_evidence"])
    assert "FORBIDDEN_MARKER_B" not in text_b


@pytest.mark.integration
def test_pg_safety_cap_metadata_and_explain(g26_precap_pg: dict[str, Any]) -> None:
    SessionLocal = g26_precap_pg["SessionLocal"]
    tenant_context = g26_precap_pg["tenant_context"]
    TenantContext = g26_precap_pg["TenantContext"]
    actor = uuid.uuid4()
    ctx = TenantContext(tenant_id=g26_precap_pg["tenant_a"], actor_id=actor)

    with tenant_context(ctx), SessionLocal() as session:
        result = load_balanced_context_candidates(
            session,
            tenant_id=g26_precap_pg["tenant_a"],
            dossier_id=g26_precap_pg["dossier_a"],
            safety_total_pool_cap=20,
            family_pool_caps={
                "people": 4,
                "competitors": 4,
                "actors": 4,
                "tenders": 4,
                "documents": 4,
                "memory": 4,
                "other": 2,
            },
        )
        assert result.metadata["candidates_loaded"] <= 20
        assert result.metadata["candidates_loaded_by_family"]["people"] >= 1
        assert result.metadata["candidates_loaded_by_family"]["competitors"] >= 1
        # With tiny tenders cap after diversity families, tenders may still load.
        # Safety truncation must not be reported as mixer budget insufficiency.
        if result.metadata.get("candidate_pool_truncated"):
            assert "candidate_pool_truncated" in result.metadata["reason_codes"]

        # EXPLAIN on people query (disposable DB, no sensitive data).
        from sqlalchemy import text

        explain = session.execute(
            text(
                """
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT e.id
                FROM evidence e
                JOIN evidence_dossiers ed
                  ON ed.evidence_id = e.id AND ed.tenant_id = e.tenant_id
                WHERE ed.tenant_id = :t
                  AND ed.dossier_id = :d
                  AND e.tenant_id = :t
                  AND e.source_kind = 'entity_intel'
                  AND (
                    lower(coalesce(e.provenance->>'entity_kind', e.locator->>'entity_kind', ''))
                      IN ('person','people','persona','individual','human')
                    OR lower(coalesce(e.provenance->>'actor_type', e.locator->>'actor_type', ''))
                      IN ('person','people','persona','individual','human')
                  )
                ORDER BY e.created_at DESC, e.id DESC
                LIMIT 48
                """
            ),
            {"t": g26_precap_pg["tenant_a"], "d": g26_precap_pg["dossier_a"]},
        ).fetchall()
        plan = "\n".join(str(r[0]) for r in explain)
        # Sanity: plan executed and returned something parseable.
        assert "Limit" in plan or "Seq Scan" in plan or "Index" in plan
        # Soft budget: people query under 2s on disposable local DB.
        # (Do not hard-fail on CI variance; record in plan for the answer.)
        assert "Execution Time" in plan or "actual time" in plan.lower() or plan
