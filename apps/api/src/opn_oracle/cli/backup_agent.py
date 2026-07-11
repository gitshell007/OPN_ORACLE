"""Host-only bridge for durable platform backup operations."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import click
from flask import Flask, current_app
from sqlalchemy import or_, select

from opn_oracle.extensions import db
from opn_oracle.platform.audit import append_global_audit_event
from opn_oracle.platform.backups import PlatformBackupArtifact, PlatformBackupOperation


def _json_output(value: dict[str, Any]) -> None:
    click.echo(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _validate_worker_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,99}", value):
        raise click.ClickException("worker-id no válido.")
    return value


def _validate_backup_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,199}", value):
        raise click.ClickException("backup-name no válido.")
    return value


def _validate_artifact_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise click.ClickException("El metadata del artefacto debe ser un objeto JSON.")

    allowed = {
        "backup_name",
        "relative_path",
        "size_bytes",
        "sha256",
        "backup_created_at",
        "verified_at",
        "expires_at",
        "origin",
    }
    if set(raw) - allowed:
        raise click.ClickException("El metadata contiene campos no permitidos.")
    name = str(raw.get("backup_name", ""))
    relative = str(raw.get("relative_path", ""))
    pure = PurePosixPath(relative)
    digest = str(raw.get("sha256", "")).lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,199}", name):
        raise click.ClickException("backup_name no válido.")
    if not relative or pure.is_absolute() or ".." in pure.parts:
        raise click.ClickException("relative_path no válido.")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise click.ClickException("sha256 no válido.")
    try:
        size = int(raw["size_bytes"])
        created = datetime.fromisoformat(str(raw["backup_created_at"]))
        verified = (
            datetime.fromisoformat(str(raw["verified_at"])) if raw.get("verified_at") else None
        )
        expires = datetime.fromisoformat(str(raw["expires_at"])) if raw.get("expires_at") else None
    except (KeyError, TypeError, ValueError) as error:
        raise click.ClickException("Fechas o tamaño de artefacto no válidos.") from error
    if size < 0 or created.tzinfo is None or (verified and verified.tzinfo is None):
        raise click.ClickException("Fechas o tamaño de artefacto no válidos.")
    if expires and (expires.tzinfo is None or expires <= created):
        raise click.ClickException("expires_at no válido.")
    origin = str(raw.get("origin", "manual"))
    if origin not in {"manual", "scheduled", "imported"}:
        raise click.ClickException("origin no válido.")
    return {
        "backup_name": name,
        "relative_path": relative,
        "size_bytes": size,
        "sha256": digest,
        "backup_created_at": created.astimezone(UTC),
        "verified_at": verified.astimezone(UTC) if verified else None,
        "expires_at": expires.astimezone(UTC) if expires else None,
        "origin": origin,
    }


def _artifact_payload(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 32_768:
            raise click.ClickException("El metadata del artefacto supera 32 KiB.")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except click.ClickException:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise click.ClickException("No se pudo leer el metadata del artefacto.") from error
    return _validate_artifact_payload(raw)


def register_backup_agent_cli(app: Flask) -> None:
    @app.cli.group("backup-agent")
    def backup_agent() -> None:
        """Puente de operaciones para el agente privilegiado del host."""

    @backup_agent.command("enqueue-scheduled")
    @click.option("--idempotency-key", required=True)
    def enqueue_scheduled(idempotency_key: str) -> None:
        """Registra la ejecución diaria; no hace el backup dentro de Flask."""

        if not 8 <= len(idempotency_key) <= 200:
            raise click.ClickException("idempotency-key no válido.")
        row = db.session.scalar(
            select(PlatformBackupOperation).where(
                PlatformBackupOperation.idempotency_key == idempotency_key
            )
        )
        if row is None:
            row = PlatformBackupOperation(
                operation_type="scheduled_backup",
                status="queued",
                requested_by_user_id=None,
                idempotency_key=idempotency_key,
            )
            db.session.add(row)
            db.session.flush()
            append_global_audit_event(
                db.session,
                action="platform.backup.scheduled_requested",
                resource_type="backup_operation",
                resource_id=row.id,
                result="success",
            )
            db.session.commit()
        elif row.operation_type != "scheduled_backup":
            raise click.ClickException("Conflicto de idempotencia.")
        _json_output({"operation_id": str(row.id), "status": row.status})

    @backup_agent.command("mark-expired")
    @click.option("--backup-name", required=True)
    def mark_expired(backup_name: str) -> None:
        """Marca el catálogo antes de que el host elimine físicamente un backup rotado."""

        backup_name = _validate_backup_name(backup_name)
        artifact = db.session.scalar(
            select(PlatformBackupArtifact)
            .where(PlatformBackupArtifact.backup_name == backup_name)
            .with_for_update()
        )
        if artifact is None:
            _json_output(
                {
                    "backup_name": backup_name,
                    "transitioned": False,
                    "reason": "not_catalogued",
                }
            )
            return
        transitioned = artifact.status == "available"
        if artifact.status not in {"available", "expired"}:
            raise click.ClickException("El backup no está disponible para expirar.")
        if transitioned:
            artifact.status = "expired"
            append_global_audit_event(
                db.session,
                action="platform.backup.expired",
                resource_type="backup_artifact",
                resource_id=artifact.id,
                result="success",
                metadata={"backup_name": artifact.backup_name},
            )
            db.session.commit()
        _json_output(
            {
                "artifact_id": str(artifact.id),
                "backup_name": artifact.backup_name,
                "status": artifact.status,
                "transitioned": transitioned,
            }
        )

    @backup_agent.command("claim-next")
    @click.option("--worker-id", required=True)
    @click.option("--lease-minutes", type=click.IntRange(5, 240), default=60, show_default=True)
    def claim_next(worker_id: str, lease_minutes: int) -> None:
        """Reclama atómicamente una operación y emite únicamente metadata no sensible."""

        worker_id = _validate_worker_id(worker_id)
        now = datetime.now(UTC)
        row = db.session.scalar(
            select(PlatformBackupOperation)
            .where(
                PlatformBackupOperation.operation_type.in_(("manual_backup", "scheduled_backup")),
                or_(
                    PlatformBackupOperation.status == "queued",
                    (
                        (PlatformBackupOperation.status == "running")
                        & (PlatformBackupOperation.lease_expires_at < now)
                    ),
                ),
            )
            .order_by(PlatformBackupOperation.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if row is None:
            _json_output({"operation": None})
            return
        row.status = "running"
        row.worker_id = worker_id
        row.lease_expires_at = now + timedelta(minutes=lease_minutes)
        row.started_at = row.started_at or now
        row.attempts += 1
        row.error_code = None
        row.error_message = None
        artifact = (
            db.session.get(PlatformBackupArtifact, row.artifact_id) if row.artifact_id else None
        )
        db.session.commit()
        _json_output(
            {
                "operation": {
                    "operation_id": str(row.id),
                    "operation_type": row.operation_type,
                    "artifact": (
                        {
                            "artifact_id": str(artifact.id),
                            "backup_name": artifact.backup_name,
                            "relative_path": artifact.relative_path,
                            "sha256": artifact.sha256,
                        }
                        if artifact
                        else None
                    ),
                    "storage_path": current_app.config["BACKUP_STORAGE_PATH"],
                    "retention_days": current_app.config["BACKUP_RETENTION_DAYS"],
                }
            }
        )

    @backup_agent.command("claim-restore")
    @click.option("--operation-id", type=click.UUID, required=True)
    @click.option("--worker-id", required=True)
    @click.option("--confirm-production", is_flag=True)
    @click.option("--lease-minutes", type=click.IntRange(15, 240), default=120, show_default=True)
    def claim_restore(
        operation_id: uuid.UUID,
        worker_id: str,
        confirm_production: bool,
        lease_minutes: int,
    ) -> None:
        """Reclama una restauración concreta tras aprobación explícita en el host."""

        worker_id = _validate_worker_id(worker_id)
        if current_app.config["APP_ENV"] == "production" and not confirm_production:
            raise click.ClickException("Producción exige --confirm-production.")
        if current_app.config["APP_ENV"] == "production" and not click.confirm(
            "¿Confirmas la recuperación de PRODUCCIÓN y la ventana de mantenimiento?"
        ):
            raise click.Abort()
        row = db.session.scalar(
            select(PlatformBackupOperation)
            .where(PlatformBackupOperation.id == operation_id)
            .with_for_update()
        )
        if row is None or row.operation_type != "restore" or row.status != "awaiting_approval":
            raise click.ClickException("La recuperación no está pendiente de aprobación host.")
        artifact = db.session.get(PlatformBackupArtifact, row.artifact_id)
        if artifact is None or artifact.status != "available" or artifact.verified_at is None:
            raise click.ClickException("El artefacto no está disponible y verificado.")
        now = datetime.now(UTC)
        row.status = "running"
        row.worker_id = worker_id
        row.lease_expires_at = now + timedelta(minutes=lease_minutes)
        row.started_at = now
        row.attempts += 1
        append_global_audit_event(
            db.session,
            action="platform.backup.restore_host_approved",
            resource_type="backup_operation",
            resource_id=row.id,
            result="success",
            metadata={"artifact_id": str(artifact.id)},
        )
        db.session.commit()
        _json_output(
            {
                "operation": {
                    "operation_id": str(row.id),
                    "operation_type": "restore",
                    "artifact": {
                        "artifact_id": str(artifact.id),
                        "backup_name": artifact.backup_name,
                        "relative_path": artifact.relative_path,
                        "sha256": artifact.sha256,
                    },
                    "storage_path": current_app.config["BACKUP_STORAGE_PATH"],
                }
            }
        )

    @backup_agent.command("complete")
    @click.option("--operation-id", type=click.UUID, required=True)
    @click.option("--worker-id", required=True)
    @click.option("--status", type=click.Choice(("succeeded", "failed")), required=True)
    @click.option("--artifact-json-file", type=click.Path(path_type=Path, dir_okay=False))
    @click.option("--artifact-json-stdin", is_flag=True)
    @click.option("--error-code")
    @click.option("--error-message")
    def complete(
        operation_id: uuid.UUID,
        worker_id: str,
        status: str,
        artifact_json_file: Path | None,
        artifact_json_stdin: bool,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        """Finaliza la operación reclamada; nunca recibe credenciales por argumento."""

        worker_id = _validate_worker_id(worker_id)
        row = db.session.scalar(
            select(PlatformBackupOperation)
            .where(PlatformBackupOperation.id == operation_id)
            .with_for_update()
        )
        if row is None:
            raise click.ClickException("Operación no encontrada.")
        if row.status != "running" or row.worker_id != worker_id:
            raise click.ClickException("La operación no está reclamada por este worker.")
        if artifact_json_file is not None and artifact_json_stdin:
            raise click.ClickException("Usa solo una fuente de metadata de artefacto.")
        if status == "succeeded" and row.operation_type.endswith("backup"):
            if artifact_json_file is None and not artifact_json_stdin:
                raise click.ClickException("Un backup correcto exige metadata de artefacto.")
            if artifact_json_stdin:
                raw_text = click.get_text_stream("stdin").read(32_769)
                if len(raw_text.encode("utf-8")) > 32_768:
                    raise click.ClickException("El metadata del artefacto supera 32 KiB.")
                try:
                    values = _validate_artifact_payload(json.loads(raw_text))
                except json.JSONDecodeError as error:
                    raise click.ClickException("Metadata JSON no válida.") from error
            else:
                assert artifact_json_file is not None
                values = _artifact_payload(artifact_json_file)
            artifact = db.session.scalar(
                select(PlatformBackupArtifact).where(
                    PlatformBackupArtifact.backup_name == values["backup_name"]
                )
            )
            if artifact is None:
                artifact = PlatformBackupArtifact(status="available", **values)
                db.session.add(artifact)
                db.session.flush()
            elif (
                artifact.sha256 != values["sha256"]
                or artifact.relative_path != values["relative_path"]
            ):
                raise click.ClickException("El nombre del backup ya pertenece a otro artefacto.")
            row.artifact_id = artifact.id
            row.result_metadata = {"artifact_id": str(artifact.id)}
        elif artifact_json_file is not None or artifact_json_stdin:
            raise click.ClickException("Esta operación no admite metadata de artefacto.")
        now = datetime.now(UTC)
        row.status = status
        row.finished_at = now
        row.worker_id = None
        row.lease_expires_at = None
        if status == "failed":
            if not error_code or not re.fullmatch(r"[a-z0-9_]{3,100}", error_code):
                raise click.ClickException("Un fallo exige --error-code seguro.")
            row.error_code = error_code
            row.error_message = (error_message or "Fallo operativo.")[:500]
        else:
            row.error_code = None
            row.error_message = None
        append_global_audit_event(
            db.session,
            action=f"platform.backup.{row.operation_type}_{status}",
            resource_type="backup_operation",
            resource_id=row.id,
            result="success" if status == "succeeded" else "failure",
            metadata={"artifact_id": str(row.artifact_id) if row.artifact_id else None},
        )
        db.session.commit()
        _json_output({"operation_id": str(row.id), "status": row.status})
