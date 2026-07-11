"""Explicit enqueue, audit and human-review APIs for AI artifacts."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint
from flask import g, request
from flask_login import current_user
from sqlalchemy import select

from opn_oracle.ai.models import AIArtifact, AIHumanReview
from opn_oracle.ai.schemas import AGENT_SCHEMAS
from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job
from opn_oracle.oracle.jobs import AIAuditLog
from opn_oracle.oracle.models import DossierSignal, Feedback, Insight, StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible

bp = APIBlueprint("ai", __name__, url_prefix="/api/v1/ai", tag="IA")
public_bp = APIBlueprint("ai_contract", __name__, url_prefix="/api/v1", tag="IA")


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


@bp.get("/audits/<uuid:audit_id>")
@require_permission("audit.read")
def get_audit(audit_id: uuid.UUID) -> Any:
    audit = db.session.scalar(
        select(AIAuditLog).where(
            AIAuditLog.id == audit_id, AIAuditLog.tenant_id == g.active_tenant_id
        )
    )
    if audit is None or audit.dossier_id is None or _dossier(audit.dossier_id, write=False) is None:
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
    if artifact is None or _dossier(artifact.dossier_id, write=True) is None:
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
