"""Unit tests for dossier profile_config exposure in AI context."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from opn_oracle.ai.context import (
    _profile_summary,
    build_declared_profile_evidence,
    declared_evidence_id,
    validate_opportunity_origin_boundary,
)


def test_profile_summary_exposes_market_fields() -> None:
    dossier = SimpleNamespace(
        profile_config={
            "version": "market.v1",
            "own_offer": "Baterías",
            "decision_to_make": "Entrar o no",
            "competitors": [{"name": "Gamma"}, {"name": "Delta"}],
            "barriers": ["Permisos"],
            "keywords": ["almacenamiento"],
            "segments": ["utility"],
            "channels": [],
            "target_buyers": [],
            "partners": [],
            "regulators": [],
            "success_indicators": [],
            "horizon": "Q4",
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["version"] == "market.v1"
    assert summary["origin"] == "declared_by_client"
    assert summary["own_offer"] == "Baterías"
    assert summary["competitors"] == ["Gamma", "Delta"]
    assert summary["barriers"] == ["Permisos"]
    assert summary["keywords"] == ["almacenamiento"]


def test_profile_summary_exposes_competitive_fields() -> None:
    dossier = SimpleNamespace(
        profile_config={
            "version": "competitive-intelligence.v1",
            "own_offer": "Producto",
            "business_objective": "Ganar cuota",
            "competitors": [{"name": "Rival"}],
            "cpv": ["90910000"],
            "keywords": ["limpieza"],
            "geographies": ["ES"],
            "segments": [],
            "target_buyers": [],
            "sources": ["PLACSP"],
            "participation_criteria": "ISO",
            "exclusion_criteria": "",
            "success_indicators": [],
            "horizon": "",
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["version"] == "competitive-intelligence.v1"
    assert summary["origin"] == "declared_by_client"
    assert summary["own_offer"] == "Producto"
    assert summary["competitors"] == ["Rival"]
    assert summary["cpv"] == ["90910000"]
    assert summary["business_objective"] == "Ganar cuota"


def test_profile_summary_exposes_custom_demo_fields() -> None:
    """custom.v1 (expediente demo) deja de devolver solo {version} vacío."""

    dossier = SimpleNamespace(
        profile_config={
            "version": "custom.v1",
            "own_offer": (
                "Nexus Ibérica Sistemas: software, plataformas e inteligencia artificial"
            ),
            "decision_to_make": "Priorizar oportunidades PLACSP de software/IA",
            "competitors": [
                {"name": "Capgemini"},
                {"name": "NTT DATA"},
                {"name": "Inetum"},
            ],
            "cpv": ["72000000", "72200000"],
            "barriers": ["Homologación"],
            "keywords": ["software", "IA"],
            "segments": ["sector público"],
            "geographies": ["ES"],
            "target_buyers": ["AGE"],
            "sources": ["PLACSP"],
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["version"] == "custom.v1"
    assert summary["origin"] == "declared_by_client"
    assert "Nexus" in summary["own_offer"]
    assert summary["competitors"] == ["Capgemini", "NTT DATA", "Inetum"]
    assert "72000000" in summary["cpv"]


def test_declared_profile_evidence_is_labeled_and_deterministic() -> None:
    """Distinción declarado/oficial en el material de contexto (salida del builder)."""

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    dossier = SimpleNamespace(
        id=dossier_id,
        profile_config={
            "version": "custom.v1",
            "own_offer": "Nexus es integradora de software/IA",
            "competitors": [{"name": "Capgemini"}],
            "cpv": ["72000000"],
        },
    )
    items = build_declared_profile_evidence(dossier)  # type: ignore[arg-type]
    assert items, "el perfil demo debe producir piezas declared"
    kinds = {item["source_kind"] for item in items}
    origins = {item["origin"] for item in items}
    assert kinds == {"declared"}
    assert origins == {"declared_by_client"}
    assert all("Declarado por el cliente" in item["extract"] for item in items)
    assert all(item["label"].startswith("Declarado por el cliente") for item in items)
    offer_id = declared_evidence_id(dossier_id, "own_offer")
    assert str(offer_id) in {item["id"] for item in items}
    # Determinismo: mismo expediente+campo → mismo UUID.
    again = build_declared_profile_evidence(dossier)  # type: ignore[arg-type]
    assert [item["id"] for item in again] == [item["id"] for item in items]


def test_client_claim_cannot_appear_as_official_fact() -> None:
    """Una afirmación del cliente no puede quedar en facts[] como fuente oficial."""

    official = uuid.UUID("11111111-1111-1111-1111-111111111111")
    declared = declared_evidence_id(
        uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688"), "own_offer"
    )
    output = {
        "facts": [
            {
                "statement": "Capgemini ganó el ZTNA según PLACSP",
                "evidence_ids": [str(official)],
            },
            {
                "statement": "Nexus es integradora de software/IA",
                "evidence_ids": [str(declared)],
            },
            {
                "statement": "Mezcla ilegítima",
                "evidence_ids": [str(official), str(declared)],
            },
        ],
        "inferences": [],
        "fit_assessment": {
            "statement": "La oferta declarada de Nexus encaja con licitaciones de software",
            "declared_evidence_ids": [str(declared)],
            "official_evidence_ids": [str(official)],
            "confidence": 70,
            "origin": "declared_by_client",
        },
        "warnings": [],
    }
    cleaned = validate_opportunity_origin_boundary(
        output,
        official_ids={official},
        declared_ids={declared},
    )
    fact_statements = [item["statement"] for item in cleaned["facts"]]
    assert "Capgemini ganó el ZTNA según PLACSP" in fact_statements
    assert "Nexus es integradora de software/IA" not in fact_statements
    # El fact mixto conserva solo el ID oficial.
    mixed = next(item for item in cleaned["facts"] if item["statement"] == "Mezcla ilegítima")
    assert mixed["evidence_ids"] == [str(official)]
    assert cleaned["fit_assessment"] is not None
    assert cleaned["fit_assessment"]["origin"] == "declared_by_client"
    assert cleaned["fit_assessment"]["declared_evidence_ids"] == [str(declared)]
    assert any("declarado" in str(w).lower() for w in cleaned["warnings"])
