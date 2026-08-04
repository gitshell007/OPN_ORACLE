"""SV2-BORRADOR · tests del generador de borrador de oferta (coste 0)."""

from __future__ import annotations

import json
import uuid
from datetime import date

from opn_oracle.ai.context import declared_evidence_id, validate_opportunity_origin_boundary
from opn_oracle.ai.draft_offer import (
    build_draft_offer,
    draft_offer_pollutes_official_facts,
    enrich_opportunity_draft_offer,
    strip_draft_from_official_facts,
)
from opn_oracle.ai.fit_scoring import score_profile_tender_fit
from opn_oracle.ai.schemas import OpportunityAnalysisOutput

# Extracto PCAP con criterios 65/60 (lo que recupera el 132) + F.2/F.3 + lotes.
BALEARES_EXTRACT = """
EXTRACTO DEL PCAP · CONTR 2026 11077 · Baleares · Red de agentes inteligentes
Fuente: PCAP oficial PLACSP (texto curado para preparación de oferta).

IDENTIFICACION
- Expediente: CONTR 2026 11077
- Objeto: servicio de diseño, desarrollo e implantación de una red de agentes inteligentes
  en el Govern de les Illes Balears (GOIB)
- Importe publicado: 5.450.796,93 EUR
- Deadline presentación ofertas: 2026-08-06
- Lotes: 2 (Lote 1: Gobernanza de la IA / Lote 2: Red de agentes inteligentes)

CRITERIOS DE ADJUDICACION
La adjudicacion se realiza segun la mejor relacion calidad-precio.
Criterios de adjudicacion evaluables mediante formulas (oferta economica) y criterios
evaluables mediante juicio de valor (oferta tecnica).
Si concurre un unico licitador, cuando la puntuacion del otro criterio sea superior a
los 65 puntos. Si concurren dos o mas licitadores, cuando la puntuacion del otro
criterio distinto de la oferta economica sea superior en 60 puntos porcentuales a la
media aritmetica de las puntuaciones obtenidas en dicho criterio por todas las empresas.

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


def _score_fit(dossier_id: uuid.UUID, official_id: uuid.UUID) -> tuple[dict, dict[str, str]]:
    declared = _nexus_declared_fields(dossier_id)
    scored = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=_baleares_official(official_id),
        as_of=date(2026, 8, 4),
    )
    assert scored is not None
    return scored, declared


def test_nexus_baleares_draft_has_sections_gaps_checklist() -> None:
    """Demo canónica: ≥3 secciones citando PCAP, gaps F.2/F.3, checklist pending."""

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.UUID("d96614d3-7f53-4f1a-b494-3567a2bd1b1d")
    fit, declared = _score_fit(dossier_id, official_id)

    draft = build_draft_offer(
        fit_assessment=fit,
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=_baleares_official(official_id),
        as_of=date(2026, 8, 4),
    )
    assert draft is not None
    assert draft["human_gate"] == "draft_requires_human_edit"
    assert "BORRADOR COMERCIAL" in draft["banner"]
    assert draft["origin"] == "declared_draft"
    assert draft["draft_engine"] == "sv2_borrador_v1"
    assert draft["tender_ref"] == "CONTR 2026 11077"
    assert draft["based_on_verdict"] == "go_conditioned"
    assert draft["lot_hint"] and "Lote 2" in draft["lot_hint"]

    sections = draft["sections"]
    assert len(sections) >= 3
    keys = {s["key"] for s in sections}
    assert "award_economic" in keys
    assert "award_technical" in keys
    # Umbrales 65/60 o solvencia como tercera+ sección
    assert "award_thresholds" in keys or "solvency_accreditation" in keys

    for sec in sections:
        assert "[oficial]" in sec["requirement"]
        assert sec["requirement_origin"] == "official"
        assert str(official_id) in sec["official_evidence_ids"] or sec["official_evidence_ids"]
        assert "[borrador declarado" in sec["our_response_draft"]
        assert sec["response_origin"] == "declared_generated"
        # No se presenta como hecho
        assert "no es hecho" in sec["our_response_draft"].casefold() or (
            "borrador" in sec["our_response_draft"].casefold()
        )

    # Gaps heredados del veredicto 133 (F.2 volumen, F.3 certificados, plazo)
    gap_blob = " ".join(draft["gaps_summary"]).casefold()
    assert "f.2" in gap_blob or "volumen" in gap_blob or "1,5" in gap_blob
    assert "f.3" in gap_blob or "certific" in gap_blob or "tres" in gap_blob
    gap_codes = {g["code"] for g in draft["gaps"]}
    assert "f2_volume" in gap_codes or any(
        "volumen" in g["description"].casefold() for g in draft["gaps"]
    )
    assert "f3_certificates" in gap_codes or any(
        "f.3" in g["description"].casefold() or "certific" in g["description"].casefold()
        for g in draft["gaps"]
    )

    checklist = draft["administrative_checklist"]
    assert len(checklist) >= 4
    by_key = {c["key"]: c for c in checklist}
    assert "deuc" in by_key
    assert by_key["deuc"]["status"] == "pending"
    assert "solvencia_f2" in by_key
    assert by_key["solvencia_f2"]["status"] in {"pending", "blocked"}
    assert "solvencia_f3" in by_key
    assert "sobre_tecnico" in by_key or "sobre_economico" in by_key

    # Statement literal usable en demo
    assert "Borrador de oferta" in draft["statement"]
    assert "draft_requires_human_edit" in draft["statement"] or "BORRADOR" in draft["banner"]


def test_no_draft_without_fit_verdict() -> None:
    """Sin veredicto de encaje no se genera borrador (puerta humana del 133)."""

    dossier_id = uuid.uuid4()
    official_id = uuid.uuid4()
    declared = _nexus_declared_fields(dossier_id)
    draft = build_draft_offer(
        fit_assessment={
            "statement": "Encaje sin veredicto",
            "declared_evidence_ids": [declared["own_offer"]],
            "official_evidence_ids": [str(official_id)],
            "confidence": 40,
            "origin": "declared_by_client",
            "dimensions": [],
            "verdict": None,
        },
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=_baleares_official(official_id),
    )
    assert draft is None


def test_enrich_attaches_draft_and_schema_roundtrip() -> None:
    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.UUID("d96614d3-7f53-4f1a-b494-3567a2bd1b1d")
    fit, declared = _score_fit(dossier_id, official_id)

    context = {
        "dossier": {"profile": NEXUS_PROFILE},
        "declared_evidence": [
            {
                "id": declared["own_offer"],
                "extract": (
                    f"[Declarado por el cliente] Oferta propia: {NEXUS_PROFILE['own_offer']}"
                ),
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
        "title": "Oportunidad Baleares",
        "recommendation": "investigate",
        "fit_assessment": fit,
        "facts": [
            {
                "statement": "Importe publicado 5.450.796,93 EUR",
                "evidence_ids": [str(official_id)],
            }
        ],
        "warnings": [],
    }
    enriched = enrich_opportunity_draft_offer(
        output, context_payload=context, as_of=date(2026, 8, 4)
    )
    assert enriched["draft_offer"] is not None
    assert len(enriched["draft_offer"]["sections"]) >= 3
    assert any("borrador de oferta" in str(w).casefold() for w in enriched["warnings"])

    # Schema + frontera
    cleaned = validate_opportunity_origin_boundary(
        enriched,
        official_ids={official_id},
        declared_ids={uuid.UUID(v) for v in declared.values()},
    )
    assert cleaned["draft_offer"] is not None
    assert cleaned["draft_offer"]["human_gate"] == "draft_requires_human_edit"
    assert cleaned["fit_assessment"]["verdict"]["recommendation"] == "go_conditioned"
    # Facts oficiales intactos (sin prosa del borrador)
    assert cleaned["facts"][0]["statement"].startswith("Importe")
    assert not draft_offer_pollutes_official_facts(cleaned)

    payload = {
        "title": "Oportunidad Baleares",
        "recommendation": "investigate",
        "scores": {
            "strategic_fit": 55,
            "urgency": 70,
            "expected_value": 60,
            "actionability": 50,
            "relationship_leverage": 40,
            "timing": 45,
            "confidence": 50,
            "execution_effort": 55,
            "blocking_risk": 60,
            "overall": 52,
        },
        "fit_assessment": cleaned["fit_assessment"],
        "draft_offer": cleaned["draft_offer"],
        "facts": cleaned["facts"],
        "inferences": [],
        "recommendations": [],
        "confidence": 50,
        "open_questions": [],
        "warnings": cleaned.get("warnings") or [],
    }
    out = OpportunityAnalysisOutput.model_validate_json(json.dumps(payload))
    assert out.draft_offer is not None
    assert out.draft_offer.human_gate == "draft_requires_human_edit"
    assert len(out.draft_offer.sections) >= 3
    assert out.draft_offer.origin == "declared_draft"


def test_frontera_095_strips_draft_prose_from_facts() -> None:
    """El borrador no contamina facts oficiales."""

    dossier_id = uuid.uuid4()
    official_id = uuid.uuid4()
    fit, declared = _score_fit(dossier_id, official_id)
    draft = build_draft_offer(
        fit_assessment=fit,
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=_baleares_official(official_id),
        as_of=date(2026, 8, 4),
    )
    assert draft is not None
    seed = draft["sections"][0]["our_response_draft"]
    polluted = {
        "facts": [
            {"statement": seed, "evidence_ids": [str(official_id)]},
            {
                "statement": "Hecho oficial limpio del pliego",
                "evidence_ids": [str(official_id)],
            },
        ],
        "draft_offer": draft,
        "warnings": [],
    }
    assert draft_offer_pollutes_official_facts(polluted)
    cleaned = strip_draft_from_official_facts(polluted)
    assert len(cleaned["facts"]) == 1
    assert "limpio" in cleaned["facts"][0]["statement"]
    assert any("borrador" in str(w).casefold() for w in cleaned["warnings"])


def test_schema_tolerates_malformed_draft_offer() -> None:
    payload = {
        "title": "Oportunidad",
        "recommendation": "investigate",
        "scores": {
            "strategic_fit": 50,
            "urgency": 50,
            "expected_value": 50,
            "actionability": 50,
            "relationship_leverage": 50,
            "timing": 50,
            "confidence": 50,
            "execution_effort": 50,
            "blocking_risk": 50,
            "overall": 50,
        },
        "draft_offer": {
            "banner": "x",
            "statement": "",
            "sections": "nope",
            "invented": True,
        },
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 50,
        "open_questions": [],
        "warnings": [],
    }
    out = OpportunityAnalysisOutput.model_validate_json(json.dumps(payload))
    assert out.draft_offer is None


def test_boundary_drops_draft_without_verdict() -> None:
    dossier_id = uuid.uuid4()
    declared = _nexus_declared_fields(dossier_id)
    official_id = uuid.uuid4()
    output = {
        "fit_assessment": {
            "statement": "sin veredicto útil",
            "declared_evidence_ids": [declared["own_offer"]],
            "official_evidence_ids": [str(official_id)],
            "confidence": 30,
            "origin": "declared_by_client",
        },
        "draft_offer": {
            "banner": "BORRADOR COMERCIAL — no es documento presentable.",
            "human_gate": "draft_requires_human_edit",
            "statement": "Borrador huérfano",
            "sections": [
                {
                    "key": "award_economic",
                    "title": "Económica",
                    "requirement": "[oficial] x",
                    "requirement_origin": "official",
                    "official_evidence_ids": [str(official_id)],
                    "our_response_draft": "[borrador declarado — no es hecho] y",
                    "response_origin": "declared_generated",
                    "declared_evidence_ids": [declared["own_offer"]],
                    "gaps": [],
                }
            ],
            "administrative_checklist": [],
            "gaps_summary": [],
            "gaps": [],
            "origin": "declared_draft",
            "official_evidence_ids": [str(official_id)],
            "declared_evidence_ids": [declared["own_offer"]],
        },
        "facts": [],
        "warnings": [],
    }
    cleaned = validate_opportunity_origin_boundary(
        output,
        official_ids={official_id},
        declared_ids={uuid.UUID(v) for v in declared.values()},
    )
    # fit sin verdict → draft omitido
    assert cleaned["draft_offer"] is None
    assert any("draft_offer omitido" in str(w) for w in cleaned["warnings"])
