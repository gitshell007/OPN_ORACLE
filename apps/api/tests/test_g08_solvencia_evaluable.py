"""SV2-G08 · solvencia evaluable con datos declarados por el cliente (coste 0)."""

from __future__ import annotations

import math
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from opn_oracle.ai.context import (
    _profile_summary,
    build_declared_profile_evidence,
    declared_evidence_id,
    validate_opportunity_origin_boundary,
)
from opn_oracle.ai.fit_scoring import (
    enrich_opportunity_fit_assessment,
    score_profile_tender_fit,
)
from opn_oracle.oracle.service import (
    DomainValidationError,
    _validated_market_profile,
    _validated_profile,
)

# --- Demo canónica ficticia (no datos reales) ---------------------------------

DEMO_DOSSIER_ID = uuid.UUID("ab7bba16-3e55-4f35-ad73-0c84e2850688")
DEMO_OFFICIAL_ID = uuid.UUID("d96614d3-aaaa-4bbb-8ccc-333333333333")

DEMO_PLIEGO_EXTRACT = """
EXTRACTO DEL PCAP · CONTR 2026 88001 · Demo G-08 Solvencia (ficticio)
Fuente: PCAP oficial sintético — fixture de tests.

IDENTIFICACION
- Expediente: CONTR 2026 88001
- Objeto: servicio de diseño e implantación de software y plataformas de IA
- CPV principal: 72200000
- Importe / valor estimado: 1.000.000 EUR
- Deadline presentación ofertas: 2026-12-31

F.2. MEDIOS DE ACREDITACION DE LA SOLVENCIA ECONOMICA Y FINANCIERA
La solvencia economica se acredita con el volumen anual de negocio. Se entiende que la
solvencia es suficiente si el volumen anual de negocio declarado por la empresa, referido
al ano de mayor volumen de los tres ultimos concluidos, es al menos una vez y media el
valor estimado del contrato (1.000.000 EUR → umbral 1.500.000 EUR).

F.3. MEDIOS DE ACREDITACION DE LA SOLVENCIA TECNICA
Medios: relacion de los servicios ejecutados en el curso de los ultimos tres anos avalada
por certificados de buena ejecucion.
"""

DEMO_PROFILE = {
    "version": "custom.v1",
    "own_offer": (
        "Nexus Ibérica Sistemas (ficticia): software, plataformas e inteligencia artificial "
        "para administraciones públicas."
    ),
    "decision_to_make": "Priorizar licitaciones software/IA con solvencia acreditada",
    "competitors": [{"name": "Capgemini"}, {"name": "NTT DATA"}],
    "cpv": ["72000000", "72200000", "72212000"],
    "barriers": ["Homologación sector público"],
    "annual_turnover": 2_000_000,
    "past_services": (
        "Servicios de implantación de plataformas software e IA para AAPP en 2023-2025, "
        "con certificados de buena ejecución de contratos similares (fixture demo)."
    ),
}


def _demo_declared(dossier_id: uuid.UUID = DEMO_DOSSIER_ID) -> dict[str, str]:
    return {
        field: str(declared_evidence_id(dossier_id, field))
        for field in (
            "own_offer",
            "cpv",
            "barriers",
            "competitors",
            "annual_turnover",
            "past_services",
        )
    }


def _demo_official(eid: uuid.UUID | None = None) -> list[dict]:
    return [
        {
            "id": str(eid or DEMO_OFFICIAL_ID),
            "extract": DEMO_PLIEGO_EXTRACT,
            "source_kind": "document",
            "locator": {"kind": "pliego_extract", "ref": "CONTR 2026 88001"},
        }
    ]


# --- Validación backend -------------------------------------------------------


@pytest.mark.parametrize("dossier_type", ["market", "competitive_intelligence", "custom"])
def test_validated_profile_accepts_and_normalizes_solvency(dossier_type: str) -> None:
    if dossier_type == "market":
        base = {
            "own_offer": "Oferta",
            "decision_to_make": "Decidir",
            "competitors": [{"name": "Rival"}],
        }
        out = _validated_profile(
            {**base, "annual_turnover": 2_000_000.0, "past_services": "Servicios 2023-25"},
            "market",
        )
    elif dossier_type == "competitive_intelligence":
        base = {
            "own_offer": "Oferta",
            "business_objective": "Ganar",
            "competitors": [{"name": "Rival"}],
        }
        out = _validated_profile(
            {**base, "annual_turnover": "1500000.50", "past_services": "Servicios CI"},
            "competitive_intelligence",
        )
    else:
        out = _validated_profile(
            {
                "version": "custom.v1",
                "own_offer": "Software",
                "annual_turnover": 2_000_000,
                "past_services": "Servicios custom",
            },
            "custom",
        )
    assert isinstance(out["annual_turnover"], (int, float))
    assert out["annual_turnover"] >= 0
    assert out.get("past_services")


def test_empty_solvency_is_clean_absence() -> None:
    market = _validated_market_profile(
        {
            "own_offer": "Oferta",
            "decision_to_make": "Decidir",
            "competitors": [{"name": "R"}],
            "annual_turnover": "",
            "past_services": "   ",
        }
    )
    assert "annual_turnover" not in market
    assert "past_services" not in market

    custom = _validated_profile(
        {"version": "custom.v1", "own_offer": "X", "annual_turnover": None, "past_services": ""},
        "custom",
    )
    assert "annual_turnover" not in custom
    assert "past_services" not in custom


@pytest.mark.parametrize(
    "raw",
    [
        -1,
        True,
        False,
        float("nan"),
        float("inf"),
        "1.000.000 EUR",
        "about 2M",
        "NaN",
    ],
)
def test_annual_turnover_rejects_invalid(raw: object) -> None:
    with pytest.raises(DomainValidationError, match="annual_turnover"):
        _validated_market_profile(
            {
                "own_offer": "Oferta",
                "decision_to_make": "Decidir",
                "competitors": [{"name": "R"}],
                "annual_turnover": raw,
            }
        )


def test_past_services_rejects_bool_and_excessive_length() -> None:
    with pytest.raises(DomainValidationError, match="past_services"):
        _validated_profile(
            {
                "version": "custom.v1",
                "own_offer": "X",
                "past_services": True,
            },
            "custom",
        )
    with pytest.raises(DomainValidationError, match="4000"):
        _validated_profile(
            {
                "version": "custom.v1",
                "own_offer": "X",
                "past_services": "x" * 4001,
            },
            "custom",
        )


# --- Profile summary + declared evidence --------------------------------------


def test_profile_summary_and_declared_evidence_transport_solvency() -> None:
    dossier = SimpleNamespace(id=DEMO_DOSSIER_ID, profile_config=dict(DEMO_PROFILE))
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["origin"] == "declared_by_client"
    assert summary["annual_turnover"] == 2_000_000
    assert "certificados" in summary["past_services"].casefold()

    items = build_declared_profile_evidence(dossier)  # type: ignore[arg-type]
    by_field = {item["locator"]["field"]: item for item in items}
    assert "annual_turnover" in by_field
    assert "past_services" in by_field
    turnover_id = declared_evidence_id(DEMO_DOSSIER_ID, "annual_turnover")
    services_id = declared_evidence_id(DEMO_DOSSIER_ID, "past_services")
    assert by_field["annual_turnover"]["id"] == str(turnover_id)
    assert by_field["past_services"]["id"] == str(services_id)
    assert by_field["annual_turnover"]["origin"] == "declared_by_client"
    assert by_field["annual_turnover"]["source_kind"] == "declared"
    assert by_field["past_services"]["source_kind"] == "declared"
    assert "Declarado por el cliente" in by_field["annual_turnover"]["label"]
    assert by_field["annual_turnover"]["locator"]["kind"] == "client_profile"
    assert by_field["past_services"]["locator"]["field"] == "past_services"
    # Determinismo UUID5
    again = build_declared_profile_evidence(dossier)  # type: ignore[arg-type]
    assert {i["id"] for i in again} == {i["id"] for i in items}

    # Origin boundary: declared IDs no pueden ser facts oficiales
    cleaned = validate_opportunity_origin_boundary(
        {
            "facts": [
                {
                    "statement": "Volumen oficial inventado",
                    "evidence_ids": [str(turnover_id)],
                }
            ],
            "inferences": [],
            "fit_assessment": {
                "statement": "Encaje",
                "declared_evidence_ids": [str(turnover_id), str(services_id)],
                "official_evidence_ids": [str(DEMO_OFFICIAL_ID)],
                "confidence": 70,
                "origin": "declared_by_client",
            },
            "warnings": [],
        },
        official_ids={DEMO_OFFICIAL_ID},
        declared_ids={turnover_id, services_id},
    )
    assert cleaned["facts"] == []
    assert cleaned["fit_assessment"] is not None
    assert str(turnover_id) in cleaned["fit_assessment"]["declared_evidence_ids"]


@pytest.mark.parametrize(
    "version,extra",
    [
        ("market.v1", {"decision_to_make": "D", "own_offer": "O"}),
        ("competitive-intelligence.v1", {"business_objective": "B", "own_offer": "O"}),
        ("custom.v1", {"own_offer": "O"}),
    ],
)
def test_profile_summary_solvency_all_versions(version: str, extra: dict) -> None:
    dossier = SimpleNamespace(
        profile_config={
            "version": version,
            "competitors": [{"name": "R"}],
            "annual_turnover": 1_000_000,
            "past_services": "Servicios",
            **extra,
        }
    )
    summary = _profile_summary(dossier)  # type: ignore[arg-type]
    assert summary["annual_turnover"] == 1_000_000
    assert summary["past_services"] == "Servicios"
    assert summary["origin"] == "declared_by_client"


# --- Scoring ------------------------------------------------------------------


def test_demo_g08_four_fit_clean_go() -> None:
    declared = _demo_declared()
    scored = score_profile_tender_fit(
        profile=DEMO_PROFILE,
        declared_by_field=declared,
        official_evidence=_demo_official(),
        as_of=date(2026, 8, 6),
    )
    assert scored is not None
    statuses = {d["key"]: d["status"] for d in scored["dimensions"]}
    assert statuses == {
        "cpv": "fit",
        "solvency": "fit",
        "lots": "fit",
        "deadline": "fit",
    }
    assert scored["verdict"]["recommendation"] == "go"
    assert scored["verdict"]["conditions"] == []
    assert scored["verdict"]["human_gate"] == "awaiting_user_confirmation"

    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert str(DEMO_OFFICIAL_ID) in solv["official_evidence_ids"]
    # Exact array equality: F.2+F.3 with both data → [turnover, services] only.
    # own_offer / barriers may appear in capability text but NEVER as evidence IDs.
    assert solv["declared_evidence_ids"] == [
        declared["annual_turnover"],
        declared["past_services"],
    ]
    assert declared["own_offer"] not in solv["declared_evidence_ids"]
    assert declared["barriers"] not in solv["declared_evidence_ids"]
    assert "[oficial]" in solv["requirement"]
    assert "[declarado]" in solv["capability"]
    assert "no es acreditación" in solv["capability"].casefold()


def test_low_volume_is_no_go() -> None:
    profile = {**DEMO_PROFILE, "annual_turnover": 100_000}
    declared = _demo_declared()
    scored = score_profile_tender_fit(
        profile=profile,
        declared_by_field=declared,
        official_evidence=_demo_official(),
        as_of=date(2026, 8, 6),
    )
    assert scored is not None
    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert solv["status"] == "no_fit"
    assert scored["verdict"]["recommendation"] == "no_go"
    assert scored["verdict"]["human_gate"] == "awaiting_user_confirmation"


@pytest.mark.parametrize("missing", ["annual_turnover", "past_services"])
def test_missing_required_field_is_go_conditioned(missing: str) -> None:
    profile = {k: v for k, v in DEMO_PROFILE.items() if k != missing}
    declared = _demo_declared()
    scored = score_profile_tender_fit(
        profile=profile,
        declared_by_field=declared,
        official_evidence=_demo_official(),
        as_of=date(2026, 8, 6),
    )
    assert scored is not None
    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert solv["status"] == "not_evaluable"
    assert scored["verdict"]["recommendation"] == "go_conditioned"
    assert scored["verdict"]["human_gate"] == "awaiting_user_confirmation"


def test_no_official_f2_f3_does_not_invent_threshold() -> None:
    extract = """
    EXTRACTO sintético sin solvencia · CONTR 2026 77001
    CPV 72200000 · Deadline presentación ofertas: 2026-12-31
    Objeto: servicio de software
    """
    scored = score_profile_tender_fit(
        profile=DEMO_PROFILE,
        declared_by_field=_demo_declared(),
        official_evidence=[
            {"id": str(uuid.uuid4()), "extract": extract, "source_kind": "document"}
        ],
        as_of=date(2026, 8, 6),
    )
    assert scored is not None
    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert solv["status"] == "not_evaluable"
    assert (
        "no hay requisito" in solv["status_reason"].casefold()
        or "no se ha localizado" in solv["requirement"].casefold()
    )


def test_solvency_declared_ids_exact_f2_f3_without_context() -> None:
    """declared_evidence_ids is exactly the F.2/F.3 fields used — array equality, not `in`."""

    declared = _demo_declared()
    # F.2 + F.3 with both data → exactly [turnover, services]
    scored = score_profile_tender_fit(
        profile=DEMO_PROFILE,
        declared_by_field=declared,
        official_evidence=_demo_official(),
        as_of=date(2026, 8, 6),
    )
    assert scored is not None
    solv = next(d for d in scored["dimensions"] if d["key"] == "solvency")
    assert solv["declared_evidence_ids"] == [
        declared["annual_turnover"],
        declared["past_services"],
    ]
    assert declared["own_offer"] not in solv["declared_evidence_ids"]
    assert declared["barriers"] not in solv["declared_evidence_ids"]
    assert all(isinstance(x, str) and uuid.UUID(x) for x in solv["declared_evidence_ids"])

    # Solo F.2 oficial → solo turnover (aunque past_services esté en el perfil)
    f2_only = """
    EXTRACTO sintético · CONTR 2026 88002
    CPV 72200000 · Deadline presentación ofertas: 2026-12-31
    F.2 Solvencia económica: volumen anual de negocio >= 1,5x valor estimado 500000 EUR.
    Objeto: servicio de software
    """
    scored_f2 = score_profile_tender_fit(
        profile=DEMO_PROFILE,
        declared_by_field=declared,
        official_evidence=[
            {"id": str(DEMO_OFFICIAL_ID), "extract": f2_only, "source_kind": "document"}
        ],
        as_of=date(2026, 8, 6),
    )
    assert scored_f2 is not None
    solv_f2 = next(d for d in scored_f2["dimensions"] if d["key"] == "solvency")
    assert solv_f2["declared_evidence_ids"] == [declared["annual_turnover"]]
    assert declared["past_services"] not in solv_f2["declared_evidence_ids"]
    assert declared["own_offer"] not in solv_f2["declared_evidence_ids"]

    # Solo F.3 oficial → solo services (aunque annual_turnover esté en el perfil)
    f3_only = """
    EXTRACTO sintético · CONTR 2026 88003
    CPV 72200000 · Deadline presentación ofertas: 2026-12-31
    F.3 Solvencia técnica: servicios ejecutados en los últimos tres años avalados
    por certificados de buena ejecución.
    Objeto: servicio de software
    """
    scored_f3 = score_profile_tender_fit(
        profile=DEMO_PROFILE,
        declared_by_field=declared,
        official_evidence=[
            {"id": str(DEMO_OFFICIAL_ID), "extract": f3_only, "source_kind": "document"}
        ],
        as_of=date(2026, 8, 6),
    )
    assert scored_f3 is not None
    solv_f3 = next(d for d in scored_f3["dimensions"] if d["key"] == "solvency")
    assert solv_f3["declared_evidence_ids"] == [declared["past_services"]]
    assert declared["annual_turnover"] not in solv_f3["declared_evidence_ids"]
    assert declared["own_offer"] not in solv_f3["declared_evidence_ids"]
    assert declared["barriers"] not in solv_f3["declared_evidence_ids"]


# --- E2E editor/PATCH → contexto → enrich (no dict manual del scorer) ---------


def test_e2e_editor_patch_validation_to_context_to_enrich_go() -> None:
    """Camino producto: validación de PATCH → profile_summary → declared → enrich → GO.

    No construye el dict del scorer a mano: el perfil pasa por ``_validated_profile``
    (misma función que create/PATCH de dossier), luego por el transporte de contexto
    y por ``enrich_opportunity_fit_assessment``.
    """

    dossier_id = DEMO_DOSSIER_ID
    # 1) Draft vacío de solvencia no puede emitir campos (simula UI pre-G-08 / vacío)
    bare = _validated_profile(
        {
            "version": "custom.v1",
            "own_offer": DEMO_PROFILE["own_offer"],
            "decision_to_make": DEMO_PROFILE["decision_to_make"],
            "competitors": DEMO_PROFILE["competitors"],
            "cpv": DEMO_PROFILE["cpv"],
            "barriers": DEMO_PROFILE["barriers"],
            "annual_turnover": "",
            "past_services": "",
        },
        "custom",
    )
    assert "annual_turnover" not in bare
    assert "past_services" not in bare

    # 2) PATCH con número + texto (lo que envía profileConfigFromDraft)
    persisted = _validated_profile(
        {
            **bare,
            "annual_turnover": 2_000_000,
            "past_services": DEMO_PROFILE["past_services"],
        },
        "custom",
    )
    assert persisted["annual_turnover"] == 2_000_000
    assert "certificados" in persisted["past_services"].casefold()

    # 3) Validación negativa (equivalente a 422 del API)
    with pytest.raises(DomainValidationError, match="annual_turnover"):
        _validated_profile({**persisted, "annual_turnover": -5}, "custom")
    with pytest.raises(DomainValidationError, match="annual_turnover"):
        _validated_profile({**persisted, "annual_turnover": True}, "custom")
    with pytest.raises(DomainValidationError, match="annual_turnover"):
        _validated_profile({**persisted, "annual_turnover": "1.000.000 EUR"}, "custom")
    with pytest.raises(DomainValidationError, match="past_services"):
        _validated_profile({**persisted, "past_services": True}, "custom")
    with pytest.raises(DomainValidationError, match="past_services"):
        _validated_profile({**persisted, "past_services": "x" * 4001}, "custom")
    # max exact length persists complete
    max_ok = _validated_profile(
        {**persisted, "past_services": "y" * 4000},
        "custom",
    )
    assert max_ok["past_services"] == "y" * 4000

    # 4) Contexto declarado (mismo camino que opportunity)
    row = SimpleNamespace(id=dossier_id, profile_config=persisted)
    profile = _profile_summary(row)  # type: ignore[arg-type]
    declared_items = build_declared_profile_evidence(row)  # type: ignore[arg-type]
    declared_ids = [item["id"] for item in declared_items]
    assert profile["annual_turnover"] == 2_000_000
    assert str(declared_evidence_id(dossier_id, "annual_turnover")) in declared_ids
    assert str(declared_evidence_id(dossier_id, "past_services")) in declared_ids

    context = {
        "dossier": {"profile": profile},
        "declared_evidence": declared_items,
        "allowed_declared_evidence_ids": declared_ids,
        "allowed_evidence_ids": [str(DEMO_OFFICIAL_ID)],
        "evidence": _demo_official(),
    }
    output = {
        "title": "Oportunidad demo G-08",
        "recommendation": "investigate",
        "fit_assessment": {
            "statement": "Encaje preliminar mock.",
            "declared_evidence_ids": [declared_ids[0]],
            "official_evidence_ids": [str(DEMO_OFFICIAL_ID)],
            "confidence": 50,
            "origin": "declared_by_client",
        },
        "facts": [],
        "warnings": [],
    }
    enriched = enrich_opportunity_fit_assessment(
        output, context_payload=context, as_of=date(2026, 8, 6)
    )
    fit = enriched["fit_assessment"]
    assert fit is not None
    statuses = {d["key"]: d["status"] for d in fit["dimensions"]}
    assert statuses == {
        "cpv": "fit",
        "solvency": "fit",
        "lots": "fit",
        "deadline": "fit",
    }
    assert fit["verdict"]["recommendation"] == "go"
    assert fit["verdict"]["conditions"] == []
    assert fit["verdict"]["human_gate"] == "awaiting_user_confirmation"
    solv = next(d for d in fit["dimensions"] if d["key"] == "solvency")
    assert solv["declared_evidence_ids"] == [
        str(declared_evidence_id(dossier_id, "annual_turnover")),
        str(declared_evidence_id(dossier_id, "past_services")),
    ]
    assert str(declared_evidence_id(dossier_id, "own_offer")) not in solv["declared_evidence_ids"]
    assert str(declared_evidence_id(dossier_id, "barriers")) not in solv["declared_evidence_ids"]
    assert "[oficial]" in solv["requirement"] and "[declarado]" in solv["capability"]


def test_validated_profile_market_and_ci_persist_solvency_fields() -> None:
    market = _validated_market_profile(
        {
            "own_offer": "Baterías",
            "decision_to_make": "Entrar",
            "competitors": [{"name": "Gamma"}],
            "annual_turnover": 3_000_000,
            "past_services": "EPC con certificados",
        }
    )
    assert market["annual_turnover"] == 3_000_000
    assert market["past_services"] == "EPC con certificados"

    ci = _validated_profile(
        {
            "own_offer": "Producto",
            "business_objective": "Ganar",
            "competitors": [{"name": "Rival"}],
            "annual_turnover": 1_250_000.25,
            "past_services": "Servicios CI",
        },
        "competitive_intelligence",
    )
    assert math.isclose(float(ci["annual_turnover"]), 1_250_000.25)
    assert ci["past_services"] == "Servicios CI"
