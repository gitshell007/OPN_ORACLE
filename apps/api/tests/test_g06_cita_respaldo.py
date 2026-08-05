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
    apply_source_url_policy_to_candidates,
    apply_source_url_policy_to_output,
    is_valid_http_source_url,
    sanitize_source_urls,
)
from opn_oracle.integrations.citation_support import (
    CITATION_DOES_NOT_SUPPORT,
    build_evidence_text_index,
    claim_supported_by_evidence,
    enforce_citation_support,
    evaluate_material_support,
    extract_support_anchors,
    format_support_rejection_summary,
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


def test_source_url_rejects_credentials_and_malformed() -> None:
    assert not is_valid_http_source_url("https://user:pass@evil.example/x")
    assert not is_valid_http_source_url("https://")
    assert not is_valid_http_source_url("http://.bad")
    assert not is_valid_http_source_url("https://exa mple.com/x")
    # urlparse ValueError path (control char in netloc-like forms is rare; empty after strip)
    assert not is_valid_http_source_url("   ")
    assert not is_valid_http_source_url("x" * 1600)


def test_sanitize_source_urls_dedupes_and_caps() -> None:
    urls = [
        "https://www.alpha-one.es/a",
        "https://www.alpha-one.es/a",
        "ftp://ignored",
        "https://www.beta-two.es/b",
        "https://www.gamma-three.es/c",
        "https://www.delta-four.es/d",
        "https://www.epsilon-five.es/e",
        "https://www.zeta-six.es/f",
    ]
    cleaned = sanitize_source_urls(urls, max_items=5)
    assert cleaned == [
        "https://www.alpha-one.es/a",
        "https://www.beta-two.es/b",
        "https://www.gamma-three.es/c",
        "https://www.delta-four.es/d",
        "https://www.epsilon-five.es/e",
    ]


def test_apply_source_url_policy_to_candidates_and_output() -> None:
    candidates = apply_source_url_policy_to_candidates(
        [
            {
                "name": "Acme",
                "source_urls": [
                    "https://www.acme-inventada.es/x",
                    "not-url",
                    "https://example.com/docs",
                ],
            },
            "skip-me",
            {"name": "Empty", "source_urls": []},
        ]
    )
    assert candidates[0]["source_urls"] == ["https://www.acme-inventada.es/x"]
    assert candidates[0]["source_urls_label"] == SOURCE_URL_UNVERIFIED_LABEL
    assert candidates[0]["source_urls_status"] == SOURCE_URL_UNVERIFIED_STATUS
    assert candidates[0]["source_urls_meta"][0]["verified"] is False
    assert candidates[1]["source_urls"] == []
    assert candidates[1]["source_urls_label"] is None

    with_urls = apply_source_url_policy_to_output(
        {
            "candidates": [
                {
                    "name": "X",
                    "source_urls": ["https://www.empresa-inventada-xyz.es/perfil"],
                }
            ],
            "warnings": [],
        }
    )
    assert with_urls["candidates"][0]["source_urls_label"] == SOURCE_URL_UNVERIFIED_LABEL
    assert any(SOURCE_URL_UNVERIFIED_LABEL in w for w in with_urls["warnings"])

    no_urls = apply_source_url_policy_to_output({"candidates": [{"name": "Y"}], "warnings": []})
    assert no_urls["warnings"] == []

    non_list = apply_source_url_policy_to_output({"candidates": "bad", "warnings": "also-bad"})
    assert non_list["candidates"] == "bad"
    assert non_list["warnings"] == []


def test_extract_anchors_dates_and_role_only_names() -> None:
    anchors = extract_support_anchors(
        "El contrato se firmó el 15/03/2024 y el CPV es 33100000 con 12,5 millones."
    )
    assert any("2024" in d or "/" in d for d in anchors.dates + anchors.numbers)
    assert any(n.startswith("12") or "125" in n or "33100000" in n for n in anchors.numbers)

    # Solo rol genérico capitalizado → no es nombre propio crítico
    role_only = extract_support_anchors("El Administrador Unico figura en el registro.")
    assert role_only.proper_names == ()


def test_claim_supported_content_ratio_and_empty_corpus() -> None:
    ok, missing = claim_supported_by_evidence(
        "Se describe un procedimiento abierto con lotes especiales",
        ["Solo hay un sello de entrada sin más detalle."],
        min_content_ratio=0.9,
    )
    assert not ok
    assert missing

    ok2, missing2 = claim_supported_by_evidence(
        "Se describe un procedimiento abierto con lotes",
        ["El procedimiento abierto con lotes se publica en el BOE."],
        min_content_ratio=0.3,
    )
    assert ok2
    assert missing2 == []

    ok3, missing3 = claim_supported_by_evidence("Laura Méndez es administradora", [""])
    assert not ok3
    assert missing3

    ok4, _ = claim_supported_by_evidence("ok", ["corpus vacío de anclajes no críticos"])
    assert ok4  # sin anclajes críticos ni tokens de contenido ≥3 tras stopwords


def test_build_evidence_text_index_merges_sources() -> None:
    index = build_evidence_text_index(
        memory_items=[
            {"evidence_id": "e1", "text": "Fragmento memoria A"},
            {"id": "e2", "extract": "Fragmento memoria B"},
            "skip",
            {"evidence_id": "", "text": "sin id"},
        ],
        signal_factual={
            "items": [
                {"evidence_id": "e1", "text": "extra e1"},
                {"id": "e3", "extract": "signal only"},
            ]
        },
        oracle_authority={
            "oracle_evidence": [
                {"id": "e4", "extract": "oracle pin"},
                {"evidence_id": "e5", "text": "oracle text"},
            ]
        },
        citations=[
            {"evidence_id": "e1", "quote": "cita del modelo"},
            {"evidence_id": "e6", "text": "quote text"},
            "skip-cit",
        ],
    )
    assert "e1" in index
    assert "Fragmento memoria A" in index["e1"]
    assert "cita del modelo" in index["e1"]
    assert index["e3"] == "signal only"
    assert "oracle pin" in index["e4"]
    assert "e6" in index


def test_evaluate_material_support_skips_without_statement_or_ids() -> None:
    assert evaluate_material_support({}, {}, path="$.facts[0]") is None
    assert evaluate_material_support({"statement": "x"}, {}, path="$.facts[0]") is None
    assert (
        evaluate_material_support(
            {"statement": "El CPV es 12345678", "evidence_ids": "not-a-list"},
            {},
            path="$.facts[0]",
        )
        is None
    )
    # evidence_id singular
    issue = evaluate_material_support(
        {
            "statement": "El administrador es Laura Méndez",
            "evidence_id": "e-x",
        },
        {"e-x": "Solo licitación sin personas."},
        path="$.facts[0]",
    )
    assert issue is not None
    assert issue.action == "withdraw"
    assert "Laura" in " ".join(issue.missing_anchors) or "laura" in issue.reason.casefold()


def test_format_support_rejection_summary_and_non_mapping_items() -> None:
    result = enforce_citation_support(
        facts=["not-a-mapping", {"statement": "sin citas"}],
        claims=[
            {
                "statement": "Importe 9.999.999 EUR y CPV 99999999",
                "evidence_ids": ["e1"],
            },
            {
                "statement": "El administrador es Laura Méndez",
                "evidence_ids": ["e1"],
            },
        ],
        evidence_text_by_id={"e1": "Licitación sin cifras ni personas."},
    )
    assert result.degraded_count >= 1
    assert result.withdrawn_count >= 1
    summary = format_support_rejection_summary(result)
    assert summary is not None
    assert CITATION_DOES_NOT_SUPPORT in summary
    assert "retirada" in summary.casefold() or "cargo" in summary.casefold()

    empty = enforce_citation_support(facts=[], claims=[], evidence_text_by_id={})
    assert format_support_rejection_summary(empty) is None


def test_claim_text_key_and_single_token_anchor() -> None:
    """Cubre statement vía 'claim'/'text' y anclaje de un solo token."""
    result = enforce_citation_support(
        facts=[
            {
                "text": "Bilbao es la sede",
                "evidence_ids": ["e1"],
            }
        ],
        claims=[
            {
                "claim": "El NIF es B12345678",
                "evidence_ids": ["e1"],
            }
        ],
        evidence_text_by_id={"e1": "Sede social en Bilbao. NIF B12345678."},
    )
    assert result.kept_count == 2
    assert result.warnings == []
