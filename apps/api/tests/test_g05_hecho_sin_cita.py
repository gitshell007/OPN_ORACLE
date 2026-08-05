"""SV2-G05-HECHO-SIN-CITA · normalizador no puede silenciar hechos sin cita.

Antes del fix, ``_normalize_signal_candidate_json``:
1. borraba facts top-level sin ``evidence_ids`` (solo conservaba statement+ids);
2. convertía párrafos ``kind=fact`` sin citas en ``inference`` conf≤70;
ambos **sin warning**. El saneo central ya no veía la señal y el cliente recibía
una inferencia o nada sin saber que el modelo afirmó un hecho sin respaldo.

Contrato:
- top-level sin cita → fuera de ``facts`` + warning con preview; citado permanece;
- todos sin cita → ``UncitedFactsError`` fail-closed;
- párrafo fact sin cita → degradado a inference **con** warning específico;
- fact citado en sección permanece fact; inference original no se acusa;
- allowlist: UUID ajeno no sobrevive ni se sustituye;
- misma política en los tres agentes report family vía ``generate_structured``.
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from opn_oracle.ai.provider import (
    LLMRequest,
    SignalGovernedLLMProvider,
    UncitedFactsError,
    _normalize_signal_candidate_json,
    _sanitize_uncited_facts_json,
)
from opn_oracle.ai.schemas import ReportOutput

REPORT_AGENTS = (
    "report_writer",
    "competitive_procurement_intelligence",
    "entity_dossier_intelligence",
)

ALLOWED = "00000000-0000-4000-8000-000000000001"
FOREIGN = "00000000-0000-4000-8000-000000000099"


def _request(agent: str, *, allowed: list[str] | None = None) -> LLMRequest:
    return LLMRequest(
        agent=agent,
        model="stub-model",
        system_prompt="Devuelve JSON estricto.",
        task_prompt="Redacta un informe.",
        context={"allowed_evidence_ids": allowed if allowed is not None else [ALLOWED]},
        max_output_tokens=500,
        classification="internal",
    )


def _base_report(
    *,
    facts: list[dict],
    sections: list[dict] | None = None,
    inferences: list | None = None,
    confidence: int = 80,
) -> dict:
    return {
        "facts": facts,
        "inferences": inferences if inferences is not None else [],
        "recommendations": [
            {
                "action": "Revisar expediente",
                "rationale": "Control de calidad del informe.",
                "priority": "medium",
            }
        ],
        "confidence": confidence,
        "open_questions": [],
        "warnings": [],
        "title": "Informe G-05",
        "executive_summary": "Resumen de prueba sin red ni LLM real.",
        "sections": sections
        if sections is not None
        else [
            {
                "heading": "Contexto",
                "paragraphs": [
                    {
                        "text": "Párrafo base con cita válida del expediente.",
                        "kind": "fact",
                        "confidence": 80,
                        "evidence_ids": [ALLOWED],
                    }
                ],
            }
        ],
        "top_opportunities": [],
        "top_risks": [],
        "recommended_actions": [],
        "decisions_required": [],
        "source_index": [],
    }


def _run_stub_provider(agent: str, payload: dict) -> ReportOutput:
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="test-key", timeout_seconds=3
    )
    envelope = {
        "provider": "stub",
        "model": "stub-model",
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost_micros": 0},
        "result": {"message": {"content": json.dumps(payload, ensure_ascii=False)}},
    }
    provider._run = lambda body, p=envelope: p  # type: ignore[method-assign]
    result = provider.generate_structured(_request(agent), ReportOutput)
    return result.output


# ---------------------------------------------------------------------------
# Test que FALLA en el SHA base (normalizer oculta el hecho) y PASA tras el fix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_normalize_preserves_uncited_signal_for_honesty_gate(agent: str) -> None:
    """Regresión G-05: el normalizador no puede hacer invisible el hecho sin cita.

    En la base, ``fact_items`` exigía statement+ids → el uncited desaparecía y
    sanitize no emitía warning. Tras el fix, el uncited llega al saneo y se retira
    con warning de producto que nombra el preview.
    """

    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            },
            {
                "statement": "Afirmación inventada sin respaldo del modelo.",
                "evidence_ids": [],
            },
        ]
    )
    raw = json.dumps(payload, ensure_ascii=False)
    normalized = _normalize_signal_candidate_json(_request(agent), raw, [ALLOWED])
    norm_data = json.loads(normalized)
    # Señal intacta antes del gate de honestidad.
    statements = [item["statement"] for item in norm_data["facts"]]
    assert "Afirmación inventada sin respaldo del modelo." in statements
    assert any(not item.get("evidence_ids") for item in norm_data["facts"])

    cleaned = _sanitize_uncited_facts_json(normalized, agent=agent)
    data = json.loads(cleaned)
    assert len(data["facts"]) == 1
    assert data["facts"][0]["statement"] == "Hecho citado permitido en adjudicación PLACSP."
    assert any("sin respaldo documental" in w for w in data["warnings"])
    assert any("Afirmación inventada sin respaldo del modelo" in w for w in data["warnings"])


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_normalize_preserves_uncited_section_fact_kind_for_honesty_gate(agent: str) -> None:
    """Regresión G-05: paragraph fact sin cita no se degrada en silencio en normalize."""

    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            }
        ],
        sections=[
            {
                "heading": "Análisis",
                "paragraphs": [
                    {
                        "text": "Párrafo fact sin citas que el modelo afirmó como hecho.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [],
                    },
                    {
                        "text": "Párrafo fact con cita válida del expediente.",
                        "kind": "fact",
                        "confidence": 85,
                        "evidence_ids": [ALLOWED],
                    },
                ],
            }
        ],
    )
    normalized = _normalize_signal_candidate_json(
        _request(agent), json.dumps(payload, ensure_ascii=False), [ALLOWED]
    )
    norm_data = json.loads(normalized)
    first = norm_data["sections"][0]["paragraphs"][0]
    # Aún kind=fact tras normalize (el gate de honestidad decide la política).
    assert first["kind"] == "fact"
    assert first["evidence_ids"] == []

    cleaned = _sanitize_uncited_facts_json(normalized, agent=agent)
    data = json.loads(cleaned)
    first_clean = data["sections"][0]["paragraphs"][0]
    assert first_clean["kind"] == "inference"
    assert first_clean["confidence"] <= 70
    second = data["sections"][0]["paragraphs"][1]
    assert second["kind"] == "fact"
    assert second["evidence_ids"] == [ALLOWED]
    assert any(
        "Se degradó a inferencia una afirmación presentada como hecho sin citas" in w
        for w in data["warnings"]
    )
    assert any(
        "Párrafo fact sin citas que el modelo afirmó como hecho" in w for w in data["warnings"]
    )


# ---------------------------------------------------------------------------
# Matriz parametrizada por los tres agentes (camino real generate_structured)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_mixed_facts_cited_remains_uncited_withdrawn_with_preview(agent: str) -> None:
    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            },
            {
                "statement": "Afirmación inventada sin respaldo del modelo.",
                "evidence_ids": [],
            },
        ]
    )
    out = _run_stub_provider(agent, payload)
    assert len(out.facts) == 1
    assert out.facts[0].statement == "Hecho citado permitido en adjudicación PLACSP."
    assert out.facts[0].evidence_ids == [UUID(ALLOWED)]
    assert any("sin respaldo documental" in w for w in out.warnings)
    assert any("Afirmación inventada sin respaldo del modelo" in w for w in out.warnings)
    # No acusar con el genérico de párrafos como si resolviera el fact top-level.
    assert not any(
        "no contiene párrafos citados" in w
        and "Afirmación inventada" not in w
        and len(out.warnings) == 1
        for w in out.warnings
    )


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_all_uncited_facts_fail_closed(agent: str) -> None:
    payload = _base_report(
        facts=[
            {"statement": "Sin cita A del modelo.", "evidence_ids": []},
            {"statement": "Sin cita B del modelo.", "evidence_ids": []},
        ]
    )
    with pytest.raises(UncitedFactsError, match="el modelo no citó nada"):
        _run_stub_provider(agent, payload)


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_section_fact_uncited_degrades_with_specific_warning(agent: str) -> None:
    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            }
        ],
        sections=[
            {
                "heading": "Análisis",
                "paragraphs": [
                    {
                        "text": "Párrafo fact sin citas que el modelo afirmó como hecho.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [],
                    },
                    {
                        "text": "Párrafo fact con cita válida del expediente.",
                        "kind": "fact",
                        "confidence": 85,
                        "evidence_ids": [ALLOWED],
                    },
                ],
            }
        ],
    )
    out = _run_stub_provider(agent, payload)
    paras = out.sections[0].paragraphs
    assert paras[0].kind == "inference"
    assert paras[0].confidence <= 70
    assert paras[0].evidence_ids == []
    assert paras[1].kind == "fact"
    assert paras[1].evidence_ids == [UUID(ALLOWED)]
    assert any(
        "Se degradó a inferencia una afirmación presentada como hecho sin citas" in w
        for w in out.warnings
    )
    assert any("Párrafo fact sin citas que el modelo afirmó como hecho" in w for w in out.warnings)


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_section_cited_fact_stays_fact_without_false_warning(agent: str) -> None:
    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            }
        ],
        sections=[
            {
                "heading": "Fundado",
                "paragraphs": [
                    {
                        "text": "Solo hechos citados del expediente autorizado.",
                        "kind": "fact",
                        "confidence": 88,
                        "evidence_ids": [ALLOWED],
                    }
                ],
            }
        ],
    )
    out = _run_stub_provider(agent, payload)
    assert out.sections[0].paragraphs[0].kind == "fact"
    assert out.sections[0].paragraphs[0].evidence_ids == [UUID(ALLOWED)]
    assert not any("Se degradó a inferencia" in w for w in out.warnings)
    assert not any("sin respaldo documental" in w for w in out.warnings)


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_original_inference_without_citation_is_not_accused(agent: str) -> None:
    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            }
        ],
        inferences=[
            {
                "statement": "Inferencia legítima sin citas del analista.",
                "reasoning_summary": "Lectura prudente del contexto autorizado.",
                "confidence": 55,
                "evidence_ids": [],
            }
        ],
        sections=[
            {
                "heading": "Lectura",
                "paragraphs": [
                    {
                        "text": "Inferencia original en sección sin citas.",
                        "kind": "inference",
                        "confidence": 60,
                        "evidence_ids": [],
                    },
                    {
                        "text": "Hecho citado que ancla la sección.",
                        "kind": "fact",
                        "confidence": 80,
                        "evidence_ids": [ALLOWED],
                    },
                ],
            }
        ],
    )
    out = _run_stub_provider(agent, payload)
    assert len(out.inferences) == 1
    assert out.inferences[0].statement == "Inferencia legítima sin citas del analista."
    assert out.sections[0].paragraphs[0].kind == "inference"
    assert out.sections[0].paragraphs[0].confidence == 60
    # No se acusa la inferencia original de ser un hecho retirado/degradado.
    assert not any("Inferencia legítima sin citas del analista" in w for w in out.warnings)
    assert not any("Inferencia original en sección sin citas" in w for w in out.warnings)
    assert not any("Se degradó a inferencia" in w for w in out.warnings)
    assert not any("sin respaldo documental" in w for w in out.warnings)


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_allowlist_adversarial_foreign_uuid_does_not_survive(agent: str) -> None:
    payload = _base_report(
        facts=[
            {
                "statement": "Hecho citado permitido en adjudicación PLACSP.",
                "evidence_ids": [ALLOWED],
            },
            {
                "statement": "Hecho solo con UUID ajeno no autorizado.",
                "evidence_ids": [FOREIGN],
            },
        ],
        sections=[
            {
                "heading": "Intruso",
                "paragraphs": [
                    {
                        "text": "Párrafo fact con UUID ajeno.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [FOREIGN],
                    },
                    {
                        "text": "Párrafo fact con cita permitida.",
                        "kind": "fact",
                        "confidence": 80,
                        "evidence_ids": [ALLOWED],
                    },
                ],
            }
        ],
    )
    out = _run_stub_provider(agent, payload)
    foreign_uuid = UUID(FOREIGN)
    assert all(foreign_uuid not in f.evidence_ids for f in out.facts)
    assert all(foreign_uuid not in p.evidence_ids for s in out.sections for p in s.paragraphs)
    # El fact con solo UUID ajeno se trata como sin cita → retirado con warning.
    assert len(out.facts) == 1
    assert out.facts[0].evidence_ids == [UUID(ALLOWED)]
    assert any("Hecho solo con UUID ajeno no autorizado" in w for w in out.warnings)
    # El párrafo con UUID ajeno se degrada (allowlist lo vació) con warning.
    assert out.sections[0].paragraphs[0].kind == "inference"
    assert out.sections[0].paragraphs[0].evidence_ids == []
    assert any("Párrafo fact con UUID ajeno" in w for w in out.warnings)
    # No se sustituye el UUID ajeno por el permitido.
    assert out.sections[0].paragraphs[0].text == "Párrafo fact con UUID ajeno."


@pytest.mark.parametrize("agent", REPORT_AGENTS)
def test_well_cited_report_semantically_stable(agent: str) -> None:
    """Salida bien citada: sin degradación ni warnings de honestidad falsos."""

    payload = _base_report(
        facts=[
            {
                "statement": "Primer hecho citado del expediente.",
                "evidence_ids": [ALLOWED],
            },
            {
                "statement": "Segundo hecho citado del expediente.",
                "evidence_ids": [ALLOWED],
            },
        ],
        sections=[
            {
                "heading": "Cuerpo",
                "paragraphs": [
                    {
                        "text": "Párrafo fact citado íntegramente.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [ALLOWED],
                    }
                ],
            }
        ],
        confidence=82,
    )
    out = _run_stub_provider(agent, payload)
    assert len(out.facts) == 2
    assert out.confidence == 82
    assert out.sections[0].paragraphs[0].kind == "fact"
    assert out.sections[0].paragraphs[0].confidence == 90
    assert not any("sin respaldo documental" in w for w in out.warnings)
    assert not any("Se degradó a inferencia" in w for w in out.warnings)
    assert not any("needs_review" in w for w in out.warnings)


def test_shape_drift_report_writer_still_normalizes_and_warns() -> None:
    """Compat con test_signal_ai_provider: drift de forma + G-05 warnings visibles."""

    evidence_id = UUID(ALLOWED)
    invented_id = UUID(FOREIGN)
    payload = {
        "facts": [
            {"statement": "Hecho con cita válida", "evidence_ids": [str(evidence_id)]},
            {"statement": "Hecho sin cita", "evidence_ids": []},
        ],
        "inferences": ["La ventana requiere revisión comercial."],
        "recommendations": [{"action": "Preparar agenda", "priority": "urgent"}],
        "confidence": "82",
        "open_questions": "¿Qué actor decide el siguiente hito?",
        "warnings": [],
        "title": "Informe CATL",
        "executive_summary": "Resumen ejecutivo",
        "sections": [
            {
                "heading": "Objetivo",
                "paragraphs": [
                    {
                        "text": "El proyecto avanza, pero esta frase venía sin cita.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [],
                    },
                    {
                        "text": "Esta cita inventada no puede pasar.",
                        "kind": "fact",
                        "confidence": 90,
                        "evidence_ids": [str(invented_id)],
                    },
                ],
            }
        ],
        "recommended_actions": [{"action": "No debe quedar como dict"}],
        "source_index": [{"evidence_id": str(invented_id), "label": "Inventada", "locator": "x"}],
    }
    out = _run_stub_provider("report_writer", payload)
    assert len(out.facts) == 1
    assert out.facts[0].statement == "Hecho con cita válida"
    assert out.facts[0].evidence_ids == [evidence_id]
    assert out.recommendations[0].priority == "medium"
    assert out.sections[0].paragraphs[0].kind == "inference"
    assert out.sections[0].paragraphs[0].evidence_ids == []
    assert out.sections[0].paragraphs[0].confidence <= 70
    assert out.sections[0].paragraphs[1].kind == "inference"
    assert out.sections[0].paragraphs[1].evidence_ids == []
    assert out.source_index == []
    assert any("Hecho sin cita" in w for w in out.warnings)
    assert any("El proyecto avanza, pero esta frase venía sin cita" in w for w in out.warnings)
    assert any("Esta cita inventada no puede pasar" in w for w in out.warnings)
    # Warnings de producto: sin nombres de funciones/códigos internos.
    joined = " | ".join(out.warnings)
    assert "_sanitize" not in joined
    assert "_normalize" not in joined
    assert "evidence_ids" not in joined
