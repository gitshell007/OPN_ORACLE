"""Initial durable tasks and database-backed scheduler."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import random
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from celery import Task, shared_task
from flask import current_app
from sqlalchemy import delete, or_, select, update

from opn_oracle.ai.provider import AIUnavailable
from opn_oracle.ai.service import (
    AIPolicyDenied,
    SignalTriageRejected,
    execute_agent,
    recover_stale_ai_executions,
    triage_dossier_signal,
)
from opn_oracle.auth.tokens import hash_token, stable_invitation_token
from opn_oracle.documents.service import DocumentError, process_document
from opn_oracle.extensions import db
from opn_oracle.integrations.service import sync_monitor
from opn_oracle.jobs.service import (
    claim_job_for_publish,
    payload_digest,
    publish_claimed_job,
    publish_job,
    stage_job,
)
from opn_oracle.notifications.email import EmailPermanentError
from opn_oracle.oracle.jobs import BackgroundJob, JobSchedule
from opn_oracle.oracle.models import SignalMonitor
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import (
    Invitation,
    PasswordResetToken,
    Tenant,
    TenantMembership,
    User,
    UserSession,
)
from opn_oracle.reporting.alerts import evaluate_alerts
from opn_oracle.reporting.exports import ExportError, process_export, purge_expired_exports
from opn_oracle.reporting.notifications import (
    NotificationPermanentError,
    NotificationTemporaryError,
    send_digest,
    send_notification_email,
)
from opn_oracle.reporting.service import ReportWorkflowError, process_report
from opn_oracle.tenants.context import TenantContext, tenant_context


class RetriableJobError(RuntimeError):
    pass


class PermanentJobError(RuntimeError):
    pass


class CancelledJobError(RuntimeError):
    pass


Handler = Callable[[dict[str, Any], BackgroundJob], dict[str, Any]]
PUBLIC_TEMPORARY_ERROR = "temporary_failure"
PUBLIC_PERMANENT_ERROR = "permanent_failure"
logger = logging.getLogger(__name__)


def _ai_handler(agent: str) -> Handler:
    def handler(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
        return _execute_ai(agent, payload, job)

    return handler


def retry_delay(attempt: int, *, jitter: float | None = None) -> float:
    """Bounded exponential backoff with full, testable jitter."""

    random_part = random.SystemRandom().uniform(0, 3) if jitter is None else jitter
    return min(300.0, float(2 ** max(1, attempt)) + max(0.0, min(3.0, random_part)))


def _stub(kind: str) -> Handler:
    def handler(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
        del job
        if payload.get("simulate") == "retryable":
            raise RetriableJobError("Dependencia temporalmente no disponible.")
        if payload.get("simulate") == "permanent":
            raise PermanentJobError("Payload no procesable.")
        return {"kind": kind, "processed": True, "resource_id": payload.get("resource_id")}

    return handler


def _evaluate_alerts(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    del job
    try:
        scheduled_at = datetime.fromisoformat(str(payload["scheduled_at"]))
    except (KeyError, TypeError, ValueError) as error:
        raise PermanentJobError("scheduled_at de alertas no es válido.") from error
    if scheduled_at.tzinfo is None:
        raise PermanentJobError("scheduled_at de alertas debe incluir timezone.")
    return evaluate_alerts(now=scheduled_at.astimezone(UTC))


def _send_email(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    if payload.get("kind") == "invitation":
        return _send_invitation_email(payload, job)
    if payload.get("kind") != "password_reset":
        raise PermanentJobError("Tipo de email no permitido.")
    user_id = uuid.UUID(str(payload["user_id"]))
    user = db.session.get(User, user_id)
    membership = db.session.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == job.tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.status == "active",
        )
    )
    if user is None or user.status != "active" or membership is None:
        raise PermanentJobError("Destinatario no disponible.")
    now = datetime.now(UTC)
    delivery_key = f"password-reset-{job.id}"
    raw = _stable_reset_token(job.id)
    reset = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.delivery_key == delivery_key)
    )
    if reset is None:
        db.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        reset = PasswordResetToken(
            user_id=user.id,
            tenant_id=job.tenant_id,
            token_hash=hash_token(raw),
            expires_at=now + timedelta(minutes=current_app.config["PASSWORD_RESET_TTL_MINUTES"]),
            delivery_key=delivery_key,
        )
        db.session.add(reset)
        db.session.commit()
    elif (
        reset.user_id != user.id
        or reset.tenant_id != job.tenant_id
        or reset.used_at is not None
        or reset.revoked_at is not None
        or reset.expires_at <= now
    ):
        raise PermanentJobError("Entrega de correo no disponible.")
    current = _delivery_checkpoint(job)
    reset = db.session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.delivery_key == delivery_key)
    )
    assert reset is not None
    if reset.delivered_at is not None:
        return {
            "kind": "password_reset",
            "token_record_id": str(reset.id),
            "delivered": True,
            "delivery_key": delivery_key,
        }
    sender = current_app.extensions["email_sender"]
    if reset.delivery_started_at is not None and not sender.supports_idempotency:
        raise PermanentJobError("El resultado SMTP anterior es desconocido; no se reenvía.")
    if reset.delivery_started_at is None:
        reset.delivery_started_at = datetime.now(UTC)
        db.session.commit()
        current = _delivery_checkpoint(current)
        reset = db.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.delivery_key == delivery_key)
        )
        assert reset is not None
    try:
        sender.send_password_reset(
            recipient=user.email,
            url=f"{current_app.config['FRONTEND_ORIGIN']}/reset-password?token={raw}",
            expires=reset.expires_at.isoformat(),
            idempotency_key=delivery_key,
        )
    except EmailPermanentError as error:
        raise PermanentJobError("El proveedor de correo rechazó la entrega.") from error
    except Exception as error:
        raise RetriableJobError("El proveedor de correo no está disponible.") from error
    reset.delivered_at = datetime.now(UTC)
    current.result_ref = {"delivery_key": delivery_key, "delivery_state": "sent"}
    current.version += 1
    db.session.commit()
    return {
        "kind": "password_reset",
        "token_record_id": str(reset.id),
        "delivered": True,
        "delivery_key": delivery_key,
    }


def _send_invitation_email(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        invitation_id = uuid.UUID(str(payload["invitation_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("Invitación no disponible.") from None
    invitation = db.session.scalar(
        select(Invitation).where(
            Invitation.id == invitation_id,
            Invitation.tenant_id == job.tenant_id,
        )
    )
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.revoked_at is not None
        or invitation.expires_at <= datetime.now(UTC)
    ):
        raise PermanentJobError("Invitación no disponible.")
    membership = db.session.scalar(
        select(TenantMembership).where(
            TenantMembership.id == invitation.membership_id,
            TenantMembership.tenant_id == job.tenant_id,
            TenantMembership.status == "invited",
        )
    )
    tenant = db.session.scalar(
        select(Tenant).where(Tenant.id == job.tenant_id, Tenant.status == "active")
    )
    user = db.session.get(User, membership.user_id) if membership is not None else None
    if tenant is None or user is None or user.status not in {"active", "invited"}:
        raise PermanentJobError("Destinatario no disponible.")
    raw = stable_invitation_token(
        invitation_id=invitation.id,
        secret_key=current_app.config["SECRET_KEY"],
    )
    if not hmac.compare_digest(hash_token(raw), invitation.token_hash):
        raise PermanentJobError("La integridad de la invitación no es válida.")
    delivery_key = f"invitation-{invitation.id}"
    state = str(job.result_ref.get("delivery_state", ""))
    if state == "sent":
        return {
            "kind": "invitation",
            "invitation_id": str(invitation.id),
            "delivered": True,
            "delivery_key": delivery_key,
        }
    sender = current_app.extensions["email_sender"]
    if state == "started" and not sender.supports_idempotency:
        raise PermanentJobError("El resultado del proveedor anterior es desconocido.")
    if state != "started":
        job.result_ref = {
            "kind": "invitation",
            "invitation_id": str(invitation.id),
            "delivery_state": "started",
        }
        job.version += 1
        db.session.commit()
        job = _delivery_checkpoint(job)
    try:
        sender.send_invitation(
            recipient=user.email,
            tenant_name=tenant.name,
            url=f"{current_app.config['FRONTEND_ORIGIN']}/invite?token={raw}",
            expires=invitation.expires_at.isoformat(),
            idempotency_key=delivery_key,
        )
    except EmailPermanentError as error:
        raise PermanentJobError("El proveedor de correo rechazó la entrega.") from error
    except Exception as error:
        raise RetriableJobError("El proveedor de correo no está disponible.") from error
    job = _delivery_checkpoint(job)
    result = {
        "kind": "invitation",
        "invitation_id": str(invitation.id),
        "delivered": True,
        "delivery_key": delivery_key,
        "delivery_state": "sent",
    }
    job.result_ref = result
    job.version += 1
    db.session.commit()
    return result


def _stable_reset_token(job_id: uuid.UUID) -> str:
    digest = hmac.new(
        current_app.config["SECRET_KEY"].encode(),
        f"password-reset:{job_id}".encode(),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


HANDLERS: dict[str, Handler] = {
    "oracle.signal.sync_monitor": lambda payload, job: _sync_monitor(payload, job),
    "oracle.signal.triage": lambda payload, job: _triage_signal(payload, job),
    "oracle.memory.refresh": _stub("memory_refresh_stub_v1"),
    "oracle.report.generate": lambda payload, job: _generate_report(payload, job),
    "oracle.export.generate": lambda payload, job: _generate_export(payload, job),
    "oracle.document.process": lambda payload, job: _process_document(payload, job),
    "notifications.send_email": _send_email,
    "notifications.send_notification": lambda payload, job: _send_notification(payload, job),
    "notifications.send_digest": lambda payload, job: _send_digest(payload, job),
    "notifications.evaluate_alerts": _evaluate_alerts,
    "maintenance.weekly_digest": lambda payload, job: _weekly_digest(payload, job),
    **{
        f"oracle.ai.{agent}": _ai_handler(agent)
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
        )
    },
}


def _generate_report(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        return process_report(uuid.UUID(str(payload["report_id"])), job)
    except (KeyError, ValueError, ReportWorkflowError) as error:
        raise PermanentJobError(str(error)) from error
    except Exception as error:
        raise RetriableJobError("La generación de informe falló temporalmente.") from error


def _generate_export(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        return process_export(uuid.UUID(str(payload["export_id"])), job)
    except (KeyError, ValueError, ExportError) as error:
        raise PermanentJobError(str(error)) from error
    except Exception as error:
        raise RetriableJobError("La exportación falló temporalmente.") from error


def _send_notification(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    del job
    try:
        return send_notification_email(uuid.UUID(str(payload["delivery_id"])))
    except (KeyError, ValueError, NotificationPermanentError) as error:
        raise PermanentJobError(str(error)) from error
    except NotificationTemporaryError as error:
        raise RetriableJobError(str(error)) from error


def _send_digest(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        return send_digest(uuid.UUID(str(payload["preference_id"])), job)
    except (KeyError, ValueError, NotificationPermanentError) as error:
        raise PermanentJobError(str(error)) from error
    except NotificationTemporaryError as error:
        raise RetriableJobError(str(error)) from error


def _process_document(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        document_id = uuid.UUID(str(payload["document_id"]))
        version_id = uuid.UUID(str(payload["version_id"]))
        return process_document(document_id, version_id, job)
    except (KeyError, ValueError, DocumentError) as error:
        raise PermanentJobError(str(error)) from error


def _execute_ai(agent: str, payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
        return execute_agent(agent=agent, dossier_id=dossier_id, job=job)
    except (KeyError, ValueError, AIPolicyDenied) as error:
        raise PermanentJobError(str(error)) from error


def _triage_signal(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        return triage_dossier_signal(payload=payload, job=job)
    except AIUnavailable as error:
        raise RetriableJobError("Ollama no está disponible temporalmente.") from error
    except (AIPolicyDenied, SignalTriageRejected, ValueError) as error:
        raise PermanentJobError(str(error)) from error


def _sync_monitor(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    try:
        monitor_id = uuid.UUID(str(payload["monitor_id"]))
    except (KeyError, ValueError):
        raise PermanentJobError("Monitor no válido.") from None
    monitor = db.session.scalar(
        select(SignalMonitor).where(
            SignalMonitor.id == monitor_id,
            SignalMonitor.tenant_id == job.tenant_id,
        )
    )
    if monitor is None or monitor.status != "active":
        raise PermanentJobError("Monitor no disponible.")
    return sync_monitor(monitor, job_id=job.id)


def _weekly_digest(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    del job
    timezone = str(payload.get("timezone", ""))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise PermanentJobError("Timezone no válida.") from None
    return {
        "kind": "weekly_digest_stub_v1",
        "processed": True,
        "timezone": timezone,
    }


def execute_durable(
    task: Task,
    *,
    job_id: str,
    tenant_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        tenant_uuid, job_uuid = uuid.UUID(tenant_id), uuid.UUID(job_id)
        expected_payload_hash = payload_digest(payload)
    except (TypeError, ValueError):
        raise PermanentJobError(PUBLIC_PERMANENT_ERROR) from None
    with tenant_context(TenantContext(tenant_id=tenant_uuid, actor_id=None)):
        try:
            return _execute_claimed_delivery(
                task,
                job_uuid=job_uuid,
                expected_payload_hash=expected_payload_hash,
                payload=payload,
            )
        finally:
            db.session.remove()


def _execute_claimed_delivery(
    task: Task,
    *,
    job_uuid: uuid.UUID,
    expected_payload_hash: bytes,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now, lease_id = datetime.now(UTC), uuid.uuid4()
    job = db.session.scalar(
        select(BackgroundJob).where(BackgroundJob.id == job_uuid).with_for_update()
    )
    if job is None or job.payload_hash != expected_payload_hash:
        raise PermanentJobError(PUBLIC_PERMANENT_ERROR)
    request_id = str(getattr(getattr(task, "request", None), "id", "") or "")
    if request_id and job.celery_task_id and request_id != job.celery_task_id:
        _log_job("job_delivery_ignored", job, reason="obsolete_delivery")
        return {"ignored": True, "reason": "obsolete_delivery"}
    if job.status == "succeeded":
        return job.result_ref
    if job.status in {"failed", "cancelled"}:
        _log_job("job_delivery_ignored", job, reason="terminal_state")
        return {"ignored": True, "reason": "terminal_state"}
    if job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
        _log_job("job_delivery_ignored", job, reason="active_delivery")
        return {"ignored": True, "reason": "active_delivery"}
    if job.cancel_requested:
        _revoke_email_delivery(job)
        job.status, job.stage, job.finished_at = "cancelled", "cancelled", now
        job.execution_lease_id = None
        job.lease_expires_at = None
        append_audit_event(
            db.session,
            action="background_job.cancelled",
            resource_type="background_job",
            resource_id=job.id,
            dossier_id=job.dossier_id,
            result="success",
            correlation_id=job.correlation_id,
        )
        job.version += 1
        db.session.commit()
        _log_job("job_cancelled", job)
        return {"cancelled": True}
    job.status, job.stage = "running", "started"
    job.execution_lease_id = lease_id
    job.lease_expires_at = now + timedelta(
        seconds=int(current_app.config["CELERY_TASK_TIME_LIMIT"]) + 60
    )
    job.attempts += 1
    job.started_at = job.started_at or now
    job.heartbeat_at = now
    job.version += 1
    db.session.commit()
    _log_job("job_started", job, lease_id=str(lease_id))
    try:
        owned = _owned_lease(job_uuid, lease_id)
        if owned is None:
            return {"ignored": True, "reason": "lease_lost"}
        owned.progress, owned.stage, owned.heartbeat_at = 10, "processing", datetime.now(UTC)
        owned.version += 1
        db.session.commit()
        result = HANDLERS[owned.job_type](payload, owned)
        owned = _owned_lease(job_uuid, lease_id)
        if owned is None:
            return {"ignored": True, "reason": "lease_lost"}
        if owned.cancel_requested:
            db.session.rollback()
            return _cancel_claimed_delivery(job_uuid, lease_id)
        owned.status, owned.stage, owned.progress = "succeeded", "completed", 100
        owned.result_ref, owned.finished_at = result, datetime.now(UTC)
        owned.error_code = owned.error_message = None
        owned.execution_lease_id = None
        owned.lease_expires_at = None
        append_audit_event(
            db.session,
            action="background_job.succeeded",
            resource_type="background_job",
            resource_id=owned.id,
            dossier_id=owned.dossier_id,
            result="success",
            correlation_id=owned.correlation_id,
            metadata={"job_type": owned.job_type, "attempts": owned.attempts},
        )
        owned.version += 1
        db.session.commit()
        _log_job("job_succeeded", owned)
        return result
    except CancelledJobError:
        db.session.rollback()
        return _cancel_claimed_delivery(job_uuid, lease_id)
    except RetriableJobError:
        db.session.rollback()
        owned = _owned_lease(job_uuid, lease_id)
        if owned is None:
            return {"ignored": True, "reason": "lease_lost"}
        owned.execution_lease_id = None
        owned.lease_expires_at = None
        if owned.attempts >= owned.max_attempts:
            owned.status, owned.stage, owned.retryable = "failed", "retry_exhausted", True
            owned.finished_at = datetime.now(UTC)
            owned.error_code = "retry_exhausted"
            owned.error_message = "Se agotaron los reintentos permitidos."
            _revoke_email_delivery(owned)
            _audit_job_failure(owned)
            db.session.commit()
            _log_job("job_failed", owned, error_code=owned.error_code)
            raise RetriableJobError(PUBLIC_TEMPORARY_ERROR) from None
        owned.status, owned.stage = "retrying", "backoff"
        owned.error_code = "temporary_failure"
        owned.error_message = "Una dependencia temporal no está disponible."
        countdown = retry_delay(owned.attempts)
        owned.not_before = datetime.now(UTC) + timedelta(seconds=countdown)
        owned.version += 1
        max_retries = max(0, owned.max_attempts - 1)
        db.session.commit()
        _log_job("job_retrying", owned, error_code=owned.error_code)
        raise task.retry(
            exc=RetriableJobError(PUBLIC_TEMPORARY_ERROR),
            countdown=countdown,
            max_retries=max_retries,
        ) from None
    except Exception:
        db.session.rollback()
        owned = _owned_lease(job_uuid, lease_id)
        if owned is None:
            return {"ignored": True, "reason": "lease_lost"}
        owned.status, owned.stage, owned.retryable = "failed", "failed", False
        owned.finished_at = datetime.now(UTC)
        owned.error_code = "permanent_failure"
        owned.error_message = "El job no pudo completarse."
        _revoke_email_delivery(owned)
        owned.execution_lease_id = None
        owned.lease_expires_at = None
        _audit_job_failure(owned)
        db.session.commit()
        _log_job("job_failed", owned, error_code=owned.error_code)
        raise PermanentJobError(PUBLIC_PERMANENT_ERROR) from None


def _owned_lease(job_id: uuid.UUID, lease_id: uuid.UUID) -> BackgroundJob | None:
    return db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.execution_lease_id == lease_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _delivery_checkpoint(job: BackgroundJob) -> BackgroundJob:
    job_id, lease_id = job.id, job.execution_lease_id
    if lease_id is None:
        raise CancelledJobError("delivery_not_owned")
    db.session.rollback()
    owned = _owned_lease(job_id, lease_id)
    if owned is None or owned.cancel_requested:
        raise CancelledJobError("delivery_cancelled")
    return owned


def _cancel_claimed_delivery(job_id: uuid.UUID, lease_id: uuid.UUID) -> dict[str, Any]:
    owned = _owned_lease(job_id, lease_id)
    if owned is None:
        return {"ignored": True, "reason": "lease_lost"}
    _revoke_email_delivery(owned)
    owned.status, owned.stage, owned.finished_at = "cancelled", "cancelled", datetime.now(UTC)
    owned.execution_lease_id = None
    owned.lease_expires_at = None
    append_audit_event(
        db.session,
        action="background_job.cancelled",
        resource_type="background_job",
        resource_id=owned.id,
        dossier_id=owned.dossier_id,
        result="success",
        correlation_id=owned.correlation_id,
    )
    owned.version += 1
    db.session.commit()
    _log_job("job_cancelled", owned)
    return {"cancelled": True}


def _revoke_email_delivery(job: BackgroundJob) -> None:
    if job.job_type != "notifications.send_email":
        return
    if job.input_payload.get("kind") == "invitation":
        try:
            invitation_id = uuid.UUID(str(job.input_payload["invitation_id"]))
        except (KeyError, ValueError):
            return
        db.session.execute(
            update(Invitation)
            .where(
                Invitation.id == invitation_id,
                Invitation.tenant_id == job.tenant_id,
                Invitation.used_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        return
    if job.input_payload.get("kind") != "password_reset":
        return
    delivery_key = f"password-reset-{job.id}"
    db.session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.delivery_key == delivery_key,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


def _log_job(event: str, job: BackgroundJob, **fields: Any) -> None:
    logger.info(
        event,
        extra={
            "event_fields": {
                "job_id": str(job.id),
                "tenant_id": str(job.tenant_id),
                "correlation_id": job.correlation_id,
                "job_type": job.job_type,
                "status": job.status,
                **fields,
            }
        },
    )


def _audit_job_failure(job: BackgroundJob) -> None:
    append_audit_event(
        db.session,
        action="background_job.failed",
        resource_type="background_job",
        resource_id=job.id,
        dossier_id=job.dossier_id,
        result="failure",
        correlation_id=job.correlation_id,
        metadata={"error_code": job.error_code},
    )
    job.version += 1


def _durable_task(name: str) -> Any:
    @shared_task(bind=True, name=name)
    def task(self: Task, *, job_id: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return execute_durable(self, job_id=job_id, tenant_id=tenant_id, payload=payload)

    return task


signal_sync_monitor = _durable_task("oracle.signal.sync_monitor")
signal_triage = _durable_task("oracle.signal.triage")
memory_refresh = _durable_task("oracle.memory.refresh")
report_generate = _durable_task("oracle.report.generate")
export_generate = _durable_task("oracle.export.generate")
document_process = _durable_task("oracle.document.process")
send_email = _durable_task("notifications.send_email")
send_notification = _durable_task("notifications.send_notification")
send_digest_task = _durable_task("notifications.send_digest")
evaluate_alerts_task = _durable_task("notifications.evaluate_alerts")
weekly_digest = _durable_task("maintenance.weekly_digest")
AI_DURABLE_TASKS = {
    agent: _durable_task(f"oracle.ai.{agent}")
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
    )
}


@shared_task(name="maintenance.expire_sessions")
def expire_sessions() -> int:
    now = datetime.now(UTC)
    total = 0
    with tenant_context(
        TenantContext(
            tenant_id=None,
            actor_id=None,
            platform_access=True,
            access_reason="Expiración de sesiones sin tenant activo",
        )
    ):
        result = db.session.execute(
            update(UserSession)
            .where(
                UserSession.active_tenant_id.is_(None),
                UserSession.revoked_at.is_(None),
                (UserSession.idle_expires_at <= now) | (UserSession.absolute_expires_at <= now),
            )
            .values(revoked_at=now)
        )
        db.session.commit()
        total += int(cast(Any, result).rowcount)
    db.session.remove()
    for tenant_id in _all_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            result = db.session.execute(
                update(UserSession)
                .where(
                    UserSession.active_tenant_id == tenant_id,
                    UserSession.revoked_at.is_(None),
                    (UserSession.idle_expires_at <= now) | (UserSession.absolute_expires_at <= now),
                )
                .values(revoked_at=now)
            )
            db.session.commit()
            total += int(cast(Any, result).rowcount)
        db.session.remove()
    return total


@shared_task(name="maintenance.cleanup_tokens")
def cleanup_tokens() -> int:
    threshold = datetime.now(UTC) - timedelta(days=7)
    total = 0
    for tenant_id in _all_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            reset = db.session.execute(
                delete(PasswordResetToken).where(
                    PasswordResetToken.tenant_id == tenant_id,
                    PasswordResetToken.expires_at < threshold,
                )
            )
            invitations = db.session.execute(
                delete(Invitation).where(
                    Invitation.tenant_id == tenant_id,
                    Invitation.expires_at < threshold,
                )
            )
            db.session.commit()
            total += (
                int(cast(Any, reset).rowcount)
                + int(cast(Any, invitations).rowcount)
                + purge_expired_exports(now=datetime.now(UTC))
            )
        db.session.remove()
    return total


def _active_tenant_ids() -> list[uuid.UUID]:
    return _tenant_ids(active_only=True)


def _all_tenant_ids() -> list[uuid.UUID]:
    return _tenant_ids(active_only=False)


def _tenant_ids(*, active_only: bool) -> list[uuid.UUID]:
    with tenant_context(
        TenantContext(
            tenant_id=None,
            actor_id=None,
            platform_access=True,
            access_reason="Enumeración de tenants para mantenimiento",
        )
    ):
        query = select(Tenant.id)
        if active_only:
            query = query.where(Tenant.status == "active")
        tenant_ids = list(db.session.scalars(query))
        db.session.rollback()
    return tenant_ids


@shared_task(name="maintenance.dispatch_queued_jobs")
def dispatch_queued_jobs() -> int:
    published = 0
    for tenant_id in _active_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            stale = datetime.now(UTC) - timedelta(minutes=2)
            jobs = list(
                db.session.scalars(
                    select(BackgroundJob)
                    .where(
                        BackgroundJob.status == "queued",
                        or_(
                            BackgroundJob.not_before.is_(None),
                            BackgroundJob.not_before <= datetime.now(UTC),
                        ),
                        or_(
                            BackgroundJob.stage.in_(("queued", "publish_pending")),
                            (
                                (BackgroundJob.stage == "publishing")
                                & (BackgroundJob.last_publish_attempt_at <= stale)
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            )
            claimed = [
                job
                for job in jobs
                if claim_job_for_publish(job, allow_stale=job.stage == "publishing")
            ]
            db.session.commit()
            for job in claimed:
                published += int(publish_claimed_job(job))
        db.session.remove()
    return published


@shared_task(name="maintenance.schedule_alert_evaluations")
def schedule_alert_evaluations() -> int:
    """Create one durable, idempotent alert evaluation per active tenant and time bucket."""

    now = datetime.now(UTC)
    bucket = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    staged: list[BackgroundJob] = []
    for tenant_id in _active_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            job = stage_job(
                "notifications.evaluate_alerts",
                payload={"scheduled_at": bucket.isoformat()},
                idempotency_key=f"alerts:{bucket.isoformat()}",
                resource_type="alert_evaluation_batch",
            )
            db.session.commit()
            staged.append(job)
            publish_job(job)
        db.session.remove()
    return len(staged)


@shared_task(name="maintenance.recover_stale_jobs")
def recover_stale_jobs() -> int:
    """Fence deliveries that exceeded the hard timeout and make them publishable again."""

    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=int(current_app.config["CELERY_TASK_TIME_LIMIT"]) + 60)
    recovered = 0
    for tenant_id in _all_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            recovered += recover_stale_ai_executions(now=now)
            jobs = list(
                db.session.scalars(
                    select(BackgroundJob)
                    .where(
                        BackgroundJob.status == "running",
                        or_(
                            BackgroundJob.lease_expires_at < now,
                            (
                                BackgroundJob.lease_expires_at.is_(None)
                                & (BackgroundJob.heartbeat_at < cutoff)
                            ),
                        ),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            )
            for job in jobs:
                job.status, job.stage = "queued", "publish_pending"
                job.celery_task_id = str(uuid.uuid4())
                job.error_code = "worker_lost"
                job.error_message = "El worker dejó de enviar heartbeat; el job se recuperará."
                job.not_before = None
                job.execution_lease_id = None
                job.lease_expires_at = None
                job.version += 1
                recovered += 1
            db.session.commit()
        db.session.remove()
    return recovered


@shared_task(name="maintenance.dispatch_due_jobs")
def dispatch_due_jobs() -> int:
    now, dispatched = datetime.now(UTC), 0
    for tenant_id in _active_tenant_ids():
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=None)):
            due = list(
                db.session.scalars(
                    select(JobSchedule)
                    .where(JobSchedule.enabled.is_(True), JobSchedule.next_run_at <= now)
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            )
            jobs: list[BackgroundJob] = []
            for schedule in due:
                occurrence = schedule.next_run_at
                payload = dict(schedule.payload)
                if schedule.task_name == "maintenance.weekly_digest":
                    payload.setdefault("timezone", schedule.timezone)
                job = stage_job(
                    schedule.task_name,
                    payload=payload,
                    idempotency_key=f"schedule:{schedule.id}:{occurrence.isoformat()}",
                )
                schedule.advance(now)
                jobs.append(job)
                dispatched += 1
            db.session.commit()
            for job in jobs:
                publish_job(job)
        db.session.remove()
    return dispatched
