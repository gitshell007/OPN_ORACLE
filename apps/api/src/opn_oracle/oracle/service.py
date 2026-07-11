"""Transactional Oracle domain services."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
        "custom",
    }
)
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
        status="draft",
        strategic_goal=str(payload.get("strategic_goal", ""))[:5000],
        geography=list(payload.get("geography", [])),
        sectors=list(payload.get("sectors", [])),
        languages=list(payload.get("languages", [])),
        owner_user_id=owner_id,
        scoring_config=scoring_config,
    )
    session.add(dossier)
    session.flush()
    if create_starter_profile:
        _apply_starter_profile(session, dossier)
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
    )
    session.commit()
    return dossier


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
    if kind == "opportunity":
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
            source_dossier_signal_id=link.id,
            overall_score=result.score,
            score_details=result.as_dict(),
            score_override=result.human_override,
            score_override_reason=reason,
            score_override_by_user_id=actor_id if override is not None else None,
            **components,
        )
    else:
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
    try:
        linked_actor_id = uuid.UUID(str(payload["actor_id"]))
    except (KeyError, ValueError) as error:
        raise DomainValidationError("actor_id es obligatorio y debe ser UUID.") from error
    if (
        session.scalar(
            select(Actor.id).where(Actor.id == linked_actor_id, Actor.tenant_id == tenant_id)
        )
        is None
    ):
        raise ResourceNotFound("Actor no encontrado.")
    components = {key: int(payload.get(key, 0)) for key in ACTOR_PRIORITY_WEIGHTS}
    result = score_actor_priority(
        components,
        weights=_weights(dossier.scoring_config, "actor_weights", ACTOR_PRIORITY_WEIGHTS),
    )
    row = DossierActor(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_id=linked_actor_id,
        roles=list(payload.get("roles", [])),
        notes=str(payload.get("notes", ""))[:5000],
        priority=result.score,
        score_details=result.as_dict(),
        **components,
    )
    session.add(row)
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


def merge_actors(
    session: Session,
    target_id: uuid.UUID,
    source_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    reason: str,
) -> Actor:
    tenant_id = require_tenant_id()
    if target_id == source_id or not reason.strip():
        raise DomainValidationError("El origen debe ser distinto y la razón es obligatoria.")
    target = session.scalar(
        select(Actor).where(Actor.id == target_id, Actor.tenant_id == tenant_id).with_for_update()
    )
    source = session.scalar(
        select(Actor).where(Actor.id == source_id, Actor.tenant_id == tenant_id).with_for_update()
    )
    if target is None or source is None:
        raise ResourceNotFound("Actor no encontrado.")
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
    target.aliases = sorted(
        {str(value) for value in [*target.aliases, *source.aliases, source.canonical_name]}
    )
    target.identifiers = source.identifiers | target.identifiers
    target.provenance = target.provenance | {
        "last_merge": {"source_actor_id": str(source.id), "reason": reason[:1000]}
    }
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
    append_audit_event(
        session,
        action="actor.merged",
        resource_type="actor",
        resource_id=target.id,
        result="success",
        metadata={
            "source_actor_id": str(source.id),
            "reason": reason[:1000],
            "actor_id": str(actor_id),
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
        "algorithm_version": "oracle-scoring-v1",
        "aggregate": "arithmetic mean; health=50+0.5*opportunity-0.5*risk",
        **aggregate,
    }


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
    order = allow_sort[sort_key].desc() if descending else allow_sort[sort_key].asc()
    total = int(session.scalar(count_query) or 0)
    rows = list(session.scalars(query.order_by(order).offset((page - 1) * size).limit(size)))
    return rows, total
