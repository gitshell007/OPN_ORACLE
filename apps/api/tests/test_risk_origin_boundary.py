"""SV2-RIESGO-DECL · frontera declarado/oficial en el agente risk + enricher."""

from __future__ import annotations

import json
import uuid

from opn_oracle.ai.context import (
    declared_evidence_id,
    enrich_risk_context_declared,
    validate_opportunity_origin_boundary,
    validate_risk_origin_boundary,
)
from opn_oracle.ai.provider import _sanitize_uncited_facts_json
from opn_oracle.ai.schemas import RiskAnalysisOutput


def _scores() -> dict:
    return {
        "impact": 50,
        "likelihood": 50,
        "velocity": 50,
        "exposure": 50,
        "uncertainty": 50,
        "controllability": 50,
        "overall": 50,
    }


def test_declared_cannot_appear_as_official_risk_fact() -> None:
    """Un fact/scenario que cite ID declared se retira o se limpia (falla antes del gate)."""

    official = uuid.UUID("11111111-1111-1111-1111-111111111111")
    declared = declared_evidence_id(uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688"), "barriers")
    output = {
        "title": "Riesgo demo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [
            {
                "statement": "Plazo del pliego según PCAP",
                "evidence_ids": [str(official)],
            },
            {
                "statement": "Homologación pendiente (lo dice el cliente)",
                "evidence_ids": [str(declared)],
            },
            {
                "statement": "Mezcla ilegítima riesgo",
                "evidence_ids": [str(official), str(declared)],
            },
        ],
        "inferences": [
            {
                "statement": "Inferencia solo declarada",
                "confidence": 40,
                "reasoning_summary": "sin base oficial",
                "evidence_ids": [str(declared)],
            }
        ],
        "scenarios": [
            {
                "name": "Escenario con declared",
                "description": "No debe sobrevivir como oficial",
                "probability": 30,
                "impact": 60,
                "evidence_ids": [str(declared)],
            },
            {
                "name": "Escenario oficial",
                "description": "Solo PCAP",
                "probability": 20,
                "impact": 50,
                "evidence_ids": [str(official)],
            },
        ],
        "risk_context_declared": [
            {
                "statement": "Barrera declarada: Homologación",
                "category": "homologation",
                "declared_evidence_ids": [str(declared)],
                "origin": "declared_by_client",
                "relevance": "Perfil",
            }
        ],
        "warnings": [],
        "confidence": 55,
        "open_questions": [],
        "recommendations": [],
    }
    cleaned = validate_risk_origin_boundary(
        output,
        official_ids={official},
        declared_ids={declared},
    )
    statements = [item["statement"] for item in cleaned["facts"]]
    assert "Plazo del pliego según PCAP" in statements
    assert "Homologación pendiente (lo dice el cliente)" not in statements
    mixed = next(
        item for item in cleaned["facts"] if item["statement"] == "Mezcla ilegítima riesgo"
    )
    assert mixed["evidence_ids"] == [str(official)]
    assert len(cleaned["inferences"]) == 0
    scenario_names = [s["name"] for s in cleaned["scenarios"]]
    assert "Escenario con declared" not in scenario_names
    assert "Escenario oficial" in scenario_names
    assert len(cleaned["risk_context_declared"]) == 1
    assert cleaned["risk_context_declared"][0]["origin"] == "declared_by_client"
    assert cleaned["risk_context_declared"][0]["declared_evidence_ids"] == [str(declared)]
    assert any("declarado" in str(w).lower() for w in cleaned["warnings"])


def test_risk_context_declared_without_ids_is_dropped() -> None:
    official = uuid.UUID("11111111-1111-1111-1111-111111111111")
    declared = declared_evidence_id(uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688"), "barriers")
    output = {
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [],
        "risk_context_declared": [
            {
                "statement": "Sin citas — debe caer",
                "category": "barrier",
                "declared_evidence_ids": [],
                "origin": "declared_by_client",
            },
            {
                "statement": "Con citas válidas",
                "category": "barrier",
                "declared_evidence_ids": [str(declared)],
                "origin": "declared_by_client",
            },
            {
                "statement": "ID inventado",
                "category": "barrier",
                "declared_evidence_ids": [str(uuid.uuid4())],
                "origin": "declared_by_client",
            },
        ],
        "warnings": [],
        "confidence": 40,
        "open_questions": [],
        "recommendations": [],
        "inferences": [],
    }
    cleaned = validate_risk_origin_boundary(
        output,
        official_ids={official},
        declared_ids={declared},
    )
    assert len(cleaned["risk_context_declared"]) == 1
    assert cleaned["risk_context_declared"][0]["statement"] == "Con citas válidas"
    assert any("risk_context_declared" in str(w) for w in cleaned["warnings"])


def test_sanitize_drops_risk_context_declared_without_evidence_id() -> None:
    """Sanitizador pre-schema: ítem declarado sin declared_evidence_ids → drop + warning."""

    payload = {
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [
            {
                "statement": "Hecho fundado",
                "evidence_ids": [str(uuid.uuid4())],
            },
            {
                "statement": "Hecho sin citas",
                "evidence_ids": [],
            },
        ],
        "risk_context_declared": [
            {
                "statement": "Barrera sin id",
                "category": "barrier",
                "declared_evidence_ids": [],
            },
            {
                "statement": "Barrera con id",
                "category": "barrier",
                "declared_evidence_ids": [str(uuid.uuid4())],
                "origin": "declared_by_client",
            },
        ],
        "confidence": 70,
        "warnings": [],
        "inferences": [],
        "recommendations": [],
        "open_questions": [],
    }
    cleaned = _sanitize_uncited_facts_json(json.dumps(payload), agent="risk")
    data = json.loads(cleaned)
    assert len(data["facts"]) == 1
    assert len(data["risk_context_declared"]) == 1
    assert data["risk_context_declared"][0]["statement"] == "Barrera con id"
    assert any("risk_context_declared" in w for w in data["warnings"])
    assert any("Se retiraron 1 fact" in w for w in data["warnings"])


def test_enrich_risk_context_declared_from_profile_barriers() -> None:
    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    barriers_id = str(declared_evidence_id(dossier_id, "barriers"))
    competitors_id = str(declared_evidence_id(dossier_id, "competitors"))
    context_payload = {
        "declared_evidence": [
            {
                "id": barriers_id,
                "extract": (
                    "[Declarado por el cliente] Barreras declaradas: "
                    "Homologación sectorial; Solvencia económica limitada"
                ),
                "source_kind": "declared",
                "origin": "declared_by_client",
                "locator": {"field": "barriers"},
            },
            {
                "id": competitors_id,
                "extract": (
                    "[Declarado por el cliente] Competidores declarados: Capgemini, NTT DATA"
                ),
                "source_kind": "declared",
                "origin": "declared_by_client",
                "locator": {"field": "competitors"},
            },
        ]
    }
    output = {
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [],
        "risk_context_declared": [],
        "warnings": [],
        "confidence": 50,
        "inferences": [],
        "recommendations": [],
        "open_questions": [],
    }
    enriched = enrich_risk_context_declared(output, context_payload=context_payload)
    items = enriched["risk_context_declared"]
    assert len(items) >= 2
    statements = " ".join(item["statement"] for item in items)
    assert "Homologación" in statements
    assert "Solvencia" in statements or "Competidores" in statements or "competitiva" in statements
    for item in items:
        assert item["origin"] == "declared_by_client"
        assert item["declared_evidence_ids"]
    # Frontera: con declared set correcto, todos pasan.
    cleaned = validate_risk_origin_boundary(
        enriched,
        official_ids=set(),
        declared_ids={uuid.UUID(barriers_id), uuid.UUID(competitors_id)},
    )
    assert len(cleaned["risk_context_declared"]) >= 2


def test_opportunity_origin_boundary_regression_intact() -> None:
    """La firma y el comportamiento del 095 no se rompen."""

    official = uuid.UUID("11111111-1111-1111-1111-111111111111")
    declared = declared_evidence_id(uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688"), "own_offer")
    output = {
        "facts": [
            {"statement": "Oficial PLACSP", "evidence_ids": [str(official)]},
            {"statement": "Solo declarado", "evidence_ids": [str(declared)]},
        ],
        "inferences": [],
        "fit_assessment": {
            "statement": "Encaje demo",
            "declared_evidence_ids": [str(declared)],
            "official_evidence_ids": [str(official)],
            "confidence": 60,
            "origin": "declared_by_client",
        },
        "warnings": [],
    }
    cleaned = validate_opportunity_origin_boundary(
        output,
        official_ids={official},
        declared_ids={declared},
    )
    assert len(cleaned["facts"]) == 1
    assert cleaned["fit_assessment"]["origin"] == "declared_by_client"
    assert cleaned["fit_assessment"]["declared_evidence_ids"] == [str(declared)]


def test_risk_schema_coerces_incomplete_declared_items() -> None:
    payload = {
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 40,
        "open_questions": [],
        "warnings": [],
        "risk_context_declared": [
            {"statement": "sin ids"},
            {
                "statement": "ok",
                "declared_evidence_ids": ["22222222-2222-2222-2222-222222222222"],
                "category": "weird_cat",
            },
        ],
    }
    # StrictModel: UUIDs se aceptan como str vía JSON (camino real del provider).
    model = RiskAnalysisOutput.model_validate_json(json.dumps(payload))
    assert len(model.risk_context_declared) == 1
    assert model.risk_context_declared[0].statement == "ok"
    assert model.risk_context_declared[0].origin == "declared_by_client"
    assert model.risk_context_declared[0].category == "other"
