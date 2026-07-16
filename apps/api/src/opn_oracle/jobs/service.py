"""Durable job creation, transitions and safe serialization."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from celery import Celery
from flask import current_app
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from opn_oracle.extensions import db
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.tenants.context import require_tenant_id

TASK_QUEUES = {
    "oracle.signal.sync_monitor": "signals",
    "oracle.signal.triage": "signals",
    "oracle.memory.refresh": "ai",
    "oracle.dossier_summary.refresh": "ai",
    "oracle.meeting_briefing.refresh": "ai",
    "oracle.weekly_change.refresh": "ai",
    "oracle.report.generate": "ai",
    "oracle.procurement_document_report.generate": "ai",
    "oracle.export.generate": "documents",
    "oracle.document.process": "documents",
    "notifications.send_email": "notifications",
    "notifications.send_notification": "notifications",
    "notifications.send_digest": "notifications",
    "notifications.evaluate_alerts": "notifications",
    "maintenance.weekly_digest": "maintenance",
    **{
        f"oracle.ai.{agent}": "ai"
        for agent in (
            "intake",
            "signal_triage",
            "entity_resolution",
            "opportunity",
            "risk",
            "actor_partnership",
            "meeting_briefing",
            "report_writer",
            "memory_curator",
            "evidence_reviewer",
            "weekly_change",
            "dossier_situation_summary",
        )
    },
}
FORBIDDEN_KEY_FAMILIES = (
    "password",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "privatekey",
)


def validate_payload(payload: dict[str, Any]) -> None:
    def walk(value: Any, key: str = "") -> None:
        normalized_key = re.sub(r"[^a-z0-9]", "", key.casefold())
        if any(family in normalized_key for family in FORBIDDEN_KEY_FAMILIES):
            raise ValueError(f"El payload de job no admite {key}.")
        if normalized_key in {"document", "rawpayload"}:
            raise ValueError(f"El payload de job no admite {key}.")
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, str(child_key))
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > 32_768:
        raise ValueError("El payload de job supera 32 KiB.")


def payload_digest(payload: dict[str, Any]) -> bytes:
    validate_payload(payload)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).digest()


def enqueue_job(
    task_name: str,
    *,
    payload: dict[str, Any],
    idempotency_key: str,
    requested_by_user_id: uuid.UUID | None = None,
    dossier_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
    max_attempts: int = 3,
    publish: bool = True,
) -> BackgroundJob:
    """Persist a job, then optionally publish it after the durable commit.

    Callers that need a wider transaction (scheduler/auth outbox) use
    :func:`stage_job` and commit their domain state together.
    """

    try:
        job = stage_job(
            task_name,
            payload=payload,
            idempotency_key=idempotency_key,
            requested_by_user_id=requested_by_user_id,
            dossier_id=dossier_id,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            request_id=request_id,
            max_attempts=max_attempts,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        tenant_id = require_tenant_id()
        existing = db.session.scalar(
            select(BackgroundJob).where(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.idempotency_key == idempotency_key,
            )
        )
        if (
            existing is None
            or existing.payload_hash != payload_digest(payload)
            or existing.job_type != task_name
        ):
            raise ValueError("La clave idempotente ya pertenece a otro payload.") from None
        job = existing
    if publish and job.status == "queued":
        publish_job(job)
    return job


def stage_job(
    task_name: str,
    *,
    payload: dict[str, Any],
    idempotency_key: str,
    requested_by_user_id: uuid.UUID | None = None,
    dossier_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    request_id: str | None = None,
    max_attempts: int = 3,
) -> BackgroundJob:
    """Create or return a job without committing or contacting the broker."""

    if task_name not in TASK_QUEUES:
        raise ValueError("Tipo de job no permitido.")
    if not 8 <= len(idempotency_key) <= 200:
        raise ValueError("La clave idempotente debe tener entre 8 y 200 caracteres.")
    if not 1 <= max_attempts <= 20:
        raise ValueError("max_attempts debe estar entre 1 y 20.")
    tenant_id = require_tenant_id()
    digest = payload_digest(payload)
    existing = db.session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.payload_hash != digest or existing.job_type != task_name:
            raise ValueError("La clave idempotente ya pertenece a otro payload.")
        return existing
    task_id = str(uuid.uuid4())
    job = BackgroundJob(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        job_type=task_name,
        status="queued",
        queue=TASK_QUEUES[task_name],
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        request_id=request_id,
        resource_type=resource_type,
        resource_id=resource_id,
        celery_task_id=task_id,
        payload_hash=digest,
        input_payload=payload,
        requested_by_user_id=requested_by_user_id,
        max_attempts=max_attempts,
    )
    db.session.add(job)
    db.session.flush()
    return job


def publish_job(job: BackgroundJob) -> bool:
    """Publish with a durable pending marker; DB remains authoritative on broker failure."""

    current = db.session.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.id == job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or not claim_job_for_publish(current):
        return False
    db.session.commit()
    return publish_claimed_job(current)


def claim_job_for_publish(job: BackgroundJob, *, allow_stale: bool = False) -> bool:
    """Claim a locked queued row without committing or contacting Redis."""

    publishable_stages = {"queued", "publish_pending", "manual_retry"}
    if job.status != "queued" or job.cancel_requested:
        return False
    if job.stage == "publishing":
        if not allow_stale:
            return False
    elif job.stage not in publishable_stages:
        return False
    job.publish_attempts += 1
    job.last_publish_attempt_at = datetime.now(UTC)
    job.stage = "publishing"
    job.version += 1
    return True


def publish_claimed_job(job: BackgroundJob) -> bool:
    """Publish a previously committed claim and persist its outcome."""

    job_id = job.id
    current = db.session.get(BackgroundJob, job_id)
    if current is None or current.status != "queued" or current.stage != "publishing":
        return False
    celery: Celery = current_app.extensions["celery"]
    try:
        celery.tasks[current.job_type].apply_async(
            kwargs={
                "job_id": str(current.id),
                "tenant_id": str(current.tenant_id),
                "payload": current.input_payload,
            },
            task_id=current.celery_task_id,
            queue=current.queue,
        )
    except Exception:
        db.session.rollback()
        current = db.session.get(BackgroundJob, job_id)
        if current is not None and current.status == "queued":
            current.stage = "publish_pending"
            current.error_code = "broker_unavailable"
            current.error_message = "El job está pendiente de publicación."
            current.version += 1
            db.session.commit()
        return False
    db.session.expire_all()
    current = db.session.get(BackgroundJob, job_id)
    if current is not None:
        current.published_at = datetime.now(UTC)
    if current is not None and current.status == "queued":
        current.stage = "published"
        current.error_code = current.error_message = None
        current.version += 1
    if current is not None:
        db.session.commit()
    return True


def serialize_job(job: BackgroundJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "tenant_id": str(job.tenant_id),
        "job_type": job.job_type,
        "queue": job.queue,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "resource_type": job.resource_type,
        "resource_id": str(job.resource_id) if job.resource_id else None,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "retryable": job.retryable,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "cancel_requested": job.cancel_requested,
        "result": job.result_ref,
        "updated_at": job.updated_at.isoformat(),
        "version": job.version,
    }


def request_cancel(job: BackgroundJob, *, expected_version: int) -> None:
    if job.version != expected_version:
        raise ValueError("El job fue modificado por otro proceso.")
    if job.status in {"succeeded", "failed", "cancelled"}:
        raise ValueError("El job ya ha finalizado.")
    now = datetime.now(UTC)
    job.cancel_requested = True
    if job.status == "queued":
        job.status, job.stage, job.finished_at = "cancelled", "cancelled", now
    job.cancel_requested_at = datetime.now(UTC)
    job.version += 1


def prepare_retry(job: BackgroundJob, *, expected_version: int) -> None:
    if job.version != expected_version:
        raise ValueError("El job fue modificado por otro proceso.")
    if job.status != "failed" or not job.retryable:
        raise ValueError("El job no admite reintento.")
    job.status, job.stage = "queued", "manual_retry"
    job.error_code = job.error_message = None
    job.finished_at = None
    job.not_before = None
    job.cancel_requested = False
    job.cancel_requested_at = None
    job.attempts = 0
    job.celery_task_id = str(uuid.uuid4())
    job.execution_lease_id = None
    job.lease_expires_at = None
    job.version += 1
