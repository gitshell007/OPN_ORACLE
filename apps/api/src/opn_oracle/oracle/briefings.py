"""AI-generated meeting briefings published as durable meeting material."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from flask import g
from sqlalchemy import func, select, update

from opn_oracle.ai.context import build_meeting_briefing_context
from opn_oracle.ai.models import AIArtifact
from opn_oracle.ai.schemas import MeetingBriefingOutput
from opn_oracle.ai.service import execute_agent
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, serialize_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.models import Briefing, Meeting
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

MEETING_BRIEFING_AGENT = "meeting_briefing"
MEETING_BRIEFING_JOB = "oracle.meeting_briefing.refresh"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _validated_payload(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return MeetingBriefingOutput.model_validate_json(encoded).model_dump(mode="json")


def serialize_briefing_response(
    briefing: Briefing | None,
    job: BackgroundJob | None,
) -> dict[str, Any]:
    return {
        "briefing": _serialize_briefing(briefing) if briefing else None,
        "job": serialize_job(job) if job else None,
    }


def _serialize_briefing(row: Briefing) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "meeting_id": str(row.meeting_id),
        "version": row.version,
        "content": row.content,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def latest_briefing(meeting_id: uuid.UUID) -> Briefing | None:
    return db.session.scalar(
        select(Briefing)
        .where(Briefing.tenant_id == g.active_tenant_id, Briefing.meeting_id == meeting_id)
        .order_by(Briefing.version.desc(), Briefing.created_at.desc())
        .limit(1)
    )


def latest_briefing_job(meeting_id: uuid.UUID) -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.tenant_id == g.active_tenant_id,
            BackgroundJob.job_type == MEETING_BRIEFING_JOB,
            BackgroundJob.resource_type == "meeting",
            BackgroundJob.resource_id == meeting_id,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )


def enqueue_meeting_briefing(
    meeting: Meeting,
    *,
    requested_by_user_id: uuid.UUID | None,
    invocation_key: str,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> BackgroundJob:
    normalized_key = invocation_key.strip()
    if not normalized_key:
        raise ValueError("La clave de preparación no es válida.")
    digest = hashlib.sha256(normalized_key.encode()).hexdigest()[:32]
    key = f"meeting-briefing:{meeting.id}:{digest}"
    tenant_id = require_tenant_id()
    reused = db.session.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.job_type == MEETING_BRIEFING_JOB,
            BackgroundJob.idempotency_key == key,
        )
    )
    job = enqueue_job(
        MEETING_BRIEFING_JOB,
        payload={"meeting_id": str(meeting.id), "dossier_id": str(meeting.dossier_id)},
        idempotency_key=key,
        requested_by_user_id=requested_by_user_id,
        dossier_id=meeting.dossier_id,
        resource_type="meeting",
        resource_id=meeting.id,
        correlation_id=correlation_id,
        request_id=request_id,
    )
    append_audit_event(
        db.session,
        action="meeting_briefing.refresh_requested",
        resource_type="meeting",
        resource_id=meeting.id,
        dossier_id=meeting.dossier_id,
        result="success",
        request_id=request_id,
        correlation_id=correlation_id,
        metadata={"job_id": str(job.id), "reused": reused is not None},
    )
    db.session.commit()
    return job


def process_meeting_briefing(meeting_id: uuid.UUID, job: BackgroundJob) -> dict[str, Any]:
    meeting = db.session.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.tenant_id == job.tenant_id)
    )
    if meeting is None:
        raise ValueError("Reunión no disponible.")
    result = execute_agent(
        agent=MEETING_BRIEFING_AGENT,
        dossier_id=meeting.dossier_id,
        job=job,
        context_factory=lambda max_tokens: build_meeting_briefing_context(
            meeting_id, max_tokens=max_tokens
        ),
        target_type="meeting_briefing",
        target_id=meeting_id,
    )
    artifact_id = uuid.UUID(result["artifact_id"])
    artifact = db.session.scalar(
        select(AIArtifact)
        .where(AIArtifact.id == artifact_id, AIArtifact.tenant_id == job.tenant_id)
        .with_for_update()
    )
    if artifact is None:
        raise ValueError("Artefacto de preparación no disponible.")
    output = _validated_payload(artifact.output)
    existing_version = (
        db.session.scalar(
            select(func.coalesce(func.max(AIArtifact.version), 0)).where(
                AIArtifact.tenant_id == job.tenant_id,
                AIArtifact.agent == MEETING_BRIEFING_AGENT,
                AIArtifact.target_type == "meeting_briefing",
                AIArtifact.target_id == meeting_id,
                AIArtifact.status.in_(("valid", "superseded")),
            )
        )
        or 0
    )
    db.session.execute(
        update(AIArtifact)
        .where(
            AIArtifact.tenant_id == job.tenant_id,
            AIArtifact.agent == MEETING_BRIEFING_AGENT,
            AIArtifact.target_type == "meeting_briefing",
            AIArtifact.target_id == meeting_id,
            AIArtifact.status == "valid",
        )
        .values(status="superseded")
    )
    artifact.status = "valid"
    artifact.version = int(existing_version) + 1
    audit = db.session.scalar(
        select(AIAuditLog).where(
            AIAuditLog.id == artifact.audit_log_id,
            AIAuditLog.tenant_id == job.tenant_id,
        )
    )
    briefing = Briefing(
        tenant_id=job.tenant_id,
        meeting_id=meeting_id,
        version=artifact.version,
        content={
            "kind": "meeting_briefing",
            "state": "ready",
            "artifact_id": str(artifact.id),
            "audit_log_id": str(audit.id) if audit else None,
            "job_id": str(job.id),
            "output_hash": hashlib.sha256(_canonical(output)).hexdigest(),
            "output": output,
        },
    )
    db.session.add(briefing)
    db.session.flush()
    append_audit_event(
        db.session,
        action="meeting_briefing.published",
        resource_type="briefing",
        resource_id=briefing.id,
        dossier_id=meeting.dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "version": artifact.version,
            "job_id": str(job.id),
            "artifact_id": str(artifact.id),
        },
    )
    db.session.commit()
    return {
        "artifact_id": str(artifact.id),
        "briefing_id": str(briefing.id),
        "version": artifact.version,
        "status": "valid",
    }
