"""G06-CITA-RESPALDO · solape afirmación↔cita + source_urls «no verificada».

Casos canónicos del prompt 000142:
(a) afirmación con cita que sí respalda → pasa intacta
(b) afirmación con cita que no respalda → retirada con aviso legible
(c) source_urls inventada → etiquetada «no verificada»
"""

from __future__ import annotations

from opn_oracle.ai.schemas import MarketCompetitorCandidate, MarketCompetitorDiscoveryOutput
from opn_oracle.ai.source_url_policy import (
    SOURCE_URL_UNVERIFIED_LABEL,
    SOURCE_URL_UNVERIFIED_STATUS,
    annotate_source_urls,
    is_valid_http_source_url,
    sanitize_source_urls,
)
from opn_oracle.integrations.citation_support import (
    CITATION_DOES_NOT_SUPPORT,
    claim_supported_by_evidence,
    enforce_citation_support,
    extract_support_anchors,
    is_person_role_claim,
)

# --- anclajes / solape -------------------------------------------------------


def test_extract_anchors_person_and_amount() -> None:
    anchors = extract_support_anchors(
        "El administrador es Laura Méndez y el importe es 1.234.567 EUR en 2024."
    )
    assert any("Laura" in n for n in anchors.proper_names)
    assert "1234567" in anchors.numbers
    assert "2024" in anchors.dates or "2024" in anchors.numbers


def test_person_role_claim_detects_administrator() -> None:
    assert is_person_role_claim("El administrador único es Laura Méndez")
    assert not is_person_role_claim("La licitación CPV 72000000 se publicó en 2024")


def test_claim_supported_when_name_in_evidence() -> None:
    ok, missing = claim_supported_by_evidence(
        "El administrador único es Juan Francisco Iturri Franco",
        ["Administrador único: Juan Francisco Iturri Franco. CIF B123."],
    )
    assert ok
    assert missing == []


def test_claim_not_supported_when_name_absent_from_evidence() -> None:
    # Caso reproducible del P0: admin inventado + cita a evidencia de licitación.
    tender = (
        "Expediente 2024/LIC/001. Objeto: suministro de material. "
        "Importe: 500.000 EUR. CPV 33100000. Sin mención a administradores."
    )
    ok, missing = claim_supported_by_evidence(
        "El administrador de la empresa es Laura Méndez",
        [tender],
    )
    assert not ok
    folded = " ".join(m.casefold() for m in missing)
    assert "laura" in folded or "mendez" in folded or "méndez" in folded


def test_case_a_supported_claim_kept_intact() -> None:
    """(a) afirmación con cita que sí respalda → pasa intacta."""
    eid = "b622f20e-aaaa-bbbb-cccc-111111111111"
    evidence = {eid: "Administrador único: Juan Francisco Iturri Franco. Domicilio social Bilbao."}
    result = enforce_citation_support(
        facts=[
            {
                "statement": "El administrador único es Juan Francisco Iturri Franco",
                "evidence_ids": [eid],
            }
        ],
        claims=[],
        evidence_text_by_id=evidence,
    )
    assert result.kept_count == 1
    assert result.withdrawn_count == 0
    assert result.degraded_count == 0
    assert len(result.facts) == 1
    assert result.facts[0]["statement"].startswith("El administrador único es Juan")
    assert result.facts[0]["evidence_ids"] == [eid]
    assert result.warnings == []


def test_case_b_unsupported_admin_claim_withdrawn_with_visible_warning() -> None:
    """(b) afirmación con cita que no respalda → retirada con aviso legible.

    Falla-antes conceptual: sin este gate, validate_citations_allowlist aceptaba
    el evidence_id de licitación y publicaba «Laura Méndez» con apariencia de verdad.
    """
    # b622f20e simula evidencia de licitación (allowlist OK, contenido no respalda).
    eid = "b622f20e-0000-0000-0000-000000000001"
    tender_only = (
        "Licitación PLACSP 2024. Objeto: impermeabilización de cubiertas. "
        "Importe 1.200.000 EUR. Órgano de contratación: Ayuntamiento."
    )
    result = enforce_citation_support(
        facts=[
            {
                "statement": "El administrador de ITURRI es Laura Méndez",
                "evidence_ids": [eid],
            }
        ],
        claims=[
            {
                "statement": "Laura Méndez figura como administradora única",
                "evidence_ids": [eid],
                "confidence": 80,
            }
        ],
        evidence_text_by_id={eid: tender_only},
    )
    assert result.facts == []
    assert result.claims == []
    assert result.withdrawn_count >= 1  # person_role
    assert result.warnings
    assert all(CITATION_DOES_NOT_SUPPORT in w for w in result.warnings)
    assert any("Laura" in issue.statement for issue in result.issues)
    # Aviso legible: el lector ve por qué (no descarte silencioso).
    assert any("retirada" in w for w in result.warnings)


def test_generic_unsupported_claim_also_withdrawn_with_reason() -> None:
    eid = "ev-generic-1"
    result = enforce_citation_support(
        facts=[],
        claims=[
            {
                "statement": "El CPV principal es 99999999-Z y el importe es 9.999.999 EUR",
                "evidence_ids": [eid],
                "confidence": 70,
            }
        ],
        evidence_text_by_id={eid: "Solo se describe el objeto del contrato sin CPV ni importe."},
    )
    assert result.claims == []
    assert result.degraded_count == 1
    assert any(CITATION_DOES_NOT_SUPPORT in w for w in result.warnings)


# --- source_urls -------------------------------------------------------------


def test_source_url_form_validation() -> None:
    assert is_valid_http_source_url("https://www.fluenceenergy.com/about")
    assert is_valid_http_source_url("http://sub.domain.co.uk/path?q=1")
    assert not is_valid_http_source_url("not-a-url")
    assert not is_valid_http_source_url("javascript:alert(1)")
    assert not is_valid_http_source_url("ftp://files.example.com/x")
    assert not is_valid_http_source_url("https://localhost/secret")
    assert not is_valid_http_source_url("https://127.0.0.1/x")
    assert not is_valid_http_source_url("https://example.com/docs")  # host reservado


def test_case_c_invented_url_labelled_unverified() -> None:
    """(c) source_urls con URL inventada → etiquetada «no verificada»."""
    invented = "https://www.empresa-inventada-xyz.es/perfil"
    cleaned = sanitize_source_urls(
        [invented, "not-a-url", "javascript:void(0)", "https://localhost/x"]
    )
    assert cleaned == [invented]
    meta = annotate_source_urls(cleaned)
    assert len(meta) == 1
    assert meta[0]["url"] == invented
    assert meta[0]["label"] == SOURCE_URL_UNVERIFIED_LABEL
    assert meta[0]["status"] == SOURCE_URL_UNVERIFIED_STATUS
    assert meta[0]["verified"] is False


def test_market_competitor_schema_sanitizes_and_labels_source_urls() -> None:
    output = MarketCompetitorDiscoveryOutput.model_validate(
        {
            "candidates": [
                {
                    "name": "Acme Inventada SL",
                    "country": "ES",
                    "rationale": "Candidato sintético de prueba.",
                    "source_urls": [
                        "https://www.empresa-inventada-xyz.es/perfil",
                        "ftp://bad",
                        "not-a-url",
                    ],
                    "confidence": 55,
                }
            ],
            "warnings": [],
        }
    )
    cand = output.candidates[0]
    assert cand.source_urls == ["https://www.empresa-inventada-xyz.es/perfil"]
    assert cand.source_urls_label == SOURCE_URL_UNVERIFIED_LABEL
    assert cand.source_urls_status == SOURCE_URL_UNVERIFIED_STATUS
    assert cand.source_urls_meta
    assert cand.source_urls_meta[0].label == "no verificada"
    assert cand.source_urls_meta[0].verified is False
    assert any(SOURCE_URL_UNVERIFIED_LABEL in w for w in output.warnings)


def test_market_competitor_candidate_rejects_garbage_urls_only() -> None:
    cand = MarketCompetitorCandidate.model_validate(
        {
            "name": "Sin fuentes",
            "country": "DE",
            "rationale": "Sin URL válida en la propuesta del modelo.",
            "source_urls": ["nota-sin-url", "http://", "https://"],
            "confidence": 20,
        }
    )
    assert cand.source_urls == []
    assert cand.source_urls_meta == []
    assert cand.source_urls_label is None
