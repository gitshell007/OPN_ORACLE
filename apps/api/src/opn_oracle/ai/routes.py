"""Explicit enqueue, audit and human-review APIs for AI artifacts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import (
    Boolean,
    Dict,
    Float,
    Integer,
    List,
    Nested,
    Raw,
    String,
)
from flask import Response, g, jsonify, make_response, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import case, select
from sqlalchemy.exc import IntegrityError

from opn_oracle.ai.models import AIArtifact, AIAttempt, AIHumanReview, OpportunityOfferDraft
from opn_oracle.ai.offer_draft import (
    OfferDraftError,
    OfferDraftVersionConflict,
    apply_editable_patch,
    cas_update_offer_draft_sql,
    make_etag,
    materialize_content_from_calculated,
    parse_expected_version,
    serialize_offer_draft,
    utc_now,
)
from opn_oracle.ai.offer_draft_docx import (
    DOCX_MEDIA_TYPE,
    build_offer_draft_docx,
    collect_evidence_ids,
    content_disposition_attachment,
    load_evidence_citation_lookup,
    resolve_evidence_citations,
    sanitize_export_filename,
)
from opn_oracle.ai.schemas import AGENT_SCHEMAS
from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.models import DossierSignal, Feedback, Insight, StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.procurement_search_profiles import get_artifact_acceptance
from opn_oracle.platform.audit import append_audit_event

bp = APIBlueprint("ai", __name__, url_prefix="/api/v1/ai", tag="IA")
public_bp = APIBlueprint("ai_contract", __name__, url_prefix="/api/v1", tag="IA")
DOSSIER_COMPLETION_WIZARD_AGENT = "dossier_completion_wizard"
TENDER_SEARCH_WIZARD_AGENT = "tender_search_wizard"
MARKET_COMPETITOR_DISCOVERY_AGENT = "market_competitor_discovery"
MARKET_COMPETITOR_DISCOVERY_TARGET = "market_discovery"
MARKET_ACTOR_DISCOVERY_AGENT = "market_actor_discovery"
MARKET_ACTOR_DISCOVERY_TARGET = "market_actor_discovery"
INTAKE_AGENT = "intake"
OPPORTUNITY_AGENT = "opportunity"
RISK_AGENT = "risk"
ACTOR_PARTNERSHIP_AGENT = "actor_partnership"
ENTITY_RESOLUTION_AGENT = "entity_resolution"
TENDER_SEARCH_WIZARD_TARGET = "tenant_search_profile"


class TenderSearchWizardInputSchema(Schema):
    description = String(required=True, validate=validate.Length(min=10, max=4_000))
    comparable = String(
        load_default=None,
        allow_none=True,
        validate=validate.Length(max=250),
    )


class TenderSearchWizardLatestInputSchema(Schema):
    mode = String(required=True, validate=validate.OneOf(["initial", "replan"]))
    description = String(allow_none=True)
    comparable = String(allow_none=True)
    profile_id = String(allow_none=True)


class TenderSearchCandidateCPVSchema(Schema):
    code = String(required=True)
    label = String(required=True)


class TenderSearchWizardPlanSchema(Schema):
    intent_summary = String(required=True)
    include_terms = List(String(), required=True)
    synonyms = List(String(), required=True)
    exclude_terms = List(String(), required=True)
    candidate_cpv = List(Nested(TenderSearchCandidateCPVSchema), required=True)
    buyers = List(String(), required=True)
    geographies = List(String(), required=True)
    scope = String(required=True, validate=validate.OneOf(["active", "historical", "all"]))
    min_amount = Float(allow_none=True)
    max_amount = Float(allow_none=True)
    assumptions = List(String(), required=True)
    questions = List(String(), required=True)
    confidence = Integer(required=True)
    discarded_count = Integer(required=True)
    discarded_reasons = Dict(keys=String(), values=Integer(), required=True)


class TenderSearchWizardArtifactSchema(Schema):
    id = String(required=True)
    dossier_id = String(allow_none=True)
    agent = String(required=True)
    schema_name = String(required=True)
    schema_version = String(required=True)
    status = String(required=True)
    output = Nested(TenderSearchWizardPlanSchema, required=True)
    created_at = String(required=True)
    updated_at = String(required=True)
    version = Integer(required=True)


class TenderSearchWizardJobSchema(Schema):
    id = String(required=True)
    tenant_id = String(required=True)
    job_type = String(required=True)
    queue = String(required=True)
    status = String(required=True)
    progress = Integer(required=True)
    stage = String(required=True)
    resource_type = String(allow_none=True)
    resource_id = String(allow_none=True)
    attempts = Integer(required=True)
    max_attempts = Integer(required=True)
    retryable = Boolean(required=True)
    created_at = String(required=True)
    started_at = String(allow_none=True)
    finished_at = String(allow_none=True)
    heartbeat_at = String(allow_none=True)
    error_code = String(allow_none=True)
    error_message = String(allow_none=True)
    cancel_requested = Boolean(required=True)
    result = Dict(keys=String(), values=Raw(), required=True)
    updated_at = String(required=True)
    version = Integer(required=True)


class TenderSearchWizardRunResponseSchema(Schema):
    job = Nested(TenderSearchWizardJobSchema, required=True)
    artifact = Nested(TenderSearchWizardArtifactSchema, allow_none=True)


class TenderSearchWizardAcceptanceSchema(Schema):
    profile_id = String(required=True)
    version = Integer(required=True)
    accepted_at = String(required=True)


class TenderSearchWizardLatestResponseSchema(TenderSearchWizardRunResponseSchema):
    job = Nested(TenderSearchWizardJobSchema, allow_none=True)
    input = Nested(TenderSearchWizardLatestInputSchema, allow_none=True)
    acceptance = Nested(TenderSearchWizardAcceptanceSchema, allow_none=True)


class MarketCompetitorDiscoveryInputSchema(Schema):
    description = String(required=True, validate=validate.Length(min=10, max=4_000))
    own_offer = String(load_default="", validate=validate.Length(max=1_000))
    sectors = List(String(validate=validate.Length(max=300)), load_default=[])
    countries = List(String(validate=validate.Length(min=2, max=3)), load_default=[])
    languages = List(String(validate=validate.Length(max=10)), load_default=[])
    known_names = List(String(validate=validate.Length(max=300)), load_default=[])
    competitors_knowledge = String(
        load_default="known",
        validate=validate.OneOf(["known", "unknown", "not_seeking"]),
    )


class SourceUrlMetaSchema(Schema):
    url = String(required=True)
    status = String(required=True)
    label = String(required=True)
    verified = Boolean(required=True)


class CitableSourcePublicSchema(Schema):
    source_id = String(required=True)
    title = String(load_default="")
    url = String(load_default="")
    snippet = String(load_default="")
    rank = Integer(load_default=1)
    domain = String(load_default="")
    label = String(load_default="")
    origin = String(load_default="web_search")
    origin_label = String(load_default="Fuente encontrada por búsqueda")


class ReservedCitableSourceSchema(Schema):
    source_id = String(required=True)
    title = String(load_default="")
    url = String(load_default="")
    snippet = String(load_default="")
    provider = String(load_default="")
    rank = Integer(load_default=1)
    content_checksum = String(load_default="")
    origin = String(load_default="web_search")
    domain = String(load_default="")
    label = String(load_default="")
    origin_label = String(load_default="Fuente encontrada por búsqueda")


class MarketCompetitorCandidateSchema(Schema):
    # Server-owned deterministic id (never from model JSON).
    candidate_id = String(allow_none=True, load_default=None)
    name = String(required=True)
    country = String(required=True)
    rationale = String(required=True)
    evidence_ids = List(String(), load_default=[])
    # Deprecated: model URLs never accredit (G-18).
    source_urls = List(String(), load_default=[])
    source_urls_meta = List(Nested(SourceUrlMetaSchema), load_default=[])
    source_urls_status = String(allow_none=True, load_default=None)
    source_urls_label = String(allow_none=True, load_default=None)
    citable_sources = List(Nested(CitableSourcePublicSchema), load_default=[])
    confidence = Integer(required=True)
    selectable = Boolean(load_default=True)


class MarketCompetitorDiscoveryOutputSchema(Schema):
    candidates = List(Nested(MarketCompetitorCandidateSchema), required=True)
    warnings = List(String(), required=True)
    reserved_citable_sources = List(Nested(ReservedCitableSourceSchema), load_default=[])


class MarketCompetitorDiscoveryArtifactSchema(Schema):
    id = String(required=True)
    dossier_id = String(allow_none=True)
    agent = String(required=True)
    schema_name = String(required=True)
    schema_version = String(required=True)
    status = String(required=True)
    output = Nested(MarketCompetitorDiscoveryOutputSchema, required=True)
    created_at = String(required=True)
    updated_at = String(required=True)
    version = Integer(required=True)


class MarketCompetitorDiscoveryRunResponseSchema(Schema):
    job = Nested(TenderSearchWizardJobSchema, required=True)
    artifact = Nested(MarketCompetitorDiscoveryArtifactSchema, allow_none=True)


class MarketCompetitorDiscoveryLatestResponseSchema(Schema):
    job = Nested(TenderSearchWizardJobSchema, allow_none=True)
    artifact = Nested(MarketCompetitorDiscoveryArtifactSchema, allow_none=True)


class MarketCompetitorSelectionSchema(Schema):
    # Required on write: server-owned candidate_id (UUID). name is display-only.
    candidate_id = String(required=True)
    name = String(load_default="")  # display-only; not used for identity
    source_ids = List(String(), required=True)
    evidence_ids = List(String(), load_default=[])  # alias accepted, not preferred


class MarketCompetitorAcceptInputSchema(Schema):
    artifact_id = String(required=True)
    dossier_id = String(required=True)
    selected = List(Nested(MarketCompetitorSelectionSchema), required=True)
    expected_version = Integer(allow_none=True, load_default=None)


class MaterializedEvidenceSchema(Schema):
    evidence_id = String(required=True)
    source_id = String(required=True)
    source_kind = String(required=True)
    source_url = String(allow_none=True)
    label = String(load_default="")


class MarketCompetitorAcceptResponseSchema(Schema):
    artifact_id = String(required=True)
    dossier_id = String(required=True)
    materialized = List(Nested(MaterializedEvidenceSchema), required=True)
    count = Integer(required=True)


class MarketActorDiscoveryInputSchema(Schema):
    """Client sends only dossier_id; intent/type/geo come from persisted profile.

    Extra client fields (forged intent/type/geo) are excluded, never trusted.
    """

    dossier_id = String(required=True)

    class Meta:
        unknown = "exclude"


class MarketActorCandidateSchema(Schema):
    candidate_id = String(allow_none=True, load_default=None)
    actor_type = String(required=True)
    organization = String(required=True)
    affiliation = String(load_default="")
    country = String(required=True)
    summary = String(required=True)
    rationale = String(load_default="")
    evidence_ids = List(String(), load_default=[])
    source_urls = List(String(), load_default=[])
    source_urls_meta = List(Nested(SourceUrlMetaSchema), load_default=[])
    source_urls_status = String(allow_none=True, load_default=None)
    source_urls_label = String(allow_none=True, load_default=None)
    citable_sources = List(Nested(CitableSourcePublicSchema), load_default=[])
    confidence = Integer(required=True)
    selectable = Boolean(load_default=True)


class MarketActorDiscoveryOutputSchema(Schema):
    candidates = List(Nested(MarketActorCandidateSchema), required=True)
    warnings = List(String(), required=True)
    reserved_citable_sources = List(Nested(ReservedCitableSourceSchema), load_default=[])


class MarketActorDiscoveryArtifactSchema(Schema):
    id = String(required=True)
    dossier_id = String(allow_none=True)
    agent = String(required=True)
    schema_name = String(required=True)
    schema_version = String(required=True)
    status = String(required=True)
    output = Nested(MarketActorDiscoveryOutputSchema, required=True)
    created_at = String(required=True)
    updated_at = String(required=True)
    version = Integer(required=True)


class MarketActorDiscoveryRunResponseSchema(Schema):
    job = Nested(TenderSearchWizardJobSchema, required=True)
    artifact = Nested(MarketActorDiscoveryArtifactSchema, allow_none=True)


class MarketActorDiscoveryLatestResponseSchema(Schema):
    job = Nested(TenderSearchWizardJobSchema, allow_none=True)
    artifact = Nested(MarketActorDiscoveryArtifactSchema, allow_none=True)


class MarketActorSelectionSchema(Schema):
    candidate_id = String(required=True)
    organization = String(load_default="")
    name = String(load_default="")  # display-only alias
    source_ids = List(String(), required=True)
    evidence_ids = List(String(), load_default=[])


class MarketActorAcceptInputSchema(Schema):
    artifact_id = String(required=True)
    dossier_id = String(required=True)
    selected = List(Nested(MarketActorSelectionSchema), required=True)
    expected_version = Integer(allow_none=True, load_default=None)


class MarketActorMaterializedActorSchema(Schema):
    candidate_id = String(required=True)
    actor_id = String(required=True)
    dossier_actor_id = String(required=True)
    canonical_key = String(required=True)
    identifiers = Dict(keys=String(), values=String(), load_default=dict)
    identity_status = String(required=True)


class MarketActorAcceptResponseSchema(Schema):
    artifact_id = String(required=True)
    dossier_id = String(required=True)
    materialized = List(Nested(MaterializedEvidenceSchema), required=True)
    count = Integer(required=True)
    # G-20-B: durable actors for the selected subset (optional for legacy clients).
    actors = List(Nested(MarketActorMaterializedActorSchema), load_default=list)
    actors_count = Integer(load_default=0)


def _tender_wizard_problem(status: int, *, detail: str, code: str) -> Response:
    response, response_status, headers = problem_response(
        status,
        detail=detail,
        code=code,
    )
    response.status_code = response_status
    response.headers.update(headers)
    return response


def _dossier(dossier_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id, StrategicDossier.tenant_id == g.active_tenant_id
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=write
    ):
        return None
    return dossier


def _audit_source_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item is not None and str(item).strip()]


def serialize_ai_audit_list_item(audit: AIAuditLog) -> dict[str, Any]:
    """Campos de listado: sin inventar; nulos se omiten o quedan como null en JSON."""
    return {
        "id": str(audit.id),
        "dossier_id": str(audit.dossier_id) if audit.dossier_id else None,
        "background_job_id": str(audit.background_job_id) if audit.background_job_id else None,
        "agent": audit.agent,
        "action": audit.action,
        "status": audit.status,
        "error_code": audit.error_code,
        "provider": audit.provider,
        "model": audit.model,
        "input_tokens": audit.input_tokens,
        "output_tokens": audit.output_tokens,
        "cost_micros": audit.actual_cost_micros,
        "currency": audit.currency,
        "latency_ms": audit.latency_ms,
        "attempt_count": audit.attempt_count,
        "source_ids": _audit_source_ids(audit.source_ids),
        "data_classification": audit.data_classification,
        "human_review_state": audit.human_review_state,
        "created_at": audit.created_at.isoformat() if audit.created_at else None,
        "started_at": audit.started_at.isoformat() if audit.started_at else None,
        "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
    }


def serialize_ai_audit_detail(
    audit: AIAuditLog, attempts: list[AIAttempt] | None = None
) -> dict[str, Any]:
    payload = serialize_ai_audit_list_item(audit)
    payload.update(
        {
            "use_case": audit.use_case,
            "prompt": {
                "name": audit.prompt_name,
                "version": audit.prompt_version,
                "hash": audit.prompt_hash.hex() if audit.prompt_hash else None,
            },
            "schema": {"name": audit.schema_name, "version": audit.schema_version},
            "usage": {
                "input_tokens": audit.input_tokens,
                "output_tokens": audit.output_tokens,
                "cost_micros": audit.actual_cost_micros,
                "currency": audit.currency,
            },
            "review_state": audit.human_review_state,
            "attempts": [
                {
                    "number": item.attempt_number,
                    "kind": item.kind,
                    "status": item.status,
                    "input_tokens": item.input_tokens,
                    "output_tokens": item.output_tokens,
                    "cost_micros": item.cost_micros,
                    "latency_ms": item.latency_ms,
                    "error_code": item.error_code,
                }
                for item in (attempts or [])
            ],
        }
    )
    return payload


@bp.post("/dossiers/<uuid:dossier_id>/agents/<string:agent>/runs")
@require_permission("ai.execute")
def enqueue_agent(dossier_id: uuid.UUID, agent: str) -> Any:
    if agent not in AGENT_SCHEMAS:
        return problem_response(404, detail="Agente no disponible.", code="not_found")
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    key = request.headers.get("Idempotency-Key", "")
    try:
        job = enqueue_job(
            f"oracle.ai.{agent}",
            payload={"dossier_id": str(dossier_id)},
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=dossier_id,
            resource_type="strategic_dossier",
            resource_id=dossier_id,
        )
    except ValueError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    return {"job_id": str(job.id), "status": job.status}, 202


def _latest_agent_artifact(dossier_id: uuid.UUID, agent: str) -> AIArtifact | None:
    return db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == agent,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )


def _latest_agent_job(dossier_id: uuid.UUID, agent: str) -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id == dossier_id,
            BackgroundJob.job_type == f"oracle.ai.{agent}",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def _serialize_agent_artifact(artifact: AIArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": str(artifact.id),
        "dossier_id": str(artifact.dossier_id) if artifact.dossier_id else None,
        "agent": artifact.agent,
        "schema_name": artifact.schema_name,
        "schema_version": artifact.schema_version,
        "status": artifact.status,
        "output": artifact.output,
        "audit_log_id": str(artifact.audit_log_id) if artifact.audit_log_id else None,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "version": artifact.version,
    }


@bp.post("/dossiers/<uuid:dossier_id>/intake/runs")
@require_permission("ai.execute")
def enqueue_intake(dossier_id: uuid.UUID) -> Any:
    """Lanza el agente de intake: propone estructura; no muta el expediente."""
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return problem_response(
            428,
            detail="Idempotency-Key es obligatorio para lanzar el análisis de entrada.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{INTAKE_AGENT}",
            payload={"dossier_id": str(dossier_id)},
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=dossier_id,
            resource_type="strategic_dossier",
            resource_id=dossier_id,
        )
    except ValueError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "job": serialize_job(job),
        "artifact": _serialize_agent_artifact(_latest_agent_artifact(dossier_id, INTAKE_AGENT)),
    }, 202


@bp.get("/dossiers/<uuid:dossier_id>/intake/latest")
@require_permission("ai.execute")
def latest_intake(dossier_id: uuid.UUID) -> Any:
    """Última propuesta de intake del expediente (solo lectura; la persona confirma)."""
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    job = _latest_agent_job(dossier_id, INTAKE_AGENT)
    artifact = _latest_agent_artifact(dossier_id, INTAKE_AGENT)
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_agent_artifact(artifact),
    }


def _enqueue_analysis_agent(dossier_id: uuid.UUID, agent: str, *, label: str) -> Any:
    """Encola un agente de análisis: propone entidad; no la crea."""
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return problem_response(
            428,
            detail=f"Idempotency-Key es obligatorio para lanzar el análisis de {label}.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{agent}",
            payload={"dossier_id": str(dossier_id)},
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=dossier_id,
            resource_type="strategic_dossier",
            resource_id=dossier_id,
        )
    except ValueError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "job": serialize_job(job),
        "artifact": _serialize_agent_artifact(_latest_agent_artifact(dossier_id, agent)),
    }, 202


def _latest_analysis_agent(dossier_id: uuid.UUID, agent: str) -> Any:
    """Última propuesta del agente (solo lectura; la persona confirma)."""
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    job = _latest_agent_job(dossier_id, agent)
    artifact = _latest_agent_artifact(dossier_id, agent)
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_agent_artifact(artifact),
    }


class OpportunityOfferDraftSectionPatchSchema(Schema):
    key = String(required=True, validate=validate.Length(min=1, max=80))
    our_response_draft = String(required=True, validate=validate.Length(min=1, max=2000))


class OpportunityOfferDraftPatchSchema(Schema):
    version = Integer(required=False, load_default=None, validate=validate.Range(min=1))
    statement = String(required=False, load_default=None, validate=validate.Length(min=1, max=4000))
    sections = List(
        Nested(OpportunityOfferDraftSectionPatchSchema),
        required=False,
        load_default=None,
    )


def _offer_draft_problem(exc: OfferDraftError):
    return problem_response(exc.status, detail=exc.message, code=exc.code)


def _load_offer_draft(dossier_id: uuid.UUID) -> OpportunityOfferDraft | None:
    return db.session.scalar(
        select(OpportunityOfferDraft).where(
            OpportunityOfferDraft.tenant_id == g.active_tenant_id,
            OpportunityOfferDraft.dossier_id == dossier_id,
        )
    )


@bp.get("/dossiers/<uuid:dossier_id>/opportunity/offer-draft")
@require_permission("ai.execute")
def get_opportunity_offer_draft(dossier_id: uuid.UUID) -> Any:
    """Borrador de oferta durable del expediente (edición humana persistente)."""
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    row = _load_offer_draft(dossier_id)
    if row is None:
        return problem_response(
            404,
            detail="No hay borrador de oferta persistido para este expediente.",
            code="offer_draft_not_found",
        )
    body = serialize_offer_draft(row)
    response = {"draft": body}
    # APIFlask/flask jsonify via dict return
    r = make_response(jsonify(response), 200)
    r.headers["ETag"] = row.etag
    return r


def _serialize_offer_draft_response(
    row: OpportunityOfferDraft, *, created: bool | None = None, status: int = 200
) -> Any:
    body = serialize_offer_draft(row)
    payload: dict[str, Any] = {"draft": body}
    if created is not None:
        payload["created"] = created
    r = make_response(jsonify(payload), status)
    r.headers["ETag"] = row.etag
    return r


@bp.post("/dossiers/<uuid:dossier_id>/opportunity/offer-draft")
@require_permission("ai.execute")
def prepare_opportunity_offer_draft(dossier_id: uuid.UUID) -> Any:
    """Materializa un borrador editable desde el draft_offer calculado del análisis.

    Idempotente: si ya existe borrador durable, lo devuelve sin sobrescribir.
    Bajo carrera en el unique (tenant_id, dossier_id), el perdedor recupera la fila
    existente (sin 500 ni segunda fila).
    """
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")

    existing = _load_offer_draft(dossier_id)
    if existing is not None:
        return _serialize_offer_draft_response(existing, created=False, status=200)

    artifact = _latest_agent_artifact(dossier_id, OPPORTUNITY_AGENT)
    if artifact is None or not isinstance(artifact.output, dict):
        return problem_response(
            422,
            detail=(
                "No hay análisis de oportunidad con borrador calculado. "
                "Ejecuta el análisis con veredicto de encaje."
            ),
            code="draft_offer_missing",
        )
    calculated = artifact.output.get("draft_offer")
    try:
        content = materialize_content_from_calculated(
            calculated if isinstance(calculated, dict) else {}
        )
    except OfferDraftError as exc:
        return _offer_draft_problem(exc)

    actor_id = current_user.id
    now = utc_now()
    row = OpportunityOfferDraft(
        id=uuid.uuid4(),
        tenant_id=g.active_tenant_id,
        dossier_id=dossier_id,
        source_artifact_id=artifact.id,
        version=1,
        etag=make_etag(1),
        content=content,
        last_edited_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.session.add(row)
    append_audit_event(
        db.session,
        action="opportunity.offer_draft.create",
        resource_type="opportunity_offer_draft",
        resource_id=row.id,
        result="success",
        dossier_id=dossier_id,
        metadata={
            "source_artifact_id": str(artifact.id),
            "version": 1,
            "section_count": len(content.get("sections") or []),
        },
    )
    try:
        db.session.commit()
    except IntegrityError:
        # Concurrent prepare: unique (tenant_id, dossier_id) — recover existing row.
        db.session.rollback()
        recovered = _load_offer_draft(dossier_id)
        if recovered is None:
            return problem_response(
                409,
                detail="No se pudo materializar el borrador por conflicto concurrente.",
                code="version_conflict",
            )
        return _serialize_offer_draft_response(recovered, created=False, status=200)

    return _serialize_offer_draft_response(row, created=True, status=201)


@bp.patch("/dossiers/<uuid:dossier_id>/opportunity/offer-draft")
@require_permission("ai.execute")
def patch_opportunity_offer_draft(dossier_id: uuid.UUID) -> Any:
    """Actualiza campos editables del borrador con CAS atómico (version en el UPDATE)."""
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    row = _load_offer_draft(dossier_id)
    if row is None:
        return problem_response(
            404,
            detail="No hay borrador de oferta persistido para este expediente.",
            code="offer_draft_not_found",
        )

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(
            422, detail="El cuerpo debe ser un objeto JSON.", code="schema_validation_failed"
        )
    # Reject client-supplied tenant/actor identities.
    for forbidden in ("tenant_id", "last_edited_by_user_id", "actor_id", "user_id"):
        if forbidden in payload:
            return problem_response(
                422,
                detail="No se aceptan identidades desde el cliente.",
                code="forbidden_field",
            )

    try:
        expected = parse_expected_version(
            body_version=payload.get("version"),
            if_match=request.headers.get("If-Match"),
        )
        if expected is None:
            raise OfferDraftError(
                "Se requiere version o cabecera If-Match para guardar el borrador.",
                code="precondition_required",
                status=428,
            )
        base = row.content if isinstance(row.content, dict) else {}
        next_content = apply_editable_patch(base, payload)
    except OfferDraftVersionConflict as exc:
        return problem_response(
            exc.status,
            detail=exc.message,
            code=exc.code,
            errors={"current_version": exc.current_version},
        )
    except OfferDraftError as exc:
        return _offer_draft_problem(exc)

    before_version = int(expected)
    after_version = before_version + 1
    after_etag = make_etag(after_version)
    now = utc_now()
    actor_id = current_user.id
    tenant_id = g.active_tenant_id

    # Atomic CAS: only one concurrent writer can match version == expected.
    result = db.session.execute(
        cas_update_offer_draft_sql(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            expected_version=before_version,
            next_content=next_content,
            actor_id=actor_id,
            new_version=after_version,
            new_etag=after_etag,
            updated_at=now,
        )
    )
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        db.session.rollback()
        current = _load_offer_draft(dossier_id)
        current_version = int(current.version) if current is not None else before_version
        return problem_response(
            409,
            detail="El borrador ha cambiado; recarga y vuelve a guardar.",
            code="version_conflict",
            errors={"current_version": current_version},
        )

    # Audit only after winning the CAS, same transaction.
    append_audit_event(
        db.session,
        action="opportunity.offer_draft.update",
        resource_type="opportunity_offer_draft",
        resource_id=row.id,
        result="success",
        dossier_id=dossier_id,
        metadata={
            "before_version": before_version,
            "after_version": after_version,
            "source_artifact_id": str(row.source_artifact_id),
        },
    )
    db.session.commit()

    # Re-load post-CAS for response (identity server-owned).
    saved = _load_offer_draft(dossier_id)
    if saved is None:
        return problem_response(
            404,
            detail="No hay borrador de oferta persistido para este expediente.",
            code="offer_draft_not_found",
        )
    return _serialize_offer_draft_response(saved, status=200)


@bp.get("/dossiers/<uuid:dossier_id>/opportunity/offer-draft/export.docx")
@require_permission("ai.execute")
def export_opportunity_offer_draft_docx(dossier_id: uuid.UUID) -> Any:
    """Exporta el borrador durable persistido como DOCX editable (Word).

    Requiere precondición de versión (``version`` query o ``If-Match``). Si el
    servidor tiene otra versión, responde 409 sin regenerar desde artifact.
    Sin fila durable: 404 honesto.
    """
    dossier = _dossier(dossier_id, write=False)
    if dossier is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    row = _load_offer_draft(dossier_id)
    if row is None:
        return problem_response(
            404,
            detail="No hay borrador de oferta persistido para este expediente.",
            code="offer_draft_not_found",
        )

    try:
        expected = parse_expected_version(
            body_version=request.args.get("version"),
            if_match=request.headers.get("If-Match"),
        )
        if expected is None:
            raise OfferDraftError(
                "Se requiere version o cabecera If-Match para exportar el borrador.",
                code="precondition_required",
                status=428,
            )
        if int(row.version) != int(expected):
            raise OfferDraftVersionConflict(current_version=int(row.version))
    except OfferDraftVersionConflict as exc:
        # Audit.result only allows success|denied|failure (not "conflict").
        append_audit_event(
            db.session,
            action="opportunity.offer_draft.export",
            resource_type="opportunity_offer_draft",
            resource_id=row.id,
            result="failure",
            dossier_id=dossier_id,
            metadata={
                "draft_id": str(row.id),
                "dossier_id": str(dossier_id),
                "version": int(row.version),
                "requested_version": int(expected) if expected is not None else None,
                "format": "docx",
                "result": "conflict",
                "error_code": "version_conflict",
            },
        )
        db.session.commit()
        return problem_response(
            exc.status,
            detail=exc.message,
            code=exc.code,
            errors={"current_version": exc.current_version},
        )
    except OfferDraftError as exc:
        return _offer_draft_problem(exc)

    content = row.content if isinstance(row.content, dict) else {}
    evidence_ids = collect_evidence_ids(content)
    lookup = load_evidence_citation_lookup(
        tenant_id=g.active_tenant_id,
        dossier_id=dossier_id,
        evidence_ids=evidence_ids,
    )
    citations = resolve_evidence_citations(evidence_ids, lookup=lookup)
    exported_at = utc_now()
    try:
        payload = build_offer_draft_docx(
            content,
            dossier_title=str(dossier.title or "Expediente"),
            version=int(row.version),
            exported_at=exported_at,
            citations=citations,
        )
    except OfferDraftError as exc:
        append_audit_event(
            db.session,
            action="opportunity.offer_draft.export",
            resource_type="opportunity_offer_draft",
            resource_id=row.id,
            result="failure",
            dossier_id=dossier_id,
            metadata={
                "draft_id": str(row.id),
                "dossier_id": str(dossier_id),
                "version": int(row.version),
                "format": "docx",
                "result": "failure",
                "error_code": exc.code,
            },
        )
        db.session.commit()
        return _offer_draft_problem(exc)

    filename = sanitize_export_filename(
        str(dossier.title or "Expediente"), version=int(row.version)
    )
    append_audit_event(
        db.session,
        action="opportunity.offer_draft.export",
        resource_type="opportunity_offer_draft",
        resource_id=row.id,
        result="success",
        dossier_id=dossier_id,
        metadata={
            "draft_id": str(row.id),
            "dossier_id": str(dossier_id),
            "version": int(row.version),
            "format": "docx",
            "result": "success",
            "byte_size": len(payload),
            "filename": filename,
            # Never include document body / statement / sections.
        },
    )
    db.session.commit()

    response = Response(payload, mimetype=DOCX_MEDIA_TYPE)
    response.headers["Content-Disposition"] = content_disposition_attachment(filename)
    response.headers["Content-Length"] = str(len(payload))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["ETag"] = row.etag
    return response


@bp.post("/dossiers/<uuid:dossier_id>/opportunity/runs")
@require_permission("ai.execute")
def enqueue_opportunity_analysis(dossier_id: uuid.UUID) -> Any:
    """Lanza el agente de oportunidad: propone; no crea la oportunidad."""
    return _enqueue_analysis_agent(dossier_id, OPPORTUNITY_AGENT, label="oportunidad")


@bp.get("/dossiers/<uuid:dossier_id>/opportunity/latest")
@require_permission("ai.execute")
def latest_opportunity_analysis(dossier_id: uuid.UUID) -> Any:
    """Última propuesta de oportunidad del expediente (solo lectura; la persona confirma)."""
    return _latest_analysis_agent(dossier_id, OPPORTUNITY_AGENT)


@bp.post("/dossiers/<uuid:dossier_id>/risk/runs")
@require_permission("ai.execute")
def enqueue_risk_analysis(dossier_id: uuid.UUID) -> Any:
    """Lanza el agente de riesgo: propone; no crea el riesgo."""
    return _enqueue_analysis_agent(dossier_id, RISK_AGENT, label="riesgo")


@bp.get("/dossiers/<uuid:dossier_id>/risk/latest")
@require_permission("ai.execute")
def latest_risk_analysis(dossier_id: uuid.UUID) -> Any:
    """Última propuesta de riesgo del expediente (solo lectura; la persona confirma)."""
    return _latest_analysis_agent(dossier_id, RISK_AGENT)


@bp.post("/dossiers/<uuid:dossier_id>/actor-partnership/runs")
@require_permission("ai.execute")
def enqueue_actor_partnership(dossier_id: uuid.UUID) -> Any:
    """Lanza priorización de actores: propone scores; no muta el expediente."""
    return _enqueue_analysis_agent(
        dossier_id, ACTOR_PARTNERSHIP_AGENT, label="priorización de actores"
    )


@bp.get("/dossiers/<uuid:dossier_id>/actor-partnership/latest")
@require_permission("ai.execute")
def latest_actor_partnership(dossier_id: uuid.UUID) -> Any:
    """Última propuesta de priorización de actores (solo lectura; la persona confirma)."""
    return _latest_analysis_agent(dossier_id, ACTOR_PARTNERSHIP_AGENT)


@bp.post("/dossiers/<uuid:dossier_id>/entity-resolution/runs")
@require_permission("ai.execute")
def enqueue_entity_resolution(dossier_id: uuid.UUID) -> Any:
    """Lanza resolución de entidades: propone match; no fusiona actores."""
    return _enqueue_analysis_agent(
        dossier_id, ENTITY_RESOLUTION_AGENT, label="resolución de entidades"
    )


@bp.get("/dossiers/<uuid:dossier_id>/entity-resolution/latest")
@require_permission("ai.execute")
def latest_entity_resolution(dossier_id: uuid.UUID) -> Any:
    """Última propuesta de resolución de entidades (solo lectura; la persona confirma)."""
    return _latest_analysis_agent(dossier_id, ENTITY_RESOLUTION_AGENT)


def _wizard_answers(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("answers debe ser una lista.")
    answers: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Cada respuesta debe ser un objeto.")
        question_id = str(item.get("question_id", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question_id or not answer:
            continue
        if len(question_id) > 120 or len(answer) > 2000:
            raise ValueError("Respuesta demasiado larga.")
        answers.append({"question_id": question_id, "answer": answer})
    return answers[:20]


def _latest_wizard_artifact(dossier_id: uuid.UUID) -> AIArtifact | None:
    return db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == DOSSIER_COMPLETION_WIZARD_AGENT,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )


def _latest_wizard_job(dossier_id: uuid.UUID) -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id == dossier_id,
            BackgroundJob.job_type == f"oracle.ai.{DOSSIER_COMPLETION_WIZARD_AGENT}",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def _serialize_wizard_artifact(artifact: AIArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "id": str(artifact.id),
        "dossier_id": str(artifact.dossier_id) if artifact.dossier_id else None,
        "agent": artifact.agent,
        "schema_name": artifact.schema_name,
        "schema_version": artifact.schema_version,
        "status": artifact.status,
        "output": artifact.output,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "version": artifact.version,
    }


def _latest_tender_search_artifact() -> AIArtifact | None:
    return db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id.is_(None),
            AIArtifact.agent == TENDER_SEARCH_WIZARD_AGENT,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )


def _latest_tender_search_job() -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id.is_(None),
            BackgroundJob.job_type == f"oracle.ai.{TENDER_SEARCH_WIZARD_AGENT}",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def _tender_search_input(value: Any) -> tuple[str, str | None]:
    if not isinstance(value, dict):
        raise ValueError("Payload no válido.")
    description = " ".join(str(value.get("description") or "").split())
    comparable = " ".join(str(value.get("comparable") or "").split()) or None
    if len(description) < 10 or len(description) > 4_000:
        raise ValueError("La descripción debe tener entre 10 y 4000 caracteres.")
    if comparable is not None and len(comparable) > 250:
        raise ValueError("La empresa comparable no puede superar 250 caracteres.")
    return description, comparable


@bp.post("/tender-search-wizard/runs")
@require_permission("ai.execute")
@bp.input(TenderSearchWizardInputSchema)
@bp.output(TenderSearchWizardRunResponseSchema, status_code=202)
def enqueue_tender_search_wizard(json_data: dict[str, Any]) -> Any:
    try:
        description, comparable = _tender_search_input(json_data)
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return _tender_wizard_problem(
            428,
            detail="Idempotency-Key es obligatorio para generar un plan.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{TENDER_SEARCH_WIZARD_AGENT}",
            payload={
                "mode": "initial",
                "description": description,
                "comparable": comparable,
            },
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            resource_type=TENDER_SEARCH_WIZARD_TARGET,
            resource_id=g.active_tenant_id,
        )
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    return {
        "job": serialize_job(job),
        "artifact": _serialize_wizard_artifact(_latest_tender_search_artifact()),
    }, 202


@bp.get("/tender-search-wizard/latest")
@require_permission("ai.execute")
@bp.output(TenderSearchWizardLatestResponseSchema)
def latest_tender_search_wizard() -> Any:
    job = _latest_tender_search_job()
    artifact = _latest_tender_search_artifact()
    accepted_profile = (
        get_artifact_acceptance(db.session(), artifact.id) if artifact is not None else None
    )
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_wizard_artifact(artifact),
        "input": (
            {
                "mode": job.input_payload.get("mode", "initial"),
                "description": job.input_payload.get("description"),
                "comparable": job.input_payload.get("comparable"),
                "profile_id": job.input_payload.get("profile_id"),
            }
            if job
            else None
        ),
        "acceptance": (
            {
                "profile_id": str(accepted_profile.id),
                "version": accepted_profile.version,
                "accepted_at": accepted_profile.last_accepted_at.isoformat(),
            }
            if accepted_profile is not None
            else None
        ),
    }


def _latest_market_discovery_artifact() -> AIArtifact | None:
    return db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id.is_(None),
            AIArtifact.agent == MARKET_COMPETITOR_DISCOVERY_AGENT,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )


def _latest_market_discovery_job() -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id.is_(None),
            BackgroundJob.job_type == f"oracle.ai.{MARKET_COMPETITOR_DISCOVERY_AGENT}",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def _serialize_market_discovery_artifact(artifact: AIArtifact | None) -> dict[str, Any] | None:
    """Serialize latest discovery: candidates + reserved sources needed for UI.

    Never leaks secrets or sources from other tenants/artifacts. Marks
    candidates without evidence_ids as non-selectable. Strips provider/checksum
    from per-candidate public sources; reserved block keeps audit fields for
    materialization clients that need them.
    """

    base = _serialize_wizard_artifact(artifact)
    if base is None:
        return None
    output = base.get("output")
    if not isinstance(output, dict):
        return base
    reserved_raw = output.get("reserved_citable_sources") or []
    reserved_public: list[dict[str, Any]] = []
    if isinstance(reserved_raw, list):
        for item in reserved_raw:
            if not isinstance(item, dict):
                continue
            reserved_public.append(
                {
                    "source_id": str(item.get("source_id") or ""),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                    "provider": str(item.get("provider") or ""),
                    "rank": int(item.get("rank") or 0) if item.get("rank") is not None else 0,
                    "content_checksum": str(item.get("content_checksum") or ""),
                    "origin": str(item.get("origin") or "web_search"),
                    "domain": str(item.get("domain") or ""),
                    "label": str(item.get("label") or item.get("title") or ""),
                    "origin_label": str(
                        item.get("origin_label") or "Fuente encontrada por búsqueda"
                    ),
                }
            )
    candidates_out: list[dict[str, Any]] = []
    for cand in output.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        evidence_ids = [
            str(item)
            for item in (cand.get("evidence_ids") or [])
            if item is not None and str(item).strip()
        ]
        public_sources = []
        for src in cand.get("citable_sources") or []:
            if not isinstance(src, dict):
                continue
            public_sources.append(
                {
                    "source_id": str(src.get("source_id") or ""),
                    "title": str(src.get("title") or ""),
                    "url": str(src.get("url") or ""),
                    "snippet": str(src.get("snippet") or ""),
                    "rank": int(src.get("rank") or 0) if src.get("rank") is not None else 0,
                    "domain": str(src.get("domain") or ""),
                    "label": str(src.get("label") or src.get("title") or ""),
                    "origin": str(src.get("origin") or "web_search"),
                    "origin_label": str(
                        src.get("origin_label") or "Fuente encontrada por búsqueda"
                    ),
                }
            )
        # If citable_sources missing but evidence_ids present, project from reserved.
        if not public_sources and evidence_ids:
            by_id = {r["source_id"]: r for r in reserved_public}
            for sid in evidence_ids:
                if sid in by_id:
                    r = by_id[sid]
                    public_sources.append(
                        {
                            "source_id": r["source_id"],
                            "title": r["title"],
                            "url": r["url"],
                            "snippet": r["snippet"],
                            "rank": r["rank"],
                            "domain": r["domain"],
                            "label": r["label"],
                            "origin": r["origin"],
                            "origin_label": r["origin_label"],
                        }
                    )
        selectable = len(evidence_ids) > 0 and len(public_sources) > 0
        raw_cid = cand.get("candidate_id")
        candidate_id = None
        if raw_cid is not None and str(raw_cid).strip():
            try:
                candidate_id = str(uuid.UUID(str(raw_cid)))
            except (ValueError, TypeError, AttributeError):
                candidate_id = None
        candidates_out.append(
            {
                "candidate_id": candidate_id,
                "name": str(cand.get("name") or ""),
                "country": str(cand.get("country") or ""),
                "rationale": str(cand.get("rationale") or ""),
                "evidence_ids": evidence_ids,
                "source_urls": [],  # never surface model URLs as citations
                "source_urls_meta": [],
                "source_urls_status": None,
                "source_urls_label": None,
                "citable_sources": public_sources,
                "confidence": int(cand.get("confidence") or 0),
                "selectable": selectable and candidate_id is not None,
            }
        )
    base["output"] = {
        "candidates": candidates_out,
        "warnings": list(output.get("warnings") or []),
        "reserved_citable_sources": reserved_public,
    }
    return base


def _market_discovery_input(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Payload no válido.")

    def _clean_list(
        field: str, *, limit: int, upper: bool = False, lower: bool = False
    ) -> list[str]:
        items = value.get(field) or []
        if not isinstance(items, list):
            raise ValueError(f"{field} debe ser una lista.")
        cleaned = [" ".join(str(item).split())[:300] for item in items]
        cleaned = [item for item in cleaned if item]
        if upper:
            cleaned = [item.upper() for item in cleaned]
        if lower:
            cleaned = [item.lower() for item in cleaned]
        return list(dict.fromkeys(cleaned))[:limit]

    description = " ".join(str(value.get("description") or "").split())
    if len(description) < 10 or len(description) > 4_000:
        raise ValueError("La descripción debe tener entre 10 y 4000 caracteres.")
    knowledge = str(value.get("competitors_knowledge") or "known").strip().lower()
    if knowledge not in {"known", "unknown", "not_seeking"}:
        raise ValueError("competitors_knowledge debe ser known, unknown o not_seeking.")
    known_names = _clean_list("known_names", limit=50) if knowledge == "known" else []
    return {
        "description": description,
        "own_offer": " ".join(str(value.get("own_offer") or "").split())[:1000],
        "sectors": _clean_list("sectors", limit=10),
        "countries": _clean_list("countries", limit=27, upper=True),
        "languages": _clean_list("languages", limit=10, lower=True),
        "known_names": known_names,
        "competitors_knowledge": knowledge,
    }


@bp.post("/market-competitor-discovery/runs")
@require_permission("ai.execute")
@bp.input(MarketCompetitorDiscoveryInputSchema)
@bp.output(MarketCompetitorDiscoveryRunResponseSchema, status_code=202)
def enqueue_market_competitor_discovery(json_data: dict[str, Any]) -> Any:
    try:
        payload = _market_discovery_input(json_data)
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return _tender_wizard_problem(
            428,
            detail="Idempotency-Key es obligatorio para proponer competidores.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{MARKET_COMPETITOR_DISCOVERY_AGENT}",
            payload=payload,
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            resource_type=MARKET_COMPETITOR_DISCOVERY_TARGET,
            resource_id=g.active_tenant_id,
        )
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    return {
        "job": serialize_job(job),
        "artifact": _serialize_market_discovery_artifact(_latest_market_discovery_artifact()),
    }, 202


@bp.get("/market-competitor-discovery/latest")
@require_permission("ai.execute")
@bp.output(MarketCompetitorDiscoveryLatestResponseSchema)
def latest_market_competitor_discovery() -> Any:
    job = _latest_market_discovery_job()
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_market_discovery_artifact(_latest_market_discovery_artifact()),
    }


@bp.post("/market-competitor-discovery/accept")
@require_permission("ai.execute")
@bp.input(MarketCompetitorAcceptInputSchema)
@bp.output(MarketCompetitorAcceptResponseSchema)
def accept_market_competitor_discovery(json_data: dict[str, Any]) -> Any:
    """Human gate: materialize selected reserved sources into Evidence for a dossier.

    Requires artifact_id + dossier_id + selected[{candidate_id, source_ids}].
    Fail-closed on cross-tenant, non-candidate status, version drift, alien UUIDs.
    Idempotent: two retries do not duplicate Evidence rows.
    """

    from opn_oracle.ai.market_materialize import MaterializeError, accept_and_materialize

    try:
        artifact_id = uuid.UUID(str(json_data["artifact_id"]))
        dossier_id = uuid.UUID(str(json_data["dossier_id"]))
    except (KeyError, TypeError, ValueError):
        return _tender_wizard_problem(
            422,
            detail="artifact_id y dossier_id deben ser UUID válidos.",
            code="validation_error",
        )
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=True
    ):
        return _tender_wizard_problem(
            404,
            detail="Expediente no disponible.",
            code="not_found",
        )
    if str(dossier.dossier_type or "") != "market":
        return _tender_wizard_problem(
            422,
            detail="Solo un expediente de tipo market puede recibir evidencias de discovery.",
            code="dossier_not_market",
        )
    selected = json_data.get("selected") or []
    if not isinstance(selected, list):
        return _tender_wizard_problem(
            422,
            detail="selected debe ser una lista.",
            code="validation_error",
        )
    expected_version = json_data.get("expected_version")
    # Actor/tenant authority is exclusively TenantContext (service has no
    # actor parameter). Defensive: context actor must match the authenticated
    # principal; mismatch fails closed with zero rows written.
    # Client-supplied actor_id / reviewer_user_id in JSON are never read.
    from opn_oracle.tenants.context import get_tenant_context

    context = get_tenant_context(required=False)
    if context is None or context.actor_id is None:
        return _tender_wizard_problem(
            401,
            detail="Se requiere un actor autenticado en el servidor para registrar la aceptación.",
            code="actor_required",
        )
    if context.actor_id != current_user.id:
        return _tender_wizard_problem(
            401,
            detail="El actor del contexto de servidor no coincide con el usuario autenticado.",
            code="actor_context_mismatch",
        )
    try:
        result = accept_and_materialize(
            artifact_id=artifact_id,
            dossier_id=dossier_id,
            selected=selected,
            expected_version=int(expected_version) if expected_version is not None else None,
            agent=MARKET_COMPETITOR_DISCOVERY_AGENT,
        )
    except MaterializeError as error:
        return _tender_wizard_problem(
            error.status,
            detail=error.detail,
            code=error.code,
        )
    return result


def _latest_market_actor_discovery_artifact(dossier_id: uuid.UUID) -> AIArtifact | None:
    """Latest actor-discovery artifact for one market dossier (never tenant-wide)."""

    return db.session.scalar(
        select(AIArtifact)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == MARKET_ACTOR_DISCOVERY_AGENT,
        )
        .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
        .limit(1)
    )


def _latest_market_actor_discovery_job(dossier_id: uuid.UUID) -> BackgroundJob | None:
    """Latest actor-discovery job for one market dossier (never tenant-wide)."""

    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id == dossier_id,
            BackgroundJob.job_type == f"oracle.ai.{MARKET_ACTOR_DISCOVERY_AGENT}",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )


def _serialize_market_actor_discovery_artifact(
    artifact: AIArtifact | None,
) -> dict[str, Any] | None:
    """Serialize actor discovery: organization/type/country + closed citations."""

    base = _serialize_wizard_artifact(artifact)
    if base is None:
        return None
    output = base.get("output")
    if not isinstance(output, dict):
        return base
    reserved_raw = output.get("reserved_citable_sources") or []
    reserved_public: list[dict[str, Any]] = []
    if isinstance(reserved_raw, list):
        for item in reserved_raw:
            if not isinstance(item, dict):
                continue
            reserved_public.append(
                {
                    "source_id": str(item.get("source_id") or ""),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                    "provider": str(item.get("provider") or ""),
                    "rank": int(item.get("rank") or 0) if item.get("rank") is not None else 0,
                    "content_checksum": str(item.get("content_checksum") or ""),
                    "origin": str(item.get("origin") or "web_search"),
                    "domain": str(item.get("domain") or ""),
                    "label": str(item.get("label") or item.get("title") or ""),
                    "origin_label": str(
                        item.get("origin_label") or "Fuente encontrada por búsqueda"
                    ),
                }
            )
    candidates_out: list[dict[str, Any]] = []
    for cand in output.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        evidence_ids = [
            str(item)
            for item in (cand.get("evidence_ids") or [])
            if item is not None and str(item).strip()
        ]
        public_sources = []
        for src in cand.get("citable_sources") or []:
            if not isinstance(src, dict):
                continue
            public_sources.append(
                {
                    "source_id": str(src.get("source_id") or ""),
                    "title": str(src.get("title") or ""),
                    "url": str(src.get("url") or ""),
                    "snippet": str(src.get("snippet") or ""),
                    "rank": int(src.get("rank") or 0) if src.get("rank") is not None else 0,
                    "domain": str(src.get("domain") or ""),
                    "label": str(src.get("label") or src.get("title") or ""),
                    "origin": str(src.get("origin") or "web_search"),
                    "origin_label": str(
                        src.get("origin_label") or "Fuente encontrada por búsqueda"
                    ),
                }
            )
        if not public_sources and evidence_ids:
            by_id = {r["source_id"]: r for r in reserved_public}
            for sid in evidence_ids:
                if sid in by_id:
                    r = by_id[sid]
                    public_sources.append(
                        {
                            "source_id": r["source_id"],
                            "title": r["title"],
                            "url": r["url"],
                            "snippet": r["snippet"],
                            "rank": r["rank"],
                            "domain": r["domain"],
                            "label": r["label"],
                            "origin": r["origin"],
                            "origin_label": r["origin_label"],
                        }
                    )
        selectable = len(evidence_ids) > 0 and len(public_sources) > 0
        raw_cid = cand.get("candidate_id")
        candidate_id = None
        if raw_cid is not None and str(raw_cid).strip():
            try:
                candidate_id = str(uuid.UUID(str(raw_cid)))
            except (ValueError, TypeError, AttributeError):
                candidate_id = None
        summary = str(cand.get("summary") or cand.get("rationale") or "")
        # G-20-B structured identity/ranking snapshot (immutable from artifact output).
        ids_raw = cand.get("ids") if isinstance(cand.get("ids"), dict) else {}
        ids_out = {
            str(k): str(v)
            for k, v in ids_raw.items()
            if k in {"rnsr", "ror", "hal_structure", "cordis_org", "idref"} and v
        }
        identity_status = str(cand.get("identity_status") or "").strip().lower()
        score_bd = cand.get("score_breakdown") if isinstance(cand.get("score_breakdown"), dict) else {}
        score_out = {
            str(k): float(v)
            for k, v in score_bd.items()
            if isinstance(v, (int, float))
        }
        origin_labels = {
            "structured": "Fuente estructurada (CORDIS/HAL/RNSR/ROR)",
            "web_search": "Fuente encontrada por búsqueda",
        }
        for src in public_sources:
            origin = str(src.get("origin") or "web_search")
            if origin in origin_labels and (
                not src.get("origin_label")
                or src.get("origin_label") == "Fuente encontrada por búsqueda"
            ):
                src["origin_label"] = origin_labels[origin]
        candidates_out.append(
            {
                "candidate_id": candidate_id,
                "actor_type": str(cand.get("actor_type") or ""),
                "organization": str(cand.get("organization") or ""),
                "affiliation": str(cand.get("affiliation") or ""),
                "country": str(cand.get("country") or ""),
                "summary": summary,
                "rationale": str(cand.get("rationale") or summary),
                "evidence_ids": evidence_ids,
                "source_urls": [],
                "source_urls_meta": [],
                "source_urls_status": None,
                "source_urls_label": None,
                "citable_sources": public_sources,
                "confidence": int(cand.get("confidence") or 0),
                "selectable": selectable and candidate_id is not None,
                "ids": ids_out,
                "identity_status": identity_status,
                "identity_reasons": [
                    str(x) for x in (cand.get("identity_reasons") or []) if x
                ][:20],
                "unresolved_reason": (
                    str(cand.get("unresolved_reason"))
                    if cand.get("unresolved_reason")
                    else None
                ),
                "rank": int(cand["rank"]) if cand.get("rank") is not None else None,
                "score": float(cand["score"]) if cand.get("score") is not None else None,
                "score_breakdown": score_out,
                "ranking_reasons": [
                    str(x) for x in (cand.get("ranking_reasons") or []) if x
                ][:30],
                "affiliations": [
                    str(x) for x in (cand.get("affiliations") or []) if x
                ][:20],
                "parent_organization": (
                    str(cand.get("parent_organization"))
                    if cand.get("parent_organization")
                    else None
                ),
                "merge_rules_applied": [
                    str(x) for x in (cand.get("merge_rules_applied") or []) if x
                ][:20],
                "candidate_key": (
                    str(cand.get("candidate_key")) if cand.get("candidate_key") else None
                ),
            }
        )
    base["output"] = {
        "candidates": candidates_out,
        "warnings": list(output.get("warnings") or []),
        "reserved_citable_sources": reserved_public,
    }
    return base


def _market_actor_discovery_payload_from_dossier(dossier: StrategicDossier) -> dict[str, Any]:
    """Build run payload exclusively from persisted market profile + dossier geo.

    Client-supplied intent/type/countries/languages/known_names are ignored.
    Never concatenates title/goal/description into discovery_intent.
    """

    from opn_oracle.ai.context import DISCOVERY_INTENT_MAX_LEN, DISCOVERY_INTENT_MIN_LEN
    from opn_oracle.ai.schemas import MARKET_ACTOR_TYPES

    if str(dossier.dossier_type or "") != "market":
        raise ValueError(
            "Solo un expediente de tipo market puede lanzar descubrimiento de actores."
        )

    profile = dossier.profile_config if isinstance(dossier.profile_config, dict) else {}
    intent = " ".join(str(profile.get("discovery_intent") or "").split())
    if len(intent) < DISCOVERY_INTENT_MIN_LEN or len(intent) > DISCOVERY_INTENT_MAX_LEN:
        raise ValueError(
            "El expediente no tiene discovery_intent válido en el perfil "
            f"(entre {DISCOVERY_INTENT_MIN_LEN} y {DISCOVERY_INTENT_MAX_LEN} caracteres)."
        )
    actor_type = str(profile.get("discovery_actor_type") or "").strip().lower()
    if actor_type not in MARKET_ACTOR_TYPES:
        raise ValueError(
            "El expediente no tiene discovery_actor_type válido en el perfil "
            "(company, research_group, technology_center, regulator o potential_customer)."
        )

    def _clean_strings(
        raw: Any, *, limit: int, upper: bool = False, lower: bool = False
    ) -> list[str]:
        if not isinstance(raw, list):
            return []
        cleaned = [" ".join(str(item).split())[:300] for item in raw]
        cleaned = [item for item in cleaned if item]
        if upper:
            cleaned = [item.upper() for item in cleaned]
        if lower:
            cleaned = [item.lower() for item in cleaned]
        return list(dict.fromkeys(cleaned))[:limit]

    known_raw = profile.get("discovery_known_names") or []
    countries = _clean_strings(dossier.geography or [], limit=27, upper=True)
    languages = _clean_strings(dossier.languages or [], limit=10, lower=True)
    return {
        "dossier_id": str(dossier.id),
        "discovery_intent": intent,
        "actor_type": actor_type,
        "countries": countries,
        "languages": languages,
        # Explicit objective exclusions only — never inject partners/regulators.
        "known_names": _clean_strings(known_raw, limit=50),
    }


# Kept for unit tests that validate free-text bounds independently of a dossier.
def _market_actor_discovery_input(value: Any) -> dict[str, Any]:
    """Validate a raw intent payload shape (tests / internal). Prefer dossier path."""

    if not isinstance(value, dict):
        raise ValueError("Payload no válido.")

    def _clean_list(
        field: str, *, limit: int, upper: bool = False, lower: bool = False
    ) -> list[str]:
        items = value.get(field) or []
        if not isinstance(items, list):
            raise ValueError(f"{field} debe ser una lista.")
        cleaned = [" ".join(str(item).split())[:300] for item in items]
        cleaned = [item for item in cleaned if item]
        if upper:
            cleaned = [item.upper() for item in cleaned]
        if lower:
            cleaned = [item.lower() for item in cleaned]
        return list(dict.fromkeys(cleaned))[:limit]

    from opn_oracle.ai.context import DISCOVERY_INTENT_MAX_LEN, DISCOVERY_INTENT_MIN_LEN
    from opn_oracle.ai.schemas import MARKET_ACTOR_TYPES

    intent = " ".join(str(value.get("discovery_intent") or "").split())
    if len(intent) < DISCOVERY_INTENT_MIN_LEN or len(intent) > DISCOVERY_INTENT_MAX_LEN:
        raise ValueError(
            f"discovery_intent debe tener entre {DISCOVERY_INTENT_MIN_LEN} y "
            f"{DISCOVERY_INTENT_MAX_LEN} caracteres."
        )
    actor_type = str(value.get("actor_type") or "").strip().lower()
    if actor_type not in MARKET_ACTOR_TYPES:
        raise ValueError(
            "actor_type debe ser company, research_group, technology_center, "
            "regulator o potential_customer."
        )
    return {
        "discovery_intent": intent,
        "actor_type": actor_type,
        "countries": _clean_list("countries", limit=27, upper=True),
        "languages": _clean_list("languages", limit=10, lower=True),
        "known_names": _clean_list("known_names", limit=50),
    }


@bp.post("/market-actor-discovery/runs")
@require_permission("ai.execute")
@bp.input(MarketActorDiscoveryInputSchema)
@bp.output(MarketActorDiscoveryRunResponseSchema, status_code=202)
def enqueue_market_actor_discovery(json_data: dict[str, Any]) -> Any:
    """Enqueue actor discovery for a market dossier using server-owned profile fields.

    Request body is only ``dossier_id``. Intent, type, known_names, geography and
    languages are loaded from the accessible market dossier; client forgeries are
    ignored. Job/artifact are scoped to that dossier (resource_type=strategic_dossier).
    """

    try:
        dossier_id = uuid.UUID(str(json_data["dossier_id"]))
    except (KeyError, TypeError, ValueError):
        return _tender_wizard_problem(
            422,
            detail="dossier_id debe ser un UUID válido.",
            code="validation_error",
        )
    dossier = _dossier(dossier_id, write=True)
    if dossier is None:
        return _tender_wizard_problem(
            404,
            detail="Expediente no disponible.",
            code="not_found",
        )
    try:
        payload = _market_actor_discovery_payload_from_dossier(dossier)
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return _tender_wizard_problem(
            428,
            detail="Idempotency-Key es obligatorio para proponer actores.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{MARKET_ACTOR_DISCOVERY_AGENT}",
            payload=payload,
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=dossier.id,
            resource_type="strategic_dossier",
            resource_id=dossier.id,
        )
    except ValueError as error:
        return _tender_wizard_problem(
            422,
            detail=str(error),
            code="validation_error",
        )
    return {
        "job": serialize_job(job),
        "artifact": _serialize_market_actor_discovery_artifact(
            _latest_market_actor_discovery_artifact(dossier.id)
        ),
    }, 202


@bp.get("/market-actor-discovery/latest")
@require_permission("ai.execute")
@bp.output(MarketActorDiscoveryLatestResponseSchema)
def latest_market_actor_discovery() -> Any:
    """Return latest job/artifact for one dossier; never a tenant-wide result."""

    raw = (request.args.get("dossier_id") or "").strip()
    if not raw:
        return _tender_wizard_problem(
            422,
            detail="dossier_id es obligatorio para consultar el descubrimiento de actores.",
            code="validation_error",
        )
    try:
        dossier_id = uuid.UUID(raw)
    except (TypeError, ValueError):
        return _tender_wizard_problem(
            422,
            detail="dossier_id debe ser un UUID válido.",
            code="validation_error",
        )
    dossier = _dossier(dossier_id, write=False)
    if dossier is None:
        return _tender_wizard_problem(
            404,
            detail="Expediente no disponible.",
            code="not_found",
        )
    job = _latest_market_actor_discovery_job(dossier_id)
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_market_actor_discovery_artifact(
            _latest_market_actor_discovery_artifact(dossier_id)
        ),
    }


@bp.post("/market-actor-discovery/accept")
@require_permission("ai.execute")
@bp.input(MarketActorAcceptInputSchema)
@bp.output(MarketActorAcceptResponseSchema)
def accept_market_actor_discovery(json_data: dict[str, Any]) -> Any:
    """Human gate for actor discovery; refuses competitor artifacts (cross-agent)."""

    from opn_oracle.ai.market_materialize import MaterializeError, accept_and_materialize

    try:
        artifact_id = uuid.UUID(str(json_data["artifact_id"]))
        dossier_id = uuid.UUID(str(json_data["dossier_id"]))
    except (KeyError, TypeError, ValueError):
        return _tender_wizard_problem(
            422,
            detail="artifact_id y dossier_id deben ser UUID válidos.",
            code="validation_error",
        )
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(
        db.session(), dossier, current_user.id, write=True
    ):
        return _tender_wizard_problem(
            404,
            detail="Expediente no disponible.",
            code="not_found",
        )
    if str(dossier.dossier_type or "") != "market":
        return _tender_wizard_problem(
            422,
            detail="Solo un expediente de tipo market puede recibir evidencias de discovery.",
            code="dossier_not_market",
        )
    selected = json_data.get("selected") or []
    if not isinstance(selected, list):
        return _tender_wizard_problem(
            422,
            detail="selected debe ser una lista.",
            code="validation_error",
        )
    expected_version = json_data.get("expected_version")
    from opn_oracle.tenants.context import get_tenant_context

    context = get_tenant_context(required=False)
    if context is None or context.actor_id is None:
        return _tender_wizard_problem(
            401,
            detail="Se requiere un actor autenticado en el servidor para registrar la aceptación.",
            code="actor_required",
        )
    if context.actor_id != current_user.id:
        return _tender_wizard_problem(
            401,
            detail="El actor del contexto de servidor no coincide con el usuario autenticado.",
            code="actor_context_mismatch",
        )
    try:
        result = accept_and_materialize(
            artifact_id=artifact_id,
            dossier_id=dossier_id,
            selected=selected,
            expected_version=int(expected_version) if expected_version is not None else None,
            agent=MARKET_ACTOR_DISCOVERY_AGENT,
        )
    except MaterializeError as error:
        return _tender_wizard_problem(
            error.status,
            detail=error.detail,
            code=error.code,
        )
    return result


@bp.post("/dossiers/<uuid:dossier_id>/completion-wizard/runs")
@require_permission("ai.execute")
def enqueue_completion_wizard(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return problem_response(422, detail="Payload no válido.", code="validation_error")
    try:
        answers = _wizard_answers(payload.get("answers"))
    except ValueError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    key = request.headers.get("Idempotency-Key", "")
    if not key:
        return problem_response(
            428,
            detail="Idempotency-Key es obligatorio para lanzar una ronda.",
            code="precondition_required",
        )
    try:
        job = enqueue_job(
            f"oracle.ai.{DOSSIER_COMPLETION_WIZARD_AGENT}",
            payload={
                "dossier_id": str(dossier_id),
                "answers": answers,
                "requested_at": datetime.now(UTC).isoformat(),
            },
            idempotency_key=key,
            requested_by_user_id=current_user.id,
            dossier_id=dossier_id,
            resource_type="strategic_dossier",
            resource_id=dossier_id,
        )
    except ValueError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    return {
        "job": serialize_job(job),
        "artifact": _serialize_wizard_artifact(_latest_wizard_artifact(dossier_id)),
    }, 202


@bp.get("/dossiers/<uuid:dossier_id>/completion-wizard/latest")
@require_permission("ai.execute")
def latest_completion_wizard(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    job = _latest_wizard_job(dossier_id)
    return {
        "job": serialize_job(job) if job else None,
        "artifact": _serialize_wizard_artifact(_latest_wizard_artifact(dossier_id)),
        "answers": job.input_payload.get("answers", []) if job else [],
    }


@bp.get("/audits/<uuid:audit_id>")
@require_permission("audit.read")
def get_audit(audit_id: uuid.UUID) -> Any:
    audit = db.session.scalar(
        select(AIAuditLog).where(
            AIAuditLog.id == audit_id, AIAuditLog.tenant_id == g.active_tenant_id
        )
    )
    if audit is None or (
        audit.dossier_id is not None and _dossier(audit.dossier_id, write=False) is None
    ):
        return problem_response(404, detail="Auditoría no disponible.", code="not_found")
    attempts = list(
        db.session.scalars(
            select(AIAttempt)
            .where(
                AIAttempt.audit_log_id == audit.id,
                AIAttempt.tenant_id == g.active_tenant_id,
            )
            .order_by(AIAttempt.attempt_number)
        )
    )
    return serialize_ai_audit_detail(audit, attempts)


@bp.post("/artifacts/<uuid:artifact_id>/reviews")
@require_permission("ai.review")
def review_artifact(artifact_id: uuid.UUID) -> Any:
    artifact = db.session.scalar(
        select(AIArtifact)
        .where(AIArtifact.id == artifact_id, AIArtifact.tenant_id == g.active_tenant_id)
        .with_for_update()
    )
    if (
        artifact is None
        or artifact.dossier_id is None
        or _dossier(artifact.dossier_id, write=True) is None
    ):
        return problem_response(404, detail="Artefacto no disponible.", code="not_found")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get("decision") not in {
        "accepted",
        "rejected",
        "changes_requested",
    }:
        return problem_response(
            422, detail="Decisión de revisión no válida.", code="validation_error"
        )
    override = payload.get("override", {})
    if not isinstance(override, dict):
        return problem_response(422, detail="Override no válido.", code="validation_error")
    review = AIHumanReview(
        tenant_id=g.active_tenant_id,
        artifact_id=artifact.id,
        reviewer_user_id=current_user.id,
        decision=payload["decision"],
        reason=str(payload.get("reason", ""))[:4000],
        override=override,
    )
    artifact.status = "valid" if review.decision == "accepted" else "rejected"
    audit = db.session.get(AIAuditLog, artifact.audit_log_id)
    if audit is not None:
        audit.human_review_state = review.decision
    db.session.add(review)
    db.session.commit()
    return {"review_id": str(review.id), "artifact_status": artifact.status}, 201


@public_bp.post("/signals/<uuid:signal_id>/retriage")
@require_permission("ai.execute")
def retriage_signal(signal_id: uuid.UUID) -> Any:
    link = db.session.scalar(
        select(DossierSignal).where(
            DossierSignal.signal_id == signal_id, DossierSignal.tenant_id == g.active_tenant_id
        )
    )
    if link is None or _dossier(link.dossier_id, write=True) is None:
        return problem_response(404, detail="Señal no disponible.", code="not_found")
    key = request.headers.get(
        "Idempotency-Key", f"retriage-{link.id}-{link.updated_at.isoformat()}"
    )
    job = enqueue_job(
        "oracle.ai.signal_triage",
        payload={"dossier_id": str(link.dossier_id), "signal_id": str(signal_id)},
        idempotency_key=key,
        requested_by_user_id=current_user.id,
        dossier_id=link.dossier_id,
        resource_type="signal",
        resource_id=signal_id,
    )
    return {"job_id": str(job.id), "status": job.status}, 202


@public_bp.post("/insights/<uuid:insight_id>/feedback")
@require_permission("dossier.write")
def insight_feedback(insight_id: uuid.UUID) -> Any:
    insight = db.session.scalar(
        select(Insight).where(Insight.id == insight_id, Insight.tenant_id == g.active_tenant_id)
    )
    if insight is None or _dossier(insight.dossier_id, write=True) is None:
        return problem_response(404, detail="Insight no disponible.", code="not_found")
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return problem_response(422, detail="Feedback no válido.", code="validation_error")
    correction = payload.get("correction", {})
    if not isinstance(correction, dict):
        return problem_response(422, detail="Corrección no válida.", code="validation_error")
    row = Feedback(
        tenant_id=g.active_tenant_id,
        dossier_id=insight.dossier_id,
        target_type="insight",
        target_id=insight.id,
        rating=payload.get("rating"),
        correction=correction,
        comment=str(payload.get("comment", ""))[:4000],
        actor_user_id=current_user.id,
    )
    db.session.add(row)
    db.session.commit()
    return {"feedback_id": str(row.id)}, 201


@public_bp.post("/ai-jobs/<uuid:job_id>/review")
@require_permission("ai.review")
def review_ai_job(job_id: uuid.UUID) -> Any:
    artifact = db.session.scalar(
        select(AIArtifact)
        .join(AIAuditLog)
        .where(AIAuditLog.background_job_id == job_id, AIAuditLog.tenant_id == g.active_tenant_id)
    )
    if artifact is None:
        return problem_response(404, detail="Job IA no disponible.", code="not_found")
    return review_artifact(artifact.id)


@public_bp.get("/ai-audit")
@require_permission("audit.read")
def list_ai_audit() -> Any:
    """Listado de ejecuciones IA del tenant con filtros opcionales.

    Query params:
      - status: pending|running|succeeded|failed|denied
      - agent: nombre de agente exacto
      - dossier_id: UUID de expediente (404 si no es accesible)
    Orden por defecto: fallidas/denegadas primero, luego created_at desc.
    """
    status_filter = (request.args.get("status") or "").strip() or None
    agent_filter = (request.args.get("agent") or "").strip() or None
    dossier_raw = (request.args.get("dossier_id") or "").strip() or None

    query = select(AIAuditLog).where(AIAuditLog.tenant_id == g.active_tenant_id)

    if dossier_raw is not None:
        try:
            dossier_id = uuid.UUID(dossier_raw)
        except ValueError:
            return problem_response(
                422, detail="dossier_id no es un UUID válido.", code="validation_error"
            )
        if _dossier(dossier_id, write=False) is None:
            return problem_response(404, detail="Expediente no disponible.", code="not_found")
        query = query.where(AIAuditLog.dossier_id == dossier_id)

    allowed_status = {"pending", "running", "succeeded", "failed", "denied"}
    if status_filter is not None:
        if status_filter not in allowed_status:
            return problem_response(
                422, detail="Estado de auditoría no válido.", code="validation_error"
            )
        query = query.where(AIAuditLog.status == status_filter)
    if agent_filter is not None:
        query = query.where(AIAuditLog.agent == agent_filter)

    # Fallidas primero (es lo que se audita); luego denegadas; resto por fecha.
    failure_rank = case(
        (AIAuditLog.status == "failed", 0),
        (AIAuditLog.status == "denied", 1),
        else_=2,
    )
    rows = list(
        db.session.scalars(query.order_by(failure_rank, AIAuditLog.created_at.desc()).limit(200))
    )
    # Aislamiento: sin expediente → visible en el tenant; con expediente → solo si accesible.
    visible = [
        row
        for row in rows
        if row.dossier_id is None or _dossier(row.dossier_id, write=False) is not None
    ]
    return {"items": [serialize_ai_audit_list_item(row) for row in visible]}
