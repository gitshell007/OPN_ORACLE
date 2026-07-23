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
from flask import Response, g, request
from flask_login import current_user
from marshmallow import validate
from sqlalchemy import select

from opn_oracle.ai.models import AIArtifact, AIHumanReview
from opn_oracle.ai.schemas import AGENT_SCHEMAS
from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.models import DossierSignal, Feedback, Insight, StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.procurement_search_profiles import get_artifact_acceptance

bp = APIBlueprint("ai", __name__, url_prefix="/api/v1/ai", tag="IA")
public_bp = APIBlueprint("ai_contract", __name__, url_prefix="/api/v1", tag="IA")
DOSSIER_COMPLETION_WIZARD_AGENT = "dossier_completion_wizard"
TENDER_SEARCH_WIZARD_AGENT = "tender_search_wizard"
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
    return {
        "id": str(audit.id),
        "dossier_id": str(audit.dossier_id),
        "agent": audit.agent,
        "status": audit.status,
        "provider": audit.provider,
        "model": audit.model,
        "prompt": {
            "name": audit.prompt_name,
            "version": audit.prompt_version,
            "hash": audit.prompt_hash.hex(),
        },
        "schema": {"name": audit.schema_name, "version": audit.schema_version},
        "usage": {
            "input_tokens": audit.input_tokens,
            "output_tokens": audit.output_tokens,
            "cost_micros": audit.actual_cost_micros,
        },
        "review_state": audit.human_review_state,
    }


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
    rows = db.session.scalars(
        select(AIAuditLog)
        .where(AIAuditLog.tenant_id == g.active_tenant_id)
        .order_by(AIAuditLog.created_at.desc())
        .limit(100)
    )
    visible = [
        row
        for row in rows
        if row.dossier_id is not None and _dossier(row.dossier_id, write=False) is not None
    ]
    return {
        "items": [
            {
                "id": str(row.id),
                "dossier_id": str(row.dossier_id),
                "agent": row.agent,
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in visible
        ]
    }
