"""Asynchronous, allowlisted CSV exports with formula-injection protection."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from flask import current_app
from sqlalchemy import Select, or_, select, text

from opn_oracle.auth.permissions import current_permissions
from opn_oracle.documents.storage import ObjectStorage, object_key
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import (
    Actor,
    DossierActor,
    DossierSignal,
    Opportunity,
    Report,
    RiskItem,
    Signal,
    StrategicDossier,
    Task,
)
from opn_oracle.oracle.policy import dossier_access_clause
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import AuditEvent
from opn_oracle.reporting.models import DataExport
from opn_oracle.reporting.notifications import create_notification, publish_notification_job
from opn_oracle.tenants.context import require_tenant_id

EXPORT_NAMESPACE = uuid.UUID("4f77bf2c-f5de-4afd-8967-2dc6f6a613e4")


class ExportError(RuntimeError):
    pass


class ExportConflictError(ExportError):
    """The idempotency key is already bound to another export intent."""


class ExportLeaseLost(RuntimeError):
    """The worker no longer owns the durable BackgroundJob lease."""


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    model: type[Any]
    permission: str
    default_columns: tuple[str, ...]
    allowed_columns: frozenset[str]
    search_columns: tuple[str, ...]


DATASETS: dict[str, DatasetSpec] = {
    "signals": DatasetSpec(
        Signal,
        "signal.read",
        ("id", "title", "source_type", "source_name", "published_at", "credibility"),
        frozenset(
            {
                "id",
                "title",
                "summary",
                "source_type",
                "source_name",
                "source_url",
                "published_at",
                "ingested_at",
                "language",
                "credibility",
            }
        ),
        ("title", "summary", "source_name"),
    ),
    "opportunities": DatasetSpec(
        Opportunity,
        "opportunity.read",
        ("id", "title", "status", "overall_score", "confidence", "deadline"),
        frozenset(
            {
                "id",
                "dossier_id",
                "title",
                "description",
                "status",
                "opportunity_type",
                "overall_score",
                "confidence",
                "deadline",
                "next_action",
                "created_at",
                "updated_at",
            }
        ),
        ("title", "description", "next_action"),
    ),
    "risks": DatasetSpec(
        RiskItem,
        "risk.read",
        ("id", "title", "status", "overall_score", "confidence", "owner_user_id"),
        frozenset(
            {
                "id",
                "dossier_id",
                "title",
                "description",
                "status",
                "category",
                "overall_score",
                "confidence",
                "mitigation",
                "owner_user_id",
                "created_at",
                "updated_at",
            }
        ),
        ("title", "description", "mitigation"),
    ),
    "actors": DatasetSpec(
        Actor,
        "actor.read",
        ("id", "canonical_name", "actor_type", "created_at"),
        frozenset({"id", "canonical_name", "actor_type", "created_at", "updated_at"}),
        ("canonical_name",),
    ),
    "tasks": DatasetSpec(
        Task,
        "task.read",
        ("id", "title", "status", "priority", "owner_user_id", "due_date"),
        frozenset(
            {
                "id",
                "dossier_id",
                "title",
                "status",
                "priority",
                "owner_user_id",
                "due_date",
                "origin",
                "created_at",
                "updated_at",
            }
        ),
        ("title",),
    ),
    "reports": DatasetSpec(
        Report,
        "report.read",
        ("id", "title", "status", "template_key", "generation_version", "published_at"),
        frozenset(
            {
                "id",
                "dossier_id",
                "title",
                "status",
                "report_type",
                "template_key",
                "template_version",
                "generation_version",
                "classification",
                "ready_at",
                "reviewed_at",
                "published_at",
                "created_at",
                "updated_at",
            }
        ),
        ("title",),
    ),
    "audit": DatasetSpec(
        AuditEvent,
        "audit.export",
        (
            "id",
            "created_at",
            "actor_type",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "result",
        ),
        frozenset(
            {
                "id",
                "created_at",
                "actor_type",
                "actor_id",
                "dossier_id",
                "action",
                "resource_type",
                "resource_id",
                "result",
                "request_id",
                "correlation_id",
                "_watermark",
            }
        ),
        ("action", "resource_type", "result"),
    ),
}


def csv_safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        raw = value.isoformat()
    elif isinstance(value, uuid.UUID):
        raw = str(value)
    elif isinstance(value, (dict, list)):
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        raw = str(value)
    probe = raw.lstrip(" \t\r\n")
    if probe.startswith(("=", "+", "-", "@")) or raw.startswith(("\t", "\r", "\n")):
        return "'" + raw
    return raw


def _normalize_request(
    dataset: str, columns: list[Any], filters: dict[str, Any]
) -> tuple[DatasetSpec, list[str], dict[str, Any]]:
    spec = DATASETS.get(dataset)
    if spec is None:
        raise ExportError("Dataset de exportación no permitido.")
    normalized_columns = (
        [str(value) for value in columns] if columns else list(spec.default_columns)
    )
    if dataset == "audit" and "_watermark" not in normalized_columns:
        normalized_columns.append("_watermark")
    if (
        not normalized_columns
        or len(normalized_columns) > 30
        or len(set(normalized_columns)) != len(normalized_columns)
        or not set(normalized_columns).issubset(spec.allowed_columns)
    ):
        raise ExportError("Columnas de exportación no permitidas.")
    allowed_filters = {"status", "search", "date_from", "date_to", "selected_ids"}
    if set(filters) - allowed_filters:
        raise ExportError("Filtro de exportación no permitido.")
    normalized_filters = dict(filters)
    if "selected_ids" in normalized_filters:
        values = normalized_filters["selected_ids"]
        if not isinstance(values, list) or len(values) > 1000:
            raise ExportError("selected_ids debe contener hasta 1000 UUID.")
        try:
            normalized_filters["selected_ids"] = [str(uuid.UUID(str(value))) for value in values]
        except ValueError as error:
            raise ExportError("selected_ids contiene un UUID no válido.") from error
    for key in ("date_from", "date_to"):
        if key in normalized_filters:
            try:
                normalized_filters[key] = datetime.fromisoformat(
                    str(normalized_filters[key]).replace("Z", "+00:00")
                ).isoformat()
            except ValueError as error:
                raise ExportError(f"{key} no es una fecha ISO válida.") from error
    return spec, normalized_columns, normalized_filters


def create_export_request(
    *,
    dataset: str,
    columns: list[Any],
    filters: dict[str, Any],
    dossier_id: uuid.UUID | None,
    requested_by_user_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[DataExport, BackgroundJob, bool]:
    tenant_id = require_tenant_id()
    if not 8 <= len(idempotency_key) <= 200:
        raise ExportError("Idempotency-Key debe tener entre 8 y 200 caracteres.")
    spec, normalized_columns, normalized_filters = _normalize_request(dataset, columns, filters)
    del spec
    request = {
        "dataset": dataset,
        "columns": normalized_columns,
        "filters": normalized_filters,
        "dossier_id": str(dossier_id) if dossier_id else None,
    }
    request_hash = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"export:{tenant_id}:{idempotency_key}"},
    )
    existing = db.session.scalar(
        select(DataExport).where(DataExport.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ExportConflictError("Idempotency-Key ya pertenece a otra exportación.")
        if existing.job_id is None:
            raise ExportError("La exportación no tiene job asociado.")
        job = db.session.get(BackgroundJob, existing.job_id)
        if job is None:
            raise ExportError("El job de exportación no está disponible.")
        return existing, job, False
    export = DataExport(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        requested_by_user_id=requested_by_user_id,
        dossier_id=dossier_id,
        dataset=dataset,
        format="csv",
        status="queued",
        filters=normalized_filters,
        columns=normalized_columns,
        watermark="",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        version=1,
    )
    db.session.add(export)
    db.session.flush()
    job = stage_job(
        "oracle.export.generate",
        payload={"export_id": str(export.id)},
        idempotency_key=f"export-generate:{export.id}",
        requested_by_user_id=requested_by_user_id,
        dossier_id=dossier_id,
        resource_type="data_export",
        resource_id=export.id,
        max_attempts=3,
    )
    export.job_id = job.id
    append_audit_event(
        db.session,
        action="export.requested",
        resource_type="data_export",
        resource_id=export.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"dataset": dataset, "columns": normalized_columns},
    )
    db.session.commit()
    publish_job(job)
    return export, job, True


def _query(export: DataExport, spec: DatasetSpec) -> Select[tuple[Any]]:
    model = spec.model
    statement = select(model)
    accessible_dossiers = select(StrategicDossier.id).where(
        dossier_access_clause(
            tenant_id=export.tenant_id,
            user_id=export.requested_by_user_id,
        )
    )
    if model is Signal:
        statement = statement.join(DossierSignal, DossierSignal.signal_id == Signal.id).where(
            DossierSignal.dossier_id.in_(accessible_dossiers)
        )
        if export.dossier_id is not None:
            statement = statement.where(DossierSignal.dossier_id == export.dossier_id)
    elif model is Actor:
        statement = statement.join(DossierActor, DossierActor.actor_id == Actor.id).where(
            DossierActor.dossier_id.in_(accessible_dossiers)
        )
        if export.dossier_id is not None:
            statement = statement.where(DossierActor.dossier_id == export.dossier_id)
    elif model is not AuditEvent and hasattr(model, "dossier_id"):
        statement = statement.where(model.dossier_id.in_(accessible_dossiers))
        if export.dossier_id is not None:
            statement = statement.where(model.dossier_id == export.dossier_id)
    elif export.dossier_id is not None:
        if model is AuditEvent:
            statement = statement.where(AuditEvent.dossier_id == export.dossier_id)
        else:
            raise ExportError("Este dataset no admite filtro por expediente.")
    status = export.filters.get("status")
    if status:
        if not hasattr(model, "status"):
            raise ExportError("Este dataset no admite filtro de estado.")
        statement = statement.where(model.status == str(status))
    search = str(export.filters.get("search", "")).strip()
    if search:
        if len(search) > 200:
            raise ExportError("El filtro search es demasiado largo.")
        statement = statement.where(
            or_(*(getattr(model, column).ilike(f"%{search}%") for column in spec.search_columns))
        )
    if "selected_ids" in export.filters:
        statement = statement.where(
            model.id.in_(uuid.UUID(value) for value in export.filters["selected_ids"])
        )
    for key, operator in (("date_from", "from"), ("date_to", "to")):
        if export.filters.get(key):
            parsed = datetime.fromisoformat(str(export.filters[key]))
            statement = statement.where(
                model.created_at >= parsed if operator == "from" else model.created_at <= parsed
            )
    return statement.order_by(model.created_at, model.id).distinct()


def process_export(export_id: uuid.UUID, job: BackgroundJob) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    execution_lease_id = job.execution_lease_id
    if execution_lease_id is None or job.status != "running":
        raise ExportLeaseLost("El worker no posee una lease activa del job.")
    export = db.session.scalar(
        select(DataExport)
        .where(DataExport.id == export_id, DataExport.tenant_id == tenant_id)
        .with_for_update()
    )
    if export is None or export.job_id != job.id:
        raise ExportError("Exportación no disponible para este job.")
    spec = DATASETS.get(export.dataset)
    if spec is None or spec.permission not in current_permissions(
        export.requested_by_user_id, tenant_id
    ):
        if export.status in {"queued", "generating", "failed"}:
            export.status = "failed"
            export.error_code = "permission_revoked"
            export.version += 1
            db.session.commit()
        raise ExportError("El permiso del dataset fue revocado antes de generar la exportación.")
    if export.status == "ready":
        return {"export_id": str(export.id), "ready": True}
    if export.status not in {"queued", "generating", "failed"}:
        raise ExportError("Estado de exportación no procesable.")
    export.status = "generating"
    export.error_code = None
    export.version += 1
    db.session.commit()
    storage_key: str | None = None
    created_notification: Any | None = None
    result_payload: dict[str, Any] | None = None
    try:
        max_rows = int(current_app.config["EXPORT_MAX_ROWS"])
        rows = list(db.session.scalars(_query(export, spec).limit(max_rows + 1)))
        if len(rows) > max_rows:
            raise ExportError("La exportación supera el límite de filas; acota los filtros.")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=[str(value) for value in export.columns])
        writer.writeheader()
        watermark = (
            f"OPN Oracle · auditoría · tenant {tenant_id} · solicitado por "
            f"{export.requested_by_user_id} · {datetime.now(UTC).isoformat()}"
        )
        for row in rows:
            record: dict[str, str] = {}
            for column in export.columns:
                name = str(column)
                value = watermark if name == "_watermark" else getattr(row, name, None)
                record[name] = csv_safe(value)
            writer.writerow(record)
        payload = b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")
        max_bytes = int(current_app.config["REPORT_MAX_ARTIFACT_BYTES"])
        if len(payload) > max_bytes:
            raise ExportError("El CSV supera el límite de artefacto.")
        storage: ObjectStorage = current_app.extensions["object_storage"]
        artifact_id = uuid.uuid5(EXPORT_NAMESPACE, f"{export.id}:{execution_lease_id}")
        storage_key = object_key(tenant_id, export.dossier_id or EXPORT_NAMESPACE, artifact_id)
        stored = storage.put(
            storage_key,
            io.BytesIO(payload),
            max_bytes=max_bytes,
            media_type="text/csv; charset=utf-8",
        )
        checksum = hashlib.sha256(payload).digest()
        if stored.checksum != checksum or stored.byte_size != len(payload):
            raise ExportError("El storage devolvió metadata inconsistente.")
        owned_job = db.session.scalar(
            select(BackgroundJob)
            .where(
                BackgroundJob.id == job.id,
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.execution_lease_id == execution_lease_id,
                BackgroundJob.status == "running",
                BackgroundJob.cancel_requested.is_(False),
                BackgroundJob.lease_expires_at >= datetime.now(UTC),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if owned_job is None:
            raise ExportLeaseLost("La lease del job cambió durante la exportación.")
        export = db.session.scalar(
            select(DataExport).where(DataExport.id == export_id).with_for_update()
        )
        if export is None or export.status != "generating":
            raise ExportError("La exportación perdió su estado de generación.")
        export.status = "ready"
        export.storage_key = storage_key
        export.checksum = checksum
        export.byte_size = len(payload)
        export.media_type = "text/csv; charset=utf-8"
        export.expires_at = datetime.now(UTC) + timedelta(
            hours=int(current_app.config["EXPORT_TTL_HOURS"])
        )
        export.watermark = watermark if export.dataset == "audit" else ""
        export.version += 1
        created_notification = create_notification(
            user_id=export.requested_by_user_id,
            notification_type="export.ready",
            severity="success",
            title="Exportación lista",
            body=f"La exportación de {export.dataset} ya se puede descargar.",
            dedupe_key=f"export-ready:{export.id}",
            link=f"/app/exports/{export.id}",
            dossier_id=export.dossier_id,
            job_id=job.id,
            resource_type="data_export",
            resource_id=export.id,
            expires_at=export.expires_at,
        )
        append_audit_event(
            db.session,
            action="export.ready",
            resource_type="data_export",
            resource_id=export.id,
            dossier_id=export.dossier_id,
            result="success",
            metadata={
                "dataset": export.dataset,
                "row_count": len(rows),
                "byte_size": len(payload),
                "checksum": checksum.hex(),
            },
        )
        db.session.commit()
        result_payload = {
            "export_id": str(export.id),
            "ready": True,
            "row_count": len(rows),
        }
    except ExportLeaseLost:
        db.session.rollback()
        if storage_key is not None:
            with suppress(Exception):
                storage = current_app.extensions["object_storage"]
                storage.delete(storage_key)
        raise
    except Exception as error:
        db.session.rollback()
        if storage_key is not None:
            with suppress(Exception):
                storage = current_app.extensions["object_storage"]
                storage.delete(storage_key)
        failed = db.session.scalar(
            select(DataExport).where(DataExport.id == export_id).with_for_update()
        )
        if failed is not None and failed.status in {"queued", "generating", "failed"}:
            failed.status = "failed"
            failed.storage_key = None
            failed.checksum = None
            failed.byte_size = None
            failed.media_type = None
            failed.expires_at = None
            failed.error_code = type(error).__name__[:100]
            failed.version += 1
            db.session.commit()
        raise
    if created_notification is not None:
        with suppress(Exception):
            publish_notification_job(created_notification)
    assert result_payload is not None
    return result_payload


def purge_expired_exports(*, now: datetime | None = None, limit: int = 100) -> int:
    """Delete expired CSV objects and retain a metadata-only audit record."""

    current = now or datetime.now(UTC)
    storage: ObjectStorage = current_app.extensions["object_storage"]
    rows = list(
        db.session.scalars(
            select(DataExport)
            .where(
                DataExport.status.in_(("ready", "expired")),
                DataExport.expires_at <= current,
            )
            .order_by(DataExport.expires_at, DataExport.id)
            .with_for_update(skip_locked=True)
            .limit(max(1, min(limit, 1000)))
        )
    )
    purged = 0
    for row in rows:
        if row.storage_key is None:
            continue
        try:
            storage.delete(row.storage_key)
        except Exception:
            db.session.rollback()
            continue
        row.status = "purged"
        row.storage_key = None
        row.checksum = None
        row.byte_size = None
        row.media_type = None
        row.version += 1
        db.session.commit()
        purged += 1
    return purged


def serialize_export(row: DataExport) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "dataset": row.dataset,
        "format": row.format,
        "status": row.status,
        "dossier_id": str(row.dossier_id) if row.dossier_id else None,
        "job_id": str(row.job_id) if row.job_id else None,
        "filters": row.filters,
        "columns": row.columns,
        "watermark": row.watermark if row.dataset == "audit" else "",
        "byte_size": row.byte_size,
        "checksum": row.checksum.hex() if row.checksum else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "error_code": row.error_code,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
