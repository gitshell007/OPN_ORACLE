"""Notification preferences, dedupe, quiet hours and durable email delivery."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app
from sqlalchemy import func, select, text

from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.notifications.email import EmailPermanentError
from opn_oracle.oracle.jobs import BackgroundJob, JobSchedule
from opn_oracle.platform.models import User
from opn_oracle.reporting.models import (
    AlertPolicy,
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from opn_oracle.tenants.context import require_tenant_id

LOCKED_NOTIFICATION_TYPES = frozenset(
    {"security.password_changed", "security.session_revoked", "security.suspicious_login"}
)
SEVERITY_RANK = {"info": 0, "success": 1, "warning": 2, "critical": 3}
ALLOWED_LINK_PREFIXES = ("/concept-a/", "/app/", "/platform/")


class NotificationError(RuntimeError):
    pass


class NotificationTemporaryError(NotificationError):
    pass


class NotificationPermanentError(NotificationError):
    pass


@dataclass(frozen=True, slots=True)
class CreatedNotification:
    notification: Notification
    email_job: BackgroundJob | None


def safe_internal_link(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    parsed = urlsplit(candidate)
    decoded_path = unquote(parsed.path)
    path_parts = decoded_path.split("/")
    if (
        not candidate.startswith(ALLOWED_LINK_PREFIXES)
        or candidate.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or "\\" in decoded_path
        or any(part in {".", ".."} for part in path_parts)
        or any(ord(character) < 32 for character in unquote(candidate))
    ):
        raise NotificationError("El enlace de notificación no es una ruta interna permitida.")
    return candidate[:1000]


def serialize_notification(row: Notification) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "type": row.notification_type,
        "severity": row.severity,
        "title": row.title,
        "body": row.body,
        "link": row.link,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "dismissed_at": row.dismissed_at.isoformat() if row.dismissed_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "resource_type": row.resource_type,
        "resource_id": str(row.resource_id) if row.resource_id else None,
        "created_at": row.created_at.isoformat(),
    }


def serialize_preference(row: NotificationPreference) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "notification_type": row.notification_type,
        "channels": row.channels,
        "digest_cadence": row.digest_cadence,
        "timezone": row.timezone,
        "local_time": row.local_time.isoformat(timespec="minutes"),
        "weekday": row.weekday,
        "quiet_hours_start": (
            row.quiet_hours_start.isoformat(timespec="minutes") if row.quiet_hours_start else None
        ),
        "quiet_hours_end": (
            row.quiet_hours_end.isoformat(timespec="minutes") if row.quiet_hours_end else None
        ),
        "minimum_severity": row.minimum_severity,
        "security_locked": row.security_locked,
        "version": row.version,
    }


def preference_for(user_id: uuid.UUID, notification_type: str) -> NotificationPreference | None:
    tenant_id = require_tenant_id()
    return db.session.scalar(
        select(NotificationPreference)
        .where(
            NotificationPreference.tenant_id == tenant_id,
            NotificationPreference.user_id == user_id,
            NotificationPreference.notification_type.in_((notification_type, "*")),
        )
        .order_by((NotificationPreference.notification_type == notification_type).desc())
        .limit(1)
    )


def _default_channels(notification_type: str) -> dict[str, bool]:
    locked = notification_type in LOCKED_NOTIFICATION_TYPES
    return {"in_app": True, "email": locked}


def _quiet_now(preference: NotificationPreference, now: datetime) -> bool:
    if preference.quiet_hours_start is None or preference.quiet_hours_end is None:
        return False
    local = now.astimezone(ZoneInfo(preference.timezone)).time().replace(tzinfo=None)
    start, end = preference.quiet_hours_start, preference.quiet_hours_end
    if start == end:
        return True
    return start <= local < end if start < end else local >= start or local < end


def _quiet_end(preference: NotificationPreference, now: datetime) -> datetime:
    if preference.quiet_hours_start is None or preference.quiet_hours_end is None:
        return now
    zone = ZoneInfo(preference.timezone)
    local_now = now.astimezone(zone)
    start, end = preference.quiet_hours_start, preference.quiet_hours_end
    candidate_date = local_now.date()
    if start >= end and local_now.time().replace(tzinfo=None) >= start:
        candidate_date += timedelta(days=1)
    candidate = datetime.combine(candidate_date, end, tzinfo=zone).astimezone(UTC)
    return candidate if candidate > now else candidate + timedelta(days=1)


def _notification_hash(value: dict[str, Any]) -> bytes:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).digest()


def create_notification(
    *,
    user_id: uuid.UUID,
    notification_type: str,
    severity: str,
    title: str,
    body: str,
    dedupe_key: str,
    link: str | None = None,
    dossier_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    report_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
    now: datetime | None = None,
) -> CreatedNotification:
    tenant_id = require_tenant_id()
    current = now or datetime.now(UTC)
    if severity not in SEVERITY_RANK:
        raise NotificationError("Severidad de notificación no válida.")
    if not title.strip() or not body.strip() or not 8 <= len(dedupe_key) <= 240:
        raise NotificationError("Contenido de notificación no válido.")
    if expires_at is not None and expires_at <= current:
        raise NotificationError("La expiración debe ser futura.")
    validated_link = safe_internal_link(link)
    request_hash = _notification_hash(
        {
            "user_id": str(user_id),
            "type": notification_type,
            "severity": severity,
            "title": title.strip()[:200],
            "body": body.strip()[:1000],
            "link": validated_link,
            "dossier_id": str(dossier_id) if dossier_id else None,
            "job_id": str(job_id) if job_id else None,
            "report_id": str(report_id) if report_id else None,
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
        }
    )
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"notification:{tenant_id}:{user_id}:{dedupe_key}"},
    )
    existing = db.session.scalar(
        select(Notification).where(
            Notification.tenant_id == tenant_id,
            Notification.user_id == user_id,
            Notification.dedupe_key == dedupe_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise NotificationError("La clave de deduplicación pertenece a otra intención.")
        delivery_job = db.session.scalar(
            select(BackgroundJob)
            .join(NotificationDelivery, NotificationDelivery.job_id == BackgroundJob.id)
            .where(NotificationDelivery.notification_id == existing.id)
        )
        return CreatedNotification(existing, delivery_job)
    preference = preference_for(user_id, notification_type)
    channels = dict(preference.channels) if preference else _default_channels(notification_type)
    minimum = preference.minimum_severity if preference else "info"
    locked = notification_type in LOCKED_NOTIFICATION_TYPES
    if not locked and SEVERITY_RANK[severity] < SEVERITY_RANK[minimum]:
        channels = {"in_app": False, "email": False}
    if locked:
        channels = {"in_app": True, "email": True}
    notification = Notification(
        tenant_id=tenant_id,
        user_id=user_id,
        notification_type=notification_type,
        severity=severity,
        title=title.strip()[:200],
        body=body.strip()[:1000],
        link=validated_link,
        in_app_visible=bool(channels.get("in_app")),
        dedupe_key=dedupe_key,
        request_hash=request_hash,
        dossier_id=dossier_id,
        job_id=job_id,
        report_id=report_id,
        resource_type=resource_type,
        resource_id=resource_id,
        expires_at=expires_at,
    )
    db.session.add(notification)
    db.session.flush()
    email_job: BackgroundJob | None = None
    cadence = "instant" if locked else (preference.digest_cadence if preference else "instant")
    quiet = preference is not None and _quiet_now(preference, current)
    if channels.get("email") and cadence == "instant":
        delivery = NotificationDelivery(
            tenant_id=tenant_id,
            notification_id=notification.id,
            channel="email",
            status="queued",
            dedupe_key=f"notification-email:{notification.id}",
            attempts=0,
        )
        db.session.add(delivery)
        db.session.flush()
        email_job = stage_job(
            "notifications.send_notification",
            payload={"delivery_id": str(delivery.id)},
            idempotency_key=f"notification-email:{delivery.id}",
            requested_by_user_id=user_id,
            dossier_id=dossier_id,
            resource_type="notification_delivery",
            resource_id=delivery.id,
            max_attempts=3,
        )
        if quiet and preference is not None:
            email_job.not_before = _quiet_end(preference, current)
        delivery.job_id = email_job.id
    return CreatedNotification(notification, email_job)


def publish_notification_job(created: CreatedNotification) -> None:
    if (
        created.email_job is not None
        and created.email_job.status == "queued"
        and (
            created.email_job.not_before is None
            or created.email_job.not_before <= datetime.now(UTC)
        )
    ):
        publish_job(created.email_job)


def next_digest_run(preference: NotificationPreference, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    try:
        zone = ZoneInfo(preference.timezone)
    except ZoneInfoNotFoundError as error:
        raise NotificationError("Timezone no válida.") from error
    local_now = current.astimezone(zone)
    for offset in range(9):
        candidate_date = local_now.date() + timedelta(days=offset)
        if preference.digest_cadence == "weekly" and candidate_date.weekday() != preference.weekday:
            continue
        candidate = datetime.combine(candidate_date, preference.local_time, tzinfo=zone)
        candidate_utc = candidate.astimezone(UTC)
        if candidate_utc > current:
            if _quiet_now(preference, candidate_utc):
                return _quiet_end(preference, candidate_utc)
            return candidate_utc
    raise NotificationError("No se pudo calcular el siguiente digest.")


def sync_digest_schedule(preference: NotificationPreference) -> JobSchedule | None:
    tenant_id = require_tenant_id()
    key = f"notification-digest:{preference.user_id}:{preference.notification_type}"
    schedule = db.session.scalar(
        select(JobSchedule).where(
            JobSchedule.tenant_id == tenant_id, JobSchedule.schedule_key == key
        )
    )
    email_enabled = preference.channels.get("email") is True
    if preference.digest_cadence not in {"daily", "weekly"} or not email_enabled:
        if schedule is not None:
            schedule.enabled = False
        return schedule
    if schedule is None:
        schedule = JobSchedule(
            tenant_id=tenant_id,
            schedule_key=key,
            task_name="notifications.send_digest",
            queue="notifications",
            payload={"preference_id": str(preference.id)},
            cadence_seconds=86400 if preference.digest_cadence == "daily" else 604800,
            next_run_at=next_digest_run(preference),
            enabled=True,
            timezone=preference.timezone,
            schedule_kind=preference.digest_cadence,
            local_time=preference.local_time,
            weekday=preference.weekday,
        )
        db.session.add(schedule)
    else:
        schedule.enabled = True
        schedule.task_name = "notifications.send_digest"
        schedule.queue = "notifications"
        schedule.payload = {"preference_id": str(preference.id)}
        schedule.cadence_seconds = 86400 if preference.digest_cadence == "daily" else 604800
        schedule.next_run_at = next_digest_run(preference)
        schedule.timezone = preference.timezone
        schedule.schedule_kind = preference.digest_cadence
        schedule.local_time = preference.local_time
        schedule.weekday = preference.weekday
    return schedule


def send_notification_email(delivery_id: uuid.UUID) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    delivery = db.session.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.id == delivery_id,
            NotificationDelivery.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if delivery is None:
        raise NotificationPermanentError("Entrega no disponible.")
    notification = db.session.scalar(
        select(Notification).where(Notification.id == delivery.notification_id)
    )
    if notification is None:
        raise NotificationPermanentError("Notificación no disponible.")
    if delivery.status == "sent":
        return {"delivery_id": str(delivery.id), "delivered": True}
    sender = current_app.extensions["email_sender"]
    if delivery.delivery_started_at is not None and not sender.supports_idempotency:
        delivery.status = "failed"
        delivery.error_code = "ambiguous_delivery"
        db.session.commit()
        raise NotificationPermanentError("El resultado SMTP anterior es desconocido.")
    user = db.session.get(User, notification.user_id)
    if user is None or user.status != "active":
        delivery.status = "skipped"
        delivery.error_code = "recipient_unavailable"
        db.session.commit()
        return {"delivery_id": str(delivery.id), "delivered": False}
    delivery.status = "sending"
    delivery.attempts += 1
    delivery.delivery_started_at = datetime.now(UTC)
    db.session.commit()
    try:
        sender.send_notification(
            recipient=user.email,
            title=notification.title,
            body=notification.body,
            url=(
                f"{current_app.config['FRONTEND_ORIGIN']}{notification.link}"
                if notification.link
                else None
            ),
            idempotency_key=delivery.dedupe_key,
        )
    except EmailPermanentError as error:
        db.session.rollback()
        delivery = db.session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
        )
        if delivery is not None:
            delivery.status = "failed"
            delivery.error_code = "provider_rejected"
            db.session.commit()
        raise NotificationPermanentError("Proveedor de correo rechazó la entrega.") from error
    except Exception as error:
        db.session.rollback()
        delivery = db.session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
        )
        if delivery is not None:
            delivery.status = "failed"
            delivery.error_code = "provider_unavailable"
            db.session.commit()
        raise NotificationTemporaryError("Proveedor de correo no disponible.") from error
    delivery = db.session.scalar(
        select(NotificationDelivery).where(NotificationDelivery.id == delivery_id).with_for_update()
    )
    if delivery is None:
        raise NotificationPermanentError("Entrega no disponible.")
    delivery.status = "sent"
    delivery.delivered_at = datetime.now(UTC)
    delivery.error_code = None
    db.session.commit()
    return {"delivery_id": str(delivery.id), "delivered": True}


def _digest_period(preference: NotificationPreference, current: datetime) -> str:
    local_now = current.astimezone(ZoneInfo(preference.timezone))
    if preference.digest_cadence == "daily":
        return local_now.date().isoformat()
    calendar = local_now.isocalendar()
    return f"{calendar.year}-W{calendar.week:02d}"


def _digest_snapshot_hash(snapshot: dict[str, Any]) -> bytes:
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).digest()


def _build_digest_snapshot(
    preference: NotificationPreference,
    period: str,
    rows: list[Notification],
) -> dict[str, Any]:
    origin = str(current_app.config["FRONTEND_ORIGIN"])
    return {
        "version": 1,
        "cadence": preference.digest_cadence,
        "preference_id": str(preference.id),
        "period": period,
        "items": [
            {
                "notification_id": str(row.id),
                "title": row.title,
                "body": row.body,
                "url": f"{origin}{row.link}" if row.link else None,
            }
            for row in rows
        ],
    }


def _validated_digest_snapshot(
    delivery: NotificationDelivery, preference_id: uuid.UUID
) -> dict[str, Any]:
    snapshot = delivery.batch_snapshot
    digest = delivery.batch_sha256
    if snapshot is None or digest is None or len(digest) != 32:
        raise NotificationPermanentError("El snapshot del digest no está disponible.")
    if not hmac.compare_digest(_digest_snapshot_hash(snapshot), digest):
        raise NotificationPermanentError("La integridad del snapshot del digest no es válida.")
    if set(snapshot) != {"version", "cadence", "preference_id", "period", "items"}:
        raise NotificationPermanentError("El contrato del snapshot del digest no es válido.")
    items = snapshot.get("items")
    if (
        snapshot.get("version") != 1
        or snapshot.get("cadence") not in {"daily", "weekly"}
        or snapshot.get("preference_id") != str(preference_id)
        or not isinstance(snapshot.get("period"), str)
        or not isinstance(items, list)
        or not 1 <= len(items) <= 50
    ):
        raise NotificationPermanentError("El contrato del snapshot del digest no es válido.")
    for item in items:
        if not isinstance(item, dict) or set(item) != {
            "notification_id",
            "title",
            "body",
            "url",
        }:
            raise NotificationPermanentError("El contrato del snapshot del digest no es válido.")
        if (
            not isinstance(item["notification_id"], str)
            or not isinstance(item["title"], str)
            or not isinstance(item["body"], str)
            or (item["url"] is not None and not isinstance(item["url"], str))
        ):
            raise NotificationPermanentError("El contrato del snapshot del digest no es válido.")
    return snapshot


def send_digest(preference_id: uuid.UUID, job: BackgroundJob) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    preference = db.session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.id == preference_id,
            NotificationPreference.tenant_id == tenant_id,
        )
    )
    if (
        preference is None
        or preference.digest_cadence not in {"daily", "weekly"}
        or preference.channels.get("email") is not True
    ):
        raise NotificationPermanentError("Preferencia de digest no disponible.")
    current = datetime.now(UTC)
    if _quiet_now(preference, current):
        raise NotificationTemporaryError("El digest está aplazado por horas silenciosas.")
    existing_for_job = db.session.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.job_id == job.id,
            NotificationDelivery.channel == "email",
        )
    )
    period = _digest_period(preference, current)
    delivery_key = (
        existing_for_job.dedupe_key
        if existing_for_job is not None
        else f"digest:{preference.id}:{period}"
    )
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"notification-delivery:{tenant_id}:{delivery_key}"},
    )
    delivery = db.session.scalar(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.channel == "email",
            NotificationDelivery.dedupe_key == delivery_key,
        )
        .with_for_update()
    )
    if existing_for_job is not None and (delivery is None or delivery.id != existing_for_job.id):
        raise NotificationPermanentError("La entrega del digest no coincide con el job.")
    if delivery is None:
        since = current - timedelta(days=1 if preference.digest_cadence == "daily" else 7)
        allowed_severities = tuple(
            severity
            for severity, rank in SEVERITY_RANK.items()
            if rank >= SEVERITY_RANK[preference.minimum_severity]
        )
        notification_criteria = [
            Notification.user_id == preference.user_id,
            Notification.dismissed_at.is_(None),
            Notification.created_at >= since,
            Notification.severity.in_(allowed_severities),
            (Notification.expires_at.is_(None) | (Notification.expires_at > current)),
        ]
        if preference.notification_type != "*":
            notification_criteria.append(
                Notification.notification_type == preference.notification_type
            )
        else:
            # A type-specific preference is authoritative. The wildcard digest must
            # not deliver that type again, even when the specific preference is off.
            specific_types = select(NotificationPreference.notification_type).where(
                NotificationPreference.user_id == preference.user_id,
                NotificationPreference.notification_type != "*",
            )
            notification_criteria.append(Notification.notification_type.not_in(specific_types))
        rows = list(
            db.session.scalars(
                select(Notification)
                .where(*notification_criteria)
                .order_by(Notification.created_at.desc(), Notification.id.desc())
                .limit(50)
            )
        )
        if not rows:
            return {"delivered": False, "count": 0}
        snapshot = _build_digest_snapshot(preference, period, rows)
        delivery = NotificationDelivery(
            tenant_id=tenant_id,
            notification_id=rows[0].id,
            job_id=job.id,
            channel="email",
            status="queued",
            dedupe_key=delivery_key,
            attempts=0,
            batch_snapshot=snapshot,
            batch_sha256=_digest_snapshot_hash(snapshot),
        )
        db.session.add(delivery)
        db.session.flush()
    snapshot = _validated_digest_snapshot(delivery, preference.id)
    snapshot_items = snapshot["items"]
    sender = current_app.extensions["email_sender"]
    if delivery is not None and delivery.status == "sent":
        return {
            "delivery_id": str(delivery.id),
            "delivered": True,
            "count": len(snapshot_items),
        }
    if (
        delivery is not None
        and delivery.delivery_started_at is not None
        and not sender.supports_idempotency
    ):
        delivery.status = "failed"
        delivery.error_code = "ambiguous_delivery"
        db.session.commit()
        raise NotificationPermanentError("El resultado SMTP anterior es desconocido.")
    user = db.session.get(User, preference.user_id)
    if user is None or user.status != "active":
        delivery.status = "skipped"
        delivery.error_code = "recipient_unavailable"
        db.session.commit()
        return {"delivery_id": str(delivery.id), "delivered": False, "count": 0}
    delivery.status = "sending"
    delivery.attempts += 1
    delivery.delivery_started_at = datetime.now(UTC)
    delivery.error_code = None
    db.session.commit()
    try:
        sender.send_digest(
            recipient=user.email,
            cadence=str(snapshot["cadence"]),
            items=tuple(
                (str(item["title"]), str(item["body"]), item["url"]) for item in snapshot_items
            ),
            preferences_url=(f"{current_app.config['FRONTEND_ORIGIN']}/app/account/notifications"),
            idempotency_key=delivery_key,
        )
    except EmailPermanentError as error:
        db.session.rollback()
        delivery = db.session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == delivery.id)
            .with_for_update()
        )
        if delivery is not None:
            delivery.status = "failed"
            delivery.error_code = "provider_rejected"
            db.session.commit()
        raise NotificationPermanentError("Proveedor de correo rechazó la entrega.") from error
    except Exception as error:
        db.session.rollback()
        delivery = db.session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.id == delivery.id)
            .with_for_update()
        )
        if delivery is not None:
            delivery.status = "failed"
            delivery.error_code = "provider_unavailable"
            db.session.commit()
        raise NotificationTemporaryError("Proveedor de correo no disponible.") from error
    delivery = db.session.scalar(
        select(NotificationDelivery)
        .where(NotificationDelivery.dedupe_key == delivery_key)
        .with_for_update()
    )
    if delivery is None:
        raise NotificationPermanentError("Entrega de digest no disponible.")
    delivery.status = "sent"
    delivery.delivered_at = datetime.now(UTC)
    delivery.error_code = None
    db.session.commit()
    return {
        "delivery_id": str(delivery.id),
        "delivered": True,
        "count": len(snapshot_items),
        "delivery_key": delivery_key,
    }


def unread_count(user_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    return int(
        db.session.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.in_app_visible.is_(True),
                Notification.read_at.is_(None),
                Notification.dismissed_at.is_(None),
                (Notification.expires_at.is_(None) | (Notification.expires_at > now)),
            )
        )
        or 0
    )


def default_alert_policy(dossier_id: uuid.UUID) -> AlertPolicy:
    from opn_oracle.reporting.alerts import effective_alert_policy

    return effective_alert_policy(dossier_id)
