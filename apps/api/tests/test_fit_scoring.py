"""SV2-ENCAJE · tests del motor de puntuación dimensional (coste 0)."""

from __future__ import annotations

import uuid
from datetime import date

from opn_oracle.ai.context import declared_evidence_id, validate_opportunity_origin_boundary
from opn_oracle.ai.fit_scoring import (
    enrich_opportunity_fit_assessment,
    score_profile_tender_fit,
)
from opn_oracle.ai.schemas import OpportunityAnalysisOutput, OpportunityFitAssessment


BALEARES_EXTRACT = """
EXTRACTO DEL PCAP · CONTR 2026 11077 · Baleares · Red de agentes inteligentes
Fuente: PCAP oficial PLACSP.

IDENTIFICACION
- Expediente: CONTR 2026 11077
- Objeto: servicio de diseño, desarrollo e implantación de una red de agentes inteligentes
  en el Govern de les Illes Balears (GOIB)
- Importe publicado: 5.450.796,93 EUR
- Deadline presentación ofertas: 2026-08-06
- Lotes: 2 (Lote 1: Gobernanza de la IA / Lote 2: Red de agentes inteligentes)

F.2. MEDIOS DE ACREDITACION DE LA SOLVENCIA ECONOMICA Y FINANCIERA
La solvencia economica se acredita con el volumen anual de negocio. Se entiende que la
solvencia es suficiente si el volumen anual de negocio declarado por la empresa, referido
al ano de mayor volumen de los tres ultimos concluidos, es al menos una vez y media el
valor estimado del contrato (o la parte correspondiente al lote).

F.3. MEDIOS DE ACREDITACION DE LA SOLVENCIA TECNICA
Medios: relacion de los servicios ejecutados en el curso de los ultimos tres anos avalada
por certificados de buena ejecucion.

LOTES
- Lote 1: Gobernanza de la IA
- Lote 2: Red de agentes inteligentes
"""

NEXUS_PROFILE = {
    "version": "custom.v1",
    "own_offer": (
        "Nexus Ibérica Sistemas: software, plataformas e inteligencia artificial para "
        "administraciones públicas y grandes cuentas (integración, analítica, agentes y "
        "modernización de sistemas)."
    ),
    "decision_to_make": "Priorizar oportunidades PLACSP de software/IA",
    "competitors": [
        {"name": "Capgemini"},
        {"name": "NTT DATA"},
        {"name": "Inetum"},
    ],
    "cpv": ["72000000", "72200000", "72212000", "72222300", "48000000"],
    "barriers": [
        "Homologación y solvencia técnica exigida en AAPP",
        "Plazos de licitación y documentación técnica",
    ],
}


def _nexus_declared_fields(dossier_id: uuid.UUID) -> dict[str, str]:
    return {
        "own_offer": str(declared_evidence_id(dossier_id, "own_offer")),
        "cpv": str(declared_evidence_id(dossier_id, "cpv")),
        "barriers": str(declared_evidence_id(dossier_id, "barriers")),
        "competitors": str(declared_evidence_id(dossier_id, "competitors")),
    }


def _baleares_official(eid: uuid.UUID | None = None) -> list[dict]:
    return [
        {
            "id": str(eid or uuid.uuid4()),
            "extract": BALEARES_EXTRACT,
            "source_kind": "document",
            "locator": {"kind": "pliego_extract", "ref": "CONTR 2026 11077"},
        }
    ]


def test_nexus_baleares_dimensions_dual_citations_and_not_evaluable() -> None:
    """Demo canónica: Nexus (ficticia) vs CONTR 2026 11077 Baleares."""

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.UUID("d96614d3-aaaa-4bbb-8ccc-111111111111")
    declared = _nexus_declared_fields(dossier_id)
    scored = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=_baleares_official(official_id),
        as_of=date(2026, 8, 4),
    )
    assert scored is not None
    assert scored["origin"] == "declared_by_client"
    assert scored["tender_ref"] == "CONTR 2026 11077"
    assert scored["scoring_engine"] == "sv2_encaje_v1"

    by_key = {d["key"]: d for d in scored["dimensions"]}
    assert set(by_key) == {"cpv", "solvency", "lots", "deadline"}

    # CPV / ámbito: TI/IA del pliego vs CPV software del perfil → fit o partial
    assert by_key["cpv"]["status"] in {"fit", "partial"}
    assert "[oficial]" in by_key["cpv"]["requirement"]
    assert "[declarado]" in by_key["cpv"]["capability"]
    assert by_key["cpv"]["requirement_origin"] == "official"
    assert by_key["cpv"]["capability_origin"] == "declared_by_client"
    assert str(official_id) in by_key["cpv"]["official_evidence_ids"] or by_key[
        "cpv"
    ]["official_evidence_ids"]  # may match AI hints
    assert declared["cpv"] in by_key["cpv"]["declared_evidence_ids"] or declared[
        "own_offer"
    ] in by_key["cpv"]["declared_evidence_ids"]

    # Solvencia: F.2/F.3 en pliego, Nexus sin volumen ni servicios 3 años
    assert by_key["solvency"]["status"] == "not_evaluable"
    assert "no evaluable con lo declarado" in by_key["solvency"]["status_reason"]
    assert "F.2" in by_key["solvency"]["requirement"]
    assert "F.3" in by_key["solvency"]["requirement"]
    cap_l = by_key["solvency"]["capability"].casefold()
    assert "volumen" in cap_l and "no" in cap_l

    # Lotes: Lote 2 red de agentes encaja con oferta de agentes/IA
    assert by_key["lots"]["status"] in {"fit", "partial"}
    assert "Lote 2" in by_key["lots"]["requirement"] or "Lote 2" in by_key["lots"][
        "capability"
    ]

    # Plazo: cierra 2026-08-06, as_of 2026-08-04 → 2 días, partial
    assert by_key["deadline"]["status"] == "partial"
    assert "2026-08-06" in by_key["deadline"]["requirement"]
    assert "no evaluable" in by_key["deadline"]["status_reason"].casefold() or (
        "corta" in by_key["deadline"]["status_reason"].casefold()
    )

    # Veredicto: go_condicionado + puerta humana
    verdict = scored["verdict"]
    assert verdict["recommendation"] == "go_conditioned"
    assert verdict["human_gate"] == "awaiting_user_confirmation"
    assert any("1,5" in c or "1.5" in c or "F.2" in c for c in verdict["conditions"])
    assert any("F.3" in c or "tres años" in c or "tres anos" in c for c in verdict["conditions"])
    assert "automática" in verdict["rationale"] or "automatica" in verdict["rationale"].casefold() or (
        "humana" in verdict["rationale"].casefold()
    )


def test_solvency_with_declared_volume_can_fail() -> None:
    """Si el perfil declara volumen insuficiente → no_fit (no inventa)."""

    dossier_id = uuid.uuid4()
    profile = {
        **NEXUS_PROFILE,
        "annual_turnover": 100_000,  # << 1.5 × 5.45M
        "past_services": "Servicios TI 2023-2025 con certificados",
    }
    declared = {
        **_nexus_declared_fields(dossier_id),
        "annual_turnover": str(declared_evidence_id(dossier_id, "annual_turnover")),
    }
    scored = score_profile_tender_fit(
        profile=profile,
        declared_by_field=declared,
        official_evidence=_baleares_official(),
        as_of=date(2026, 8, 4),
    )
    assert scored is not None
    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert solv["status"] == "no_fit"
    assert scored["verdict"]["recommendation"] == "no_go"


def test_closed_deadline_is_no_go() -> None:
    dossier_id = uuid.uuid4()
    scored = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        declared_by_field=_nexus_declared_fields(dossier_id),
        official_evidence=_baleares_official(),
        as_of=date(2026, 8, 10),  # after 2026-08-06
    )
    assert scored is not None
    deadline = next(d for d in scored["dimensions"] if d["key"] == "deadline")
    assert deadline["status"] == "no_fit"
    assert scored["verdict"]["recommendation"] == "no_go"


def test_schema_accepts_dimensional_fit() -> None:
    import json

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.uuid4()
    scored = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        declared_by_field=_nexus_declared_fields(dossier_id),
        official_evidence=_baleares_official(official_id),
        as_of=date(2026, 8, 4),
    )
    assert scored is not None
    # Wire format (JSON) — mismo camino que service.run_agent (strict=True).
    fit = OpportunityFitAssessment.model_validate_json(json.dumps(scored))
    assert fit.verdict is not None
    assert fit.verdict.human_gate == "awaiting_user_confirmation"
    assert len(fit.dimensions) == 4
    # Embebido en OpportunityAnalysisOutput
    payload = {
        "title": "Oportunidad Baleares agentes",
        "recommendation": "investigate",
        "scores": {
            "strategic_fit": 50,
            "urgency": 80,
            "expected_value": 70,
            "actionability": 40,
            "relationship_leverage": 30,
            "timing": 20,
            "confidence": 50,
            "execution_effort": 70,
            "blocking_risk": 60,
            "overall": 50,
        },
        "fit_assessment": scored,
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 50,
        "open_questions": [],
        "warnings": [],
    }
    out = OpportunityAnalysisOutput.model_validate_json(json.dumps(payload))
    assert out.fit_assessment is not None
    assert out.fit_assessment.verdict is not None
    assert out.fit_assessment.verdict.recommendation == "go_conditioned"


def test_enrich_merges_into_opportunity_output() -> None:
    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.uuid4()
    declared = _nexus_declared_fields(dossier_id)
    context = {
        "dossier": {"profile": NEXUS_PROFILE},
        "declared_evidence": [
            {
                "id": declared["own_offer"],
                "extract": f"[Declarado por el cliente] Oferta propia: {NEXUS_PROFILE['own_offer']}",
                "source_kind": "declared",
                "locator": {"field": "own_offer"},
            },
            {
                "id": declared["cpv"],
                "extract": "[Declarado por el cliente] CPV de interés declarados: "
                + ", ".join(NEXUS_PROFILE["cpv"]),
                "source_kind": "declared",
                "locator": {"field": "cpv"},
            },
            {
                "id": declared["barriers"],
                "extract": "[Declarado por el cliente] Barreras declaradas: "
                + "; ".join(NEXUS_PROFILE["barriers"]),
                "source_kind": "declared",
                "locator": {"field": "barriers"},
            },
        ],
        "allowed_declared_evidence_ids": list(declared.values()),
        "allowed_evidence_ids": [str(official_id)],
        "evidence": _baleares_official(official_id),
    }
    output = {
        "title": "Oportunidad",
        "recommendation": "investigate",
        "fit_assessment": {
            "statement": "Encaje genérico mock con la oferta.",
            "declared_evidence_ids": [declared["own_offer"]],
            "official_evidence_ids": [str(official_id)],
            "confidence": 55,
            "origin": "declared_by_client",
        },
        "facts": [],
        "warnings": [],
    }
    enriched = enrich_opportunity_fit_assessment(
        output, context_payload=context, as_of=date(2026, 8, 4)
    )
    fit = enriched["fit_assessment"]
    assert fit is not None
    assert len(fit["dimensions"]) == 4
    assert fit["verdict"]["recommendation"] == "go_conditioned"
    assert fit["verdict"]["human_gate"] == "awaiting_user_confirmation"
    # frontera sigue limpia
    cleaned = validate_opportunity_origin_boundary(
        enriched,
        official_ids={official_id},
        declared_ids={uuid.UUID(v) for v in declared.values()},
    )
    assert cleaned["fit_assessment"] is not None
    assert cleaned["fit_assessment"]["origin"] == "declared_by_client"
    assert cleaned["fit_assessment"]["verdict"]["human_gate"] == "awaiting_user_confirmation"
    solv = next(
        d for d in cleaned["fit_assessment"]["dimensions"] if d["key"] == "solvency"
    )
    assert solv["status"] == "not_evaluable"


def test_no_invention_without_official_evidence() -> None:
    """Sin pliego, solvencia/lotes/plazo no inventan umbrales."""

    dossier_id = uuid.uuid4()
    scored = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        declared_by_field=_nexus_declared_fields(dossier_id),
        official_evidence=[],
        as_of=date(2026, 8, 4),
    )
    assert scored is not None
    by_key = {d["key"]: d for d in scored["dimensions"]}
    assert by_key["solvency"]["status"] == "not_evaluable"
    assert by_key["deadline"]["status"] == "not_evaluable"
