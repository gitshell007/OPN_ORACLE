"""SV2-PROSA · dedup gaps/declared + guardarraíl de pulido de prosa."""

from __future__ import annotations

import json
import uuid

from opn_oracle.ai.context import (
    declared_evidence_id,
    dedupe_risk_context_declared,
    enrich_risk_context_declared,
    normalize_risk_declared_core,
    validate_risk_origin_boundary,
)
from opn_oracle.ai.draft_offer import (
    build_draft_offer,
    normalize_gap_statement,
    unique_gap_strings,
)
from opn_oracle.ai.draft_prose import (
    extract_protected_tokens,
    polish_draft_offer_prose,
    polish_text_with_guardrail,
    validate_prose_polish,
)
from opn_oracle.ai.fit_scoring import score_profile_tender_fit
from opn_oracle.ai.schemas import OpportunityAnalysisOutput, RiskAnalysisOutput

# Reutiliza corpus real del 134/137.
BALEARES_EXTRACT = """
EXTRACTO DEL PCAP · CONTR 2026 11077 · Baleares · Red de agentes inteligentes
CRITERIOS DE ADJUDICACION
La adjudicacion se realiza segun la mejor relacion calidad-precio.
Criterios de adjudicacion evaluables mediante formulas (oferta economica) y criterios
evaluables mediante juicio de valor (oferta tecnica).
Si concurre un unico licitador, cuando la puntuacion del otro criterio sea superior a
los 65 puntos. Si concurren dos o mas licitadores, cuando la puntuacion del otro
criterio distinto de la oferta economica sea superior en 60 puntos porcentuales a la
media aritmetica de las puntuaciones obtenidas en dicho criterio por todas las empresas.
F.2. MEDIOS DE ACREDITACION DE LA SOLVENCIA ECONOMICA Y FINANCIERA
volumen anual de negocio al menos una vez y media el valor estimado.
F.3. MEDIOS DE ACREDITACION DE LA SOLVENCIA TECNICA
relacion de los servicios ejecutados en el curso de los ultimos tres anos.
LOTES
- Lote 1: Gobernanza de la IA
- Lote 2: Red de agentes inteligentes
"""

NEXUS_PROFILE = {
    "version": "custom.v1",
    "own_offer": (
        "Nexus Ibérica Sistemas: software, plataformas e inteligencia artificial para "
        "administraciones públicas y grandes cuentas."
    ),
    "cpv": ["72000000", "72200000"],
    "barriers": [
        "Homologación y solvencia técnica exigida en AAPP",
        "Escala comercial frente a integradores globales",
        "Plazos de licitación y documentación técnica",
    ],
    "competitors": [{"name": "Capgemini"}, {"name": "NTT DATA"}],
}


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


# ---------------------------------------------------------------------------
# Dedup gaps (draft_offer) — datos del patrón 137
# ---------------------------------------------------------------------------


def test_unique_gap_strings_dedupes_normalized() -> None:
    items = [
        "no evaluable con lo declarado: F.2 exige volumen >=1,5x y F.3 servicios de 3 años",
        "no evaluable con lo declarado: F.2 exige volumen >=1,5x y F.3 servicios de 3 años",
        "  no evaluable con lo declarado: F.2 exige volumen >=1,5x y F.3 servicios de 3 años  ",
        "Otro gap distinto",
    ]
    out = unique_gap_strings(items)
    assert len(out) == 2
    assert normalize_gap_statement(out[0]) == normalize_gap_statement(items[0])


def test_draft_offer_gaps_summary_and_section_gaps_are_unique() -> None:
    """Con los datos reales del 137 (misma razón F.2+F.3 en f2 y f3) no se repite."""

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    official_id = uuid.uuid4()
    declared = {
        "own_offer": str(declared_evidence_id(dossier_id, "own_offer")),
        "cpv": str(declared_evidence_id(dossier_id, "cpv")),
        "barriers": str(declared_evidence_id(dossier_id, "barriers")),
    }
    fit = score_profile_tender_fit(
        profile=NEXUS_PROFILE,
        official_evidence=[
            {
                "id": str(official_id),
                "extract": BALEARES_EXTRACT,
                "source_kind": "document",
                "locator": {"kind": "pliego_extract", "ref": "CONTR 2026 11077"},
            }
        ],
        declared_by_field=declared,
        as_of=None,
    )
    # Fuerza la condición de colisión del 137: misma description en dos codes.
    verdict = fit.get("verdict") or {}
    collision = (
        "no evaluable con lo declarado: F.2 exige volumen >=1,5x y F.3 "
        "servicios de 3 años; el perfil no aporta ninguno de esos datos."
    )
    verdict["conditions"] = [*(verdict.get("conditions") or []), collision]
    # Añade dimensión not_evaluable que repite el mismo texto (como en el 137).
    dims = list(fit.get("dimensions") or [])
    dims.append(
        {
            "key": "solvency",
            "status": "not_evaluable",
            "status_reason": (
                "no evaluable con lo declarado: F.2 exige volumen >=1,5x y F.3 "
                "servicios de 3 años; el perfil no aporta ninguno de esos datos."
            ),
            "requirement": "F.2/F.3",
            "capability": "no declarado",
            "requirement_origin": "official",
            "capability_origin": "declared",
            "official_evidence_ids": [str(official_id)],
            "declared_evidence_ids": [declared["own_offer"]],
        }
    )
    fit["dimensions"] = dims
    fit["verdict"] = verdict

    draft = build_draft_offer(
        fit_assessment=fit,
        profile=NEXUS_PROFILE,
        declared_by_field=declared,
        official_evidence=[
            {
                "id": str(official_id),
                "extract": BALEARES_EXTRACT,
                "source_kind": "document",
            }
        ],
    )
    assert draft is not None
    summary = draft["gaps_summary"]
    keys = [normalize_gap_statement(x) for x in summary]
    assert len(keys) == len(set(keys)), f"gaps_summary con duplicados: {summary}"

    for sec in draft["sections"]:
        sec_keys = [normalize_gap_statement(x) for x in (sec.get("gaps") or [])]
        assert len(sec_keys) == len(set(sec_keys)), f"sección {sec['key']} gaps dup: {sec['gaps']}"

    gap_descs = [normalize_gap_statement(g["description"]) for g in draft["gaps"]]
    assert len(gap_descs) == len(set(gap_descs))


# ---------------------------------------------------------------------------
# Dedup risk_context_declared — datos del 138 (7 → ≤4)
# ---------------------------------------------------------------------------


def test_dedupe_risk_context_declared_merges_138_style_duplicates() -> None:
    """Los 7 ítems del demo 138 (3 barreras x 2 + competitive) → ≤4 con categories."""

    eid = "b0ac9713-b554-5feb-b9b5-7ecacf48b607"
    items_138 = [
        {
            "statement": "Homologación y solvencia técnica exigida en AAPP",
            "category": "homologation",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": "Escala comercial frente a integradores globales",
            "category": "competitive",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": "Plazos de licitación y documentación técnica",
            "category": "deadline",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": (
                "Barrera declarada por el cliente: Homologación y solvencia técnica exigida en AAPP"
            ),
            "category": "solvency",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": (
                "Barrera declarada por el cliente: Escala comercial frente a integradores globales"
            ),
            "category": "barrier",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": (
                "Barrera declarada por el cliente: Plazos de licitación y documentación técnica"
            ),
            "category": "deadline",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
        {
            "statement": "Presión competitiva declarada: Capgemini, NTT DATA, Inetum",
            "category": "competitive",
            "declared_evidence_ids": [eid],
            "origin": "declared_by_client",
            "relevance": "",
        },
    ]
    # Antes: 7. Después: ≤4.
    assert len(items_138) == 7
    merged = dedupe_risk_context_declared(items_138)
    assert len(merged) <= 4
    assert len(merged) >= 3

    # Homologación + solvencia fusionadas.
    cores = {normalize_risk_declared_core(i["statement"]): i for i in merged}
    homo = cores.get(
        normalize_risk_declared_core("Homologación y solvencia técnica exigida en AAPP")
    )
    assert homo is not None
    cats = set(homo.get("categories") or [homo.get("category")])
    assert "homologation" in cats or "solvency" in cats
    # Preferimos categories multi cuando hubo merge.
    assert len(cats) >= 2 or homo.get("category") in {"solvency", "homologation"}

    # Evidence conservada.
    for item in merged:
        assert item["declared_evidence_ids"]
        assert item["origin"] == "declared_by_client"


def test_enrich_plus_llm_duplicates_collapse() -> None:
    """LLM aporta 3 + enrich añade las mismas con prefijo → fusionadas."""

    dossier_id = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
    barriers_id = str(declared_evidence_id(dossier_id, "barriers"))
    competitors_id = str(declared_evidence_id(dossier_id, "competitors"))
    context_payload = {
        "declared_evidence": [
            {
                "id": barriers_id,
                "extract": (
                    "[Declarado por el cliente] Barreras declaradas: "
                    "Homologación y solvencia técnica exigida en AAPP; "
                    "Escala comercial frente a integradores globales; "
                    "Plazos de licitación y documentación técnica"
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
    # Simula output LLM del 138 (3 barreras sin prefijo).
    output = {
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [],
        "risk_context_declared": [
            {
                "statement": "Homologación y solvencia técnica exigida en AAPP",
                "category": "homologation",
                "declared_evidence_ids": [barriers_id],
                "origin": "declared_by_client",
                "relevance": "",
            },
            {
                "statement": "Escala comercial frente a integradores globales",
                "category": "competitive",
                "declared_evidence_ids": [barriers_id],
                "origin": "declared_by_client",
                "relevance": "",
            },
            {
                "statement": "Plazos de licitación y documentación técnica",
                "category": "deadline",
                "declared_evidence_ids": [barriers_id],
                "origin": "declared_by_client",
                "relevance": "",
            },
        ],
        "warnings": [],
        "confidence": 50,
        "inferences": [],
        "recommendations": [],
        "open_questions": [],
    }
    enriched = enrich_risk_context_declared(output, context_payload=context_payload)
    items = enriched["risk_context_declared"]
    assert len(items) <= 4
    # Schema roundtrip.
    payload = {
        **enriched,
        "title": "Riesgo",
        "recommended_status": "watch",
        "scores": _scores(),
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 45,
        "open_questions": [],
        "warnings": [],
    }
    model = RiskAnalysisOutput.model_validate_json(json.dumps(payload))
    assert len(model.risk_context_declared) <= 4


def test_validate_risk_origin_boundary_still_dedupes() -> None:
    eid = uuid.UUID("b0ac9713-b554-5feb-b9b5-7ecacf48b607")
    output = {
        "facts": [],
        "inferences": [],
        "scenarios": [],
        "warnings": [],
        "risk_context_declared": [
            {
                "statement": "Homologación y solvencia técnica exigida en AAPP",
                "category": "homologation",
                "declared_evidence_ids": [str(eid)],
                "origin": "declared_by_client",
            },
            {
                "statement": (
                    "Barrera declarada por el cliente: "
                    "Homologación y solvencia técnica exigida en AAPP"
                ),
                "category": "solvency",
                "declared_evidence_ids": [str(eid)],
                "origin": "declared_by_client",
            },
        ],
    }
    cleaned = validate_risk_origin_boundary(output, official_ids=set(), declared_ids={eid})
    assert len(cleaned["risk_context_declared"]) == 1
    cats = cleaned["risk_context_declared"][0].get("categories") or []
    assert "homologation" in cats and "solvency" in cats


# ---------------------------------------------------------------------------
# Guardarraíl anti-invención
# ---------------------------------------------------------------------------


def test_guardrail_rejects_invented_number() -> None:
    seed = (
        "[borrador declarado — no es hecho] Semilla de oferta económica para Lote 2. "
        "Sin cifras inventadas. Edición humana obligatoria antes de presentar."
    )
    polished = (
        "[borrador declarado — no es hecho] Oferta económica orientada a Lote 2 por "
        "1.500.000 €. Edición humana obligatoria."
    )
    ok, reason = validate_prose_polish(seed, polished)
    assert ok is False
    assert reason.startswith("invented_tokens")
    final, polished_flag, r = polish_text_with_guardrail(seed, polished)
    assert polished_flag is False
    assert final == seed
    assert "invented" in r


def test_guardrail_rejects_missing_label() -> None:
    seed = (
        "[borrador declarado — no es hecho] Semilla de memoria técnica orientada a Lote 2. "
        "Edición humana obligatoria antes de presentar."
    )
    polished = "Memoria técnica natural orientada a Lote 2. Edición humana obligatoria."
    ok, reason = validate_prose_polish(seed, polished)
    assert ok is False
    assert reason == "missing_draft_label"


def test_guardrail_accepts_safe_rewrite() -> None:
    seed = (
        "[borrador declarado — no es hecho] Semilla de oferta económica para Lote 2. "
        "Partir del valor estimado del pliego. Gap heredado: sin volumen F.2. "
        "Edición humana obligatoria antes de presentar."
    )
    polished = (
        "[borrador declarado — no es hecho] Propuesta económica orientada a Lote 2: "
        "partimos del valor estimado del pliego. Recordatorio: falta acreditar volumen "
        "F.2. Edición humana obligatoria antes de presentar."
    )
    ok, reason = validate_prose_polish(seed, polished)
    assert ok is True
    assert reason == "ok"
    # F.2 y Lote 2 no son inventados.
    assert "f.2" in extract_protected_tokens(polished)


def test_polish_draft_offer_prose_with_injectable_fn() -> None:
    seed = (
        "[borrador declarado — no es hecho] Semilla genérica de respuesta. "
        "Edición humana obligatoria antes de presentar."
    )
    draft = {
        "statement": "Borrador de oferta (esqueleto) para CONTR 2026 11077 · Lote 2.",
        "sections": [
            {
                "key": "award_economic",
                "title": "Oferta económica",
                "requirement": "[oficial] fórmulas",
                "our_response_draft": seed,
                "our_response_seed": seed,
                "gaps": [],
            },
            {
                "key": "award_technical",
                "title": "Oferta técnica",
                "requirement": "[oficial] juicio",
                "our_response_draft": seed,
                "our_response_seed": seed,
                "gaps": [],
            },
            {
                "key": "award_thresholds",
                "title": "Umbrales",
                "requirement": "[oficial] 65/60",
                "our_response_draft": seed,
                "our_response_seed": seed,
                "gaps": [],
            },
        ],
    }

    def good_polish(key: str, text: str) -> str:
        if key == "statement":
            return "Borrador de oferta natural para CONTR 2026 11077 · Lote 2."
        return (
            "[borrador declarado — no es hecho] Párrafo natural de director comercial. "
            "Edición humana obligatoria antes de presentar."
        )

    out = polish_draft_offer_prose(draft, polish_fn=good_polish)
    polished_secs = [s for s in out["sections"] if s.get("prose_polished")]
    assert len(polished_secs) >= 3
    assert out["prose_engine"] == "sv2_prosa_v1"
    assert out["prose_polished_count"] >= 3
    for s in polished_secs:
        assert "borrador declarado" in s["our_response_draft"].casefold()
        assert s["our_response_seed"] == seed


def test_polish_fallback_on_invention_per_section() -> None:
    seed = (
        "[borrador declarado — no es hecho] Semilla sin importes. "
        "Edición humana obligatoria antes de presentar."
    )
    draft = {
        "statement": "Borrador demo",
        "sections": [
            {
                "key": "award_economic",
                "our_response_draft": seed,
                "our_response_seed": seed,
            }
        ],
    }

    def invent(_key: str, _text: str) -> str:
        return (
            "[borrador declarado — no es hecho] Oferta a 999.999 €. "
            "Edición humana obligatoria antes de presentar."
        )

    out = polish_draft_offer_prose(draft, polish_fn=invent)
    sec = out["sections"][0]
    assert sec["prose_polished"] is False
    assert sec["our_response_draft"] == seed
    assert str(sec.get("prose_polish_reason") or "").startswith("invented_tokens")


def test_opportunity_schema_accepts_prose_fields() -> None:
    seed = (
        "[borrador declarado — no es hecho] texto. Edición humana obligatoria antes de presentar."
    )
    payload = {
        "title": "Opp",
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
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 50,
        "open_questions": [],
        "warnings": [],
        "draft_offer": {
            "banner": "BORRADOR COMERCIAL — no es documento presentable.",
            "human_gate": "draft_requires_human_edit",
            "statement": "Borrador demo",
            "sections": [
                {
                    "key": "award_economic",
                    "title": "Económica",
                    "requirement": "[oficial] x",
                    "our_response_draft": seed,
                    "our_response_seed": seed,
                    "prose_polished": True,
                    "prose_polish_reason": "ok",
                    "gaps": ["gap a", "gap a"],  # dedup en coerce
                }
            ],
            "gaps_summary": ["gap a", "gap a"],
            "prose_engine": "sv2_prosa_v1",
            "prose_polished_count": 1,
        },
    }
    model = OpportunityAnalysisOutput.model_validate_json(json.dumps(payload))
    assert model.draft_offer is not None
    assert model.draft_offer.sections[0].prose_polished is True
    assert model.draft_offer.sections[0].gaps == ["gap a"]
    assert model.draft_offer.gaps_summary == ["gap a"]
