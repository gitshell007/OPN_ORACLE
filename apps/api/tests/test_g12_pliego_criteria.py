"""G12-UMBRAL · criterios/umbrales del pliego sin cifras fijas 65/60.

Gates:
- baseline: contexto/prompt no afirma 65/60 si el pliego no los trae
- 70/30 desde evidencia con cita
- missing → desconocido/no verificable, sin % inventado
- conflict entre documentos → no elige en silencio
- umbral mínimo ≠ ponderación
- tenant B never leaks into A
- path real build_context + serialización final estilo Preguntar
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest

from opn_oracle.ai.draft_offer import build_draft_offer
from opn_oracle.ai.pliego_criteria import (
    RESOLUTION_CONFLICT,
    RESOLUTION_MISSING,
    RESOLUTION_VERIFIED,
    format_criteria_security_clause,
    resolve_pliego_criteria,
)

# ---------------------------------------------------------------------------
# Fixtures (evidence text — product code must not hardcode these as truth)
# ---------------------------------------------------------------------------

PLIEGO_70_30 = """
EXTRACTO DEL PCAP · CONTR 2026 99001 · Demo G12
CRITERIOS DE ADJUDICACION
La adjudicacion se realiza segun la mejor relacion calidad-precio.
Ponderacion de criterios de adjudicacion:
- Oferta tecnica (juicio de valor): 70 %
- Oferta economica (formulas): 30 %
"""

PLIEGO_THRESHOLDS_65_60 = """
CRITERIOS DE ADJUDICACION
Si concurre un unico licitador, cuando la puntuacion del otro criterio sea superior a
los 65 puntos. Si concurren dos o mas licitadores, cuando la puntuacion del otro
criterio distinto de la oferta economica sea superior en 60 puntos porcentuales a la
media aritmetica de las puntuaciones obtenidas en dicho criterio por todas las empresas.
"""

PLIEGO_COMBINED_70_AND_MIN60 = """
CRITERIOS DE ADJUDICACION
Oferta tecnica: 70 %. Oferta economica: 30 %.
Dentro del criterio tecnico se exige una puntuacion minima de 60 puntos para no ser excluido.
"""

PLIEGO_NO_NUMBERS = """
CRITERIOS DE ADJUDICACION
La adjudicacion se realiza segun la mejor relacion calidad-precio.
Criterios evaluables mediante formulas (oferta economica) y juicio de valor (oferta tecnica).
Sin cifras de ponderacion en este extracto.
"""

PLIEGO_CONFLICT_A = """
EXTRACTO PCAP v1 · CRITERIOS DE ADJUDICACION
Oferta tecnica: 70 %. Oferta economica: 30 %.
"""

PLIEGO_CONFLICT_B = """
EXTRACTO PCAP v2 (rectificacion) · CRITERIOS DE ADJUDICACION
Oferta tecnica: 60 %. Oferta economica: 40 %.
"""

FORBIDDEN_MARKER_B = "FORBIDDEN_TENANT_B_MARKER_G12_UMBRAL_ZZZ"

FIXED_65_60_IN_PRODUCT = re.compile(
    r"criterios\s+65\s*/\s*60|umbrales?\s+(?:de\s+)?65\s*/\s*60|65/60\s+umbral|"
    r"Prioridad pliego:\s*criterios\s+65/60|"
    r"umbrales de 65 puntos \(único licitador\) / 60 puntos|"
    r"Umbrales de puntuación 65/60|"
    r"65\s*/\s*60\s+puntos",
    re.IGNORECASE,
)


def _evidence(extract: str, *, eid: uuid.UUID | None = None, kind: str = "document") -> dict:
    return {
        "id": str(eid or uuid.uuid4()),
        "extract": extract,
        "source_kind": kind,
        "locator": {"kind": "pliego_extract"},
        "classification": "internal",
        "untrusted_data": True,
    }


def _final_prompt_blob(payload: MappingLike) -> str:
    """Mirror provider user message: task + authorised context JSON."""

    return (
        "Responde a la pregunta del usuario.\n\n"
        "Contexto autorizado (JSON):\n"
        f"{json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}"
    )


MappingLike = dict[str, Any]


# ---------------------------------------------------------------------------
# Pure resolver unit gates
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_70_30_award_weights_verified_with_provenance() -> None:
    eid = uuid.uuid4()
    res = resolve_pliego_criteria([_evidence(PLIEGO_70_30, eid=eid)])
    assert res.award_weights_status == RESOLUTION_VERIFIED
    by_role = {i["role"]: i for i in res.award_weights}
    assert by_role["technical"]["value"] == 70.0
    assert by_role["technical"]["unit"] == "percent"
    assert by_role["economic"]["value"] == 30.0
    assert str(eid) in by_role["technical"]["evidence_ids"]
    assert res.min_thresholds_status == RESOLUTION_MISSING
    public = res.to_public()
    assert public["status"] == RESOLUTION_VERIFIED
    assert public["oracle_internal_fit"]["items"] == []
    assert any(p["evidence_id"] == str(eid) for p in public["provenance"])


@pytest.mark.unit
def test_resolve_missing_no_invented_percent() -> None:
    res = resolve_pliego_criteria([_evidence(PLIEGO_NO_NUMBERS)])
    assert res.award_weights_status == RESOLUTION_MISSING
    assert res.min_thresholds_status == RESOLUTION_MISSING
    assert res.award_weights == []
    assert res.min_score_thresholds == []
    assert res.has_criteria_block is True
    blob = json.dumps(res.to_public(), ensure_ascii=False)
    assert "65" not in blob
    assert "60" not in blob
    assert "70" not in blob
    assert any("desconocido/no verificable" in lim for lim in res.limitations)
    clause = format_criteria_security_clause(res)
    assert "65/60" not in clause
    assert "no inventes" in clause.casefold() or "no verificable" in clause.casefold()


@pytest.mark.unit
def test_resolve_conflict_does_not_pick_winner() -> None:
    a = _evidence(PLIEGO_CONFLICT_A, eid=uuid.uuid4())
    b = _evidence(PLIEGO_CONFLICT_B, eid=uuid.uuid4())
    res = resolve_pliego_criteria([a, b])
    assert res.award_weights_status == RESOLUTION_CONFLICT
    tech = next(i for i in res.award_weights if i["role"] == "technical")
    assert tech["status"] == RESOLUTION_CONFLICT
    values = {c["value"] for c in tech["candidates"]}
    assert values == {70.0, 60.0}
    # No silent single value on conflict item.
    assert "value" not in tech or tech.get("status") == RESOLUTION_CONFLICT
    public = res.to_public()
    assert public["status"] == RESOLUTION_CONFLICT
    assert any("conflicto" in lim.casefold() for lim in res.limitations)


@pytest.mark.unit
def test_resolve_separates_weight_from_min_threshold() -> None:
    """70% weight + 60 pts min threshold must not collapse into one field."""

    res = resolve_pliego_criteria([_evidence(PLIEGO_COMBINED_70_AND_MIN60)])
    assert res.award_weights_status == RESOLUTION_VERIFIED
    assert res.min_thresholds_status == RESOLUTION_VERIFIED
    weights = {i["role"]: i["value"] for i in res.award_weights if i.get("status") == "verified"}
    assert weights.get("technical") == 70.0
    assert weights.get("economic") == 30.0
    thr = [
        i
        for i in res.min_score_thresholds
        if i.get("status") == "verified" and i.get("value") == 60.0
    ]
    assert thr, "60 points min must land in min_score_thresholds, not award_weights"
    assert all(i.get("kind") != "award_weight" for i in thr)
    # Weight 70 is not a min threshold.
    assert all(i.get("value") != 70.0 for i in res.min_score_thresholds)


@pytest.mark.unit
def test_resolve_thresholds_65_60_as_min_not_weights() -> None:
    """Historical Baleares language: 65/60 are umbrales, not 65%/60% weights."""

    res = resolve_pliego_criteria([_evidence(PLIEGO_THRESHOLDS_65_60)])
    assert res.award_weights_status == RESOLUTION_MISSING
    assert res.min_thresholds_status == RESOLUTION_VERIFIED
    roles = {
        i["role"]: i["value"] for i in res.min_score_thresholds if i.get("status") == "verified"
    }
    assert roles.get("single_bidder_min_points") == 65.0
    assert roles.get("multi_bidder_pp_above_mean") == 60.0


@pytest.mark.unit
def test_generic_percentage_threshold_preserves_percent_unit() -> None:
    """A percentage threshold must not be mislabeled as points in prompt metadata."""

    res = resolve_pliego_criteria(
        [_evidence("El criterio técnico establece un umbral mínimo de 60% para continuar.")]
    )
    assert res.award_weights_status == RESOLUTION_MISSING
    assert res.min_thresholds_status == RESOLUTION_VERIFIED
    thresholds = [
        item for item in res.min_score_thresholds if item.get("status") == RESOLUTION_VERIFIED
    ]
    assert len(thresholds) == 1
    assert thresholds[0]["role"] == "minimum_score"
    assert thresholds[0]["value"] == 60.0
    assert thresholds[0]["unit"] == "percent"


@pytest.mark.unit
def test_allowlist_drops_other_evidence() -> None:
    allowed = uuid.uuid4()
    foreign = uuid.uuid4()
    res = resolve_pliego_criteria(
        [
            _evidence(PLIEGO_70_30, eid=allowed),
            _evidence(PLIEGO_CONFLICT_B, eid=foreign),
        ],
        allowed_evidence_ids=[str(allowed)],
    )
    assert res.award_weights_status == RESOLUTION_VERIFIED
    for item in res.award_weights:
        if item.get("status") == "verified":
            assert str(foreign) not in item.get("evidence_ids", [])
    assert all(p["evidence_id"] != str(foreign) for p in res.provenance)


# ---------------------------------------------------------------------------
# Draft offer: no invented 65/60 when pliego has 70/30 or nothing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_draft_offer_70_30_does_not_rewrite_as_65_60() -> None:
    official_id = uuid.uuid4()
    fit = {
        "verdict": {
            "recommendation": "go_conditioned",
            "human_gate": "awaiting_user_confirmation",
            "conditions": ["acreditar solvencia"],
        },
        "gaps": [],
        "lot_hint": "Lote 1",
        "statement": "encaje demo",
    }
    draft = build_draft_offer(
        fit_assessment=fit,
        profile={"version": "custom.v1", "own_offer": "Demo SaaS AAPP"},
        declared_by_field={},
        official_evidence=[_evidence(PLIEGO_70_30, eid=official_id)],
        as_of=None,
    )
    assert draft is not None
    blob = json.dumps(draft, ensure_ascii=False)
    assert "70" in blob
    assert "30" in blob
    # Productive invented phrases must not appear.
    assert FIXED_65_60_IN_PRODUCT.search(blob) is None
    # Bare 65/60 only allowed if evidence had them (it does not).
    assert "65/60" not in blob
    assert "65 puntos" not in blob


@pytest.mark.unit
def test_draft_offer_missing_marks_unknown_threshold() -> None:
    fit = {
        "verdict": {
            "recommendation": "go_conditioned",
            "human_gate": "awaiting_user_confirmation",
            "conditions": [],
        },
        "gaps": [],
        "lot_hint": None,
        "statement": "encaje",
    }
    draft = build_draft_offer(
        fit_assessment=fit,
        profile={"version": "custom.v1", "own_offer": "X"},
        declared_by_field={},
        official_evidence=[_evidence(PLIEGO_NO_NUMBERS)],
        as_of=None,
    )
    assert draft is not None
    blob = json.dumps(draft, ensure_ascii=False).casefold()
    assert "no verificable" in blob or "desconocido" in blob
    assert "65/60" not in blob
    assert FIXED_65_60_IN_PRODUCT.search(blob) is None


# ---------------------------------------------------------------------------
# build_context path (Preguntar) — real function + final prompt serialisation
# ---------------------------------------------------------------------------


@dataclass
class _EvRow:
    id: uuid.UUID
    source_kind: str
    extract: str
    classification: str = "internal"
    provenance: dict[str, Any] = field(default_factory=dict)
    locator: dict[str, Any] = field(default_factory=dict)
    checksum: bytes = field(default_factory=lambda: hashlib.sha256(b"g12").digest())
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeLoadResult:
    def __init__(self, candidates: list[_EvRow]) -> None:
        self.candidates = candidates
        self.metadata = {
            "loader": "context_family_candidate_loader.v1",
            "strategy": "per_family_bounded_select",
            "queries_run": 0,
            "candidate_pool_truncated_before_family_floor": False,
        }


class _FakeMixResult:
    def __init__(self, selected: list[_EvRow]) -> None:
        self.selected = selected
        self.selected_extracts = {str(r.id): r.extract for r in selected}
        self.metadata = {
            "mixer": "context_family_mix.v1",
            "selected_by_family": {"documents": len(selected)},
            "reason_codes": [],
            "budget_insufficient_for_all_families": False,
        }


def _patch_build_context_deps(dossier_id: uuid.UUID, tenant_id: uuid.UUID, rows: list[_EvRow]):
    dossier = MagicMock()
    dossier.id = dossier_id
    dossier.tenant_id = tenant_id
    dossier.title = "G12 demo"
    dossier.dossier_type = "opportunity"
    dossier.description = "test"
    dossier.strategic_goal = None
    dossier.sectors = []
    dossier.geography = []
    dossier.languages = []
    dossier.profile = {"version": "custom.v1", "own_offer": "Demo"}
    dossier.current_intent_revision_id = None
    dossier.version = 1

    session = MagicMock()

    def _scalar(statement: Any) -> Any:
        text = str(statement)
        if "StrategicDossier" in text or "strategic_dossiers" in text:
            return dossier
        return None

    def _scalars(statement: Any) -> Any:
        class _R:
            def __iter__(self_inner):
                return iter(())

            def all(self_inner):
                return []

        return _R()

    session.scalar = _scalar
    session.scalars = _scalars

    return session, dossier


@pytest.mark.unit
def test_build_context_70_30_in_payload_and_final_prompt_no_fixed_65_60() -> None:
    """Atraviesa build_context() y la serialización final que consume Preguntar."""

    from opn_oracle.ai.context import build_context

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    eid = uuid.uuid4()
    rows = [
        _EvRow(id=eid, source_kind="document", extract=PLIEGO_70_30),
    ]
    session, _dossier = _patch_build_context_deps(dossier_id, tenant_id, rows)

    with (
        patch("opn_oracle.ai.context.db") as db_mod,
        patch("opn_oracle.ai.context.require_tenant_id", return_value=tenant_id),
        patch(
            "opn_oracle.ai.context_candidate_loader.load_balanced_context_candidates",
            return_value=_FakeLoadResult(rows),
        ),
        patch(
            "opn_oracle.ai.context_mix.mix_context_evidence",
            return_value=_FakeMixResult(rows),
        ),
    ):
        db_mod.session = session
        built = build_context(dossier_id, max_tokens=2000, question="¿ponderación del pliego?")

    payload = built.payload
    assert "pliego_criteria" in payload
    criteria = payload["pliego_criteria"]
    assert criteria["award_weights"]["status"] == RESOLUTION_VERIFIED
    values = {
        i["role"]: i["value"]
        for i in criteria["award_weights"]["items"]
        if i.get("status") == "verified"
    }
    assert values.get("technical") == 70.0
    assert values.get("economic") == 30.0
    # Provenance cites dossier evidence id.
    assert any(p.get("evidence_id") == str(eid) for p in criteria.get("provenance") or [])

    security = str(payload.get("security_instruction") or "")
    assert "65/60" not in security
    assert FIXED_65_60_IN_PRODUCT.search(security) is None
    assert "pliego_criteria" in security

    final_prompt = _final_prompt_blob(payload)
    assert "70" in final_prompt
    assert "30" in final_prompt
    assert FIXED_65_60_IN_PRODUCT.search(final_prompt) is None
    # Manifest bounded metadata
    assert (
        built.manifest.get("pliego_criteria", {}).get("award_weights_status") == RESOLUTION_VERIFIED
    )


@pytest.mark.unit
def test_build_context_missing_criteria_no_invented_percent_in_prompt() -> None:
    from opn_oracle.ai.context import build_context

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    rows = [
        _EvRow(
            id=uuid.uuid4(),
            source_kind="document",
            extract=PLIEGO_NO_NUMBERS,
        ),
    ]
    session, _ = _patch_build_context_deps(dossier_id, tenant_id, rows)

    with (
        patch("opn_oracle.ai.context.db") as db_mod,
        patch("opn_oracle.ai.context.require_tenant_id", return_value=tenant_id),
        patch(
            "opn_oracle.ai.context_candidate_loader.load_balanced_context_candidates",
            return_value=_FakeLoadResult(rows),
        ),
        patch(
            "opn_oracle.ai.context_mix.mix_context_evidence",
            return_value=_FakeMixResult(rows),
        ),
    ):
        db_mod.session = session
        built = build_context(dossier_id, max_tokens=1500)

    criteria = built.payload["pliego_criteria"]
    assert criteria["status"] == RESOLUTION_MISSING or (
        criteria["award_weights"]["status"] == RESOLUTION_MISSING
        and criteria["min_score_thresholds"]["status"] == RESOLUTION_MISSING
    )
    final_prompt = _final_prompt_blob(built.payload)
    assert FIXED_65_60_IN_PRODUCT.search(final_prompt) is None
    assert "65/60" not in final_prompt
    # No invented classic demo pair outside evidence (evidence has no digits).
    assert not re.search(r"\b65\b", final_prompt)
    assert not re.search(r"\b60\b", final_prompt)
    assert "desconocido/no verificable" in final_prompt or "no inventes" in final_prompt.casefold()


@pytest.mark.unit
def test_build_context_conflict_exposed_not_silent() -> None:
    from opn_oracle.ai.context import build_context

    tenant_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    rows = [
        _EvRow(id=uuid.uuid4(), source_kind="document", extract=PLIEGO_CONFLICT_A),
        _EvRow(id=uuid.uuid4(), source_kind="document", extract=PLIEGO_CONFLICT_B),
    ]
    session, _ = _patch_build_context_deps(dossier_id, tenant_id, rows)

    with (
        patch("opn_oracle.ai.context.db") as db_mod,
        patch("opn_oracle.ai.context.require_tenant_id", return_value=tenant_id),
        patch(
            "opn_oracle.ai.context_candidate_loader.load_balanced_context_candidates",
            return_value=_FakeLoadResult(rows),
        ),
        patch(
            "opn_oracle.ai.context_mix.mix_context_evidence",
            return_value=_FakeMixResult(rows),
        ),
    ):
        db_mod.session = session
        built = build_context(dossier_id, max_tokens=2000)

    criteria = built.payload["pliego_criteria"]
    assert criteria["award_weights"]["status"] == RESOLUTION_CONFLICT
    final_prompt = _final_prompt_blob(built.payload)
    assert "conflict" in final_prompt.casefold() or "conflicto" in final_prompt.casefold()
    # Both candidate values present; no single silent pick.
    assert "70" in final_prompt and "60" in final_prompt


@pytest.mark.unit
def test_tenant_b_forbidden_marker_never_in_tenant_a_resolution() -> None:
    """Allowlist / bag of A cannot cite B extract with forbidden marker."""

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()
    evidence_a = _evidence(PLIEGO_70_30, eid=id_a)
    evidence_b = _evidence(
        PLIEGO_CONFLICT_B + f"\n{FORBIDDEN_MARKER_B}\nOferta tecnica: 55 %.",
        eid=id_b,
    )
    res = resolve_pliego_criteria(
        [evidence_a, evidence_b],
        allowed_evidence_ids=[str(id_a)],
    )
    blob = json.dumps(res.to_public(), ensure_ascii=False)
    assert FORBIDDEN_MARKER_B not in blob
    assert all(p["evidence_id"] != str(id_b) for p in res.provenance)
    values = {i["role"]: i["value"] for i in res.award_weights if i.get("status") == "verified"}
    assert values.get("technical") == 70.0
    assert 55.0 not in values.values()


@pytest.mark.unit
def test_baseline_red_fixed_phrase_absent_from_product_sources() -> None:
    """After fix: productive sources must not contain the old fixed priority phrase."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "opn_oracle" / "ai"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "Prioridad pliego: criterios 65/60" in text:
            offenders.append(str(path))
        if re.search(r'points_hint": "65/60 umbral PCAP', text):
            offenders.append(str(path))
        if "Umbrales de puntuación 65/60" in text and "test_" not in path.name:
            offenders.append(str(path))
    assert offenders == [], f"fixed 65/60 still in product: {offenders}"


# ---------------------------------------------------------------------------
# Optional real PostgreSQL gate (disposable)
# ---------------------------------------------------------------------------

_DISPOSABLE = ("test", "aislados", "ci", "g12")


def _assert_disposable(url: str, *, env_name: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0]
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "postgres", "pg"}:
        raise RuntimeError(f"{env_name} host={host!r} not disposable")
    if not db_name or not any(m in db_name.lower() for m in _DISPOSABLE):
        raise RuntimeError(f"{env_name} database={db_name!r} not disposable")
    return url


@pytest.mark.integration
def test_g12_build_context_pg_persist_and_resolve() -> None:
    """PostgreSQL real desechable: evidence A/B, build_context, isolation."""

    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for G12 PG gate")
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL") or migration_url
    if not migration_url:
        pytest.skip("TEST_DATABASE_URL required")
    migration_url = _assert_disposable(migration_url, env_name="TEST_DATABASE_URL")
    runtime_url = _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL")
    redis_url = os.getenv("TEST_REDIS_URL") or "redis://127.0.0.1:6379/14"

    from pathlib import Path

    from flask_migrate import upgrade
    from sqlalchemy import create_engine, text

    from opn_oracle import create_app
    from opn_oracle.ai.context import build_context
    from opn_oracle.tenants.context import TenantContext, tenant_context

    app = create_app(
        {
            "APP_ENV": "test",
            "TESTING": True,
            "SECRET_KEY": "g12-umbral-pliego-criteria-secret-key-32b",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    migrator = create_engine(migration_url)
    # Runtime role needs table privileges after migrate (migrator owns objects).
    with migrator.begin() as conn:
        conn.execute(text("GRANT USAGE ON SCHEMA public TO oracle_app"))
        conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO oracle_app"
            )
        )
        conn.execute(text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO oracle_app"))

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()
    ev_a_id = uuid.uuid4()
    ev_b_id = uuid.uuid4()
    actor_id = uuid.uuid4()

    with migrator.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"g12-a-{tenant_a.hex[:8]}", "G12 Tenant A"),
            (tenant_b, f"g12-b-{tenant_b.hex[:8]}", "G12 Tenant B"),
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
            (workspace_a, tenant_a, f"g12-ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"g12-ws-b-{workspace_b.hex[:6]}"),
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
            (dossier_a, tenant_a, workspace_a, "G12 Dossier A"),
            (dossier_b, tenant_b, workspace_b, "G12 Dossier B"),
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
            eid: uuid.UUID,
            tid: uuid.UUID,
            did: uuid.UUID,
            extract: str,
            *,
            ref: str,
        ) -> None:
            # memory_signal shape: no document FK; provenance must include source_kind.
            prov = {
                "source_kind": "memory_signal",
                "document_role": "pliego",
                "ref": ref,
            }
            conn.execute(
                text(
                    "INSERT INTO evidence("
                    "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                    "provenance, version, created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, 'memory_signal', :extract, '{}'::jsonb, :checksum, 'internal', "
                    "CAST(:prov AS jsonb), 1, now(), now())"
                ),
                {
                    "id": eid,
                    "t": tid,
                    "extract": extract,
                    "checksum": hashlib.sha256(extract.encode()).digest(),
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

        _insert_ev(ev_a_id, tenant_a, dossier_a, PLIEGO_70_30, ref="g12-a")
        _insert_ev(
            ev_b_id,
            tenant_b,
            dossier_b,
            PLIEGO_CONFLICT_B + "\n" + FORBIDDEN_MARKER_B,
            ref="g12-b",
        )

    with app.app_context():
        ctx = TenantContext(tenant_id=tenant_a, actor_id=actor_id)
        with tenant_context(ctx):
            built = build_context(dossier_a, max_tokens=2000, question="¿ponderación 70/30?")
            payload = built.payload
            blob = _final_prompt_blob(payload)
            assert FORBIDDEN_MARKER_B not in blob
            criteria = payload.get("pliego_criteria") or {}
            assert criteria.get("award_weights", {}).get("status") == RESOLUTION_VERIFIED
            values = {
                i["role"]: i["value"]
                for i in (criteria.get("award_weights") or {}).get("items") or []
                if i.get("status") == "verified"
            }
            assert values.get("technical") == 70.0
            assert values.get("economic") == 30.0
            assert FIXED_65_60_IN_PRODUCT.search(blob) is None
            assert "65/60" not in blob
            # Evidence id from tenant A is cited; B never appears.
            assert str(ev_b_id) not in blob
            assert any(
                p.get("evidence_id") == str(ev_a_id) for p in (criteria.get("provenance") or [])
            )
