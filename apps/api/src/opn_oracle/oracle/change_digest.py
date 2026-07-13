"""Strategic weekly-change digest for the product changes screen."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import g
from sqlalchemy import func, select, update

from opn_oracle.ai.context import build_weekly_change_context
from opn_oracle.ai.models import AIArtifact
from opn_oracle.ai.schemas import WeeklyChangeOutput
from opn_oracle.ai.service import execute_agent
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.models import StatusHistory, StrategicDossier
from opn_oracle.oracle.policy import dossier_access_clause
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

WEEKLY_CHANGE_AGENT = "weekly_change"
WEEKLY_CHANGE_JOB = "oracle.weekly_change.refresh"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _validated_payload(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return WeeklyChangeOutput.model_validate_json(encoded).model_dump(mode="json")


def default_period() -> tuple[datetime, datetime]:
    end = datetime.now(UTC)
    return end - timedelta(days=7), end


def parse_period(payload: dict[str, Any] | None = None) -> tuple[datetime, datetime]:
    value = payload or {}
    start_raw = value.get("period_start")
    end_raw = value.get("period_end")
    if not start_raw and not end_raw:
        return default_period()
    end = _parse_datetime(end_raw) if end_raw else datetime.now(UTC)
    start = _parse_datetime(start_raw) if start_raw else end - timedelta(days=7)
    if end <= start:
        raise ValueError("El periodo de cambios no es válido.")
    return start.astimezone(UTC), end.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def resolve_digest_dossier_id(
    *,
    user_id: uuid.UUID,
    requested_dossier_id: uuid.UUID | None,
) -> uuid.UUID | None:
    access = dossier_access_clause(tenant_id=g.active_tenant_id, user_id=user_id)
    if requested_dossier_id is not None:
        return db.session.scalar(
            select(StrategicDossier.id).where(
                StrategicDossier.id == requested_dossier_id,
                StrategicDossier.tenant_id == g.active_tenant_id,
                access,
            )
        )
    recent = db.session.scalar(
        select(StatusHistory.dossier_id)
        .join(StrategicDossier, StrategicDossier.id == StatusHistory.dossier_id)
        .where(StatusHistory.tenant_id == g.active_tenant_id, access)
        .order_by(StatusHistory.created_at.desc())
        .limit(1)
    )
    if recent is not None:
        return recent
    return db.session.scalar(
        select(StrategicDossier.id)
        .where(StrategicDossier.tenant_id == g.active_tenant_id, access)
        .order_by(StrategicDossier.updated_at.desc())
        .limit(1)
    )


def _artifact_query(dossier_id: uuid.UUID) -> Any:
    return (
        select(AIArtifact, AIAuditLog)
        .join(AIAuditLog, AIAuditLog.id == AIArtifact.audit_log_id)
        .where(
            AIArtifact.tenant_id == g.active_tenant_id,
            AIArtifact.dossier_id == dossier_id,
            AIArtifact.agent == WEEKLY_CHANGE_AGENT,
            AIArtifact.target_type == "weekly_change",
            AIArtifact.target_id == dossier_id,
        )
    )


def serialize_digest_artifact(artifact: AIArtifact, audit: AIAuditLog) -> dict[str, Any]:
    return {
        "id": str(artifact.id),
        "tenant_id": str(artifact.tenant_id),
        "dossier_id": str(artifact.dossier_id),
        "version": artifact.version,
        "status": artifact.status,
        "created_at": artifact.created_at.isoformat(),
        "updated_at": artifact.updated_at.isoformat(),
        "output": artifact.output,
        "audit": {
            "id": str(audit.id),
            "provider": audit.provider,
            "model": audit.model,
            "prompt_name": audit.prompt_name,
            "prompt_version": audit.prompt_version,
            "status": audit.status,
            "input_tokens": audit.input_tokens,
            "output_tokens": audit.output_tokens,
            "latency_ms": audit.latency_ms,
        },
    }


def get_current_digest(dossier_id: uuid.UUID) -> dict[str, Any]:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == g.active_tenant_id,
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
            BackgroundJob.job_type == WEEKLY_CHANGE_JOB,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    return {
        "state": "ready" if row else "empty",
        "scope": "dossier",
        "dossier_id": str(dossier_id),
        "dossier_title": dossier.title if dossier else "",
        "digest": serialize_digest_artifact(*row) if row else None,
        "job": serialize_job(job) if job else None,
    }


def enqueue_weekly_change_digest(
    dossier_id: uuid.UUID,
    *,
    period_start: datetime,
    period_end: datetime,
    requested_by_user_id: uuid.UUID | None,
    invocation_key: str,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> BackgroundJob:
    normalized_key = invocation_key.strip()
    if not normalized_key:
        raise ValueError("La clave de digest no es válida.")
    digest = hashlib.sha256(normalized_key.encode()).hexdigest()[:32]
    key = f"weekly-change:{dossier_id}:{digest}"
    tenant_id = require_tenant_id()
    reused = db.session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.job_type == WEEKLY_CHANGE_JOB,
            BackgroundJob.idempotency_key == key,
        )
    )
    job = enqueue_job(
        WEEKLY_CHANGE_JOB,
        payload={
            "dossier_id": str(dossier_id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
        idempotency_key=key,
        requested_by_user_id=requested_by_user_id,
        dossier_id=dossier_id,
        resource_type="weekly_change",
        resource_id=dossier_id,
        correlation_id=correlation_id,
        request_id=request_id,
    )
    append_audit_event(
        db.session,
        action="weekly_change.refresh_requested",
        resource_type="weekly_change",
        resource_id=dossier_id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        correlation_id=correlation_id,
        metadata={
            "job_id": str(job.id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "reused": reused is not None,
        },
    )
    db.session.commit()
    return job


def process_weekly_change_digest(dossier_id: uuid.UUID, job: BackgroundJob) -> dict[str, Any]:
    try:
        period_start, period_end = parse_period(job.input_payload)
    except ValueError as error:
        raise ValueError(str(error)) from error
    result = execute_agent(
        agent=WEEKLY_CHANGE_AGENT,
        dossier_id=dossier_id,
        job=job,
        context_factory=lambda max_tokens: build_weekly_change_context(
            dossier_id,
            period_start=period_start,
            period_end=period_end,
            max_tokens=max_tokens,
        ),
        target_type="weekly_change",
        target_id=dossier_id,
    )
    artifact_id = uuid.UUID(result["artifact_id"])
    artifact = db.session.scalar(
        select(AIArtifact)
        .where(AIArtifact.id == artifact_id, AIArtifact.tenant_id == job.tenant_id)
        .with_for_update()
    )
    if artifact is None:
        raise ValueError("Artefacto de digest no disponible.")
    output = _validated_payload(artifact.output)
    existing_version = (
        db.session.scalar(
            select(func.coalesce(func.max(AIArtifact.version), 0)).where(
                AIArtifact.tenant_id == job.tenant_id,
                AIArtifact.agent == WEEKLY_CHANGE_AGENT,
                AIArtifact.target_type == "weekly_change",
                AIArtifact.target_id == dossier_id,
                AIArtifact.status.in_(("valid", "superseded")),
            )
        )
        or 0
    )
    db.session.execute(
        update(AIArtifact)
        .where(
            AIArtifact.tenant_id == job.tenant_id,
            AIArtifact.agent == WEEKLY_CHANGE_AGENT,
            AIArtifact.target_type == "weekly_change",
            AIArtifact.target_id == dossier_id,
            AIArtifact.status == "valid",
        )
        .values(status="superseded")
    )
    artifact.status = "valid"
    artifact.version = int(existing_version) + 1
    artifact.output = output
    append_audit_event(
        db.session,
        action="weekly_change.published",
        resource_type="weekly_change",
        resource_id=artifact.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={"version": artifact.version, "job_id": str(job.id)},
    )
    db.session.commit()
    return {"artifact_id": str(artifact.id), "version": artifact.version, "status": "valid"}
