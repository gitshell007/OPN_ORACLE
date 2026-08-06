"""Transactional Oracle domain services."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opn_oracle.ai.models import AIArtifact, AIContextEvidence, AIHumanReview
from opn_oracle.oracle.actor_candidates import ACTOR_TYPES, clean_labels
from opn_oracle.oracle.actor_tax_id import (
    TaxIdConflictError,
    TaxIdValidationError,
    assign_actor_tax_id,
    hydrate_dossier_actor_tax_ids_from_awards,
    resolve_or_create_actor,
    usable_company_tax_id,
)
from opn_oracle.oracle.intent import (
    DossierIntentRevision,
    DossierOffering,
    IntelligenceRequirement,
    compute_intent_content_hash,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.links import (
    DossierCollaborator,
    MeetingActor,
    OpportunityActor,
    OpportunitySignal,
    RiskActor,
    RiskSignal,
)
from opn_oracle.oracle.models import (
    Actor,
    ActorTaxIdConflict,
    Decision,
    DossierActor,
    DossierObjective,
    DossierSignal,
    Hypothesis,
    Meeting,
    Opportunity,
    Relationship,
    RiskItem,
    ScoreHistory,
    Signal,
    StatusHistory,
    StrategicDossier,
    Task,
    Watchlist,
)
from opn_oracle.oracle.policy import (
    active_membership_exists,
    dossier_accessible,
    dossier_manageable,
    is_tenant_admin,
)
from opn_oracle.oracle.scoring import (
    ACTOR_PRIORITY_WEIGHTS,
    ALGORITHM_VERSION,
    OPPORTUNITY_WEIGHTS,
    RISK_WEIGHTS,
    SIGNAL_WEIGHTS,
    aggregate_dossier_scores,
    score_actor_priority,
    score_opportunity,
    score_risk,
    score_signal,
)
from opn_oracle.oracle.starter_profiles import (
    STARTER_PROFILE_VERSION,
    starter_profile_for,
)
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import Workspace
from opn_oracle.tenants.context import require_tenant_id

DOSSIER_TYPES = frozenset(
    {
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
    }
)
# ISO 3166-1 alpha-2 o ISO 3166-2 (subdivisión). Sin catálogo cerrado de estados
# ni de CCAA: el formato basta; mercados fuera de la UE y subdivisiones ES-* son válidos.
# La proyección hacia Signal aplana a país (ver geography_codes_for_signal).
_ISO_GEOGRAPHY = re.compile(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$")
DOSSIER_TRANSITIONS = {
    "draft": frozenset({"active", "archived"}),
    "active": frozenset({"paused", "archived"}),
    "paused": frozenset({"active", "archived"}),
    "archived": frozenset(),
}
OPPORTUNITY_TRANSITIONS = {
    "identified": frozenset({"qualified", "dismissed"}),
    "qualified": frozenset({"pursuing", "dismissed"}),
    "pursuing": frozenset({"won", "lost", "dismissed"}),
    "won": frozenset(),
    "lost": frozenset(),
    "dismissed": frozenset(),
}
RISK_TRANSITIONS = {
    "open": frozenset({"monitoring", "mitigated", "accepted", "closed"}),
    "monitoring": frozenset({"mitigated", "accepted", "closed"}),
    "mitigated": frozenset({"monitoring", "closed"}),
    "accepted": frozenset({"monitoring", "closed"}),
    "closed": frozenset(),
}


class DomainValidationError(ValueError):
    pass


class VersionConflict(RuntimeError):
    pass


class ResourceNotFound(LookupError):
    pass


# Re-export tax-id domain errors for routes/OpenAPI consumers.
__all_tax_id_errors__ = (TaxIdConflictError, TaxIdValidationError)


def _optional_date(value: Any, field: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise DomainValidationError(f"{field} debe ser una fecha ISO.") from error


def _bounded_text(payload: dict[str, Any], field: str, limit: int = 5000) -> str:
    return str(payload.get(field, "")).strip()[:limit]


def _override(payload: dict[str, Any], actor_id: uuid.UUID) -> tuple[int | None, str | None]:
    del actor_id  # Attribution is persisted by the caller; kept explicit in this boundary.
    if payload.get("score_override") is None:
        return None, None
    value = int(payload["score_override"])
    reason = str(payload.get("score_override_reason", "")).strip()
    if not reason:
        raise DomainValidationError("score_override_reason es obligatoria para un override.")
    if not 0 <= value <= 100:
        raise DomainValidationError("score_override debe estar entre 0 y 100.")
    return value, reason[:1000]


def _weights(config: dict[str, Any], key: str, defaults: dict[str, float]) -> dict[str, float]:
    configured = config.get(key, {})
    if not isinstance(configured, dict):
        raise DomainValidationError(f"{key} debe ser un objeto.")
    result = defaults | {
        name: float(value) for name, value in configured.items() if name in defaults
    }
    if any(abs(value) > 1 for value in result.values()):
        raise DomainValidationError("Los pesos deben estar entre -1 y 1.")
    return result


def _require_dossier_access(
    session: Session, dossier_id: uuid.UUID, actor_id: uuid.UUID, *, write: bool = True
) -> StrategicDossier:
    tenant_id = require_tenant_id()
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id, StrategicDossier.tenant_id == tenant_id
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, actor_id, write=write):
        raise ResourceNotFound("Expediente no encontrado.")
    return dossier


def _active_user(session: Session, tenant_id: uuid.UUID, value: Any, field: str) -> uuid.UUID:
    try:
        user_id = uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise DomainValidationError(f"{field} debe ser UUID.") from error
    if not active_membership_exists(session, tenant_id, user_id):
        raise DomainValidationError(f"{field} debe ser un miembro activo del tenant.")
    return user_id


def _profile_strings(value: Any, field: str, *, limit: int = 30) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise DomainValidationError(f"{field} debe ser una lista.")
    cleaned = [" ".join(str(item).strip().split())[:300] for item in value]
    return list(dict.fromkeys(item for item in cleaned if item))[:limit]


def _geography_codes(value: Any) -> list[str]:
    """Normaliza códigos de geografía a ISO 3166-1 alpha-2 o ISO 3166-2.

    Oracle conserva la subdivisión (p. ej. ES-VC). La proyección hacia Signal
    debe usar geography_codes_for_signal para enviar solo el país.
    """
    codes = [item.upper() for item in _profile_strings(value, "geography", limit=50)]
    invalid = sorted(code for code in codes if not _ISO_GEOGRAPHY.fullmatch(code))
    if invalid:
        raise DomainValidationError(
            "geography solo admite ISO 3166-1 alpha-2 o ISO 3166-2 "
            "(p. ej. ES, ES-VC, DE, US); no válidos: " + ", ".join(invalid)
        )
    return codes


def geography_codes_for_signal(codes: list[str] | None) -> list[str]:
    """Aplana ISO 3166-2 a país alpha-2 para monitores Signal (deduplicado, orden estable).

    Signal acepta cualquier string en geographies y no filtra web_search por él;
    aun así se proyecta solo el país para no enviar subdivisiones que el receptor
    no interpreta (procurement country_code es String(2); monitores no validan
    formato pero tampoco consumen subdivisiones).
    """
    countries: list[str] = []
    seen: set[str] = set()
    for raw in codes or []:
        code = str(raw).strip().upper()
        if not code:
            continue
        country = code.split("-", 1)[0]
        if len(country) != 2 or not country.isalpha():
            continue
        if country not in seen:
            seen.add(country)
            countries.append(country)
    return countries


def _language_codes(value: Any) -> list[str]:
    return [item.lower() for item in _profile_strings(value, "languages", limit=20)]


def _validated_competitors(raw_competitors: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_competitors, list):
        raise DomainValidationError("competitors debe ser una lista.")
    competitors: list[dict[str, Any]] = []
    for raw in raw_competitors[:20]:
        if not isinstance(raw, dict):
            raise DomainValidationError("Cada competidor debe ser un objeto.")
        name = " ".join(str(raw.get("name", "")).strip().split())[:300]
        if not name:
            continue
        website = str(raw.get("website", "")).strip()[:1500]
        if website and not website.startswith(("https://", "http://")):
            raise DomainValidationError("La web del competidor debe usar http o https.")
        competitors.append(
            {
                "name": name,
                "website": website,
                "aliases": _profile_strings(raw.get("aliases", []), "aliases"),
                "country": str(raw.get("country", "")).strip()[:120],
                "tax_id": str(raw.get("tax_id", "")).strip()[:120],
            }
        )
    return competitors


_COMPETITORS_KNOWLEDGE_VALUES = frozenset({"known", "unknown", "not_seeking"})

# Solvencia declarada por el cliente (G-08): no es evidencia oficial.
_PAST_SERVICES_MAX_LEN = 4000
_ANNUAL_TURNOVER_MAX = 1e15
_CLEAN_NUMERIC_RE = re.compile(r"^\d+(?:\.\d+)?$")


def _normalize_annual_turnover(raw: Any) -> int | float:
    """Validate client-declared annual turnover (EUR). Returns finite number ≥0.

    Rejects booleans, NaN/inf, negatives and ambiguous monetary strings.
    Empty/null is handled by the caller as clean absence (no key).
    """

    if isinstance(raw, bool) or raw is None:
        raise DomainValidationError(
            "annual_turnover debe ser un número ≥0 en EUR (declarado por el cliente); "
            "no se aceptan booleanos ni vacío ambiguo."
        )
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        # Exterior whitespace only; internal spaces are thousand separators → reject.
        cleaned = raw.strip()
        if not cleaned or re.search(r"\s", cleaned):
            raise DomainValidationError(
                "annual_turnover debe ser un número JSON válido ≥0 en EUR "
                "(sin símbolos de moneda ni formatos ambiguos)."
            )
        cleaned = cleaned.replace(",", ".")
        if not _CLEAN_NUMERIC_RE.fullmatch(cleaned):
            raise DomainValidationError(
                "annual_turnover debe ser un número JSON válido ≥0 en EUR "
                "(sin símbolos de moneda ni formatos ambiguos)."
            )
        value = float(cleaned)
    else:
        raise DomainValidationError(
            "annual_turnover debe ser un número ≥0 en EUR (declarado por el cliente)."
        )
    if not math.isfinite(value) or value < 0 or value > _ANNUAL_TURNOVER_MAX:
        raise DomainValidationError(
            "annual_turnover debe ser un número finito ≥0 en EUR "
            "(sin NaN, infinito ni valores negativos)."
        )
    # Normalización estable: enteros exactos como int, resto float.
    if value == int(value) and abs(value) < 10**15:
        return int(value)
    return value


def _normalize_past_services(raw: Any) -> str:
    """Validate optional past_services text. Empty → raise (caller treats absence)."""

    if isinstance(raw, bool) or raw is None:
        raise DomainValidationError(
            "past_services debe ser texto (servicios similares de los últimos 3 años); "
            "no se aceptan booleanos."
        )
    if not isinstance(raw, str):
        raise DomainValidationError(
            "past_services debe ser texto con la descripción de servicios similares "
            "y su acreditación (declarado por el cliente)."
        )
    text = " ".join(raw.split()).strip()
    if not text:
        raise DomainValidationError("past_services vacío se omite; no envíes cadena fantasma.")
    if len(text) > _PAST_SERVICES_MAX_LEN:
        raise DomainValidationError(
            f"past_services supera el límite de {_PAST_SERVICES_MAX_LEN} caracteres."
        )
    return text


def _validated_declared_solvency(value: dict[str, Any]) -> dict[str, Any]:
    """Optional annual_turnover / past_services shared by market, CI and custom.

    Empty / null / whitespace → clean absence (key omitted). Never stores 0, NaN
    or ghost strings for empty inputs; 0 is a valid explicit volume only when
    provided as a number.
    """

    out: dict[str, Any] = {}
    if "annual_turnover" in value:
        raw = value.get("annual_turnover")
        if raw is not None and raw != "":
            if isinstance(raw, str) and not raw.strip():
                pass  # absence limpia
            else:
                out["annual_turnover"] = _normalize_annual_turnover(raw)
    if "past_services" in value:
        raw = value.get("past_services")
        if raw is not None and raw != "":
            if isinstance(raw, str) and not raw.strip():
                pass  # absence limpia
            else:
                out["past_services"] = _normalize_past_services(raw)
    return out


def _validated_competitors_knowledge(
    value: dict[str, Any], *, competitors: list[dict[str, Any]]
) -> str:
    """Normalize honest intent about competitors for market intake.

    ``known`` requires at least one named competitor (exclusion list for discovery).
    ``unknown`` / ``not_seeking`` allow an empty list so the user is not forced to lie.
    Legacy payloads with names but no field default to ``known``; empty list without
    field remains invalid (must declare intent explicitly).
    """

    raw = str(value.get("competitors_knowledge", "")).strip().lower()
    if raw in _COMPETITORS_KNOWLEDGE_VALUES:
        knowledge = raw
    elif competitors:
        knowledge = "known"
    else:
        raise DomainValidationError(
            "Indica si conoces competidores (known), aún no lo sabes (unknown) o no los "
            "buscas (not_seeking)."
        )
    if knowledge == "known" and not competitors:
        raise DomainValidationError(
            "Si conoces competidores, añade al menos un nombre; si no, elige "
            "«unknown» o «not_seeking»."
        )
    if knowledge != "known":
        # Honest exit: never store invented exclusion names.
        return knowledge
    return knowledge


_DISCOVERY_ACTOR_TYPES = frozenset(
    {
        "company",
        "research_group",
        "technology_center",
        "regulator",
        "potential_customer",
    }
)
_DISCOVERY_INTENT_MIN = 10
_DISCOVERY_INTENT_MAX = 2000


def _validated_market_discovery_intent(
    value: dict[str, Any],
) -> tuple[str, str | None, list[str]]:
    """Optional free-text actor discovery intent (G-19).

    Stored separately from title/goal/description. Empty/whitespace is omitted
    (not inventing intent). When present, length and actor_type are validated.
    ``discovery_known_names`` are exclusions only for that objective.
    """

    raw_intent = value.get("discovery_intent")
    if raw_intent is None or (isinstance(raw_intent, str) and not str(raw_intent).strip()):
        # Optional: competitor-only market create remains valid without intent.
        # Without intent, do not keep discovery_known_names (not exclusions for actor search).
        return "", None, []

    intent = " ".join(str(raw_intent).split())
    if len(intent) < _DISCOVERY_INTENT_MIN or len(intent) > _DISCOVERY_INTENT_MAX:
        raise DomainValidationError(
            f"discovery_intent debe tener entre {_DISCOVERY_INTENT_MIN} y "
            f"{_DISCOVERY_INTENT_MAX} caracteres."
        )
    actor_type = (
        str(value.get("discovery_actor_type") or value.get("actor_type") or "").strip().lower()
    )
    if actor_type not in _DISCOVERY_ACTOR_TYPES:
        raise DomainValidationError(
            "Con discovery_intent debes indicar discovery_actor_type "
            "(company, research_group, technology_center, regulator o potential_customer)."
        )
    known_names = _profile_strings(
        value.get("discovery_known_names", []), "discovery_known_names", limit=50
    )
    return intent, actor_type, known_names


def _validated_market_profile(value: dict[str, Any]) -> dict[str, Any]:
    own_offer = " ".join(str(value.get("own_offer", "")).strip().split())[:500]
    decision_to_make = str(value.get("decision_to_make", "")).strip()[:2000]
    competitors = _validated_competitors(value.get("competitors", []))
    if not own_offer or not decision_to_make:
        raise DomainValidationError(
            "El expediente de mercado exige oferta propia y decisión a tomar."
        )
    knowledge = _validated_competitors_knowledge(value, competitors=competitors)
    if knowledge != "known":
        competitors = []
    discovery_intent, discovery_actor_type, discovery_known_names = (
        _validated_market_discovery_intent(value)
    )
    profile = {
        "version": "market.v1",
        "own_offer": own_offer,
        "decision_to_make": decision_to_make,
        "horizon": str(value.get("horizon", "")).strip()[:300],
        "segments": _profile_strings(value.get("segments", []), "segments"),
        "channels": _profile_strings(value.get("channels", []), "channels"),
        "target_buyers": _profile_strings(value.get("target_buyers", []), "target_buyers"),
        "competitors": competitors,
        "competitors_knowledge": knowledge,
        # G-19: free-text intent + target actor type (never title/goal concat).
        "discovery_intent": discovery_intent,
        "discovery_actor_type": discovery_actor_type,
        "discovery_known_names": discovery_known_names,
        "partners": _profile_strings(value.get("partners", []), "partners"),
        "regulators": _profile_strings(value.get("regulators", []), "regulators"),
        "barriers": _profile_strings(value.get("barriers", []), "barriers"),
        "success_indicators": _profile_strings(
            value.get("success_indicators", []), "success_indicators"
        ),
        "keywords": _profile_strings(value.get("keywords", []), "keywords", limit=60),
    }
    profile.update(_validated_declared_solvency(value))
    return profile


def _validated_profile(value: Any, dossier_type: str) -> dict[str, Any]:
    if value in (None, {}):
        if dossier_type == "competitive_intelligence":
            raise DomainValidationError("Completa el perfil de inteligencia competitiva.")
        return {}
    if not isinstance(value, dict):
        raise DomainValidationError("profile_config debe ser un objeto.")
    if dossier_type == "market":
        return _validated_market_profile(value)
    if dossier_type != "competitive_intelligence":
        # custom / opportunity / project / …: free-form JSONB + common solvency validation.
        cleaned = dict(value)
        cleaned.pop("annual_turnover", None)
        cleaned.pop("past_services", None)
        cleaned.update(_validated_declared_solvency(value))
        return cleaned
    own_offer = " ".join(str(value.get("own_offer", "")).strip().split())[:500]
    business_objective = str(value.get("business_objective", "")).strip()[:3000]
    raw_competitors = value.get("competitors", [])
    if not own_offer or not business_objective or not isinstance(raw_competitors, list):
        raise DomainValidationError(
            "La inteligencia competitiva exige oferta propia, objetivo y competidores."
        )
    competitors = _validated_competitors(raw_competitors)
    if not competitors:
        raise DomainValidationError("Añade al menos un competidor.")
    profile = {
        "version": "competitive-intelligence.v1",
        "own_offer": own_offer,
        "competitors": competitors,
        "segments": _profile_strings(value.get("segments", []), "segments"),
        "geographies": _profile_strings(value.get("geographies", []), "geographies"),
        "target_buyers": _profile_strings(value.get("target_buyers", []), "target_buyers"),
        "horizon": str(value.get("horizon", "")).strip()[:300],
        "business_objective": business_objective,
        "keywords": _profile_strings(value.get("keywords", []), "keywords", limit=60),
        "cpv": _profile_strings(value.get("cpv", []), "cpv", limit=60),
        "sources": _profile_strings(value.get("sources", []), "sources"),
        "participation_criteria": str(value.get("participation_criteria", "")).strip()[:5000],
        "exclusion_criteria": str(value.get("exclusion_criteria", "")).strip()[:5000],
        "success_indicators": _profile_strings(
            value.get("success_indicators", []), "success_indicators"
        ),
    }
    profile.update(_validated_declared_solvency(value))
    return profile


def create_dossier(
    session: Session, payload: dict[str, Any], *, actor_id: uuid.UUID
) -> StrategicDossier:
    tenant_id = require_tenant_id()
    workspace_value = payload.get("workspace_id")
    if workspace_value is None:
        workspace = session.scalar(
            select(Workspace)
            .where(
                Workspace.tenant_id == tenant_id,
                Workspace.status == "active",
                Workspace.is_default.is_(True),
            )
            .limit(1)
        )
    else:
        try:
            workspace_id = uuid.UUID(str(workspace_value))
        except ValueError as error:
            raise DomainValidationError("workspace_id debe ser UUID.") from error
        workspace = session.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.tenant_id == tenant_id,
                Workspace.status == "active",
            )
        )
    if workspace is None:
        raise ResourceNotFound("No existe un workspace activo disponible.")
    title = str(payload.get("title", "")).strip()
    dossier_type = str(payload.get("type", "custom"))
    if not title or len(title) > 240 or dossier_type not in DOSSIER_TYPES:
        raise DomainValidationError("Título o tipo de expediente no válido.")
    requested_owner = payload.get("owner_user_id", actor_id)
    owner_id = _active_user(session, tenant_id, requested_owner, "owner_user_id")
    if owner_id != actor_id and not is_tenant_admin(session, tenant_id, actor_id):
        raise ResourceNotFound("No puedes asignar otro propietario.")
    scoring_config = payload.get("scoring_config", {})
    if not isinstance(scoring_config, dict):
        raise DomainValidationError("scoring_config debe ser un objeto.")
    create_starter_profile = payload.get("create_starter_profile", False)
    if not isinstance(create_starter_profile, bool):
        raise DomainValidationError("create_starter_profile debe ser booleano.")
    accept_creation_intent = payload.get("accept_creation_intent", False)
    if not isinstance(accept_creation_intent, bool):
        raise DomainValidationError("accept_creation_intent debe ser booleano.")
    initial_status = str(payload.get("initial_status", "draft"))
    if initial_status not in {"draft", "active"}:
        raise DomainValidationError("initial_status solo admite draft o active.")
    profile_config = _validated_profile(payload.get("profile_config", {}), dossier_type)
    _weights(scoring_config, "opportunity_weights", OPPORTUNITY_WEIGHTS)
    _weights(scoring_config, "risk_weights", RISK_WEIGHTS)
    _weights(scoring_config, "signal_weights", SIGNAL_WEIGHTS)
    _weights(scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS)
    dossier = StrategicDossier(
        tenant_id=tenant_id,
        workspace_id=workspace.id,
        title=title,
        description=str(payload.get("description", ""))[:10000],
        dossier_type=dossier_type,
        status=initial_status,
        strategic_goal=str(payload.get("strategic_goal", ""))[:5000],
        geography=_geography_codes(payload.get("geography", [])),
        sectors=_profile_strings(payload.get("sectors", []), "sectors"),
        languages=_language_codes(payload.get("languages", [])),
        owner_user_id=owner_id,
        scoring_config=scoring_config,
        profile_config=profile_config,
    )
    session.add(dossier)
    session.flush()
    if create_starter_profile:
        _apply_starter_profile(session, dossier)
        if dossier_type == "competitive_intelligence":
            _apply_competitive_profile(session, dossier, actor_id=actor_id)
        elif dossier_type == "market" and profile_config:
            _apply_market_profile(session, dossier, actor_id=actor_id)
    if accept_creation_intent:
        _apply_human_reviewed_creation_intent(session, dossier, actor_id=actor_id)
    collaborators = payload.get("collaborator_user_ids", [])
    if not isinstance(collaborators, list):
        raise DomainValidationError("collaborator_user_ids debe ser una lista.")
    for value in dict.fromkeys(collaborators):
        collaborator_id = _active_user(session, tenant_id, value, "collaborator_user_ids")
        if collaborator_id != owner_id:
            session.add(
                DossierCollaborator(
                    tenant_id=tenant_id,
                    dossier_id=dossier.id,
                    user_id=collaborator_id,
                    role="collaborator",
                )
            )
    append_audit_event(
        session,
        action="dossier.created",
        resource_type="strategic_dossier",
        resource_id=dossier.id,
        dossier_id=dossier.id,
        result="success",
        metadata={
            "initial_status": initial_status,
            "profile_version": profile_config.get("version") if profile_config else None,
        },
    )
    # Column defaults are 0/0/0; without a refresh an empty dossier reads as
    # health=0 (worst) instead of the neutral aggregate (health=50).
    _refresh_dossier_aggregates(session, dossier.id)
    session.commit()
    return dossier


def _apply_human_reviewed_creation_intent(
    session: Session,
    dossier: StrategicDossier,
    *,
    actor_id: uuid.UUID,
) -> None:
    """Persist the dossier creation form as accepted, versioned intake memory.

    Clicking ``Crear expediente`` is the human acceptance boundary: this is not an
    LLM proposal and it never activates a monitor.  The accepted revision, bounded
    intelligence need and own offering are created in the dossier transaction so a
    newly-created dossier can immediately rehydrate the same context in Ask/Brief.
    """

    schema_key_by_type = {
        "market": "market",
        "competitive_intelligence": "competitive-intelligence",
        "tender_or_grant": "procurement",
        "risk_watch": "research",
        "technology": "research",
    }
    requirement_class_by_type = {
        "market": "market_scan",
        "competitive_intelligence": "competitive_watch",
        "tender_or_grant": "procurement_fit",
        "risk_watch": "risk_watch",
        "technology": "research_question",
    }
    schema_key = schema_key_by_type.get(dossier.dossier_type, "custom")
    requirement_class = requirement_class_by_type.get(dossier.dossier_type, "custom")
    request_text = (
        "\n\n".join(
            part
            for part in (
                f"Objetivo: {dossier.strategic_goal.strip()}"
                if dossier.strategic_goal.strip()
                else "",
                f"Contexto: {dossier.description.strip()}" if dossier.description.strip() else "",
            )
            if part
        )
        or f"Expediente: {dossier.title}"
    )
    structured_spec = {
        "origin": "human_reviewed_creation_form",
        "dossier_type": dossier.dossier_type,
        "title": dossier.title,
        "strategic_goal": dossier.strategic_goal,
        "geography": list(dossier.geography or []),
        "sectors": list(dossier.sectors or []),
        "languages": list(dossier.languages or []),
        "profile": dict(dossier.profile_config or {}),
    }
    content_hash = compute_intent_content_hash(
        schema_key=schema_key,
        schema_version="v1",
        request_text=request_text,
        structured_spec=structured_spec,
    )
    now = datetime.now(UTC)
    revision = DossierIntentRevision(
        tenant_id=dossier.tenant_id,
        dossier_id=dossier.id,
        version=1,
        schema_key=schema_key,
        schema_version="v1",
        request_text=request_text,
        structured_spec=structured_spec,
        status="accepted",
        content_hash=content_hash,
        source_refs=[
            {
                "kind": "dossier_creation",
                "ref": "human-reviewed-form",
                "label": "Formulario revisado por el usuario",
            }
        ],
        proposed_by_user_id=actor_id,
        accepted_by_user_id=actor_id,
        accepted_at=now,
        row_version=1,
    )
    session.add(revision)
    session.flush()
    dossier.current_intent_revision_id = revision.id
    requirement = IntelligenceRequirement(
        tenant_id=dossier.tenant_id,
        dossier_id=dossier.id,
        intent_revision_id=revision.id,
        requirement_class=requirement_class,
        priority="high",
        question=(dossier.strategic_goal.strip() or f"¿Qué debemos conocer sobre {dossier.title}?")[
            :2000
        ],
        decision_to_support=str((dossier.profile_config or {}).get("decision_to_make", ""))[:2000],
        scope={
            "geography": list(dossier.geography or []),
            "sectors": list(dossier.sectors or []),
        },
        exclusions={},
        success_criteria=list((dossier.profile_config or {}).get("success_indicators", []))[:20],
        status="active",
        alignment_state="aligned",
    )
    session.add(requirement)
    own_offer = str((dossier.profile_config or {}).get("own_offer", "")).strip()
    if own_offer:
        session.add(
            DossierOffering(
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                intent_revision_id=revision.id,
                name=own_offer[:300],
                aliases=[],
                taxonomies={"sectors": list(dossier.sectors or [])},
                description=own_offer[:5000],
                status="active",
            )
        )
    append_audit_event(
        session,
        action="intent.accepted_at_creation",
        resource_type="dossier_intent_revision",
        resource_id=revision.id,
        dossier_id=dossier.id,
        result="success",
        metadata={
            "version": revision.version,
            "schema_key": schema_key,
            "content_hash": content_hash,
            "human_reviewed": True,
            "monitors_created": False,
        },
    )


def _apply_starter_profile(session: Session, dossier: StrategicDossier) -> None:
    """Add the explicitly requested editable starting context in this transaction."""

    profile = starter_profile_for(dossier.dossier_type)
    objective_description = (
        f"{profile.objective_focus}\n\nObjetivo declarado: {dossier.strategic_goal}"
    )
    session.add(
        DossierObjective(
            tenant_id=dossier.tenant_id,
            dossier_id=dossier.id,
            title=profile.objective_title,
            description=objective_description,
            priority="high",
            position=0,
        )
    )
    for position, (statement, rationale) in enumerate(profile.hypotheses):
        session.add(
            Hypothesis(
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                statement=statement,
                rationale=rationale,
                confidence=50,
                position=position,
            )
        )
    session.add(
        Watchlist(
            tenant_id=dossier.tenant_id,
            dossier_id=dossier.id,
            name="Vigilancia inicial",
            query_config={
                "profile_version": STARTER_PROFILE_VERSION,
                "dossier_type": dossier.dossier_type,
                "keywords": [dossier.title],
                "source_types": list(profile.source_types),
                "requires_review": True,
            },
            cadence="daily",
        )
    )


def _ensure_dossier_actor(
    session: Session,
    dossier: StrategicDossier,
    name: str,
    *,
    roles: list[str],
    provenance_source: str,
    actor_type: str = "organization",
    aliases: list[str] | None = None,
    identifiers: dict[str, Any] | None = None,
    actor_metadata: dict[str, Any] | None = None,
) -> None:
    canonical_name = " ".join(str(name).strip().split())
    if not canonical_name:
        return
    # G-16: tax_id governs durable identity when present; name is fallback.
    actor = resolve_or_create_actor(
        session,
        tenant_id=dossier.tenant_id,
        canonical_name=canonical_name,
        actor_type=actor_type,
        aliases=list(aliases or []),
        identifiers=dict(identifiers or {}),
        actor_metadata=dict(actor_metadata or {}),
        provenance={"source": provenance_source, "verified": False},
    )
    link = session.scalar(
        select(DossierActor).where(
            DossierActor.tenant_id == dossier.tenant_id,
            DossierActor.dossier_id == dossier.id,
            DossierActor.actor_id == actor.id,
        )
    )
    if link is not None:
        merged_roles = list(dict.fromkeys([*link.roles, *roles]))
        if merged_roles != list(link.roles):
            link.roles = merged_roles
        hydrate_dossier_actor_tax_ids_from_awards(
            session,
            tenant_id=dossier.tenant_id,
            dossier_id=dossier.id,
            actor_ids={actor.id},
        )
        return
    components = {
        "influence": 0,
        "relevance_to_dossier": 70,
        "relationship_strength": 0,
        "accessibility": 0,
        "strategic_alignment": 0,
        "recent_activity": 0,
    }
    score = score_actor_priority(
        components,
        weights=_weights(dossier.scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS),
    )
    session.add(
        DossierActor(
            tenant_id=dossier.tenant_id,
            dossier_id=dossier.id,
            actor_id=actor.id,
            roles=list(roles),
            notes=(
                "Alta guiada: identidad, capacidades y relaciones pendientes de "
                "contraste con evidencias."
            ),
            priority=score.score,
            score_details=score.as_dict(),
            **components,
        )
    )
    session.flush()
    # Actor nuevo/enlazado: si ya hay awards fijados con NIF, hidratar de inmediato.
    hydrate_dossier_actor_tax_ids_from_awards(
        session,
        tenant_id=dossier.tenant_id,
        dossier_id=dossier.id,
        actor_ids={actor.id},
    )


def _apply_competitive_profile(
    session: Session, dossier: StrategicDossier, *, actor_id: uuid.UUID
) -> None:
    """Create specific editable work without claiming unverified confidence."""

    profile = dossier.profile_config
    for competitor in profile.get("competitors", []):
        _ensure_dossier_actor(
            session,
            dossier,
            competitor["name"],
            roles=["competidor"],
            provenance_source="competitive_intelligence_intake",
            aliases=competitor.get("aliases", []),
            identifiers={"tax_id": competitor["tax_id"]} if competitor.get("tax_id") else {},
            actor_metadata={
                "website": competitor.get("website", ""),
                "country": competitor.get("country", ""),
                "competitive_profile": {
                    "confidence": None,
                    "confidence_basis": "Sin evidencias vinculadas",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            },
        )
    watchlist = session.scalar(
        select(Watchlist).where(
            Watchlist.tenant_id == dossier.tenant_id,
            Watchlist.dossier_id == dossier.id,
            Watchlist.name == "Vigilancia inicial",
        )
    )
    if watchlist is not None:
        watchlist.query_config = {
            **watchlist.query_config,
            "keywords": profile["keywords"],
            "cpv": profile["cpv"],
            "competitors": [item["name"] for item in profile["competitors"]],
            "aliases": [alias for item in profile["competitors"] for alias in item["aliases"]],
            "geographies": profile["geographies"],
            "buyers": profile["target_buyers"],
            "sources": profile["sources"],
        }
    for position, title in enumerate(
        (
            "Resolver variantes registrales de los competidores",
            "Revisar adjudicaciones y licitaciones del alcance definido",
            "Validar capacidades y diferenciadores con evidencia",
        )
    ):
        session.add(
            Task(
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                title=title,
                status="open",
                owner_user_id=actor_id,
                priority="high" if position == 0 else "medium",
                origin="starter_profile",
                content={"profile_version": profile["version"]},
            )
        )


def _apply_market_profile(
    session: Session, dossier: StrategicDossier, *, actor_id: uuid.UUID
) -> None:
    """Materialise the market intake as editable context without unverified claims."""

    profile = dossier.profile_config
    for competitor in profile.get("competitors", []):
        _ensure_dossier_actor(
            session,
            dossier,
            competitor["name"],
            roles=["competidor"],
            provenance_source="market_intake",
            aliases=competitor.get("aliases", []),
            identifiers={"tax_id": competitor["tax_id"]} if competitor.get("tax_id") else {},
            actor_metadata={
                "website": competitor.get("website", ""),
                "country": competitor.get("country", ""),
            },
        )
    for partner in profile.get("partners", []):
        _ensure_dossier_actor(
            session, dossier, partner, roles=["partner"], provenance_source="market_intake"
        )
    for regulator in profile.get("regulators", []):
        _ensure_dossier_actor(
            session,
            dossier,
            regulator,
            roles=["regulador"],
            provenance_source="market_intake",
            actor_type="institution",
        )
    watchlist = session.scalar(
        select(Watchlist).where(
            Watchlist.tenant_id == dossier.tenant_id,
            Watchlist.dossier_id == dossier.id,
            Watchlist.name == "Vigilancia inicial",
        )
    )
    if watchlist is not None:
        # Claves alineadas con el MonitorSpec de Signal Avanza para que el borrador
        # sea convertible en monitor sin re-mapear nombres.
        entity_names = list(
            dict.fromkeys(
                [item["name"] for item in profile.get("competitors", [])]
                + profile.get("partners", [])
                + profile.get("regulators", [])
            )
        )[:50]
        keywords = list(
            dict.fromkeys(
                profile.get("keywords", [])
                + profile.get("segments", [])
                + profile.get("channels", [])
            )
        )[:50]
        watchlist.query_config = {
            **watchlist.query_config,
            "query": "",
            "keywords": keywords or list(watchlist.query_config.get("keywords", [])),
            "entities": [{"type": "company", "name": name} for name in entity_names],
            "languages": [str(item).lower() for item in dossier.languages],
            # Subdivisiones ISO 3166-2 se conservan en dossier.geography; Signal recibe país.
            "geographies": geography_codes_for_signal(list(dossier.geography or [])),
            "cadence": "daily",
        }
    rationale_parts = []
    if profile.get("horizon"):
        rationale_parts.append(f"Horizonte: {profile['horizon']}.")
    if profile.get("own_offer"):
        rationale_parts.append(f"Oferta propia: {profile['own_offer']}.")
    session.add(
        Decision(
            tenant_id=dossier.tenant_id,
            dossier_id=dossier.id,
            title=profile["decision_to_make"][:300],
            status="proposed",
            rationale=" ".join(rationale_parts),
            content={"profile_version": profile["version"], "origin": "market_intake"},
        )
    )
    for barrier in profile.get("barriers", [])[:10]:
        session.add(
            RiskItem(
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                category="barrier",
                status="open",
                title=barrier[:300],
                description=(
                    "Barrera declarada en el intake de mercado; pendiente de contraste "
                    "con evidencia."
                ),
            )
        )
    for position, title in enumerate(
        (
            "Validar tamaño y evolución del mercado con evidencia",
            "Contrastar barreras regulatorias y de entrada",
            "Revisar y activar la vigilancia del radar de mercado",
        )
    ):
        session.add(
            Task(
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                title=title,
                status="open",
                owner_user_id=actor_id,
                priority="high" if position == 0 else "medium",
                origin="starter_profile",
                content={"profile_version": profile["version"]},
            )
        )


def update_dossier(
    session: Session,
    dossier_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    expected_version: int,
    actor_id: uuid.UUID,
    commit: bool = True,
) -> StrategicDossier:
    tenant_id = require_tenant_id()
    dossier = _require_dossier_access(session, dossier_id, actor_id)
    locked_dossier = session.scalar(
        select(StrategicDossier).where(StrategicDossier.id == dossier.id).with_for_update()
    )
    assert locked_dossier is not None
    dossier = locked_dossier
    if dossier.version != expected_version:
        raise VersionConflict("El expediente fue modificado por otro usuario.")
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    if "status" in payload:
        previous_status = dossier.status
        target = str(payload["status"])
        if target not in DOSSIER_TRANSITIONS[dossier.status]:
            raise DomainValidationError("Transición de estado no válida.")
        dossier.status = target
        _record_status(
            session,
            dossier,
            dossier.id,
            "dossier",
            previous_status,
            target,
            actor_id,
            str(payload.get("status_reason", "")),
        )
    for field, limit in (("title", 240), ("description", 10000), ("strategic_goal", 5000)):
        if field in payload:
            value = str(payload[field]).strip()[:limit]
            if field == "title" and not value:
                raise DomainValidationError("El título no puede estar vacío.")
            setattr(dossier, field, value)
    if "owner_user_id" in payload:
        if not dossier_manageable(session, dossier, actor_id):
            raise ResourceNotFound("Expediente no encontrado.")
        dossier.owner_user_id = _active_user(
            session, tenant_id, payload["owner_user_id"], "owner_user_id"
        )
    if "scoring_config" in payload:
        scoring_config = payload["scoring_config"]
        if not isinstance(scoring_config, dict):
            raise DomainValidationError("scoring_config debe ser un objeto.")
        _weights(scoring_config, "opportunity_weights", OPPORTUNITY_WEIGHTS)
        _weights(scoring_config, "risk_weights", RISK_WEIGHTS)
        _weights(scoring_config, "signal_weights", SIGNAL_WEIGHTS)
        _weights(scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS)
        dossier.scoring_config = scoring_config
    if "profile_config" in payload:
        dossier.profile_config = _validated_profile(payload["profile_config"], dossier.dossier_type)
    if "sectors" in payload:
        dossier.sectors = _profile_strings(payload["sectors"], "sectors")
    if "geography" in payload:
        dossier.geography = _geography_codes(payload["geography"])
    if "languages" in payload:
        dossier.languages = _language_codes(payload["languages"])
    dossier.version += 1
    append_audit_event(
        session,
        action="dossier.updated",
        resource_type="strategic_dossier",
        resource_id=dossier.id,
        dossier_id=dossier.id,
        result="success",
        metadata={"version": dossier.version},
    )
    if commit:
        session.commit()
    return dossier


def archive_dossier(
    session: Session, dossier_id: uuid.UUID, *, actor_id: uuid.UUID, expected_version: int
) -> StrategicDossier:
    dossier = update_dossier(
        session,
        dossier_id,
        {"status": "archived"},
        expected_version=expected_version,
        actor_id=actor_id,
        commit=False,
    )
    dossier.archived_at = datetime.now(UTC)
    dossier.archived_by_user_id = actor_id
    session.commit()
    return dossier


def delete_dossiers(
    session: Session, dossier_ids: list[uuid.UUID], *, actor_id: uuid.UUID
) -> list[uuid.UUID]:
    """Permanently remove a bounded, fully authorized set of dossiers.

    Most dependent records cascade from ``strategic_dossiers``. Two AI graphs use
    RESTRICT and must be cleared first: context evidence anchored on
    ``evidence_dossiers``, and human reviews that pin AI artifacts.
    Audit events deliberately remain: their dossier reference is set to null by
    the foreign-key policy, while resource id and metadata preserve the trail.
    """

    tenant_id = require_tenant_id()
    unique_ids = list(dict.fromkeys(dossier_ids))
    if not unique_ids or len(unique_ids) > 100:
        raise DomainValidationError("Selecciona entre uno y cien expedientes para eliminar.")
    dossiers = list(
        session.scalars(
            select(StrategicDossier)
            .where(
                StrategicDossier.tenant_id == tenant_id,
                StrategicDossier.id.in_(unique_ids),
            )
            .order_by(StrategicDossier.id)
            .with_for_update()
        )
    )
    if len(dossiers) != len(unique_ids) or any(
        not dossier_manageable(session, dossier, actor_id) for dossier in dossiers
    ):
        # Keep unavailable resources indistinguishable from missing ones and avoid
        # a partial deletion if the selection changed between listing and submission.
        raise ResourceNotFound("Uno o varios expedientes ya no están disponibles.")

    # RESTRICT on evidence_dossiers blocks the cascade when AI context still points
    # at those join rows; clear them before deleting the dossiers.
    session.execute(
        delete(AIContextEvidence).where(
            AIContextEvidence.tenant_id == tenant_id,
            AIContextEvidence.dossier_id.in_(unique_ids),
        )
    )
    artifact_ids = list(
        session.scalars(
            select(AIArtifact.id).where(
                AIArtifact.tenant_id == tenant_id,
                AIArtifact.dossier_id.in_(unique_ids),
            )
        )
    )
    if artifact_ids:
        session.execute(
            delete(AIHumanReview).where(
                AIHumanReview.tenant_id == tenant_id,
                AIHumanReview.artifact_id.in_(artifact_ids),
            )
        )

    deleted_ids: list[uuid.UUID] = []
    for dossier in dossiers:
        append_audit_event(
            session,
            action="dossier.deleted",
            resource_type="strategic_dossier",
            resource_id=dossier.id,
            dossier_id=dossier.id,
            result="success",
            metadata={
                "deleted_dossier_id": str(dossier.id),
                "title": dossier.title,
                "dossier_type": dossier.dossier_type,
            },
        )
        deleted_ids.append(dossier.id)
        session.delete(dossier)
    session.commit()
    return deleted_ids


def review_signal_link(
    session: Session, link_id: uuid.UUID, payload: dict[str, Any], *, actor_id: uuid.UUID
) -> DossierSignal:
    tenant_id = require_tenant_id()
    link = session.scalar(
        select(DossierSignal)
        .where(DossierSignal.id == link_id, DossierSignal.tenant_id == tenant_id)
        .with_for_update()
    )
    if link is None:
        raise ResourceNotFound("Señal no encontrada.")
    _require_dossier_access(session, link.dossier_id, actor_id)
    dossier = session.get(StrategicDossier, link.dossier_id)
    if dossier is None or dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    if "version" not in payload:
        raise DomainValidationError("version es obligatoria.")
    expected = int(payload["version"])
    if link.triage_version != expected:
        raise VersionConflict("La revisión de señal cambió.")
    for field in ("relevance", "novelty", "confidence", "strategic_impact"):
        value = int(payload.get(field, getattr(link, field)))
        if not 0 <= value <= 100:
            raise DomainValidationError(f"{field} debe estar entre 0 y 100.")
        setattr(link, field, value)
    link.status = str(payload.get("status", "reviewed"))
    if link.status not in {"reviewed", "dismissed"}:
        raise DomainValidationError("Estado de revisión no válido.")
    link.why_it_matters = str(payload.get("why_it_matters", ""))[:5000]
    link.recommended_action = str(payload.get("recommended_action", ""))[:5000]
    link.reviewer_user_id = actor_id
    link.reviewed_at = datetime.now(UTC)
    link.triage_version += 1
    signal = session.get(Signal, link.signal_id)
    result = score_signal(
        {
            "relevance": link.relevance,
            "novelty": link.novelty,
            "strategic_impact": link.strategic_impact,
            "source_credibility": signal.credibility if signal else 0,
            "confidence": link.confidence,
        },
        weights=_weights(dossier.scoring_config, "signal_weights", SIGNAL_WEIGHTS),
    )
    link.overall_score = result.score
    link.score_details = result.as_dict()
    append_audit_event(
        session,
        action="signal.reviewed",
        resource_type="dossier_signal",
        resource_id=link.id,
        dossier_id=link.dossier_id,
        result="success",
        metadata={"status": link.status, "triage_version": link.triage_version},
    )
    session.commit()
    return link


def promote_signal_link(
    session: Session,
    link_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    idempotency_key: str,
    actor_id: uuid.UUID,
) -> Opportunity | RiskItem:
    tenant_id = require_tenant_id()
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    operation_key = f"signal.promote:{link_id}:{key_hash}"
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    link = session.scalar(
        select(DossierSignal)
        .where(DossierSignal.id == link_id, DossierSignal.tenant_id == tenant_id)
        .with_for_update()
    )
    if link is None:
        raise ResourceNotFound("Señal no encontrada.")
    dossier = _require_dossier_access(session, link.dossier_id, actor_id)
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    # Authorization always precedes idempotent replay. The lookup happens after locking the
    # contextual link so concurrent requests cannot bypass payload comparison.
    locked_prior = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.idempotency_key == operation_key,
        )
    )
    if locked_prior is not None:
        if locked_prior.result_ref.get("request_hash") != request_hash:
            raise VersionConflict("Idempotency-Key ya fue usada con otro payload.")
        locked_model = (
            Opportunity if locked_prior.result_ref.get("kind") == "opportunity" else RiskItem
        )
        locked_resource = session.get(
            locked_model, uuid.UUID(str(locked_prior.result_ref["resource_id"]))
        )
        if locked_resource is not None:
            return cast(Opportunity | RiskItem, locked_resource)
    if link.status == "promoted" and link.promoted_resource_id:
        model = Opportunity if link.promoted_resource_type == "opportunity" else RiskItem
        existing = session.get(model, link.promoted_resource_id)
        if existing is not None:
            return cast(Opportunity | RiskItem, existing)
    if link.status != "reviewed":
        raise DomainValidationError("La señal debe revisarse antes de promoverse.")
    kind = str(payload.get("kind", "opportunity"))
    title = str(payload.get("title", "")).strip()
    if not title or kind not in {"opportunity", "risk"}:
        raise DomainValidationError("Título y tipo de promoción son obligatorios.")
    create_task = payload.get("create_task", False)
    if not isinstance(create_task, bool):
        raise DomainValidationError("create_task debe ser booleano.")
    if kind == "opportunity":
        next_action = _bounded_text(payload, "next_action")
        due_date = _optional_date(payload.get("due_date", payload.get("deadline")), "due_date")
        effort_value = payload.get("execution_effort", payload.get("effort", 50))
        components = {
            key: int(effort_value if key == "effort" else payload.get(key, 50))
            for key in (
                "strategic_fit",
                "urgency",
                "expected_value",
                "actionability",
                "relationship_leverage",
                "timing",
                "confidence",
                "effort",
                "blocking_risk",
            )
        }
        override, reason = _override(payload, actor_id)
        result = score_opportunity(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "opportunity_weights", OPPORTUNITY_WEIGHTS),
        )
        resource: Opportunity | RiskItem = Opportunity(
            tenant_id=tenant_id,
            dossier_id=link.dossier_id,
            title=title,
            description=str(payload.get("description", "")),
            deadline=due_date,
            next_action=next_action,
            source_dossier_signal_id=link.id,
            overall_score=result.score,
            score_details=result.as_dict(),
            score_override=result.human_override,
            score_override_reason=reason,
            score_override_by_user_id=actor_id if override is not None else None,
            **components,
        )
    else:
        mitigation = _bounded_text(payload, "mitigation")
        due_date = _optional_date(payload.get("due_date"), "due_date")
        components = {
            key: int(payload.get(key, 50))
            for key in (
                "likelihood",
                "impact",
                "velocity",
                "exposure",
                "uncertainty",
                "controllability",
            )
        }
        confidence = int(payload.get("confidence", 50))
        override, reason = _override(payload, actor_id)
        result = score_risk(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "risk_weights", RISK_WEIGHTS),
        )
        resource = RiskItem(
            tenant_id=tenant_id,
            dossier_id=link.dossier_id,
            title=title,
            description=str(payload.get("description", "")),
            mitigation=mitigation,
            due_date=due_date,
            source_dossier_signal_id=link.id,
            confidence=confidence,
            overall_score=result.score,
            score_details=result.as_dict(),
            score_override=result.human_override,
            score_override_reason=reason,
            score_override_by_user_id=actor_id if override is not None else None,
            **components,
        )
    session.add(resource)
    session.flush()
    action_text = next_action if kind == "opportunity" else mitigation
    task_id: uuid.UUID | None = None
    if create_task and action_text:
        task = Task(
            tenant_id=tenant_id,
            dossier_id=link.dossier_id,
            title=action_text[:300],
            content={
                "source": "signal_promotion",
                "dossier_signal_id": str(link.id),
                "signal_id": str(link.signal_id),
                "promoted_resource_type": kind,
                "promoted_resource_id": str(resource.id),
                "promoted_resource_title": title,
            },
            status="open",
            owner_user_id=actor_id,
            due_date=due_date,
            priority="high" if kind == "risk" else "medium",
            linked_resource_type=kind,
            linked_resource_id=resource.id,
            origin="signal",
        )
        session.add(task)
        session.flush()
        task_id = task.id
    if kind == "opportunity":
        session.add(
            OpportunitySignal(
                tenant_id=tenant_id,
                opportunity_id=resource.id,
                signal_id=link.signal_id,
            )
        )
    else:
        session.add(
            RiskSignal(
                tenant_id=tenant_id,
                risk_id=resource.id,
                signal_id=link.signal_id,
            )
        )
    link.status = "promoted"
    link.promoted_resource_type = kind
    link.promoted_resource_id = resource.id
    session.add(
        ScoreHistory(
            tenant_id=tenant_id,
            dossier_id=link.dossier_id,
            resource_type=kind,
            resource_id=resource.id,
            score=result.score,
            algorithm_version=result.algorithm_version,
            details=result.as_dict(),
        )
    )
    append_audit_event(
        session,
        action="signal.promoted",
        resource_type=kind,
        resource_id=resource.id,
        dossier_id=link.dossier_id,
        result="success",
        metadata={"dossier_signal_id": str(link.id), "algorithm_version": result.algorithm_version},
    )
    session.add(
        BackgroundJob(
            tenant_id=tenant_id,
            dossier_id=link.dossier_id,
            job_type="signal.promote",
            status="succeeded",
            queue="default",
            idempotency_key=operation_key,
            progress=100,
            stage="completed",
            payload_hash=bytes.fromhex(request_hash),
            input_payload={},
            attempts=1,
            max_attempts=1,
            retryable=False,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            requested_by_user_id=actor_id,
            result_ref={
                "request_hash": request_hash,
                "kind": kind,
                "resource_id": str(resource.id),
                "task_id": str(task_id) if task_id is not None else None,
            },
        )
    )
    _refresh_dossier_aggregates(session, link.dossier_id)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.idempotency_key == operation_key,
            )
        )
        if concurrent is None or concurrent.result_ref.get("request_hash") != request_hash:
            raise VersionConflict("Conflicto concurrente de idempotencia.") from None
        model = Opportunity if concurrent.result_ref.get("kind") == "opportunity" else RiskItem
        concurrent_resource = session.get(
            model, uuid.UUID(str(concurrent.result_ref["resource_id"]))
        )
        if concurrent_resource is None:
            raise VersionConflict("La promoción concurrente no está disponible.") from None
        return cast(Opportunity | RiskItem, concurrent_resource)
    return resource


def create_scored_resource(
    session: Session,
    model: type[Opportunity] | type[RiskItem],
    dossier_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    actor_id: uuid.UUID,
) -> Opportunity | RiskItem:
    tenant_id = require_tenant_id()
    dossier = _require_dossier_access(session, dossier_id, actor_id)
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    title = str(payload.get("title", "")).strip()
    if not title:
        raise DomainValidationError("title es obligatorio.")
    owner_id = None
    if payload.get("owner_user_id") is not None:
        owner_id = _active_user(session, tenant_id, payload["owner_user_id"], "owner_user_id")
    override, reason = _override(payload, actor_id)
    if model is Opportunity:
        effort = payload.get("execution_effort", payload.get("effort", 0))
        components = {
            key: int(effort if key == "effort" else payload.get(key, 0))
            for key in OPPORTUNITY_WEIGHTS
        }
        result = score_opportunity(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "opportunity_weights", OPPORTUNITY_WEIGHTS),
        )
        row: Opportunity | RiskItem = Opportunity(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            title=title[:300],
            description=str(payload.get("description", ""))[:10000],
            opportunity_type=str(payload.get("opportunity_type", "custom"))[:80],
            status="identified",
            next_action=str(payload.get("next_action", ""))[:5000],
            owner_user_id=owner_id,
            overall_score=result.score,
            score_details=result.as_dict() | {"normalized_execution_effort": components["effort"]},
            score_override=override,
            score_override_reason=reason,
            score_override_by_user_id=actor_id if override is not None else None,
            **components,
        )
        kind = "opportunity"
    else:
        components = {key: int(payload.get(key, 0)) for key in RISK_WEIGHTS}
        confidence = int(payload.get("confidence", 50))
        result = score_risk(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "risk_weights", RISK_WEIGHTS),
        )
        row = RiskItem(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            title=title[:300],
            description=str(payload.get("description", ""))[:10000],
            category=str(payload.get("category", "strategic"))[:80],
            status="open",
            mitigation=str(payload.get("mitigation", ""))[:5000],
            owner_user_id=owner_id,
            confidence=confidence,
            overall_score=result.score,
            score_details=result.as_dict(),
            score_override=override,
            score_override_reason=reason,
            score_override_by_user_id=actor_id if override is not None else None,
            **components,
        )
        kind = "risk"
    session.add(row)
    session.flush()
    _record_score(session, row, dossier_id, kind, result.as_dict())
    append_audit_event(
        session,
        action=f"{kind}.created",
        resource_type=kind,
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"override": override is not None, "override_reason": reason},
    )
    _refresh_dossier_aggregates(session, dossier_id)
    session.commit()
    return row


def update_scored_resource(
    session: Session,
    model: type[Opportunity] | type[RiskItem],
    resource_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    expected_version: int,
) -> Opportunity | RiskItem:
    tenant_id = require_tenant_id()
    loaded = session.scalar(
        select(model).where(model.id == resource_id, model.tenant_id == tenant_id).with_for_update()
    )
    if loaded is None:
        raise ResourceNotFound("Recurso no encontrado.")
    row = cast(Opportunity | RiskItem, loaded)
    dossier = _require_dossier_access(session, row.dossier_id, actor_id)
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    if row.version != expected_version:
        raise VersionConflict("El recurso fue modificado por otro usuario.")
    transitions = OPPORTUNITY_TRANSITIONS if isinstance(row, Opportunity) else RISK_TRANSITIONS
    if "status" in payload:
        previous_status = row.status
        target = str(payload["status"])
        if target not in transitions[row.status]:
            raise DomainValidationError("Transición de estado no válida.")
        row.status = target
        record_status_change(
            session,
            dossier_id=row.dossier_id,
            resource_type="opportunity" if isinstance(row, Opportunity) else "risk",
            resource_id=row.id,
            from_status=previous_status,
            to_status=target,
            actor_id=actor_id,
            reason=str(payload.get("status_reason", "")),
        )
    for field in ("title", "description", "next_action", "mitigation"):
        if field in payload and hasattr(row, field):
            value = str(payload[field]).strip()
            if field == "title" and not value:
                raise DomainValidationError("title no puede estar vacío.")
            setattr(row, field, value[:10000])
    if "owner_user_id" in payload:
        row.owner_user_id = (
            None
            if payload["owner_user_id"] is None
            else _active_user(session, tenant_id, payload["owner_user_id"], "owner_user_id")
        )
    override = row.score_override
    reason = row.score_override_reason
    if "score_override" in payload:
        override, reason = _override(payload, actor_id)
    if isinstance(row, Opportunity):
        for key in OPPORTUNITY_WEIGHTS:
            source = (
                "execution_effort" if key == "effort" and "execution_effort" in payload else key
            )
            if source in payload:
                setattr(row, key, int(payload[source]))
        components = {key: int(getattr(row, key)) for key in OPPORTUNITY_WEIGHTS}
        result = score_opportunity(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "opportunity_weights", OPPORTUNITY_WEIGHTS),
        )
        kind = "opportunity"
        details = result.as_dict() | {"normalized_execution_effort": components["effort"]}
    else:
        for key in RISK_WEIGHTS:
            if key in payload:
                setattr(row, key, int(payload[key]))
        if "confidence" in payload:
            row.confidence = int(payload["confidence"])
        components = {key: int(getattr(row, key)) for key in RISK_WEIGHTS}
        result = score_risk(
            components,
            override=override,
            weights=_weights(dossier.scoring_config, "risk_weights", RISK_WEIGHTS),
        )
        kind = "risk"
        details = result.as_dict()
    row.overall_score = result.score
    row.score_details = details
    row.score_override = override
    row.score_override_reason = reason
    row.score_override_by_user_id = actor_id if override is not None else None
    row.version += 1
    _record_score(session, row, row.dossier_id, kind, details)
    append_audit_event(
        session,
        action=f"{kind}.updated",
        resource_type=kind,
        resource_id=row.id,
        dossier_id=row.dossier_id,
        result="success",
        metadata={"version": row.version, "override_reason": reason},
    )
    _refresh_dossier_aggregates(session, row.dossier_id)
    session.commit()
    return row


def _record_score(
    session: Session,
    row: Opportunity | RiskItem,
    dossier_id: uuid.UUID,
    kind: str,
    details: dict[str, Any],
) -> None:
    session.add(
        ScoreHistory(
            tenant_id=row.tenant_id,
            dossier_id=dossier_id,
            resource_type=kind,
            resource_id=row.id,
            score=row.overall_score,
            algorithm_version=str(details.get("algorithm_version", "oracle-scoring-v1")),
            details=details,
        )
    )


def record_status_change(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    from_status: str,
    to_status: str,
    actor_id: uuid.UUID,
    reason: str = "",
) -> None:
    session.add(
        StatusHistory(
            tenant_id=require_tenant_id(),
            dossier_id=dossier_id,
            resource_type=resource_type[:50],
            resource_id=resource_id,
            from_status=from_status[:40],
            to_status=to_status[:40],
            actor_user_id=actor_id,
            reason=reason[:1000],
        )
    )


def _record_status(
    session: Session,
    row: StrategicDossier,
    dossier_id: uuid.UUID,
    resource_type: str,
    from_status: str,
    to_status: str,
    actor_id: uuid.UUID,
    reason: str,
) -> None:
    record_status_change(
        session,
        dossier_id=dossier_id,
        resource_type=resource_type,
        resource_id=row.id,
        from_status=from_status,
        to_status=to_status,
        actor_id=actor_id,
        reason=reason,
    )


def create_dossier_actor(
    session: Session, dossier_id: uuid.UUID, payload: dict[str, Any], *, actor_id: uuid.UUID
) -> DossierActor:
    tenant_id = require_tenant_id()
    dossier = _require_dossier_access(session, dossier_id, actor_id)
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    actor: Actor | None = None
    if payload.get("actor_id"):
        try:
            linked_actor_id = uuid.UUID(str(payload["actor_id"]))
        except ValueError as error:
            raise DomainValidationError("actor_id debe ser UUID.") from error
        actor = session.scalar(
            select(Actor).where(Actor.id == linked_actor_id, Actor.tenant_id == tenant_id)
        )
        if actor is None:
            raise ResourceNotFound("Actor no encontrado.")
    else:
        canonical_name = " ".join(str(payload.get("canonical_name", "")).strip().split())
        actor_type = str(payload.get("actor_type", "organization")).strip().lower()
        if not canonical_name:
            raise DomainValidationError("canonical_name es obligatorio.")
        if actor_type not in ACTOR_TYPES:
            raise DomainValidationError("actor_type no es válido.")
        labels = clean_labels(payload.get("tags", []))
        identifiers = dict(payload.get("identifiers") or {})
        actor = resolve_or_create_actor(
            session,
            tenant_id=tenant_id,
            canonical_name=canonical_name[:300],
            actor_type=actor_type,
            identifiers=identifiers,
            actor_metadata={"tags": labels} if labels else {},
            provenance=dict(payload.get("provenance", {})),
        )
        if labels:
            metadata = dict(actor.actor_metadata or {})
            metadata["tags"] = clean_labels([*clean_labels(metadata.get("tags", [])), *labels])
            actor.actor_metadata = metadata
            actor.version += 1
        linked_actor_id = actor.id
    existing_link = session.scalar(
        select(DossierActor).where(
            DossierActor.tenant_id == tenant_id,
            DossierActor.dossier_id == dossier_id,
            DossierActor.actor_id == linked_actor_id,
        )
    )
    requested_roles = clean_labels(payload.get("roles", []))
    if existing_link is not None:
        existing_link.roles = clean_labels([*clean_labels(existing_link.roles), *requested_roles])
        if payload.get("notes"):
            existing_link.notes = str(payload["notes"])[:5000]
        existing_link.version += 1
        hydrate_dossier_actor_tax_ids_from_awards(
            session,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            actor_ids={linked_actor_id},
        )
        session.commit()
        return existing_link
    components = {key: int(payload.get(key, 0)) for key in ACTOR_PRIORITY_WEIGHTS}
    result = score_actor_priority(
        components,
        weights=_weights(dossier.scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS),
    )
    row = DossierActor(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_id=linked_actor_id,
        roles=requested_roles,
        notes=str(payload.get("notes", ""))[:5000],
        priority=result.score,
        score_details=result.as_dict(),
        **components,
    )
    session.add(row)
    session.flush()
    append_audit_event(
        session,
        action="actor.linked",
        resource_type="actor",
        resource_id=linked_actor_id,
        dossier_id=dossier_id,
        result="success",
        metadata={"created_from_name": payload.get("actor_id") is None},
    )
    # Al enlazar actor a expediente con awards ya fijados, hidratar CIF si es inequívoco.
    hydrate_dossier_actor_tax_ids_from_awards(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_ids={linked_actor_id},
    )
    session.commit()
    return row


def update_dossier_actor(
    session: Session,
    dossier_actor_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    actor_id: uuid.UUID,
    expected_version: int,
) -> DossierActor:
    tenant_id = require_tenant_id()
    row = session.scalar(
        select(DossierActor)
        .where(DossierActor.id == dossier_actor_id, DossierActor.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise ResourceNotFound("Actor contextual no encontrado.")
    dossier = _require_dossier_access(session, row.dossier_id, actor_id)
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    if row.version != expected_version:
        raise VersionConflict("El actor contextual fue modificado por otro usuario.")
    for key in ACTOR_PRIORITY_WEIGHTS:
        if key in payload:
            setattr(row, key, int(payload[key]))
    if "roles" in payload:
        row.roles = list(payload["roles"])
    if "notes" in payload:
        row.notes = str(payload["notes"])[:5000]
    result = score_actor_priority(
        {key: int(getattr(row, key)) for key in ACTOR_PRIORITY_WEIGHTS},
        weights=_weights(dossier.scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS),
    )
    row.priority = result.score
    row.score_details = result.as_dict()
    row.version += 1
    append_audit_event(
        session,
        action="dossier_actor.updated",
        resource_type="dossier_actor",
        resource_id=row.id,
        dossier_id=row.dossier_id,
        result="success",
        metadata={"version": row.version, "priority": row.priority},
    )
    session.commit()
    return row


_PROTECTED_NON_FISCAL_IDENTIFIERS = frozenset({"lei", "duns", "isin", "ticker"})
_FISCAL_IDENTIFIER_KEYS = frozenset({"tax_id", "tax_id_scheme", "tax_id_declared", "tax_id_source"})


class TaxIdMergeBlocked(DomainValidationError):
    """Two durable tax_ids differ — merge must not mutate either actor."""

    def __init__(self, message: str, *, target_tax_id: str, source_tax_id: str) -> None:
        super().__init__(message)
        self.target_tax_id = target_tax_id
        self.source_tax_id = source_tax_id
        self.code = "tax_id_merge_blocked"


def _merge_identifiers_governed(
    target: Actor,
    source: Actor,
) -> dict[str, Any]:
    """Merge JSON identifiers: fiscal is column-authoritative; LEI/DUNS never overwritten.

    Target wins on protected non-fiscal keys when present; source fills gaps.
    Other non-fiscal keys: target wins on collision, source contributes missing.
    """

    target_ids = dict(target.identifiers or {}) if isinstance(target.identifiers, dict) else {}
    source_ids = dict(source.identifiers or {}) if isinstance(source.identifiers, dict) else {}
    merged: dict[str, Any] = {}

    # Non-fiscal union with target preference; protect LEI/DUNS from overwrite.
    for key, value in source_ids.items():
        if key in _FISCAL_IDENTIFIER_KEYS:
            continue
        merged[key] = value
    for key, value in target_ids.items():
        if key in _FISCAL_IDENTIFIER_KEYS:
            continue
        if key in _PROTECTED_NON_FISCAL_IDENTIFIERS and target_ids.get(key) not in (None, ""):
            merged[key] = target_ids[key]
        else:
            merged[key] = value if value not in (None, "") else merged.get(key, value)

    # Fiscal block: durable column is source of truth after tax transfer logic.
    durable = usable_company_tax_id(getattr(target, "tax_id", None))
    if durable:
        merged["tax_id"] = durable
        merged["tax_id_scheme"] = (
            target.tax_id_scheme or target_ids.get("tax_id_scheme") or "ES_CIF"
        )
        declared = target_ids.get("tax_id_declared") or source_ids.get("tax_id_declared") or durable
        merged["tax_id_declared"] = declared
        source_block = source_ids.get("tax_id_source")
        target_block = target_ids.get("tax_id_source")
        if isinstance(target_block, dict):
            merged["tax_id_source"] = target_block
        elif isinstance(source_block, dict):
            merged["tax_id_source"] = source_block
    return merged


def _count_actor_references(
    session: Session,
    *,
    actor_ids: tuple[uuid.UUID, ...],
) -> dict[str, int]:
    dossier_links = session.scalar(
        select(func.count()).select_from(DossierActor).where(DossierActor.actor_id.in_(actor_ids))
    )
    opportunity_links = session.scalar(
        select(func.count())
        .select_from(OpportunityActor)
        .where(OpportunityActor.actor_id.in_(actor_ids))
    )
    risk_links = session.scalar(
        select(func.count()).select_from(RiskActor).where(RiskActor.actor_id.in_(actor_ids))
    )
    meeting_links = session.scalar(
        select(func.count()).select_from(MeetingActor).where(MeetingActor.actor_id.in_(actor_ids))
    )
    relationships = session.scalar(
        select(func.count())
        .select_from(Relationship)
        .where(
            (Relationship.from_actor_id.in_(actor_ids)) | (Relationship.to_actor_id.in_(actor_ids))
        )
    )
    return {
        "dossier_actors": int(dossier_links or 0),
        "opportunity_actors": int(opportunity_links or 0),
        "risk_actors": int(risk_links or 0),
        "meeting_actors": int(meeting_links or 0),
        "relationships": int(relationships or 0),
    }


def preview_merge_actors(
    session: Session,
    target_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    """Read-only merge preview: winner, tax provenance, aliases and reference impact."""

    tenant_id = require_tenant_id()
    if target_id == source_id:
        raise DomainValidationError("El origen debe ser distinto del destino.")
    target = session.scalar(
        select(Actor).where(Actor.id == target_id, Actor.tenant_id == tenant_id)
    )
    source = session.scalar(
        select(Actor).where(Actor.id == source_id, Actor.tenant_id == tenant_id)
    )
    if target is None or source is None:
        raise ResourceNotFound("Actor no encontrado.")

    target_tax = usable_company_tax_id(getattr(target, "tax_id", None))
    source_tax = usable_company_tax_id(getattr(source, "tax_id", None))
    blocked = bool(target_tax and source_tax and target_tax != source_tax)
    block_reason = None
    if blocked:
        block_reason = f"NIF durables distintos ({target_tax} vs {source_tax}); fusión bloqueada."

    # Fiscal destination rule: if only one has durable tax_id, that actor should win.
    fiscal_winner_id = None
    if target_tax and not source_tax:
        fiscal_winner_id = str(target.id)
    elif source_tax and not target_tax:
        fiscal_winner_id = str(source.id)
    elif target_tax and source_tax and target_tax == source_tax:
        fiscal_winner_id = str(target.id)

    source_refs = _count_actor_references(session, actor_ids=(source.id,))
    both_refs = _count_actor_references(session, actor_ids=(source.id, target.id))
    del actor_id  # reserved for future access checks parity with merge

    return {
        "blocked": blocked,
        "block_reason": block_reason,
        "target": {
            "id": str(target.id),
            "name": target.canonical_name,
            "tax_id": target_tax,
            "tax_id_scheme": target.tax_id_scheme,
            "tax_id_country": target.tax_id_country,
            "aliases": list(target.aliases or []),
            "identifiers": dict(target.identifiers or {}),
            "version": int(target.version or 1),
            "has_durable_tax_id_column": target_tax is not None,
        },
        "source": {
            "id": str(source.id),
            "name": source.canonical_name,
            "tax_id": source_tax,
            "tax_id_scheme": source.tax_id_scheme,
            "tax_id_country": source.tax_id_country,
            "aliases": list(source.aliases or []),
            "identifiers": dict(source.identifiers or {}),
            "version": int(source.version or 1),
            "has_durable_tax_id_column": source_tax is not None,
        },
        "suggested_target_id": fiscal_winner_id or str(target.id),
        "resulting_aliases": sorted(
            {
                str(value)
                for value in [*target.aliases, *source.aliases, source.canonical_name]
                if value
            }
        ),
        "reference_impact": {
            "source_only": source_refs,
            "combined_before": both_refs,
            "summary": (
                f"Se moverán/deduplicarán {source_refs['dossier_actors']} vínculos de expediente, "
                f"{source_refs['opportunity_actors']} de oportunidad, "
                f"{source_refs['risk_actors']} de riesgo, "
                f"{source_refs['meeting_actors']} de reunión y "
                f"{source_refs['relationships']} relaciones del origen."
            ),
        },
        "confirmation_required": {
            "confirm": True,
            "reason_min_length": 3,
            "expected_target_version": int(target.version or 1),
            "expected_source_version": int(source.version or 1),
        },
    }


def _resolve_open_tax_conflicts_for_merge(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    target: Actor,
    source: Actor,
    actor_id: uuid.UUID,
    reason: str,
) -> list[str]:
    """Close open ActorTaxIdConflict rows for this pair only after a successful merge path."""

    open_conflicts = list(
        session.scalars(
            select(ActorTaxIdConflict).where(
                ActorTaxIdConflict.tenant_id == tenant_id,
                ActorTaxIdConflict.status == "open",
                (
                    (
                        (ActorTaxIdConflict.winner_actor_id == target.id)
                        & (ActorTaxIdConflict.loser_actor_id == source.id)
                    )
                    | (
                        (ActorTaxIdConflict.winner_actor_id == source.id)
                        & (ActorTaxIdConflict.loser_actor_id == target.id)
                    )
                ),
            )
        )
    )
    resolved_ids: list[str] = []
    now = datetime.now(UTC)
    for conflict in open_conflicts:
        # Mark resolved in-txn before source delete. CASCADE may later remove the
        # row when the source actor is deleted; actor.merged audit keeps the trail.
        conflict.status = "resolved"
        conflict.resolution_note = (
            f"Resuelto por fusión humana actor.merged: source={source.id} → target={target.id}. "
            f"{reason[:500]}"
        )[:2000]
        conflict.resolved_at = now
        conflict.resolved_by_user_id = actor_id
        conflict.version = int(conflict.version or 1) + 1
        resolved_ids.append(str(conflict.id))
    return resolved_ids


def merge_actors(
    session: Session,
    target_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    reason: str,
    expected_target_version: int | None = None,
    expected_source_version: int | None = None,
    confirm: bool = False,
    match_reason: str | None = None,
) -> Actor:
    """Human-confirmed, tax-safe, CAS-guarded actor merge.

    Requires ``confirm=True``, a non-empty reason and expected versions for both
    actors. Distinct durable tax_ids block without mutation. Idempotent when the
    source is already gone and the target records the same last_merge source.
    """

    if target_id == source_id:
        raise DomainValidationError("El origen debe ser distinto del destino.")
    if not reason or not reason.strip():
        raise DomainValidationError("La razón es obligatoria.")
    if not confirm:
        raise DomainValidationError("La fusión requiere confirmación inequívoca (confirm=true).")
    if expected_target_version is None or expected_source_version is None:
        raise DomainValidationError(
            "expected_target_version y expected_source_version son obligatorios (CAS)."
        )

    tenant_id = require_tenant_id()

    # Lock in stable id order to avoid deadlocks under concurrent merges.
    first_id, second_id = sorted((target_id, source_id), key=str)
    first = session.scalar(
        select(Actor).where(Actor.id == first_id, Actor.tenant_id == tenant_id).with_for_update()
    )
    second = session.scalar(
        select(Actor).where(Actor.id == second_id, Actor.tenant_id == tenant_id).with_for_update()
    )
    by_id = {row.id: row for row in (first, second) if row is not None}
    target = by_id.get(target_id)
    source = by_id.get(source_id)

    # Idempotent retry: source already deleted after a prior successful merge into target.
    if target is not None and source is None:
        provenance = dict(target.provenance or {}) if isinstance(target.provenance, dict) else {}
        raw_last = provenance.get("last_merge")
        last_merge: dict[str, Any] = raw_last if isinstance(raw_last, dict) else {}
        if str(last_merge.get("source_actor_id") or "") == str(source_id):
            return target
        raise ResourceNotFound("Actor origen no encontrado.")
    if target is None or source is None:
        raise ResourceNotFound("Actor no encontrado.")

    if int(target.version or 1) != int(expected_target_version):
        raise VersionConflict(
            "El actor destino fue modificado por otro usuario (CAS). Recarga y reintenta."
        )
    if int(source.version or 1) != int(expected_source_version):
        raise VersionConflict(
            "El actor origen fue modificado por otro usuario (CAS). Recarga y reintenta."
        )

    target_tax = usable_company_tax_id(getattr(target, "tax_id", None))
    source_tax = usable_company_tax_id(getattr(source, "tax_id", None))
    if target_tax and source_tax and target_tax != source_tax:
        raise TaxIdMergeBlocked(
            f"Fusión bloqueada: NIF durables distintos ({target_tax} vs {source_tax}).",
            target_tax_id=target_tax,
            source_tax_id=source_tax,
        )

    # Fiscal destination guard: refuse when client chose a destination without the
    # durable NIF while the source holds it (no silent fiscal demotion).
    if source_tax and not target_tax:
        # Transfer is allowed via shared service below; destination may receive NIF.
        pass

    affected_dossiers = set(
        session.scalars(
            select(DossierActor.dossier_id).where(DossierActor.actor_id.in_((source.id, target.id)))
        )
    )
    affected_dossiers.update(
        value
        for value in session.scalars(
            select(Relationship.dossier_id).where(
                Relationship.dossier_id.is_not(None),
                (Relationship.from_actor_id.in_((source.id, target.id)))
                | (Relationship.to_actor_id.in_((source.id, target.id))),
            )
        )
        if value is not None
    )
    affected_dossiers.update(
        session.scalars(
            select(Opportunity.dossier_id)
            .join(OpportunityActor, OpportunityActor.opportunity_id == Opportunity.id)
            .where(OpportunityActor.actor_id.in_((source.id, target.id)))
        )
    )
    affected_dossiers.update(
        session.scalars(
            select(RiskItem.dossier_id)
            .join(RiskActor, RiskActor.risk_id == RiskItem.id)
            .where(RiskActor.actor_id.in_((source.id, target.id)))
        )
    )
    affected_dossiers.update(
        session.scalars(
            select(Meeting.dossier_id)
            .join(MeetingActor, MeetingActor.meeting_id == Meeting.id)
            .where(MeetingActor.actor_id.in_((source.id, target.id)))
        )
    )
    dossiers: dict[uuid.UUID, StrategicDossier] = {}
    for dossier_id in affected_dossiers:
        dossier = _require_dossier_access(session, dossier_id, actor_id)
        if dossier.status == "archived":
            raise DomainValidationError("No se pueden fusionar actores de un expediente archivado.")
        dossiers[dossier_id] = dossier

    # Transfer durable tax_id via shared fiscal service when only source holds it.
    # Release the source column first so the partial unique index allows the
    # target assignment inside the same transaction (source is deleted next).
    if source_tax and not target_tax:
        transfer_raw = source.tax_id
        transfer_declared = (
            (source.identifiers or {}).get("tax_id_declared")
            if isinstance(source.identifiers, dict)
            else None
        ) or transfer_raw
        source.tax_id = None
        source.tax_id_scheme = None
        source.tax_id_country = None
        session.flush()
        try:
            assign_actor_tax_id(
                session,
                target,
                transfer_raw,
                provenance={
                    "kind": "merge_transfer",
                    "source_actor_id": str(source.id),
                    "reason": reason[:500],
                },
                declared=transfer_declared,
                allow_same=True,
                bump_version=False,
            )
        except TaxIdConflictError as error:
            raise DomainValidationError(str(error)) from error
        except TaxIdValidationError as error:
            raise DomainValidationError(str(error)) from error

    target.aliases = sorted(
        {str(value) for value in [*target.aliases, *source.aliases, source.canonical_name] if value}
    )
    target.identifiers = _merge_identifiers_governed(target, source)
    previous_provenance = (
        dict(target.provenance or {}) if isinstance(target.provenance, dict) else {}
    )
    source_provenance = dict(source.provenance or {}) if isinstance(source.provenance, dict) else {}
    target.provenance = {
        **source_provenance,
        **previous_provenance,
        "last_merge": {
            "source_actor_id": str(source.id),
            "source_name": source.canonical_name,
            "reason": reason[:1000],
            "match_reason": (match_reason or "")[:80] or None,
            "expected_target_version": int(expected_target_version),
            "expected_source_version": int(expected_source_version),
            "source_tax_id": source_tax,
            "target_tax_id": usable_company_tax_id(getattr(target, "tax_id", None)),
        },
    }
    target.version = int(target.version or 1) + 1

    for link in list(
        session.scalars(select(DossierActor).where(DossierActor.actor_id == source.id))
    ):
        existing = session.scalar(
            select(DossierActor).where(
                DossierActor.dossier_id == link.dossier_id, DossierActor.actor_id == target.id
            )
        )
        if existing:
            existing.roles = sorted({*existing.roles, *link.roles})
            for field in ACTOR_PRIORITY_WEIGHTS:
                setattr(existing, field, max(getattr(existing, field), getattr(link, field)))
            score = score_actor_priority(
                {field: getattr(existing, field) for field in ACTOR_PRIORITY_WEIGHTS},
                weights=_weights(
                    dossiers[existing.dossier_id].scoring_config,
                    "actor_weights",
                    ACTOR_PRIORITY_WEIGHTS,
                ),
            )
            existing.priority, existing.score_details = score.score, score.as_dict()
            session.delete(link)
        else:
            score = score_actor_priority(
                {field: getattr(link, field) for field in ACTOR_PRIORITY_WEIGHTS},
                weights=_weights(
                    dossiers[link.dossier_id].scoring_config,
                    "actor_weights",
                    ACTOR_PRIORITY_WEIGHTS,
                ),
            )
            link.priority, link.score_details = score.score, score.as_dict()
            link.version += 1
            link.actor_id = target.id
    for model_class in (OpportunityActor, RiskActor, MeetingActor):
        link_model: Any = model_class
        actor_column = link_model.actor_id
        for association in list(
            session.scalars(select(link_model).where(actor_column == source.id))
        ):
            identity = {
                column.name: getattr(association, column.name)
                for column in link_model.__table__.primary_key.columns
                if column.name != "actor_id"
            }
            exists_target = session.scalar(
                select(link_model).where(
                    link_model.actor_id == target.id,
                    *(getattr(link_model, key) == value for key, value in identity.items()),
                )
            )
            if exists_target:
                session.delete(association)
            else:
                association.actor_id = target.id
    for relationship in list(
        session.scalars(
            select(Relationship).where(
                (Relationship.from_actor_id == source.id) | (Relationship.to_actor_id == source.id)
            )
        )
    ):
        new_from = (
            target.id if relationship.from_actor_id == source.id else relationship.from_actor_id
        )
        new_to = target.id if relationship.to_actor_id == source.id else relationship.to_actor_id
        if new_from == new_to:
            session.delete(relationship)
        else:
            relationship.from_actor_id, relationship.to_actor_id = new_from, new_to

    resolved_conflicts = _resolve_open_tax_conflicts_for_merge(
        session,
        tenant_id=tenant_id,
        target=target,
        source=source,
        actor_id=actor_id,
        reason=reason,
    )

    append_audit_event(
        session,
        action="actor.merged",
        resource_type="actor",
        resource_id=target.id,
        result="success",
        metadata={
            "source_actor_id": str(source.id),
            "source_name": source.canonical_name,
            "target_name": target.canonical_name,
            "reason": reason[:1000],
            "match_reason": match_reason,
            "expected_target_version": int(expected_target_version),
            "expected_source_version": int(expected_source_version),
            "target_version_after": int(target.version or 1),
            "tax_id": usable_company_tax_id(getattr(target, "tax_id", None)),
            "resolved_tax_id_conflicts": resolved_conflicts,
            # Informational only; audit.actor_id comes from TenantContext.
            "requested_by_user_id": str(actor_id),
        },
    )
    session.flush()
    session.delete(source)
    session.commit()
    return target


def _refresh_dossier_aggregates(session: Session, dossier_id: uuid.UUID) -> None:
    dossier = session.get(StrategicDossier, dossier_id)
    if dossier is None:
        return
    opportunities = list(
        session.scalars(
            select(Opportunity.overall_score).where(Opportunity.dossier_id == dossier_id)
        )
    )
    risks = list(
        session.scalars(select(RiskItem.overall_score).where(RiskItem.dossier_id == dossier_id))
    )
    aggregate = aggregate_dossier_scores(opportunities, risks)
    dossier.health_score = aggregate["health_score"]
    dossier.opportunity_score = aggregate["opportunity_score"]
    dossier.risk_score = aggregate["risk_score"]
    dossier.score_explanation = {
        "algorithm_version": ALGORITHM_VERSION,
        "aggregate": "arithmetic mean; health=50+0.5*opportunity-0.5*risk",
        "opportunity_count": len(opportunities),
        "risk_count": len(risks),
        **aggregate,
    }


def _dossier_aggregates_stale(dossier: StrategicDossier) -> bool:
    explanation = dossier.score_explanation if isinstance(dossier.score_explanation, dict) else {}
    return explanation.get("algorithm_version") != ALGORITHM_VERSION


def ensure_dossier_aggregates(
    session: Session, dossier: StrategicDossier, *, commit: bool = True
) -> StrategicDossier:
    """Self-heal dossiers created before aggregates were refreshed on create.

    Proof of a successful run is ``score_explanation.algorithm_version``. An empty
    ``{}`` means the row still carries column defaults (health 0) and must be
    recomputed from current opportunities/risks.
    """

    if not _dossier_aggregates_stale(dossier):
        return dossier
    _refresh_dossier_aggregates(session, dossier.id)
    if commit:
        session.commit()
        session.refresh(dossier)
    return dossier


def ensure_dossier_aggregates_many(
    session: Session, dossiers: list[StrategicDossier]
) -> list[StrategicDossier]:
    """Batch self-heal for list endpoints (single commit)."""

    stale = [row for row in dossiers if _dossier_aggregates_stale(row)]
    if not stale:
        return dossiers
    for row in stale:
        _refresh_dossier_aggregates(session, row.id)
    session.commit()
    for row in stale:
        session.refresh(row)
    return dossiers


def order_with_nulls_last(column: Any, *, descending: bool) -> Any:
    """Product contract: rows without a sort value never cover those that have one.

    Applies to deadline/due_date (and any other nullable sort column): ascending or
    descending, nulls stay at the end so the working week stays legible.
    """

    base = column.desc() if descending else column.asc()
    return base.nulls_last()


def list_page(
    session: Session,
    model: type[Any],
    *,
    page: int,
    size: int,
    sort_key: str,
    descending: bool,
    filters: dict[str, Any],
    allow_sort: dict[str, Any],
    search_columns: tuple[Any, ...] = (),
    search: str = "",
    extra_criteria: tuple[Any, ...] = (),
) -> tuple[list[Any], int]:
    if page < 1 or size < 1 or size > 100 or sort_key not in allow_sort:
        raise DomainValidationError("Paginación u ordenación no válida.")
    query = select(model)
    count_query = select(func.count()).select_from(model)
    if extra_criteria:
        query = query.where(*extra_criteria)
        count_query = count_query.where(*extra_criteria)
    for column_name, value in filters.items():
        if value is None or not hasattr(model, column_name):
            continue
        criterion = getattr(model, column_name) == value
        query, count_query = query.where(criterion), count_query.where(criterion)
    if search:
        term = f"%{search[:100]}%"
        criterion = __import__("sqlalchemy").or_(*(column.ilike(term) for column in search_columns))
        query, count_query = query.where(criterion), count_query.where(criterion)
    order = order_with_nulls_last(allow_sort[sort_key], descending=descending)
    total = int(session.scalar(count_query) or 0)
    rows = list(session.scalars(query.order_by(order).offset((page - 1) * size).limit(size)))
    return rows, total
