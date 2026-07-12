"""Versioned contextual Oracle summary for a single dossier."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from flask import g
from flask_login import current_user
from sqlalchemy import func, select, update

from opn_oracle.ai.context import build_dossier_situation_context
from opn_oracle.ai.models import AIArtifact, AIContextSnapshot
from opn_oracle.ai.schemas import DossierSituationSummaryOutput
from opn_oracle.ai.service import execute_agent
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.models import Evidence, Feedback, LivingSummary
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

SUMMARY_AGENT = "dossier_situation_summary"
SUMMARY_JOB = "oracle.dossier_summary.refresh"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _validated_summary_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Rehydrate JSONB with JSON semantics so strict UUID/date fields remain valid."""

    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return DossierSituationSummaryOutput.model_validate_json(encoded).model_dump(mode="json")


def _collect_evidence_ids(value: Any) -> set[uuid.UUID]:
    if isinstance(value, dict):
        cited: set[uuid.UUID] = set()
        for key, child in value.items():
            if key == "evidence_ids" and isinstance(child, list):
                for item in child:
                    try:
                        cited.add(uuid.UUID(str(item)))
                    except ValueError:
                        continue
            else:
                cited.update(_collect_evidence_ids(child))
        return cited
    if isinstance(value, list):
        return {item for child in value for item in _collect_evidence_ids(child)}
    return set()


def _evidence_citations(ids: set[uuid.UUID]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = list(
        db.session.scalars(
            select(Evidence).where(Evidence.tenant_id == g.active_tenant_id, Evidence.id.in_(ids))
        )
    )
    return [
        {
            "id": str(row.id),
            "tenant_id": str(row.tenant_id),
            "source_kind": row.source_kind,
            "source_url": row.source_url,
            "locator": row.locator,
            "extract": row.extract[:500],
            "classification": row.classification,
        }
        for row in rows
    ]


def _artifact_query(dossier_id: uuid.UUID) -> Any:
    return (
        select(AIArtifact, AIAuditLog)
        .join(AIAuditLog, AIAuditLog.id == AIArtifact.audit_log_id)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == SUMMARY_AGENT,
        )
    )


def serialize_summary_artifact(artifact: AIArtifact, audit: AIAuditLog) -> dict[str, Any]:
    cited = _collect_evidence_ids(artifact.output)
    return {
        "id": str(artifact.id),
        "tenant_id": str(artifact.tenant_id),
        "dossier_id": str(artifact.dossier_id),
        "version": artifact.version,
        "status": artifact.status,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "output": artifact.output,
        "citations": _evidence_citations(cited),
        "audit": {
            "id": str(audit.id),
            "tenant_id": str(audit.tenant_id),
            "provider": audit.provider,
            "model": audit.model,
            "prompt_name": audit.prompt_name,
            "prompt_version": audit.prompt_version,
            "prompt_hash": audit.prompt_hash.hex(),
            "context_hash": audit.context_hash.hex() if audit.context_hash else None,
            "input_tokens": audit.input_tokens,
            "output_tokens": audit.output_tokens,
            "cost_micros": audit.actual_cost_micros,
            "latency_ms": audit.latency_ms,
            "status": audit.status,
        },
    }


def get_current_summary(dossier_id: uuid.UUID) -> dict[str, Any]:
    living = db.session.scalar(
        select(LivingSummary).where(
            LivingSummary.tenant_id == g.active_tenant_id,
            LivingSummary.dossier_id == dossier_id,
        )
    )
    row = db.session.execute(
        _artifact_query(dossier_id)
        .where(AIArtifact.status == "valid")
        .order_by(AIArtifact.version.desc(), AIArtifact.created_at.desc())
        .limit(1)
    ).first()
    job = db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.dossier_id == dossier_id,
            BackgroundJob.job_type == SUMMARY_JOB,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    generation_trigger = living.summary.get("generation_trigger") if living else None
    if generation_trigger not in {"manual", "nightly"}:
        generation_trigger = None
    if row is None:
        return {
            "state": "empty",
            "summary": None,
            "living_summary_version": living.version if living else None,
            "generation_trigger": generation_trigger,
            "job": serialize_job(job) if job else None,
        }
    artifact, audit = row
    return {
        "state": "ready",
        "summary": serialize_summary_artifact(artifact, audit),
        "living_summary_version": living.version if living else None,
        "generation_trigger": generation_trigger,
        "last_refreshed_at": living.last_refreshed_at.isoformat()
        if living and living.last_refreshed_at
        else None,
        "job": serialize_job(job) if job else None,
    }


def enqueue_summary_refresh(
    dossier_id: uuid.UUID,
    *,
    trigger: str,
    invocation_key: str,
    requested_by_user_id: uuid.UUID | None,
    scheduled_for: str | None = None,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> BackgroundJob:
    """Queue exactly one generation for a user action or nightly occurrence.

    The previous material-hash key reused successful generations indefinitely, so a
    manual refresh could not create a new version when the dossier had not changed.
    A client idempotency key now deduplicates only the same click/request, while the
    nightly scheduler uses one stable occurrence key per calendar night.
    """

    if trigger not in {"manual", "nightly"}:
        raise ValueError("Origen de actualización no válido.")
    normalized_key = invocation_key.strip()
    if not normalized_key or len(normalized_key) > 500:
        raise ValueError("La clave de actualización no es válida.")
    digest = hashlib.sha256(normalized_key.encode()).hexdigest()[:32]
    key = f"oracle-summary:{trigger}:{dossier_id}:{digest}"
    tenant_id = require_tenant_id()
    reused = db.session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.dossier_id == dossier_id,
            BackgroundJob.job_type == SUMMARY_JOB,
            BackgroundJob.idempotency_key == key,
        )
    )
    job = enqueue_job(
        SUMMARY_JOB,
        payload={
            "dossier_id": str(dossier_id),
            "trigger": trigger,
            **({"scheduled_for": scheduled_for} if scheduled_for else {}),
        },
        idempotency_key=key,
        requested_by_user_id=requested_by_user_id,
        dossier_id=dossier_id,
        resource_type="oracle_summary",
        resource_id=dossier_id,
        correlation_id=correlation_id,
        request_id=request_id,
    )
    append_audit_event(
        db.session,
        action="oracle_summary.refresh_requested",
        resource_type="oracle_summary",
        resource_id=dossier_id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        correlation_id=correlation_id,
        metadata={
            "job_id": str(job.id),
            "trigger": trigger,
            "scheduled_for": scheduled_for,
            "reused": reused is not None,
        },
    )
    db.session.commit()
    return job


def process_summary_refresh(dossier_id: uuid.UUID, job: BackgroundJob) -> dict[str, Any]:
    result = execute_agent(
        agent=SUMMARY_AGENT,
        dossier_id=dossier_id,
        job=job,
        context_factory=lambda max_tokens: build_dossier_situation_context(
            dossier_id, max_tokens=max_tokens
        ),
        target_type="oracle_summary",
        target_id=dossier_id,
    )
    artifact_id = uuid.UUID(result["artifact_id"])
    artifact = db.session.scalar(
        select(AIArtifact)
        .where(AIArtifact.id == artifact_id, AIArtifact.tenant_id == job.tenant_id)
        .with_for_update()
    )
    if artifact is None:
        raise ValueError("Artefacto de resumen no disponible.")
    output = _validated_summary_payload(artifact.output)
    existing_version = (
        db.session.scalar(
            select(func.coalesce(func.max(AIArtifact.version), 0)).where(
                AIArtifact.tenant_id == job.tenant_id,
                AIArtifact.dossier_id == dossier_id,
                AIArtifact.agent == SUMMARY_AGENT,
                AIArtifact.status.in_(("valid", "superseded")),
            )
        )
        or 0
    )
    db.session.execute(
        update(AIArtifact)
        .where(
            AIArtifact.tenant_id == job.tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == SUMMARY_AGENT,
            AIArtifact.status == "valid",
        )
        .values(status="superseded")
    )
    artifact.status = "valid"
    artifact.version = int(existing_version) + 1
    now = datetime.now(UTC)
    living = db.session.scalar(
        select(LivingSummary)
        .where(LivingSummary.tenant_id == job.tenant_id, LivingSummary.dossier_id == dossier_id)
        .with_for_update()
    )
    summary_payload = {
        "kind": "dossier_situation_summary",
        "generation_trigger": str(job.input_payload.get("trigger", "manual")),
        "artifact_id": str(artifact.id),
        "headline": output["headline"],
        "executive_summary": output["executive_summary"],
        "situation_status": output["situation_status"],
        "confidence": output["confidence"],
        "evidence_coverage": output["evidence_coverage"],
        "output_hash": hashlib.sha256(_canonical(output)).hexdigest(),
    }
    if living is None:
        living = LivingSummary(
            tenant_id=job.tenant_id,
            dossier_id=dossier_id,
            version=1,
            summary=summary_payload,
            last_refreshed_at=now,
        )
        db.session.add(living)
    else:
        living.version += 1
        living.summary = summary_payload
        living.last_refreshed_at = now
    append_audit_event(
        db.session,
        action="oracle_summary.published",
        resource_type="oracle_summary",
        resource_id=artifact.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "version": artifact.version,
            "job_id": str(job.id),
            "trigger": str(job.input_payload.get("trigger", "manual")),
        },
    )
    db.session.commit()
    return {"artifact_id": str(artifact.id), "version": artifact.version, "status": "valid"}


def list_summary_versions(dossier_id: uuid.UUID) -> dict[str, Any]:
    rows = list(
        db.session.execute(
            _artifact_query(dossier_id).order_by(
                AIArtifact.version.desc(), AIArtifact.created_at.desc()
            )
        )
    )
    return {"data": [serialize_summary_artifact(artifact, audit) for artifact, audit in rows]}


def get_summary_version(dossier_id: uuid.UUID, version_id: uuid.UUID) -> dict[str, Any] | None:
    row = db.session.execute(
        _artifact_query(dossier_id).where(AIArtifact.id == version_id).limit(1)
    ).first()
    if row is None:
        return None
    artifact, audit = row
    snapshot = db.session.scalar(
        select(AIContextSnapshot).where(
            AIContextSnapshot.audit_log_id == audit.id,
            AIContextSnapshot.tenant_id == g.active_tenant_id,
        )
    )
    serialized = serialize_summary_artifact(artifact, audit)
    serialized["snapshot"] = {
        "context_hash": snapshot.context_hash.hex() if snapshot else None,
        "source_manifest": snapshot.source_manifest if snapshot else {},
        "estimated_tokens": snapshot.estimated_tokens if snapshot else 0,
        "redaction_summary": snapshot.redaction_summary if snapshot else {},
        "injection_indicators": snapshot.injection_indicators if snapshot else [],
    }
    return serialized


def create_summary_feedback(
    dossier_id: uuid.UUID, version_id: uuid.UUID, payload: dict[str, Any]
) -> Feedback:
    artifact = db.session.scalar(
        select(AIArtifact).where(
            AIArtifact.id == version_id,
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == SUMMARY_AGENT,
        )
    )
    if artifact is None:
        raise ValueError("Version de resumen no disponible.")
    correction = payload.get("correction", {})
    if not isinstance(correction, dict):
        raise ValueError("correction debe ser un objeto.")
    rating = payload.get("rating")
    if rating is not None and not isinstance(rating, int):
        raise ValueError("rating debe ser entero.")
    row = Feedback(
        tenant_id=g.active_tenant_id,
        dossier_id=dossier_id,
        target_type="oracle_summary",
        target_id=version_id,
        rating=rating,
        correction=correction,
        comment=str(payload.get("comment", ""))[:4000],
        actor_user_id=current_user.id,
    )
    db.session.add(row)
    append_audit_event(
        db.session,
        action="oracle_summary.feedback_created",
        resource_type="oracle_summary",
        resource_id=version_id,
        dossier_id=dossier_id,
        result="success",
        request_id=getattr(g, "request_id", None),
        correlation_id=getattr(g, "correlation_id", None),
    )
    db.session.commit()
    return row
