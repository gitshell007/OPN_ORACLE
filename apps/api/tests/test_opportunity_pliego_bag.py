"""SV2-E2E-VIVO · bag de opportunity prioriza PCAP/documentos frente al pin fino.

Demuestra el fallo del camino vivo: con solo el pin PLACSP (sin F.2/F.3/65/60)
el motor cae a not_evaluable / fallback; con chunks de extracto PCAP en el bag
(ranking pliego) produce fit completo + draft ≥3 secciones con citas reales.
"""

from __future__ import annotations

import uuid
from datetime import date

from opn_oracle.ai.context import (
    _is_opportunity_pliego_materialization,
    declared_evidence_id,
    diversify_evidence_by_source_kind,
    pliego_evidence_family,
    pliego_evidence_richness,
    rank_opportunity_evidence_items,
)
from opn_oracle.ai.draft_offer import enrich_opportunity_draft_offer
from opn_oracle.ai.fit_scoring import enrich_opportunity_fit_assessment

# Pin PLACSP fino (como d96614d3 en vivo): sin F.2/F.3 ni 65/60.
THIN_PIN_EXTRACT = (
    "Licitación PLACSP CONTR 2026 11077: servicio de diseño, desarrollo e implantación "
    "de una red de agentes inteligentes en el Govern de les Illes Balears (GOIB), en "
    "2 lotes (Lote 1: Gobernanza de la IA / Lote 2: Red de agentes inteligentes). "
    "Importe 5.450.796,93 EUR. Deadline 2026-08-06. CPV 72230000, 72263000."
)

CRITERIA_CHUNK = """
CRITERIOS DE ADJUDICACION
La adjudicacion se realiza segun la mejor relacion calidad-precio.
Criterios de adjudicacion evaluables mediante formulas (oferta economica) y criterios
evaluables mediante juicio de valor (oferta tecnica).
Si concurre un unico licitador, cuando la puntuacion del otro criterio sea superior a
los 65 puntos. Si concurren dos o mas licitadores, cuando la puntuacion del otro
criterio distinto de la oferta economica sea superior en 60 puntos porcentuales a la
media aritmetica de las puntuaciones obtenidas en dicho criterio por todas las empresas.
"""

F2_CHUNK = """
F.2. MEDIOS DE ACREDITACION DE LA SOLVENCIA ECONOMICA Y FINANCIERA
La solvencia economica se acredita con el volumen anual de negocio. Se entiende que la
solvencia es suficiente si el volumen anual de negocio declarado por la empresa, referido
al ano de mayor volumen de los tres ultimos concluidos, es al menos una vez y media el
valor estimado del contrato (o la parte correspondiente al lote).
"""

F3_CHUNK = """
F.3. MEDIOS DE ACREDITACION DE LA SOLVENCIA TECNICA (art. 90, 93 y 94 LCSP)
Medios: Clasificacion en los subgrupos de clasificacion correspondientes al contrato,
o bien, relacion de los servicios ejecutados en el curso de los ultimos tres anos avalada
por certificados de buena ejecucion.
"""

LOTS_CHUNK = """
LOTES
- Lote 1: Gobernanza de la IA
- Lote 2: Red de agentes inteligentes
EXTRACTO DEL PCAP · CONTR 2026 11077 · Baleares
"""

PORTFOLIO_NOISE = (
    "Licitación PLACSP 5832/2026 tiene un CPV de 48442000 y deadline 2026-08-03. "
    "Sin relación con Baleares ni agentes inteligentes."
)

NEXUS_PROFILE = {
    "version": "custom.v1",
    "own_offer": (
        "Nexus Ibérica Sistemas: software, plataformas e inteligencia artificial para "
        "administraciones públicas y grandes cuentas."
    ),
    "cpv": ["72000000", "72200000", "72212000", "72222300", "48000000"],
    "barriers": [
        "Homologación y solvencia técnica exigida en AAPP",
        "Plazos de licitación y documentación técnica",
    ],
}


def _declared_list(dossier_id: uuid.UUID) -> list[dict]:
    fields = {
        "own_offer": "Oferta propia: Nexus Ibérica Sistemas…",
        "cpv": "CPV de interés: 72000000, 72200000",
        "barriers": "Barreras declaradas: Homologación; Plazos",
    }
    out = []
    for field, extract in fields.items():
        out.append(
            {
                "id": str(declared_evidence_id(dossier_id, field)),
                "extract": extract,
                "locator": {"field": field},
                "source_kind": "declared",
            }
        )
    return out


def test_rank_prefers_pliego_chunks_over_thin_pin_and_noise() -> None:
    pin_id = str(uuid.uuid4())
    crit_id = str(uuid.uuid4())
    f2_id = str(uuid.uuid4())
    f3_id = str(uuid.uuid4())
    noise_id = str(uuid.uuid4())
    items = [
        {"id": noise_id, "extract": PORTFOLIO_NOISE, "source_kind": "procurement"},
        {"id": pin_id, "extract": THIN_PIN_EXTRACT, "source_kind": "procurement"},
        {"id": crit_id, "extract": CRITERIA_CHUNK, "source_kind": "document"},
        {"id": f2_id, "extract": F2_CHUNK, "source_kind": "document"},
        {"id": f3_id, "extract": F3_CHUNK, "source_kind": "memory_signal"},
    ]
    ranked = rank_opportunity_evidence_items(items, char_budget=8000, max_items=10)
    ids = [str(i["id"]) for i in ranked]
    # Pliego families first (document preferred over thin pin).
    assert crit_id in ids
    assert f2_id in ids
    assert f3_id in ids
    # Corpus must contain 65 puntos and F.2 for engines.
    corpus = " ".join(str(i.get("extract") or "") for i in ranked)
    assert "65 puntos" in corpus
    assert "F.2" in corpus or "volumen anual de negocio" in corpus.lower()
    assert pliego_evidence_richness(CRITERIA_CHUNK, source_kind="document") > (
        pliego_evidence_richness(THIN_PIN_EXTRACT, source_kind="procurement")
    )


def test_pliego_family_tags() -> None:
    assert pliego_evidence_family(CRITERIA_CHUNK) == "criteria"
    assert pliego_evidence_family(F2_CHUNK) == "f2"
    assert pliego_evidence_family(F3_CHUNK) == "f3"
    assert pliego_evidence_family(LOTS_CHUNK) == "lots"


def test_thin_pin_only_solvency_not_evaluable() -> None:
    """Reproduce deuda 134: bag = pin fino → solvencia not_evaluable."""
    dossier_id = uuid.uuid4()
    pin_id = str(uuid.uuid4())
    declared = _declared_list(dossier_id)
    context = {
        "dossier": {"id": str(dossier_id), "profile": NEXUS_PROFILE},
        "evidence": [{"id": pin_id, "extract": THIN_PIN_EXTRACT, "source_kind": "procurement"}],
        "allowed_evidence_ids": [pin_id],
        "declared_evidence": declared,
        "allowed_declared_evidence_ids": [d["id"] for d in declared],
    }
    out = enrich_opportunity_fit_assessment(
        {"title": "t", "confidence": 40, "facts": [], "warnings": []},
        context_payload=context,
        as_of=date(2026, 8, 4),
    )
    fit = out["fit_assessment"]
    solv = next(d for d in fit["dimensions"] if d["key"] == "solvency")
    assert solv["status"] == "not_evaluable"
    assert "no hay requisito de solvencia" in (solv.get("status_reason") or "").lower() or (
        "no se ha localizado" in (solv.get("requirement") or "").lower()
    )


def test_pliego_bag_yields_full_fit_and_draft_sections() -> None:
    """Con bag ranking (pin + document chunks) → fit rico + draft ≥3 con citas PCAP."""
    dossier_id = uuid.uuid4()
    pin_id = str(uuid.uuid4())
    crit_id = str(uuid.uuid4())
    f2_id = str(uuid.uuid4())
    f3_id = str(uuid.uuid4())
    lots_id = str(uuid.uuid4())
    declared = _declared_list(dossier_id)

    bag_items = [
        {"id": pin_id, "extract": THIN_PIN_EXTRACT, "source_kind": "procurement"},
        {"id": crit_id, "extract": CRITERIA_CHUNK, "source_kind": "document"},
        {"id": f2_id, "extract": F2_CHUNK, "source_kind": "document"},
        {"id": f3_id, "extract": F3_CHUNK, "source_kind": "document"},
        {"id": lots_id, "extract": LOTS_CHUNK, "source_kind": "document"},
        {
            "id": str(uuid.uuid4()),
            "extract": PORTFOLIO_NOISE,
            "source_kind": "procurement",
        },
    ]
    ranked = rank_opportunity_evidence_items(bag_items, char_budget=12000, max_items=12)
    allow = [str(i["id"]) for i in ranked]
    context = {
        "dossier": {"id": str(dossier_id), "profile": NEXUS_PROFILE},
        "evidence": ranked,
        "allowed_evidence_ids": allow,
        "declared_evidence": declared,
        "allowed_declared_evidence_ids": [d["id"] for d in declared],
    }
    out = enrich_opportunity_fit_assessment(
        {"title": "t", "confidence": 40, "facts": [], "warnings": []},
        context_payload=context,
        as_of=date(2026, 8, 4),
    )
    fit = out["fit_assessment"]
    assert len(fit.get("dimensions") or []) >= 4
    solv = next(d for d in fit["dimensions"] if d["key"] == "solvency")
    # Con F.2/F.3 en bag: requisito localizado (status not_evaluable por perfil, no por bag).
    assert (
        "F.2" in (solv.get("requirement") or "")
        or "volumen" in (solv.get("requirement") or "").lower()
    )
    assert f2_id in (solv.get("official_evidence_ids") or []) or any(
        eid in (solv.get("official_evidence_ids") or []) for eid in (f2_id, f3_id)
    )
    assert fit.get("verdict", {}).get("human_gate") == "awaiting_user_confirmation"

    out = enrich_opportunity_draft_offer(out, context_payload=context, as_of=date(2026, 8, 4))
    draft = out["draft_offer"]
    sections = draft.get("sections") or []
    assert len(sections) >= 3
    # At least 3 sections cite real pliego document evidence (not only thin pin).
    pliego_cited = 0
    for sec in sections:
        eids = set(sec.get("official_evidence_ids") or [])
        req = str(sec.get("requirement") or "")
        if (
            eids & {crit_id, f2_id, f3_id, lots_id}
            or "65" in req
            or "F.2" in req
            or "juicio" in req
        ):
            pliego_cited += 1
    assert pliego_cited >= 3, f"expected ≥3 pliego-cited sections, got {pliego_cited}: {sections}"
    checklist = draft.get("administrative_checklist") or []
    assert len(checklist) >= 5
    assert draft.get("human_gate") == "draft_requires_human_edit"
    # Statement literal anchors PCAP criteria / tender.
    statement = str(draft.get("statement") or "")
    assert "CONTR 2026 11077" in statement or "borrador" in statement.lower()


class _FakeEvidence:
    def __init__(
        self,
        source_kind: str,
        extract: str,
        *,
        provenance: dict | None = None,
        locator: dict | None = None,
    ) -> None:
        self.source_kind = source_kind
        self.extract = extract
        self.provenance = provenance or {}
        self.locator = locator or {}


def test_diversify_prevents_document_flood_after_pliego_materialize() -> None:
    """Regresión baseline: 70 document chunks no pueden borrar entity_intel del bag genérico."""

    docs = [_FakeEvidence("document", f"pliego chunk {i}") for i in range(70)]
    entity = [_FakeEvidence("entity_intel", f"Laura admin fact {i}") for i in range(5)]
    proc = [_FakeEvidence("procurement", f"pin placsp {i}") for i in range(5)]
    # Newest first: documents dominate like post-materialize created_at desc.
    candidates = docs + entity + proc
    selected = diversify_evidence_by_source_kind(candidates, limit=50, max_per_kind=15)
    kinds = [r.source_kind for r in selected]
    # Without diversify, limit=50 would be 50x document. With diversify, all
    # non-document kinds are preserved and document is soft-capped first.
    assert kinds.count("entity_intel") == 5
    assert kinds.count("procurement") == 5
    assert any("Laura" in r.extract for r in selected)
    assert kinds.count("document") <= 40  # residual fill after other kinds
    assert kinds.count("document") < 50
    assert len(selected) == 50


def test_opportunity_materialization_flag() -> None:
    opp = _FakeEvidence(
        "document",
        "pliego",
        provenance={"materialized_for": "sv2_e2e_vivo_opportunity"},
    )
    normal = _FakeEvidence("document", "upload normal")
    assert _is_opportunity_pliego_materialization(opp) is True
    assert _is_opportunity_pliego_materialization(normal) is False


def test_oracle_authority_bag_excludes_opportunity_materializations() -> None:
    """Preguntar authority (40 slots) must keep memory_signal after pliego materialize.

    Without the filter, kind_rank document=1 fills all 40 slots with opportunity
    chunks and Laura/admin markers vanish from the dual-ask authority block.
    """

    mat_docs = [
        _FakeEvidence(
            "document",
            f"pliego materializado {i} NORAI criterios 65/60",
            provenance={"materialized_for": "sv2_e2e_vivo_opportunity"},
        )
        for i in range(72)
    ]
    memory = [
        _FakeEvidence(
            "memory_signal",
            f"[company:name:nexus] company.administrator: Laura Mendez fact {i}",
        )
        for i in range(20)
    ]
    proc = [_FakeEvidence("procurement", f"PLACSP pin {i}") for i in range(8)]
    # Simulate authority pre-order: document before memory_signal (kind_rank).
    candidates = mat_docs + proc + memory
    filtered = [r for r in candidates if not _is_opportunity_pliego_materialization(r)]
    selected = diversify_evidence_by_source_kind(filtered, limit=40, max_per_kind=12)
    kinds = [r.source_kind for r in selected]
    assert kinds.count("document") == 0  # all documents were opportunity-only
    assert kinds.count("memory_signal") >= 12
    assert kinds.count("procurement") == 8
    assert any("Laura Mendez" in r.extract for r in selected)
    assert not any(
        _is_opportunity_pliego_materialization(r)
        for r in selected  # type: ignore[arg-type]
    )
