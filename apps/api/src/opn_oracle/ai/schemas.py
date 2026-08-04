"""Strict structured outputs shared by Oracle AI agents."""

from __future__ import annotations

from datetime import date as CalendarDate
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _coerce_calendar_date(value: Any) -> Any:
    """Accept ISO date strings after JSON storage under ``strict=True``.

    Pydantic strict mode rejects ``str → date`` coercion. Agent outputs and AI
    artifacts are persisted with ``model_dump(mode="json")`` and reloaded with
    ``model_validate_json``; without this bridge, ``deadline`` /
    ``due_date`` / ``suggested_review_date`` fail the roundtrip even though the
    wire format is the canonical ISO date.
    """

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        # LLM/mocks sometimes emit a full ISO datetime for a date-only field.
        if "T" in text:
            text = text.split("T", 1)[0]
        try:
            return CalendarDate.fromisoformat(text)
        except ValueError:
            return value
    return value


# Use on every CalendarDate field so JSON storage stays round-trippable without
# weakening StrictModel.extra/forbid or removing the field from strict checks.
JsonDate = Annotated[CalendarDate, BeforeValidator(_coerce_calendar_date)]


def _coerce_confidence_0_100(value: Any) -> Any:
    """Models often emit 0.0-1.0 floats; Oracle schemas store 0-100 ints."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if 0.0 <= number <= 1.0:
            return round(number * 100)
        return max(0, min(100, round(number)))
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        try:
            number = float(text)
        except ValueError:
            return value
        if 0.0 <= number <= 1.0:
            return round(number * 100)
        return max(0, min(100, round(number)))
    return value


def _coerce_str_list(value: Any) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    return value


class Fact(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[UUID] = Field(min_length=1)


class Inference(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    reasoning_summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class Recommendation(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    priority: Literal["low", "medium", "high", "critical"]


class SituationFact(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationInference(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    reasoning_summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationChange(StrictModel):
    change: str = Field(min_length=1, max_length=4000)
    importance: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationOpportunity(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    urgency: Literal["low", "medium", "high", "critical"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationRisk(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=4000)
    severity: Literal["low", "medium", "high", "critical"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationActor(StrictModel):
    actor_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    relevance: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationMilestone(StrictModel):
    label: str = Field(min_length=1, max_length=500)
    date: JsonDate | None = None
    status: str = Field(min_length=1, max_length=200)
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationDecision(StrictModel):
    decision: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=4000)
    urgency: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(min_length=1)


class SituationAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    priority: Literal["low", "medium", "high", "critical"]


class EvidenceCoverage(StrictModel):
    cited_items: int = Field(ge=0)
    available_items: int = Field(ge=0)
    limitations: list[str] = Field(default_factory=list)


class EntityMention(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    entity_type: Literal["person", "organization", "place", "technology", "other"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class DuplicateHint(StrictModel):
    signal_id: UUID
    rationale: str = Field(min_length=1, max_length=2000)
    confidence: int = Field(ge=0, le=100)


class ContradictionHint(StrictModel):
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=2)
    confidence: int = Field(ge=0, le=100)


class AgentOutput(StrictModel):
    facts: list[Fact]
    inferences: list[Inference]
    recommendations: list[Recommendation]
    confidence: int = Field(ge=0, le=100)
    open_questions: list[str]
    warnings: list[str]


class IntakeOutput(AgentOutput):
    proposed_title: str
    proposed_description: str
    dossier_type: Literal[
        "project",
        "strategic_account",
        "market",
        "technology",
        "tender_or_grant",
        "investment",
        "partnership",
        "product_launch",
        "regulatory_affair",
        "risk_watch",
        "competitive_intelligence",
        "custom",
    ]


class ScoreSet(StrictModel):
    relevance: int = Field(ge=0, le=100)
    novelty: int = Field(ge=0, le=100)
    strategic_impact: int = Field(ge=0, le=100)
    source_credibility: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class SignalTriageOutput(AgentOutput):
    category: Literal[
        "news",
        "official_publication",
        "social_signal",
        "company_signal",
        "market_signal",
        "regulatory_signal",
        "tender_or_grant",
        "relationship_signal",
        "internal_document",
        "risk_signal",
        "opportunity_signal",
        "other",
    ]
    recommended_status: Literal["reviewed", "dismissed", "candidate_for_promotion"]
    scores: ScoreSet
    why_it_matters: str
    recommended_next_action: str = "Revisión humana"
    entities: list[EntityMention] = Field(default_factory=list)
    duplicate_hints: list[DuplicateHint] = Field(default_factory=list)
    contradiction_hints: list[ContradictionHint] = Field(default_factory=list)


class EntityResolutionOutput(AgentOutput):
    decision: Literal["match", "no_match", "needs_review", "create_new"]
    matched_actor_id: UUID | None
    rationale: str


class OpportunityScores(StrictModel):
    strategic_fit: int = Field(ge=0, le=100)
    urgency: int = Field(ge=0, le=100)
    expected_value: int = Field(ge=0, le=100)
    actionability: int = Field(ge=0, le=100)
    relationship_leverage: int = Field(ge=0, le=100)
    timing: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    execution_effort: int = Field(ge=0, le=100)
    blocking_risk: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class CandidateActor(StrictModel):
    actor_id: UUID | None = None
    name: str = Field(min_length=1, max_length=500)
    role: str = Field(min_length=1, max_length=500)
    evidence_ids: list[UUID] = Field(default_factory=list)


class NextBestAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    owner_role: str = Field(min_length=1, max_length=500)
    due_date: JsonDate | None = None
    rationale: str = Field(min_length=1, max_length=4000)


class OpportunityFitDimension(StrictModel):
    """Una dimensión de encaje con citas duales (oficial + declarado).

    SV2-ENCAJE: CPV, solvencia, lotes, plazo. El requisito cita el pliego
    (``requirement_origin=official``); la capacidad cita el perfil
    (``capability_origin=declared_by_client``). ``not_evaluable`` es honesto
    cuando el perfil no aporta el dato (p. ej. volumen anual).
    """

    key: Literal["cpv", "solvency", "lots", "deadline", "other"] = "other"
    label: str = Field(min_length=1, max_length=200)
    requirement: str = Field(min_length=1, max_length=2000)
    requirement_origin: Literal["official"] = "official"
    official_evidence_ids: list[UUID] = Field(default_factory=list)
    capability: str = Field(min_length=1, max_length=2000)
    capability_origin: Literal["declared_by_client"] = "declared_by_client"
    declared_evidence_ids: list[UUID] = Field(default_factory=list)
    status: Literal["fit", "partial", "no_fit", "not_evaluable"]
    status_reason: str = Field(min_length=1, max_length=1000)


class OpportunityFitVerdict(StrictModel):
    """Veredicto propuesto con puerta humana — nunca decisión automática."""

    recommendation: Literal["go", "no_go", "go_conditioned"]
    conditions: list[str] = Field(default_factory=list)
    human_gate: Literal["awaiting_user_confirmation"] = "awaiting_user_confirmation"
    rationale: str = Field(min_length=1, max_length=2000)


class OpportunityFitAssessment(StrictModel):
    """Encaje oferta↔oportunidad anclado en material **declarado por el cliente**.

    Distinto de ``facts[]``: los ``declared_evidence_ids`` tienen ``source_kind=declared``
    (perfil del expediente). Los ``official_evidence_ids`` enlazan licitaciones u
    otras fuentes oficiales que el encaje menciona, sin convertir lo declarado
    en hecho verificado.

    SV2-ENCAJE: ``dimensions`` (CPV/solvencia/lotes/plazo con citas duales) y
    ``verdict`` (go / no-go / go-condicionado + puerta humana).

    La frontera de IDs se revalida en ``validate_opportunity_origin_boundary``:
    si no hay declared válido, el bloque se anula en post-proceso.
    """

    statement: str = Field(min_length=1, max_length=4000)
    declared_evidence_ids: list[UUID] = Field(default_factory=list)
    official_evidence_ids: list[UUID] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    origin: Literal["declared_by_client"] = "declared_by_client"
    dimensions: list[OpportunityFitDimension] = Field(default_factory=list)
    verdict: OpportunityFitVerdict | None = None
    tender_ref: str | None = Field(default=None, max_length=200)
    scoring_engine: str | None = Field(default=None, max_length=80)
    scored_as_of: str | None = Field(default=None, max_length=40)


class DraftOfferGap(StrictModel):
    """Gap a acreditar (suele heredarse del veredicto de encaje)."""

    code: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=800)
    severity: Literal["blocking", "important", "info"] = "important"
    origin: Literal["verdict_condition", "pliego", "profile"] = "verdict_condition"


class DraftOfferSection(StrictModel):
    """Sección del borrador = criterio del PCAP (o bloque de habilitación).

    ``requirement`` es oficial; ``our_response_draft`` es semilla declarada/generada
    (nunca hecho). ``gaps`` lista lo que falta por acreditar en esa sección.
    """

    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    points_hint: str | None = Field(default=None, max_length=200)
    requirement: str = Field(min_length=1, max_length=2000)
    requirement_origin: Literal["official"] = "official"
    official_evidence_ids: list[UUID] = Field(default_factory=list)
    our_response_draft: str = Field(min_length=1, max_length=2000)
    response_origin: Literal["declared_generated"] = "declared_generated"
    declared_evidence_ids: list[UUID] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class DraftOfferChecklistItem(StrictModel):
    """Ítem de checklist administrativa (DEUC, sobres, solvencia…)."""

    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=500)
    status: Literal["pending", "ready", "blocked"] = "pending"
    source: Literal["pliego", "admin"] = "pliego"


class OpportunityDraftOffer(StrictModel):
    """Borrador de oferta guiado por el pliego (SV2-BORRADOR).

    Solo se genera si existe ``fit_assessment.verdict``. Es material **declarado/
    generado** (``origin=declared_draft``): no contamina ``facts[]`` oficiales
    (frontera 095). Puerta humana propia: ``draft_requires_human_edit``.
    """

    banner: str = Field(min_length=1, max_length=500)
    human_gate: Literal["draft_requires_human_edit"] = "draft_requires_human_edit"
    statement: str = Field(min_length=1, max_length=4000)
    tender_ref: str | None = Field(default=None, max_length=200)
    lot_hint: str | None = Field(default=None, max_length=200)
    sections: list[DraftOfferSection] = Field(default_factory=list)
    administrative_checklist: list[DraftOfferChecklistItem] = Field(default_factory=list)
    gaps_summary: list[str] = Field(default_factory=list)
    gaps: list[DraftOfferGap] = Field(default_factory=list)
    draft_engine: str | None = Field(default=None, max_length=80)
    drafted_as_of: str | None = Field(default=None, max_length=40)
    origin: Literal["declared_draft"] = "declared_draft"
    based_on_verdict: str | None = Field(default=None, max_length=40)
    official_evidence_ids: list[UUID] = Field(default_factory=list)
    declared_evidence_ids: list[UUID] = Field(default_factory=list)


class OpportunityAnalysisOutput(AgentOutput):
    title: str
    opportunity_type: Literal[
        "grant",
        "tender",
        "partner",
        "client",
        "market",
        "investment",
        "media",
        "regulatory",
        "other",
    ] = "other"
    summary: str = ""
    recommendation: Literal["go", "investigate", "hold", "no_go"]
    scores: OpportunityScores
    deadline: JsonDate | None = None
    confirmed_requirements: list[str] = Field(default_factory=list)
    unknown_requirements: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    candidate_actors: list[CandidateActor] = Field(default_factory=list)
    next_best_action: NextBestAction | None = None
    fit_assessment: OpportunityFitAssessment | None = None
    draft_offer: OpportunityDraftOffer | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_invalid_fit_assessment(cls, value: Any) -> Any:
        """Tolera mocks/LLM que inventan un fit_assessment incompleto o vacío.

        En lugar de tumbar el job (ValidationError), se descarta el bloque y la
        frontera de origen / motor dimensional lo rellenan o lo dejan en null.

        SV2-ENCAJE: también limpia ``dimensions``/``verdict`` malformados y
        descarta claves extra (StrictModel.extra=forbid) para no tumbar el job
        cuando Signal/LLM inventa campos.

        SV2-BORRADOR: coacciona ``draft_offer`` de forma tolerante (o lo anula).
        """

        if not isinstance(value, dict):
            return value
        fit = value.get("fit_assessment")
        if fit in (None, "", {}, []):
            value["fit_assessment"] = None
        elif not isinstance(fit, dict):
            value["fit_assessment"] = None
        else:
            statement = str(fit.get("statement") or "").strip()
            declared = fit.get("declared_evidence_ids")
            if not statement or not isinstance(declared, list) or not declared:
                value["fit_assessment"] = None
            else:
                allowed_keys = {
                    "statement",
                    "declared_evidence_ids",
                    "official_evidence_ids",
                    "confidence",
                    "origin",
                    "dimensions",
                    "verdict",
                    "tender_ref",
                    "scoring_engine",
                    "scored_as_of",
                }
                cleaned: dict[str, Any] = {
                    key: fit[key] for key in allowed_keys if key in fit
                }
                cleaned["statement"] = statement[:4000]
                cleaned["declared_evidence_ids"] = declared
                # Normalizar origin desconocido al canónico declarado.
                if cleaned.get("origin") not in {None, "", "declared_by_client"}:
                    cleaned["origin"] = "declared_by_client"
                if "confidence" in cleaned:
                    cleaned["confidence"] = _coerce_confidence_0_100(cleaned["confidence"])

                # Dimensiones: conservar solo dicts con campos mínimos válidos.
                raw_dims = cleaned.get("dimensions")
                if raw_dims is not None:
                    good_dims: list[dict[str, Any]] = []
                    if isinstance(raw_dims, list):
                        for dim in raw_dims:
                            if not isinstance(dim, dict):
                                continue
                            status = str(dim.get("status") or "").strip()
                            if status not in {"fit", "partial", "no_fit", "not_evaluable"}:
                                continue
                            req = str(dim.get("requirement") or "").strip()
                            cap = str(dim.get("capability") or "").strip()
                            reason = str(dim.get("status_reason") or "").strip()
                            label = str(dim.get("label") or dim.get("key") or "dimensión").strip()
                            if not (req and cap and reason and label):
                                continue
                            key = str(dim.get("key") or "other").strip()
                            if key not in {"cpv", "solvency", "lots", "deadline", "other"}:
                                key = "other"
                            good_dims.append(
                                {
                                    "key": key,
                                    "label": label[:200],
                                    "requirement": req[:2000],
                                    "requirement_origin": "official",
                                    "official_evidence_ids": dim.get("official_evidence_ids")
                                    if isinstance(dim.get("official_evidence_ids"), list)
                                    else [],
                                    "capability": cap[:2000],
                                    "capability_origin": "declared_by_client",
                                    "declared_evidence_ids": dim.get("declared_evidence_ids")
                                    if isinstance(dim.get("declared_evidence_ids"), list)
                                    else [],
                                    "status": status,
                                    "status_reason": reason[:1000],
                                }
                            )
                    cleaned["dimensions"] = good_dims

                # Veredicto: solo si recommendation es conocida; si no, se omite.
                raw_verdict = cleaned.get("verdict")
                if raw_verdict is not None:
                    if isinstance(raw_verdict, dict):
                        rec = str(raw_verdict.get("recommendation") or "").strip()
                        rationale = str(raw_verdict.get("rationale") or "").strip()
                        if rec in {"go", "no_go", "go_conditioned"} and rationale:
                            cleaned["verdict"] = {
                                "recommendation": rec,
                                "conditions": [
                                    str(c)[:500]
                                    for c in (raw_verdict.get("conditions") or [])
                                    if str(c).strip()
                                ][:12]
                                if isinstance(raw_verdict.get("conditions"), list)
                                else [],
                                "human_gate": "awaiting_user_confirmation",
                                "rationale": rationale[:2000],
                            }
                        else:
                            cleaned.pop("verdict", None)
                    else:
                        cleaned.pop("verdict", None)

                for opt in ("tender_ref", "scoring_engine", "scored_as_of"):
                    if opt in cleaned and cleaned[opt] is not None:
                        cleaned[opt] = str(cleaned[opt])[
                            :200 if opt == "tender_ref" else 80
                        ]

                value["fit_assessment"] = cleaned

        # SV2-BORRADOR: coaccionar draft_offer o anularlo sin tumbar el job.
        value = cls._coerce_draft_offer(value)
        return value

    @staticmethod
    def _coerce_draft_offer(value: dict[str, Any]) -> dict[str, Any]:
        draft = value.get("draft_offer")
        if draft in (None, "", {}, []):
            value["draft_offer"] = None
            return value
        if not isinstance(draft, dict):
            value["draft_offer"] = None
            return value
        statement = str(draft.get("statement") or "").strip()
        banner = str(draft.get("banner") or "").strip()
        sections = draft.get("sections")
        if not statement or not banner or not isinstance(sections, list) or not sections:
            value["draft_offer"] = None
            return value

        good_sections: list[dict[str, Any]] = []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            title = str(sec.get("title") or "").strip()
            req = str(sec.get("requirement") or "").strip()
            resp = str(sec.get("our_response_draft") or "").strip()
            key = str(sec.get("key") or title or "section").strip()[:80]
            if not (title and req and resp and key):
                continue
            gaps_raw = sec.get("gaps") if isinstance(sec.get("gaps"), list) else []
            good_sections.append(
                {
                    "key": key,
                    "title": title[:300],
                    "points_hint": (
                        str(sec.get("points_hint"))[:200]
                        if sec.get("points_hint")
                        else None
                    ),
                    "requirement": req[:2000],
                    "requirement_origin": "official",
                    "official_evidence_ids": sec.get("official_evidence_ids")
                    if isinstance(sec.get("official_evidence_ids"), list)
                    else [],
                    "our_response_draft": resp[:2000],
                    "response_origin": "declared_generated",
                    "declared_evidence_ids": sec.get("declared_evidence_ids")
                    if isinstance(sec.get("declared_evidence_ids"), list)
                    else [],
                    "gaps": [str(g)[:500] for g in gaps_raw if str(g).strip()][:12],
                }
            )
        if not good_sections:
            value["draft_offer"] = None
            return value

        checklist_raw = draft.get("administrative_checklist")
        good_checklist: list[dict[str, Any]] = []
        if isinstance(checklist_raw, list):
            for item in checklist_raw:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                desc = str(item.get("description") or "").strip()
                ckey = str(item.get("key") or label or "item").strip()[:80]
                status = str(item.get("status") or "pending").strip()
                if status not in {"pending", "ready", "blocked"}:
                    status = "pending"
                if not (label and desc and ckey):
                    continue
                source = str(item.get("source") or "pliego").strip()
                if source not in {"pliego", "admin"}:
                    source = "pliego"
                good_checklist.append(
                    {
                        "key": ckey,
                        "label": label[:300],
                        "description": desc[:500],
                        "status": status,
                        "source": source,
                    }
                )

        gaps_raw = draft.get("gaps")
        good_gaps: list[dict[str, Any]] = []
        if isinstance(gaps_raw, list):
            for g in gaps_raw:
                if not isinstance(g, dict):
                    continue
                code = str(g.get("code") or "").strip()[:80]
                desc = str(g.get("description") or "").strip()
                if not (code and desc):
                    continue
                sev = str(g.get("severity") or "important").strip()
                if sev not in {"blocking", "important", "info"}:
                    sev = "important"
                origin = str(g.get("origin") or "verdict_condition").strip()
                if origin not in {"verdict_condition", "pliego", "profile"}:
                    origin = "verdict_condition"
                good_gaps.append(
                    {
                        "code": code,
                        "description": desc[:800],
                        "severity": sev,
                        "origin": origin,
                    }
                )

        gaps_summary = draft.get("gaps_summary")
        if not isinstance(gaps_summary, list):
            gaps_summary = [g["description"] for g in good_gaps]
        else:
            gaps_summary = [str(x)[:500] for x in gaps_summary if str(x).strip()][:12]

        cleaned_draft: dict[str, Any] = {
            "banner": banner[:500],
            "human_gate": "draft_requires_human_edit",
            "statement": statement[:4000],
            "tender_ref": (
                str(draft["tender_ref"])[:200] if draft.get("tender_ref") else None
            ),
            "lot_hint": (
                str(draft["lot_hint"])[:200] if draft.get("lot_hint") else None
            ),
            "sections": good_sections,
            "administrative_checklist": good_checklist,
            "gaps_summary": gaps_summary,
            "gaps": good_gaps,
            "draft_engine": (
                str(draft["draft_engine"])[:80] if draft.get("draft_engine") else None
            ),
            "drafted_as_of": (
                str(draft["drafted_as_of"])[:40] if draft.get("drafted_as_of") else None
            ),
            "origin": "declared_draft",
            "based_on_verdict": (
                str(draft["based_on_verdict"])[:40]
                if draft.get("based_on_verdict")
                else None
            ),
            "official_evidence_ids": draft.get("official_evidence_ids")
            if isinstance(draft.get("official_evidence_ids"), list)
            else [],
            "declared_evidence_ids": draft.get("declared_evidence_ids")
            if isinstance(draft.get("declared_evidence_ids"), list)
            else [],
        }
        value["draft_offer"] = cleaned_draft
        return value


class RiskScores(StrictModel):
    impact: int = Field(ge=0, le=100)
    likelihood: int = Field(ge=0, le=100)
    velocity: int = Field(ge=0, le=100)
    exposure: int = Field(ge=0, le=100)
    uncertainty: int = Field(ge=0, le=100)
    controllability: int = Field(ge=0, le=100)
    overall: int = Field(ge=0, le=100)


class RiskScenario(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=4000)
    probability: int = Field(ge=0, le=100)
    impact: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class RiskMitigation(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    owner_role: str = Field(min_length=1, max_length=500)
    effectiveness: int = Field(ge=0, le=100)
    trigger: str = Field(min_length=1, max_length=1000)


class RiskAnalysisOutput(AgentOutput):
    title: str
    category: Literal[
        "regulatory",
        "commercial",
        "reputational",
        "operational",
        "territorial",
        "financial",
        "technical",
        "relationship",
        "security",
        "other",
    ] = "other"
    description: str = ""
    recommended_status: Literal["watch", "mitigate", "accept_candidate", "dismiss_candidate"]
    scores: RiskScores
    leading_indicators: list[str] = Field(default_factory=list)
    suggested_owner_role: str = ""
    suggested_review_date: JsonDate | None = None
    scenarios: list[RiskScenario] = Field(default_factory=list)
    mitigations: list[RiskMitigation] = Field(default_factory=list)


class ActorScores(StrictModel):
    influence: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    relationship_strength: int = Field(ge=0, le=100)
    accessibility: int = Field(ge=0, le=100)
    strategic_alignment: int = Field(ge=0, le=100)
    recent_activity: int = Field(ge=0, le=100)
    overall_priority: int = Field(ge=0, le=100)


class ActorRole(StrictModel):
    role: str = Field(min_length=1, max_length=500)
    basis: Literal["fact", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ActorRelationship(StrictModel):
    counterpart_actor_id: UUID | None = None
    counterpart_name: str = Field(min_length=1, max_length=500)
    relationship_type: str = Field(min_length=1, max_length=500)
    basis: Literal["fact", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class EngagementAction(StrictModel):
    action: str = Field(min_length=1, max_length=2000)
    channel: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)
    priority: Literal["low", "medium", "high", "critical"]


class ActorAnalysisOutput(AgentOutput):
    actor_id: UUID | None
    roles: list[ActorRole] = Field(default_factory=list)
    scores: ActorScores
    confirmed_relationships: list[str] = Field(default_factory=list)
    inferred_relationships: list[str] = Field(default_factory=list)
    observable_interests: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    relationships: list[ActorRelationship] = Field(default_factory=list)
    engagement_actions: list[EngagementAction] = Field(default_factory=list)


class BriefingQuestion(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=1000)
    priority: Literal["low", "medium", "high", "critical"]
    basis: Literal["fact", "hypothesis", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ExpectedObjection(StrictModel):
    objection: str = Field(min_length=1, max_length=2000)
    response: str = Field(min_length=1, max_length=2000)
    basis: Literal["fact", "hypothesis", "inference"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class MeetingBriefingOutput(AgentOutput):
    meeting_objective: str
    minimum_outcome: str
    ideal_outcome: str
    hypotheses_to_validate: list[str] = Field(default_factory=list)
    participant_context: list[str] = Field(default_factory=list)
    key_messages: list[str] = Field(default_factory=list)
    questions: list[BriefingQuestion] = Field(default_factory=list)
    expected_objections: list[ExpectedObjection] = Field(default_factory=list)
    do_not_disclose: list[str] = Field(default_factory=list)
    desired_close: str = ""
    follow_up_tasks: list[str] = Field(default_factory=list)


class ReportParagraph(StrictModel):
    text: str = Field(min_length=1, max_length=8000)
    kind: Literal["fact", "inference", "recommendation", "decision"]
    confidence: int = Field(ge=0, le=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class ReportSection(StrictModel):
    heading: str = Field(min_length=1, max_length=500)
    paragraphs: list[ReportParagraph]


class SourceIndexEntry(StrictModel):
    evidence_id: UUID
    label: str = Field(min_length=1, max_length=1000)
    locator: str = Field(min_length=1, max_length=2000)


class ReportOutput(AgentOutput):
    title: str
    executive_summary: str
    sections: list[ReportSection] = Field(default_factory=list)
    top_opportunities: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    decisions_required: list[str] = Field(default_factory=list)
    source_index: list[SourceIndexEntry] = Field(default_factory=list)


class MemoryChange(StrictModel):
    change: str = Field(min_length=1, max_length=4000)
    importance: Literal["low", "medium", "high", "critical"]
    evidence_ids: list[UUID] = Field(default_factory=list)


class MemoryItem(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    status: str = Field(min_length=1, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list)


class MemoryCuratorOutput(AgentOutput):
    living_summary: str
    what_changed: list[MemoryChange]
    current_objectives: list[MemoryItem] = Field(default_factory=list)
    active_hypotheses: list[MemoryItem] = Field(default_factory=list)
    supported_hypotheses: list[MemoryItem] = Field(default_factory=list)
    contradicted_hypotheses: list[MemoryItem] = Field(default_factory=list)
    human_decisions: list[MemoryItem] = Field(default_factory=list)
    next_milestones: list[MemoryItem] = Field(default_factory=list)


class ClaimIssue(StrictModel):
    path: str
    claim: str
    reason: str


class EvidenceReviewerOutput(AgentOutput):
    verdict: Literal["pass", "pass_with_warnings", "fail"]
    unsupported_claims: list[ClaimIssue]
    misused_evidence: list[ClaimIssue] = Field(default_factory=list)
    missing_evidence: list[ClaimIssue] = Field(default_factory=list)
    classification_errors: list[str] = Field(default_factory=list)
    privacy_or_security_issues: list[str] = Field(default_factory=list)
    prompt_injection_indicators: list[str] = Field(default_factory=list)
    confidence_issues: list[str] = Field(default_factory=list)
    required_corrections: list[str]


class WeeklyChange(StrictModel):
    area: str = Field(min_length=1, max_length=500)
    change: str = Field(min_length=1, max_length=4000)
    significance: Literal["low", "medium", "high", "critical"]
    previous_state: str = Field(min_length=1, max_length=2000)
    current_state: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(default_factory=list)


class WeeklyChangeOutput(AgentOutput):
    period_start: datetime
    period_end: datetime
    coverage_summary: str
    changes: list[WeeklyChange] = Field(default_factory=list)
    no_change_areas: list[str] = Field(default_factory=list)


class DossierSituationSummaryOutput(StrictModel):
    headline: str = Field(min_length=1, max_length=500)
    executive_summary: str = Field(min_length=1, max_length=8000)
    situation_status: Literal["stable", "advancing", "blocked", "deteriorating", "uncertain"]
    facts: list[SituationFact] = Field(default_factory=list)
    inferences: list[SituationInference] = Field(default_factory=list)
    material_changes: list[SituationChange] = Field(default_factory=list)
    opportunities: list[SituationOpportunity] = Field(default_factory=list)
    risks: list[SituationRisk] = Field(default_factory=list)
    relevant_actors: list[SituationActor] = Field(default_factory=list)
    deadlines_and_milestones: list[SituationMilestone] = Field(default_factory=list)
    decisions_required: list[SituationDecision] = Field(default_factory=list)
    recommended_actions: list[SituationAction] = Field(default_factory=list)
    knowledge_gaps: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: int = Field(ge=0, le=100)
    evidence_coverage: EvidenceCoverage
    warnings: list[str] = Field(default_factory=list)


class DossierWizardSectionDiagnostic(StrictModel):
    section: Literal[
        "goal",
        "signals",
        "procurement",
        "opportunities",
        "risks",
        "actors",
        "hypotheses",
        "other",
    ]
    status: Literal["ok", "incomplete", "empty"]
    explanation: str = Field(min_length=1, max_length=2000)


class DossierWizardQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_.:-]+$")
    question: str = Field(min_length=1, max_length=1000)
    why_it_matters: str = Field(min_length=1, max_length=2000)
    expected_input: str = Field(min_length=1, max_length=1000)


class DossierWizardPrefill(StrictModel):
    # create_signal_monitor
    name: str | None = Field(default=None, max_length=200)
    query: str | None = Field(default=None, max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=50)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=20)
    geographies: list[str] = Field(default_factory=list, max_length=50)
    cadence: str | None = Field(default=None, max_length=50)
    # pin_procurement
    procurement_query: str | None = Field(default=None, max_length=1000)
    procurement_kind: Literal["tender", "award"] | None = None
    # create_opportunity/create_risk/create_actor
    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=2000)
    mitigation: str | None = Field(default=None, max_length=2000)
    actor_type: Literal["person", "organization", "institution", "program", "other"] | None = None
    tags: list[str] = Field(default_factory=list, max_length=30)
    roles: list[str] = Field(default_factory=list, max_length=30)
    # generic guidance
    note: str | None = Field(default=None, max_length=2000)


class DossierWizardRecommendedAction(StrictModel):
    kind: Literal[
        "create_signal_monitor",
        "pin_procurement",
        "create_opportunity",
        "create_risk",
        "create_actor",
        "refine_goal",
        "other",
    ]
    title: str = Field(min_length=1, max_length=500)
    rationale: str = Field(min_length=1, max_length=2000)
    prefill: DossierWizardPrefill = Field(default_factory=DossierWizardPrefill)


class DossierCompletionWizardOutput(StrictModel):
    summary: str = Field(min_length=1, max_length=4000)
    confidence: int = Field(ge=0, le=100)
    warnings: list[str] = Field(default_factory=list)
    section_diagnostics: list[DossierWizardSectionDiagnostic] = Field(default_factory=list)
    questions: list[DossierWizardQuestion] = Field(default_factory=list)
    recommended_actions: list[DossierWizardRecommendedAction] = Field(default_factory=list)


class TenderSearchCandidateCPV(StrictModel):
    code: str = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=1000)


class TenderSearchWizardOutput(StrictModel):
    """Candidate search plan; Oracle post-validates its CPVs and search tokens."""

    intent_summary: str = Field(min_length=1, max_length=4000)
    include_terms: list[str] = Field(default_factory=list, max_length=50)
    synonyms: list[str] = Field(default_factory=list, max_length=50)
    exclude_terms: list[str] = Field(default_factory=list, max_length=50)
    candidate_cpv: list[TenderSearchCandidateCPV] = Field(default_factory=list, max_length=50)
    buyers: list[str] = Field(default_factory=list, max_length=30)
    geographies: list[str] = Field(default_factory=list, max_length=30)
    scope: Literal["active", "historical", "all"]
    min_amount: Decimal | None = Field(default=None, ge=0)
    max_amount: Decimal | None = Field(default=None, ge=0)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    questions: list[str] = Field(default_factory=list, max_length=20)
    confidence: int = Field(ge=0, le=100)
    discarded_count: int = Field(default=0, ge=0)
    discarded_reasons: dict[str, int] = Field(default_factory=dict)


class DossierQuestionCitation(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(default="", max_length=500)


class DossierQuestionClaim(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    confidence: int = Field(default=50, ge=0, le=100)


class DossierQuestionConflict(StrictModel):
    statement: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    confidence: int = Field(default=50, ge=0, le=100)


class DossierQuestionAnswerOutput(AgentOutput):
    """Respuesta a Preguntar a Oracle con citas acotadas a evidence_ids permitidos.

    Separa hechos (facts), claims, conflicts, unknowns (open_questions) y citations.
    Cada citation.evidence_id debe pertenecer a allowed_evidence_ids del input.
    """

    answer_text: str = Field(min_length=1, max_length=8000)
    citations: list[DossierQuestionCitation] = Field(default_factory=list, max_length=20)
    claims: list[DossierQuestionClaim] = Field(default_factory=list, max_length=10)
    conflicts: list[DossierQuestionConflict] = Field(default_factory=list, max_length=10)
    unknowns: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def _coerce_model_quirks(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "confidence" in payload:
            payload["confidence"] = _coerce_confidence_0_100(payload["confidence"])
        inferences = payload.get("inferences")
        if isinstance(inferences, list):
            fixed: list[Any] = []
            for item in inferences:
                if isinstance(item, dict) and "confidence" in item:
                    row = dict(item)
                    row["confidence"] = _coerce_confidence_0_100(row["confidence"])
                    fixed.append(row)
                else:
                    fixed.append(item)
            payload["inferences"] = fixed
        if "unknowns" not in payload and isinstance(payload.get("open_questions"), list):
            payload["unknowns"] = list(payload["open_questions"])
        for key in ("unknowns", "warnings", "open_questions"):
            if key in payload:
                payload[key] = _coerce_str_list(payload[key])
        return payload


class CustomBriefPlanSection(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    required: bool = True
    notes: str = Field(default="", max_length=500)


class ReportCustomBriefPlanOutput(StrictModel):
    """Plan revisable de Informe libre (no redacta el informe completo)."""

    version: Literal["custom_brief_plan.v1"] = "custom_brief_plan.v1"
    audience: str = Field(min_length=1, max_length=200)
    scope: str = Field(min_length=1, max_length=1000)
    period: str = Field(default="sin fijar", max_length=200)
    sections: list[CustomBriefPlanSection] = Field(min_length=1, max_length=12)
    formats: list[str] = Field(default_factory=lambda: ["html", "json"], max_length=5)
    notes: list[str] = Field(default_factory=list, max_length=10)
    confidence: int = Field(ge=0, le=100)
    open_questions: list[str] = Field(default_factory=list, max_length=10)
    warnings: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def _coerce_model_quirks(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "confidence" in payload:
            payload["confidence"] = _coerce_confidence_0_100(payload["confidence"])
        for key in ("notes", "open_questions", "warnings", "formats"):
            if key in payload:
                payload[key] = _coerce_str_list(payload[key])
        return payload


AGENT_SCHEMAS: dict[str, type[BaseModel]] = {
    "intake": IntakeOutput,
    "signal_triage": SignalTriageOutput,
    "entity_resolution": EntityResolutionOutput,
    "opportunity": OpportunityAnalysisOutput,
    "risk": RiskAnalysisOutput,
    "actor_partnership": ActorAnalysisOutput,
    "meeting_briefing": MeetingBriefingOutput,
    "report_writer": ReportOutput,
    "competitive_procurement_intelligence": ReportOutput,
    "entity_dossier_intelligence": ReportOutput,
    "memory_curator": MemoryCuratorOutput,
    "evidence_reviewer": EvidenceReviewerOutput,
    "weekly_change": WeeklyChangeOutput,
    "dossier_situation_summary": DossierSituationSummaryOutput,
    "dossier_completion_wizard": DossierCompletionWizardOutput,
    "tender_search_wizard": TenderSearchWizardOutput,
    "dossier_question_answer": DossierQuestionAnswerOutput,
    "report_custom_brief_plan": ReportCustomBriefPlanOutput,
}
