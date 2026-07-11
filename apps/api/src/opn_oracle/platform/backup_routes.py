"""Platform-superadmin backup control plane.

These endpoints only persist requests. A least-privileged host agent performs filesystem,
PostgreSQL and service operations outside the HTTP process.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from apiflask import APIBlueprint
from flask import current_app, request
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from opn_oracle.auth.permissions import recent_auth_required, require_platform_admin
from opn_oracle.common.errors import problem_response
from opn_oracle.common.request_context import get_correlation_id, get_request_id
from opn_oracle.extensions import db
from opn_oracle.platform.audit import append_global_audit_event
from opn_oracle.platform.backups import PlatformBackupArtifact, PlatformBackupOperation

bp = APIBlueprint(
    "platform_backups",
    __name__,
    url_prefix="/api/v1/platform/backups",
    tag="Backups de plataforma",
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _artifact(row: PlatformBackupArtifact) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "backup_name": row.backup_name,
        "status": row.status,
        "origin": row.origin,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "backup_created_at": _iso(row.backup_created_at),
        "verified_at": _iso(row.verified_at),
        "expires_at": _iso(row.expires_at),
    }


def _operation(row: PlatformBackupOperation) -> dict[str, Any]:
    return {
        "operation_id": str(row.id),
        "operation_type": row.operation_type,
        "status": row.status,
        "artifact_id": str(row.artifact_id) if row.artifact_id else None,
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "error_code": row.error_code,
    }


def _idempotency_key() -> str | None:
    key = request.headers.get("Idempotency-Key", "").strip()
    return key if 8 <= len(key) <= 200 else None


def _existing_operation(key: str) -> PlatformBackupOperation | None:
    return db.session.scalar(
        select(PlatformBackupOperation).where(PlatformBackupOperation.idempotency_key == key)
    )


def _create_operation(
    operation_type: str,
    *,
    key: str,
    artifact_id: uuid.UUID | None = None,
    status: str = "queued",
) -> tuple[PlatformBackupOperation, bool]:
    existing = _existing_operation(key)
    if existing is not None:
        if existing.operation_type != operation_type or existing.artifact_id != artifact_id:
            raise ValueError("La clave idempotente ya pertenece a otra operación.")
        return existing, False
    operation = PlatformBackupOperation(
        operation_type=operation_type,
        status=status,
        requested_by_user_id=current_user.id,
        artifact_id=artifact_id,
        idempotency_key=key,
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
    )
    db.session.add(operation)
    db.session.flush()
    return operation, True


@bp.get("")
@require_platform_admin
def list_backups() -> dict[str, Any]:
    artifacts = db.session.scalars(
        select(PlatformBackupArtifact)
        .where(PlatformBackupArtifact.status == "available")
        .order_by(PlatformBackupArtifact.backup_created_at.desc())
        .limit(200)
    )
    operations = db.session.scalars(
        select(PlatformBackupOperation)
        .order_by(PlatformBackupOperation.created_at.desc())
        .limit(50)
    )
    return {
        "items": [_artifact(row) for row in artifacts],
        "operations": [_operation(row) for row in operations],
        "retention_days": current_app.config["BACKUP_RETENTION_DAYS"],
        "storage_path": current_app.config["BACKUP_STORAGE_PATH"],
    }


@bp.post("")
@recent_auth_required
@require_platform_admin
def request_manual_backup() -> Any:
    key = _idempotency_key()
    if key is None:
        return problem_response(
            422,
            detail="Idempotency-Key es obligatorio y debe tener entre 8 y 200 caracteres.",
            code="validation_error",
        )
    try:
        operation, created = _create_operation("manual_backup", key=key)
        if created:
            append_global_audit_event(
                db.session,
                action="platform.backup.manual_requested",
                resource_type="backup_operation",
                resource_id=operation.id,
                actor_id=current_user.id,
                result="success",
                request_id=get_request_id(),
                correlation_id=get_correlation_id(),
            )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        replay = _existing_operation(key)
        if replay is None or replay.operation_type != "manual_backup":
            return problem_response(
                409, detail="Conflicto de idempotencia.", code="idempotency_conflict"
            )
        operation = replay
        created = False
    except ValueError as error:
        db.session.rollback()
        return problem_response(409, detail=str(error), code="idempotency_conflict")
    return _operation(operation), 202 if created else 200


@bp.post("/<uuid:artifact_id>/restore")
@recent_auth_required
@require_platform_admin
def request_restore(artifact_id: uuid.UUID) -> Any:
    key = _idempotency_key()
    if key is None:
        return problem_response(
            422,
            detail="Idempotency-Key es obligatorio y debe tener entre 8 y 200 caracteres.",
            code="validation_error",
        )
    artifact = db.session.scalar(
        select(PlatformBackupArtifact).where(
            PlatformBackupArtifact.id == artifact_id,
            PlatformBackupArtifact.status == "available",
        )
    )
    if artifact is None:
        return problem_response(404, detail="Backup no encontrado.", code="not_found")
    payload = request.get_json(silent=True)
    confirmation = str(payload.get("confirmation", "")) if isinstance(payload, dict) else ""
    expected = f"RECUPERAR {artifact.backup_name}"
    if confirmation != expected:
        return problem_response(
            422,
            detail=f"Escribe exactamente: {expected}",
            code="restore_confirmation_required",
        )
    existing = _existing_operation(key)
    if existing is not None:
        if existing.operation_type != "restore" or existing.artifact_id != artifact.id:
            return problem_response(
                409, detail="Conflicto de idempotencia.", code="idempotency_conflict"
            )
        return _operation(existing), 200
    running_restore = db.session.scalar(
        select(PlatformBackupOperation.id).where(
            PlatformBackupOperation.operation_type == "restore",
            PlatformBackupOperation.status.in_(("awaiting_approval", "running")),
        )
    )
    if running_restore is not None:
        return problem_response(
            409,
            detail="Ya existe una recuperación pendiente o en ejecución.",
            code="restore_in_progress",
        )
    try:
        operation, created = _create_operation(
            "restore", key=key, artifact_id=artifact.id, status="awaiting_approval"
        )
        if created:
            append_global_audit_event(
                db.session,
                action="platform.backup.restore_requested",
                resource_type="backup_operation",
                resource_id=operation.id,
                actor_id=current_user.id,
                result="success",
                metadata={"artifact_id": str(artifact.id)},
                request_id=get_request_id(),
                correlation_id=get_correlation_id(),
            )
        db.session.commit()
    except (IntegrityError, ValueError):
        db.session.rollback()
        replay = _existing_operation(key)
        if (
            replay is None
            or replay.operation_type != "restore"
            or replay.artifact_id != artifact.id
        ):
            return problem_response(
                409, detail="Conflicto de idempotencia.", code="idempotency_conflict"
            )
        operation = replay
        created = False
    return _operation(operation), 202 if created else 200


@bp.get("/operations/<uuid:operation_id>")
@require_platform_admin
def get_backup_operation(operation_id: uuid.UUID) -> Any:
    row = db.session.get(PlatformBackupOperation, operation_id)
    if row is None:
        return problem_response(404, detail="Operación no encontrada.", code="not_found")
    return _operation(row)
