"""Versioned report workflow with immutable snapshots and artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any

from flask import current_app
from sqlalchemy import delete, func, select, text

from opn_oracle.ai.context import BuiltContext, FrozenEvidence, build_frozen_context
from opn_oracle.ai.models import AIArtifact
from opn_oracle.ai.schemas import ReportOutput
from opn_oracle.ai.service import execute_agent
from opn_oracle.documents.storage import ObjectStorage, object_key
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.oracle.competitive_procurement import (
    COMPETITIVE_PROCUREMENT_TEMPLATE,
    pinned_award_winners,
)
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.links import EvidenceDossier, ReportEvidence
from opn_oracle.oracle.models import (
    DossierActor,
    DossierObjective,
    DossierProcurementItem,
    Evidence,
    Hypothesis,
    LivingSummary,
    Meeting,
    Opportunity,
    Report,
    RiskItem,
    StrategicDossier,
)
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import TenantMembership
from opn_oracle.reporting.models import (
    ReportArtifact,
    ReportReview,
    ReportRevision,
    ReportSnapshotEvidence,
)
from opn_oracle.reporting.notifications import (
    CreatedNotification,
    create_notification,
    publish_notification_job,
)
from opn_oracle.reporting.registry import ReportTemplate, ReportTemplateRegistry
from opn_oracle.reporting.rendering import PDFRenderer, RenderContext, render_report_html
from opn_oracle.tenants.context import require_tenant_id


class ReportWorkflowError(RuntimeError):
    pass


class ReportConflictError(ReportWorkflowError):
    """The idempotency key or optimistic state belongs to another intent."""


class ReportLeaseLost(RuntimeError):
    """The worker no longer owns the durable BackgroundJob lease."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def _sha256(value: Any) -> bytes:
    return hashlib.sha256(_canonical(value)).digest()


def _all_evidence_ids(output: ReportOutput) -> set[uuid.UUID]:
    values = _claim_evidence_ids(output)
    values.update(item.evidence_id for item in output.source_index)
    return values


def _claim_evidence_ids(output: ReportOutput) -> set[uuid.UUID]:
    values: set[uuid.UUID] = set()
    values.update(evidence_id for item in output.facts for evidence_id in item.evidence_ids)
    values.update(evidence_id for item in output.inferences for evidence_id in item.evidence_ids)
    for section in output.sections:
        for paragraph in section.paragraphs:
            values.update(paragraph.evidence_ids)
    return values


def _validate_report_output(
    output: ReportOutput,
    *,
    template: ReportTemplate,
    snapshot_ids: set[uuid.UUID],
) -> None:
    headings = [section.heading.strip() for section in output.sections]
    missing = [heading for heading in template.sections if heading not in headings]
    if missing:
        raise ReportWorkflowError(
            f"El informe no contiene las secciones requeridas: {', '.join(missing)}."
        )
    for section in output.sections:
        for paragraph in section.paragraphs:
            if paragraph.kind == "fact" and not paragraph.evidence_ids:
                raise ReportWorkflowError("Cada párrafo factual debe citar evidencia.")
    cited = _claim_evidence_ids(output)
    source_index_ids = {item.evidence_id for item in output.source_index}
    if not cited.issubset(snapshot_ids) or not source_index_ids.issubset(snapshot_ids):
        raise ReportWorkflowError("El informe cita evidencia fuera de su snapshot.")
    if source_index_ids != cited:
        raise ReportWorkflowError(
            "El índice de fuentes debe coincidir exactamente con las evidencias citadas."
        )


def _normalize_report_paragraph_claims(output: ReportOutput) -> ReportOutput:
    """Avoid publishing uncited facts by downgrading them to bounded inferences."""

    payload = output.model_dump(mode="json")
    changed = False
    for section in payload.get("sections", []):
        for paragraph in section.get("paragraphs", []):
            if paragraph.get("kind") == "fact" and not paragraph.get("evidence_ids"):
                paragraph["kind"] = "inference"
                paragraph["confidence"] = min(int(paragraph.get("confidence", 0)), 70)
                changed = True
    if not changed:
        return output
    return ReportOutput.model_validate_json(_canonical(payload))


def _authoritative_source_index(
    output: ReportOutput, snapshot_rows: list[ReportSnapshotEvidence]
) -> ReportOutput:
    output = _normalize_report_paragraph_claims(output)
    cited = _claim_evidence_ids(output)
    by_id = {item.evidence_id: item for item in snapshot_rows}
    payload = output.model_dump(mode="json")
    payload["source_index"] = [
        {
            "evidence_id": str(item.evidence_id),
            "label": item.source_label,
            "locator": json.dumps(
                item.locator, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        }
        for item in snapshot_rows
        if item.evidence_id in cited and item.evidence_id in by_id
    ]
    return _sanitize_report_prose(ReportOutput.model_validate_json(_canonical(payload)))


_UUID_IN_PROSE = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.IGNORECASE)


def _sanitize_report_prose(output: ReportOutput) -> ReportOutput:
    """Keep evidence UUIDs structured while exposing only human citation indices in prose."""

    citations = {
        str(item.evidence_id).lower(): f"[{index}]"
        for index, item in enumerate(output.source_index, start=1)
    }
    payload = output.model_dump(mode="json")

    def sanitize(value: Any, *, key: str | None = None) -> Any:
        if key in {"evidence_id", "evidence_ids"}:
            return value
        if isinstance(value, str):
            return _UUID_IN_PROSE.sub(
                lambda match: citations.get(match.group(0).lower(), "[fuente no disponible]"),
                value,
            )
        if isinstance(value, list):
            return [sanitize(item) for item in value]
        if isinstance(value, dict):
            return {item_key: sanitize(item, key=item_key) for item_key, item in value.items()}
        return value

    sanitized = sanitize(payload)
    if sanitized == payload:
        return output
    return ReportOutput.model_validate_json(_canonical(sanitized))


def _sanitize_report_content_for_ui(content: dict[str, Any]) -> dict[str, Any]:
    """Sanitize legacy stored report prose without mutating persisted JSON."""

    try:
        output = ReportOutput.model_validate_json(_canonical(content))
    except ValueError:
        return content
    sanitized = _sanitize_report_prose(output).model_dump(mode="json")
    return sanitized if isinstance(sanitized, dict) else content


def _validate_options(
    template: ReportTemplate, dossier_id: uuid.UUID, raw: dict[str, Any]
) -> dict[str, Any]:
    allowed = set(template.input_contract.get("properties", {})) | {
        "formats",
        "classification",
        "confidentiality_label",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ReportWorkflowError(
            f"Opciones de informe no admitidas: {', '.join(sorted(unknown))}."
        )
    options = dict(raw)
    for required in template.input_contract.get("required", []):
        if required != "dossier_id" and not options.get(required):
            raise ReportWorkflowError(f"{required} es obligatorio para este template.")
    for key, declared in template.input_contract.get("properties", {}).items():
        if key not in options:
            continue
        kind = str(declared).removesuffix("?")
        value = options[key]
        if kind == "string":
            if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
                raise ReportWorkflowError(f"{key} debe ser texto de entre 1 y 500 caracteres.")
            options[key] = value.strip()
        elif kind == "date":
            if not isinstance(value, str):
                raise ReportWorkflowError(f"{key} debe ser una fecha ISO.")
        elif kind == "uuid":
            try:
                options[key] = str(uuid.UUID(str(value)))
            except ValueError as error:
                raise ReportWorkflowError(f"{key} debe ser UUID.") from error
        elif kind == "uuid[]":
            if not isinstance(value, list) or len(value) > 100:
                raise ReportWorkflowError(f"{key} debe ser una lista de hasta 100 UUID.")
            try:
                options[key] = sorted({str(uuid.UUID(str(item))) for item in value})
            except ValueError as error:
                raise ReportWorkflowError(f"{key} contiene un UUID no válido.") from error
        else:
            raise ReportWorkflowError(f"Contrato de template no soportado para {key}.")
    for key, model in (
        ("opportunity_id", Opportunity),
        ("risk_id", RiskItem),
        ("meeting_id", Meeting),
    ):
        if key not in options:
            continue
        try:
            resource_id = uuid.UUID(str(options[key]))
        except ValueError as error:
            raise ReportWorkflowError(f"{key} debe ser UUID.") from error
        resource = db.session.scalar(
            select(model).where(model.id == resource_id, model.dossier_id == dossier_id)
        )
        if resource is None:
            raise ReportWorkflowError(f"{key} no pertenece al expediente.")
        options[key] = str(resource_id)
    if "actor_ids" in options:
        actor_ids = {uuid.UUID(value) for value in options["actor_ids"]}
        found = set(
            db.session.scalars(
                select(DossierActor.actor_id).where(
                    DossierActor.dossier_id == dossier_id,
                    DossierActor.actor_id.in_(actor_ids),
                )
            )
        )
        if found != actor_ids:
            raise ReportWorkflowError("actor_ids contiene un actor ajeno al expediente.")
        options["actor_ids"] = sorted(str(value) for value in actor_ids)
    if "owner_user_ids" in options:
        owner_ids = {uuid.UUID(value) for value in options["owner_user_ids"]}
        found_owners = set(
            db.session.scalars(
                select(TenantMembership.user_id).where(
                    TenantMembership.tenant_id == require_tenant_id(),
                    TenantMembership.user_id.in_(owner_ids),
                    TenantMembership.status == "active",
                )
            )
        )
        if found_owners != owner_ids:
            raise ReportWorkflowError("owner_user_ids contiene un miembro inactivo o ajeno.")
        options["owner_user_ids"] = sorted(str(value) for value in owner_ids)
    for key in ("period_start", "period_end", "deadline"):
        if key in options:
            try:
                options[key] = date.fromisoformat(str(options[key])).isoformat()
            except ValueError as error:
                raise ReportWorkflowError(f"{key} debe ser una fecha ISO.") from error
    if (
        options.get("period_start")
        and options.get("period_end")
        and options["period_start"] > options["period_end"]
    ):
        raise ReportWorkflowError("period_start no puede ser posterior a period_end.")
    formats = options.get("formats", ["html", "json"])
    if not isinstance(formats, list) or not formats:
        raise ReportWorkflowError("formats debe ser una lista no vacía.")
    normalized_formats = tuple(dict.fromkeys(str(value) for value in formats))
    if not set(normalized_formats).issubset(template.formats):
        raise ReportWorkflowError("Formato de informe no permitido por el template.")
    renderer: PDFRenderer = current_app.extensions["pdf_renderer"]
    if "pdf" in normalized_formats and not renderer.enabled:
        raise ReportWorkflowError("PDF no está habilitado; solicita HTML o JSON.")
    options["formats"] = list(normalized_formats)
    classification = str(options.get("classification", "internal"))
    if classification not in {"public", "internal"}:
        raise ReportWorkflowError("classification debe ser public o internal.")
    options["classification"] = classification
    allowed_labels = {"Público"} if classification == "public" else {"Uso interno", "Confidencial"}
    default_label = "Público" if classification == "public" else "Uso interno"
    label = str(options.get("confidentiality_label", default_label)).strip()
    if label not in allowed_labels:
        raise ReportWorkflowError("confidentiality_label no es válido.")
    options["confidentiality_label"] = label
    return options


def _snapshot(
    dossier: StrategicDossier, template: ReportTemplate, options: dict[str, Any]
) -> tuple[dict[str, Any], list[Evidence]]:
    procurement_items = (
        list(
            db.session.scalars(
                select(DossierProcurementItem)
                .where(DossierProcurementItem.dossier_id == dossier.id)
                .order_by(DossierProcurementItem.created_at.desc(), DossierProcurementItem.id)
                .limit(50)
            )
        )
        if template.key in {"tender", COMPETITIVE_PROCUREMENT_TEMPLATE}
        else []
    )
    if template.key == COMPETITIVE_PROCUREMENT_TEMPLATE:
        evidence_ids = [item.evidence_id for item in procurement_items if item.kind == "award"]
    else:
        evidence_ids = list(
            db.session.scalars(
                select(EvidenceDossier.evidence_id).where(EvidenceDossier.dossier_id == dossier.id)
            )
        )
    evidence = list(
        db.session.scalars(
            select(Evidence)
            .where(Evidence.id.in_(evidence_ids))
            .order_by(Evidence.created_at, Evidence.id)
            .limit(500)
        )
    )
    objectives = list(
        db.session.scalars(
            select(DossierObjective)
            .where(DossierObjective.dossier_id == dossier.id)
            .order_by(DossierObjective.position, DossierObjective.id)
            .limit(10)
        )
    )
    hypotheses = list(
        db.session.scalars(
            select(Hypothesis)
            .where(Hypothesis.dossier_id == dossier.id)
            .order_by(Hypothesis.created_at, Hypothesis.id)
            .limit(10)
        )
    )
    living_summary = db.session.scalar(
        select(LivingSummary).where(LivingSummary.dossier_id == dossier.id)
    )
    payload = {
        "schema": "oracle-report-snapshot-v1",
        "captured_at": datetime.now(UTC).isoformat(),
        "dossier": {
            "id": str(dossier.id),
            "title": dossier.title,
            "description": dossier.description,
            "strategic_goal": dossier.strategic_goal,
            "status": dossier.status,
            "version": dossier.version,
        },
        "template": {
            "key": template.key,
            "version": template.version,
            "sha256": template.sha256.hex(),
            "sections": list(template.sections),
            "evidence_policy": template.evidence_policy,
        },
        "options": options,
        "objectives": [
            {"id": str(item.id), "title": item.title, "status": item.status} for item in objectives
        ],
        "hypotheses": [
            {
                "id": str(item.id),
                "statement": item.statement,
                "status": item.status,
                "confidence": item.confidence,
            }
            for item in hypotheses
        ],
        "living_summary": living_summary.summary if living_summary else {},
        "procurement_items": [
            {
                "id": str(item.id),
                "kind": item.kind,
                "folder_id": item.folder_id,
                "source_url": item.source_url,
                "evidence_id": str(item.evidence_id),
                "snapshot": item.snapshot,
            }
            for item in procurement_items
        ],
        "evidence": [_snapshot_evidence_payload(item) for item in evidence],
    }
    return payload, evidence


def _snapshot_evidence_payload(item: Evidence) -> dict[str, Any]:
    source_label = item.source_url or f"Evidencia {item.id}"
    frozen = {
        "extract": item.extract,
        "locator": item.locator,
        "classification": item.classification,
        "source_label": source_label,
    }
    return {
        "id": str(item.id),
        "version": item.version,
        "checksum": item.checksum.hex(),
        "classification": item.classification,
        "locator": item.locator,
        "source_label": source_label,
        "snapshot_row_hash": _sha256(frozen).hex(),
    }


def _validate_report_snapshot(report: Report) -> list[ReportSnapshotEvidence]:
    if _sha256(report.source_snapshot) != report.source_snapshot_hash:
        raise ReportWorkflowError(
            "El snapshot del informe no supera la verificación de integridad."
        )
    source_template = report.source_snapshot.get("template", {})
    try:
        template = ReportTemplateRegistry().get(report.template_key, report.template_version)
    except KeyError as error:
        raise ReportWorkflowError("El contrato congelado del informe fue alterado.") from error
    if (
        source_template.get("key") != report.template_key
        or source_template.get("version") != report.template_version
        or source_template.get("sha256") != template.sha256.hex()
        or report.options != report.source_snapshot.get("options")
    ):
        raise ReportWorkflowError("El contrato congelado del informe fue alterado.")
    rows = list(
        db.session.scalars(
            select(ReportSnapshotEvidence).where(ReportSnapshotEvidence.report_id == report.id)
        )
    )
    source_evidence = report.source_snapshot.get("evidence", [])
    metadata = {str(item["id"]): item for item in source_evidence}
    rows_by_id = {str(item.evidence_id): item for item in rows}
    if set(metadata) != set(rows_by_id):
        raise ReportWorkflowError("El conjunto de evidencia del snapshot fue alterado.")
    ordered_rows = [rows_by_id[str(item["id"])] for item in source_evidence]
    for row in ordered_rows:
        expected = metadata[str(row.evidence_id)]
        frozen = {
            "extract": row.extract,
            "locator": row.locator,
            "classification": row.classification,
            "source_label": row.source_label,
        }
        if (
            expected.get("snapshot_row_hash") != _sha256(frozen).hex()
            or expected.get("checksum") != row.evidence_hash.hex()
        ):
            raise ReportWorkflowError("Una evidencia congelada del informe fue alterada.")
    return ordered_rows


def _frozen_report_context(report: Report, max_tokens: int) -> BuiltContext:
    snapshot_rows = _validate_report_snapshot(report)
    snapshot_by_id = {str(item.evidence_id): item for item in snapshot_rows}
    ordered_ids = [str(item["id"]) for item in report.source_snapshot.get("evidence", [])]
    evidence_rows = {
        str(item.id): item
        for item in db.session.scalars(
            select(Evidence).where(Evidence.id.in_(item.evidence_id for item in snapshot_rows))
        )
    }
    frozen: list[FrozenEvidence] = []
    for evidence_id in ordered_ids:
        snapshot = snapshot_by_id.get(evidence_id)
        evidence = evidence_rows.get(evidence_id)
        if snapshot is None or evidence is None:
            raise ReportWorkflowError("El snapshot de evidencia ya no es reproducible.")
        frozen.append(
            FrozenEvidence(
                row=evidence,
                extract=snapshot.extract,
                classification=snapshot.classification,
                locator=dict(snapshot.locator),
                checksum=snapshot.evidence_hash,
            )
        )
    source = report.source_snapshot
    return build_frozen_context(
        dossier_id=report.dossier_id,
        dossier=dict(source.get("dossier", {})),
        objectives=list(source.get("objectives", [])),
        hypotheses=list(source.get("hypotheses", [])),
        living_summary=dict(source.get("living_summary", {})),
        evidence=tuple(frozen),
        max_tokens=max_tokens,
        procurement_items=list(source.get("procurement_items", [])),
    )


def refresh_report_snapshot(report: Report) -> None:
    """Replace a draft snapshot after a durable pre-processing step.

    Procurement document reports use this only before invoking the report
    writer, so the final snapshot remains immutable and reproducible.
    """
    if report.status not in {"draft", "generating"}:
        raise ReportWorkflowError("El snapshot solo se puede preparar antes de generar.")
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == report.dossier_id,
            StrategicDossier.tenant_id == report.tenant_id,
        )
    )
    if dossier is None:
        raise ReportWorkflowError("Expediente no disponible para preparar el informe.")
    template = ReportTemplateRegistry().get(report.template_key, report.template_version)
    snapshot, evidence = _snapshot(dossier, template, report.options)
    db.session.execute(
        delete(ReportSnapshotEvidence).where(ReportSnapshotEvidence.report_id == report.id)
    )
    db.session.execute(delete(ReportEvidence).where(ReportEvidence.report_id == report.id))
    report.source_snapshot = snapshot
    report.source_snapshot_hash = _sha256(snapshot)
    report.version += 1
    for item in evidence:
        db.session.add(
            ReportSnapshotEvidence(
                tenant_id=report.tenant_id,
                report_id=report.id,
                evidence_id=item.id,
                dossier_id=report.dossier_id,
                evidence_hash=item.checksum,
                extract=item.extract,
                locator=item.locator,
                classification=item.classification,
                source_label=item.source_url or f"Evidencia {item.id}",
            )
        )
        db.session.add(
            ReportEvidence(
                tenant_id=report.tenant_id,
                report_id=report.id,
                evidence_id=item.id,
            )
        )
    db.session.commit()


def create_report_request(
    dossier: StrategicDossier,
    *,
    template_key: str,
    options: dict[str, Any],
    requested_by_user_id: uuid.UUID,
    idempotency_key: str,
    parent_report_id: uuid.UUID | None = None,
    job_type: str = "oracle.report.generate",
) -> tuple[Report, BackgroundJob, bool]:
    tenant_id = require_tenant_id()
    if dossier.status == "archived":
        raise ReportWorkflowError("Un expediente archivado es de solo lectura.")
    if not 8 <= len(idempotency_key) <= 200:
        raise ReportWorkflowError("Idempotency-Key debe tener entre 8 y 200 caracteres.")
    template = ReportTemplateRegistry().get(template_key)
    normalized = _validate_options(template, dossier.id, options)
    if template.key == COMPETITIVE_PROCUREMENT_TEMPLATE:
        pinned_awards = list(
            db.session.scalars(
                select(DossierProcurementItem).where(
                    DossierProcurementItem.tenant_id == tenant_id,
                    DossierProcurementItem.dossier_id == dossier.id,
                    DossierProcurementItem.kind == "award",
                )
            )
        )
        available_winners = pinned_award_winners(pinned_awards)
        selected_company = str(normalized.get("company_name", "")).strip()
        by_casefold = {winner.casefold(): winner for winner in available_winners}
        if not available_winners:
            raise ReportWorkflowError(
                "Fija al menos una adjudicación antes de generar inteligencia competitiva."
            )
        if selected_company.casefold() not in by_casefold:
            raise ReportWorkflowError(
                "El adjudicatario debe coincidir con una denominación registral fijada "
                "en el expediente."
            )
        normalized["company_name"] = by_casefold[selected_company.casefold()]
    request_payload = {
        "dossier_id": str(dossier.id),
        "template_key": template.key,
        "template_version": template.version,
        "options": normalized,
        "parent_report_id": str(parent_report_id) if parent_report_id else None,
        "job_type": job_type,
    }
    request_hash = _sha256(request_payload)
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"report-request:{tenant_id}:{idempotency_key}"},
    )
    existing = db.session.scalar(
        select(Report).where(
            Report.tenant_id == tenant_id, Report.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ReportConflictError("Idempotency-Key ya pertenece a otra solicitud.")
        if existing.background_job_id is None:
            raise ReportWorkflowError("La solicitud idempotente no tiene job asociado.")
        job = db.session.get(BackgroundJob, existing.background_job_id)
        if job is None:
            raise ReportWorkflowError("El job asociado no está disponible.")
        return existing, job, False
    if parent_report_id is not None:
        parent = db.session.scalar(
            select(Report).where(Report.id == parent_report_id, Report.dossier_id == dossier.id)
        )
        if parent is None:
            raise ReportWorkflowError("El informe padre no pertenece al expediente.")
    slot = f"report-version:{tenant_id}:{dossier.id}:{template.key}"
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"), {"slot": slot}
    )
    generation_version = (
        int(
            db.session.scalar(
                select(func.coalesce(func.max(Report.generation_version), 0)).where(
                    Report.dossier_id == dossier.id, Report.template_key == template.key
                )
            )
            or 0
        )
        + 1
    )
    snapshot, evidence = _snapshot(dossier, template, normalized)
    if normalized["classification"] == "public" and any(
        item.classification == "internal" for item in evidence
    ):
        raise ReportWorkflowError(
            "Un informe público no puede incluir evidencia interna en su snapshot."
        )
    report_title = f"{template.label} · {dossier.title}"
    if template.key == COMPETITIVE_PROCUREMENT_TEMPLATE:
        report_title = f"{template.label}: {normalized['company_name']} · {dossier.title}"
    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        title=report_title,
        status="draft",
        content={},
        report_type=template.report_type,
        template_key=template.key,
        template_version=template.version,
        generation_version=generation_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        version=1,
        options=normalized,
        source_snapshot=snapshot,
        source_snapshot_hash=_sha256(snapshot),
        snapshot_hash_algorithm="canonical-json-sha256-v1",
        classification=normalized["classification"],
        confidentiality_label=normalized["confidentiality_label"],
        requested_by_user_id=requested_by_user_id,
        generated_by_user_id=requested_by_user_id,
        parent_report_id=parent_report_id,
    )
    db.session.add(report)
    db.session.flush()
    for item in evidence:
        db.session.add(
            ReportSnapshotEvidence(
                tenant_id=tenant_id,
                report_id=report.id,
                evidence_id=item.id,
                dossier_id=dossier.id,
                evidence_hash=item.checksum,
                extract=item.extract,
                locator=item.locator,
                classification=item.classification,
                source_label=item.source_url or f"Evidencia {item.id}",
            )
        )
        db.session.add(
            ReportEvidence(tenant_id=tenant_id, report_id=report.id, evidence_id=item.id)
        )
    job = stage_job(
        job_type,
        payload={"report_id": str(report.id)},
        idempotency_key=f"report-generate:{report.id}",
        requested_by_user_id=requested_by_user_id,
        dossier_id=dossier.id,
        resource_type="report",
        resource_id=report.id,
        max_attempts=3,
    )
    report.background_job_id = job.id
    append_audit_event(
        db.session,
        action="report.requested",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier.id,
        result="success",
        metadata={
            "template": template.key,
            "template_version": template.version,
            "generation_version": generation_version,
            "evidence_count": len(evidence),
        },
    )
    db.session.commit()
    publish_job(job)
    return report, job, True


def freeze_report_enrichment(
    report: Report,
    *,
    key: str,
    payload: dict[str, Any],
    evidence: Evidence,
    source_label: str,
) -> None:
    """Freeze a durable preprocessing result into a draft report snapshot.

    The derived Evidence row must already be linked to the dossier through
    ``EvidenceDossier`` so the composite FK on ``ReportSnapshotEvidence`` remains
    tenant- and dossier-safe.
    """

    if report.status not in {"draft", "failed"}:
        raise ReportWorkflowError("El informe ya no admite preparación de su snapshot.")
    source_snapshot = dict(report.source_snapshot)
    if key in source_snapshot:
        return
    frozen = {
        "extract": evidence.extract,
        "locator": evidence.locator,
        "classification": evidence.classification,
        "source_label": source_label,
    }
    evidence_metadata = {
        "id": str(evidence.id),
        "version": evidence.version,
        "checksum": evidence.checksum.hex(),
        "classification": evidence.classification,
        "locator": evidence.locator,
        "source_label": source_label,
        "snapshot_row_hash": _sha256(frozen).hex(),
    }
    source_snapshot[key] = payload
    source_snapshot["evidence"] = [
        evidence_metadata,
        *list(source_snapshot.get("evidence", [])),
    ]
    report.source_snapshot = source_snapshot
    report.source_snapshot_hash = _sha256(source_snapshot)
    report.version += 1
    db.session.add(
        ReportSnapshotEvidence(
            tenant_id=report.tenant_id,
            report_id=report.id,
            evidence_id=evidence.id,
            dossier_id=report.dossier_id,
            evidence_hash=evidence.checksum,
            extract=evidence.extract,
            locator=evidence.locator,
            classification=evidence.classification,
            source_label=source_label,
        )
    )
    db.session.add(
        ReportEvidence(
            tenant_id=report.tenant_id,
            report_id=report.id,
            evidence_id=evidence.id,
        )
    )


def _store_artifact(
    *,
    report: Report,
    revision: ReportRevision,
    format_name: str,
    media_type: str,
    payload: bytes,
) -> ReportArtifact:
    max_bytes = int(current_app.config["REPORT_MAX_ARTIFACT_BYTES"])
    if len(payload) > max_bytes:
        raise ReportWorkflowError("El artefacto supera el límite configurado.")
    artifact_id = uuid.uuid4()
    key = object_key(report.tenant_id, report.dossier_id, artifact_id)
    storage: ObjectStorage = current_app.extensions["object_storage"]
    stored = storage.put(key, io.BytesIO(payload), max_bytes=max_bytes, media_type=media_type)
    checksum = hashlib.sha256(payload).digest()
    if stored.checksum != checksum or stored.byte_size != len(payload):
        storage.delete(key)
        raise ReportWorkflowError("El storage devolvió metadata inconsistente.")
    artifact = ReportArtifact(
        id=artifact_id,
        tenant_id=report.tenant_id,
        report_id=report.id,
        revision_id=revision.id,
        format=format_name,
        status="available",
        storage_key=key,
        checksum=checksum,
        byte_size=len(payload),
        media_type=media_type,
        artifact_metadata={
            "renderer": {
                "html": "oracle-safe-html-v1",
                "json": "canonical-json-v1",
                "pdf": type(current_app.extensions["pdf_renderer"]).__name__,
            }[format_name],
            "report_version": report.generation_version,
            "revision_no": revision.revision_no,
        },
    )
    db.session.add(artifact)
    return artifact


def _render_revision_artifacts(report: Report, revision: ReportRevision) -> list[ReportArtifact]:
    template = ReportTemplateRegistry().get(report.template_key, report.template_version)
    formats = set(str(value) for value in report.options.get("formats", ["html", "json"]))
    context = RenderContext(
        report_id=str(report.id),
        version=report.generation_version,
        generated_on=datetime.now(UTC).date(),
        confidentiality_label=report.confidentiality_label,
        template_label=template.label,
    )
    max_bytes = int(current_app.config["REPORT_MAX_ARTIFACT_BYTES"])
    artifacts: list[ReportArtifact] = []
    try:
        if "html" in formats:
            html_payload = render_report_html(revision.content, context, max_bytes=max_bytes)
            artifacts.append(
                _store_artifact(
                    report=report,
                    revision=revision,
                    format_name="html",
                    media_type="text/html; charset=utf-8",
                    payload=html_payload,
                )
            )
        if "json" in formats:
            artifacts.append(
                _store_artifact(
                    report=report,
                    revision=revision,
                    format_name="json",
                    media_type="application/json",
                    payload=_canonical(revision.content),
                )
            )
        if "pdf" in formats:
            renderer: PDFRenderer = current_app.extensions["pdf_renderer"]
            if not renderer.enabled:
                raise ReportWorkflowError("PDF no está habilitado.")
            html_payload = render_report_html(revision.content, context, max_bytes=max_bytes)
            pdf_payload = renderer.render(html_payload, max_bytes=max_bytes)
            if not pdf_payload.startswith(b"%PDF-"):
                raise ReportWorkflowError("El renderer no devolvió un PDF válido.")
            artifacts.append(
                _store_artifact(
                    report=report,
                    revision=revision,
                    format_name="pdf",
                    media_type="application/pdf",
                    payload=pdf_payload,
                )
            )
    except Exception:
        storage: ObjectStorage = current_app.extensions["object_storage"]
        for artifact in artifacts:
            with suppress(Exception):
                storage.delete(artifact.storage_key)
            if artifact in db.session.new:
                db.session.expunge(artifact)
        raise
    return artifacts


def _pending_artifact_keys() -> list[str]:
    return [
        item.storage_key
        for item in db.session.new
        if isinstance(item, ReportArtifact) and item.storage_key
    ]


def process_report(
    report_id: uuid.UUID,
    job: BackgroundJob,
    *,
    agent: str = "report_writer",
    requested_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    execution_lease_id = job.execution_lease_id
    if execution_lease_id is None or job.status != "running":
        raise ReportLeaseLost("El worker no posee una lease activa del job.")
    report = db.session.scalar(
        select(Report)
        .where(Report.id == report_id, Report.tenant_id == tenant_id)
        .with_for_update()
    )
    if report is None or report.background_job_id != job.id:
        raise ReportWorkflowError("Informe no disponible para este job.")
    try:
        _validate_report_snapshot(report)
    except ReportWorkflowError as error:
        if report.status in {"draft", "generating", "failed"}:
            report.status = "failed"
            report.error_code = type(error).__name__[:100]
            report.error_message = "No se pudo generar el informe. Revisa el job para más detalle."
            report.version += 1
            db.session.commit()
        raise
    existing_revision = db.session.scalar(
        select(ReportRevision).where(ReportRevision.report_id == report.id).limit(1)
    )
    if report.status in {"ready", "reviewed", "published", "superseded"} and existing_revision:
        return {"report_id": str(report.id), "revision_id": str(existing_revision.id)}
    if report.status not in {"draft", "generating", "failed"}:
        raise ReportWorkflowError("Estado de informe no procesable.")
    report.status = "generating"
    report.error_code = report.error_message = None
    report.version += 1
    db.session.commit()
    written_keys: list[str] = []
    created_notification: CreatedNotification | None = None
    result_payload: dict[str, Any] | None = None
    frozen_report = report
    try:
        supplemental_context = {
            "report_id": str(report.id),
            "template_key": report.template_key,
            "template_version": report.template_version,
            "required_sections": report.source_snapshot["template"]["sections"],
            "evidence_policy": report.source_snapshot["template"]["evidence_policy"],
            "options": report.options,
            "snapshot_hash": report.source_snapshot_hash.hex(),
            **(requested_scope or {}),
        }
        result = execute_agent(
            agent=agent,
            dossier_id=report.dossier_id,
            job=job,
            supplemental_context=supplemental_context,
            context_factory=lambda max_tokens: _frozen_report_context(frozen_report, max_tokens),
            target_type="report",
            target_id=report.id,
        )
        artifact = db.session.get(AIArtifact, uuid.UUID(result["artifact_id"]))
        if artifact is None or artifact.target_id != report.id:
            raise ReportWorkflowError("El agente no produjo un artefacto de informe válido.")
        output = ReportOutput.model_validate_json(_canonical(artifact.output))
        snapshot_rows = _validate_report_snapshot(report)
        output = _authoritative_source_index(output, snapshot_rows)
        snapshot_ids = {item.evidence_id for item in snapshot_rows}
        template = ReportTemplateRegistry().get(report.template_key, report.template_version)
        _validate_report_output(output, template=template, snapshot_ids=snapshot_ids)
        payload = output.model_dump(mode="json")
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
            .execution_options(populate_existing=True)
        )
        if owned_job is None:
            raise ReportLeaseLost("La lease del job cambió durante la generación.")
        report = db.session.scalar(select(Report).where(Report.id == report_id).with_for_update())
        if report is None or report.status != "generating":
            raise ReportWorkflowError("El informe perdió su estado de generación.")
        revision = ReportRevision(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            report_id=report.id,
            revision_no=1,
            status="ready",
            title=output.title[:300],
            content=payload,
            content_hash=_sha256(payload),
            created_by_user_id=report.requested_by_user_id,
            change_summary="Generación inicial validada por Evidence Reviewer.",
        )
        db.session.add(revision)
        db.session.flush()
        artifacts = _render_revision_artifacts(report, revision)
        written_keys.extend(item.storage_key for item in artifacts)
        final_owned_job = db.session.scalar(
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
        if final_owned_job is None:
            raise ReportLeaseLost("La lease del job expiró durante el render.")
        now = datetime.now(UTC)
        report.title = output.title[:300]
        report.content = payload
        report.status = "ready"
        report.ready_at = now
        report.ai_artifact_id = artifact.id
        report.generated_by_user_id = report.requested_by_user_id
        report.version += 1
        created_notification = create_notification(
            user_id=report.requested_by_user_id,
            notification_type="report.ready",
            severity="success",
            title="Informe listo para revisión",
            body=f"{report.title} ya está disponible con sus evidencias.",
            dedupe_key=f"report-ready:{report.id}:{revision.id}",
            link=f"/app/dossiers/{report.dossier_id}/reports?report={report.id}",
            dossier_id=report.dossier_id,
            job_id=job.id,
            report_id=report.id,
            resource_type="report",
            resource_id=report.id,
        )
        append_audit_event(
            db.session,
            action="report.ready",
            resource_type="report",
            resource_id=report.id,
            dossier_id=report.dossier_id,
            result="success",
            metadata={
                "revision": revision.revision_no,
                "formats": sorted(item.format for item in artifacts),
                "ai_artifact_id": str(artifact.id),
            },
        )
        db.session.commit()
        result_payload = {
            "report_id": str(report.id),
            "revision_id": str(revision.id),
            "artifact_ids": [str(item.id) for item in artifacts],
        }
    except ReportLeaseLost:
        written_keys.extend(_pending_artifact_keys())
        db.session.rollback()
        artifact_storage = current_app.extensions["object_storage"]
        for key in set(written_keys):
            with suppress(Exception):
                artifact_storage.delete(key)
        raise
    except Exception as error:
        written_keys.extend(_pending_artifact_keys())
        db.session.rollback()
        storage: ObjectStorage = current_app.extensions["object_storage"]
        for key in written_keys:
            with suppress(Exception):
                storage.delete(key)
        failed = db.session.scalar(select(Report).where(Report.id == report_id).with_for_update())
        if failed is not None and failed.status in {"draft", "generating", "failed"}:
            failed.status = "failed"
            failed.error_code = type(error).__name__[:100]
            failed.error_message = "No se pudo generar el informe. Revisa el job para más detalle."
            failed.version += 1
            db.session.commit()
        raise
    if created_notification is not None:
        with suppress(Exception):
            publish_notification_job(created_notification)
    assert result_payload is not None
    return result_payload


def latest_revision(report_id: uuid.UUID) -> ReportRevision | None:
    return db.session.scalar(
        select(ReportRevision)
        .where(ReportRevision.report_id == report_id)
        .order_by(ReportRevision.revision_no.desc())
        .limit(1)
    )


def create_human_revision(
    report: Report, *, payload: dict[str, Any], user_id: uuid.UUID, change_summary: str
) -> ReportRevision:
    if report.status not in {"ready", "reviewed"}:
        raise ReportWorkflowError(
            "Solo informes no publicados admiten revisión in-place; crea una nueva versión."
        )
    output = ReportOutput.model_validate_json(_canonical(payload))
    snapshot_rows = _validate_report_snapshot(report)
    output = _authoritative_source_index(output, snapshot_rows)
    allowed = {item.evidence_id for item in snapshot_rows}
    template = ReportTemplateRegistry().get(report.template_key, report.template_version)
    _validate_report_output(output, template=template, snapshot_ids=allowed)
    previous = latest_revision(report.id)
    if previous is None:
        raise ReportWorkflowError("El informe no tiene una revisión base.")
    revision = ReportRevision(
        id=uuid.uuid4(),
        tenant_id=report.tenant_id,
        report_id=report.id,
        revision_no=previous.revision_no + 1,
        status="ready",
        title=output.title[:300],
        content=output.model_dump(mode="json"),
        content_hash=_sha256(output.model_dump(mode="json")),
        created_by_user_id=user_id,
        change_summary=change_summary.strip()[:1000],
    )
    written_keys: list[str] = []
    try:
        previous.status = "superseded"
        db.session.add(revision)
        db.session.flush()
        artifacts = _render_revision_artifacts(report, revision)
        written_keys.extend(item.storage_key for item in artifacts)
        report.title = revision.title
        report.content = revision.content
        report.status = "ready"
        report.reviewed_at = None
        report.reviewed_by_user_id = None
        report.version += 1
        append_audit_event(
            db.session,
            action="report.revision_created",
            resource_type="report",
            resource_id=report.id,
            dossier_id=report.dossier_id,
            result="success",
            metadata={"revision": revision.revision_no},
        )
        db.session.commit()
    except Exception:
        written_keys.extend(_pending_artifact_keys())
        db.session.rollback()
        storage: ObjectStorage = current_app.extensions["object_storage"]
        for key in set(written_keys):
            with suppress(Exception):
                storage.delete(key)
        raise
    return revision


def review_report(
    report: Report,
    *,
    revision_id: uuid.UUID,
    decision: str,
    comment: str,
    reviewer_user_id: uuid.UUID,
) -> ReportReview:
    if report.status not in {"ready", "reviewed"}:
        raise ReportWorkflowError("El informe no está listo para revisión.")
    revision = db.session.scalar(
        select(ReportRevision).where(
            ReportRevision.id == revision_id, ReportRevision.report_id == report.id
        )
    )
    if revision is None or revision != latest_revision(report.id):
        raise ReportWorkflowError("Solo puede revisarse la revisión vigente.")
    if decision not in {"approved", "changes_requested", "comment"}:
        raise ReportWorkflowError("Decisión de revisión no válida.")
    if decision != "approved" and not comment.strip():
        raise ReportWorkflowError("El comentario es obligatorio para esta decisión.")
    review = ReportReview(
        tenant_id=report.tenant_id,
        report_id=report.id,
        revision_id=revision.id,
        reviewer_user_id=reviewer_user_id,
        decision=decision,
        comment=comment.strip()[:10000],
    )
    db.session.add(review)
    if decision == "approved":
        report.status = "reviewed"
        report.reviewed_at = datetime.now(UTC)
        report.reviewed_by_user_id = reviewer_user_id
        revision.status = "reviewed"
    elif decision == "changes_requested":
        report.status = "ready"
        revision.status = "ready"
    report.version += 1
    append_audit_event(
        db.session,
        action=f"report.review.{decision}",
        resource_type="report",
        resource_id=report.id,
        dossier_id=report.dossier_id,
        result="success",
        metadata={"revision_id": str(revision.id)},
    )
    db.session.commit()
    return review


def publish_report(report: Report, *, publisher_user_id: uuid.UUID) -> Report:
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": (f"report-publish:{report.tenant_id}:{report.dossier_id}:{report.template_key}")},
    )
    current = db.session.scalar(
        select(Report)
        .where(Report.id == report.id, Report.tenant_id == report.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or current.status != "reviewed":
        raise ReportWorkflowError("El informe debe estar revisado antes de publicar.")
    newer = db.session.scalar(
        select(Report.id)
        .where(
            Report.dossier_id == current.dossier_id,
            Report.template_key == current.template_key,
            Report.generation_version > current.generation_version,
            Report.status.in_(("reviewed", "published")),
        )
        .order_by(Report.generation_version.desc())
        .limit(1)
    )
    if newer is not None:
        raise ReportWorkflowError("Existe una versión posterior revisada o publicada.")
    revision = latest_revision(current.id)
    if revision is None or revision.status != "reviewed":
        raise ReportWorkflowError("La revisión vigente no está aprobada.")
    now = datetime.now(UTC)
    previous = list(
        db.session.scalars(
            select(Report)
            .where(
                Report.dossier_id == current.dossier_id,
                Report.template_key == current.template_key,
                Report.status == "published",
                Report.id != current.id,
            )
            .with_for_update()
        )
    )
    for item in previous:
        item.status = "superseded"
        item.superseded_at = now
        item.version += 1
        previous_revision = latest_revision(item.id)
        if previous_revision is not None:
            previous_revision.status = "superseded"
    current.status = "published"
    current.published_at = now
    current.published_by_user_id = publisher_user_id
    current.version += 1
    revision.status = "published"
    append_audit_event(
        db.session,
        action="report.published",
        resource_type="report",
        resource_id=current.id,
        dossier_id=current.dossier_id,
        result="success",
        metadata={"revision_id": str(revision.id), "superseded_count": len(previous)},
    )
    db.session.commit()
    return current


def serialize_report(report: Report, *, detail: bool = False) -> dict[str, Any]:
    revision = latest_revision(report.id)
    artifacts = []
    reviews = []
    evidence = []
    generation: dict[str, Any] | None = None
    if getattr(report, "ai_artifact_id", None) is not None:
        generation_row = db.session.execute(
            select(AIAuditLog)
            .join(AIArtifact, AIArtifact.audit_log_id == AIAuditLog.id)
            .where(
                AIArtifact.id == report.ai_artifact_id,
                AIArtifact.tenant_id == report.tenant_id,
            )
        ).scalar_one_or_none()
        if generation_row is not None:
            generation = {
                "provider": generation_row.provider,
                "model": generation_row.model,
                "prompt_name": generation_row.prompt_name,
                "prompt_version": generation_row.prompt_version,
                "latency_ms": generation_row.latency_ms,
                "estimated_cost_micros": generation_row.estimated_cost_micros,
                "actual_cost_micros": generation_row.actual_cost_micros,
            }
    if revision is not None:
        artifacts = list(
            db.session.scalars(
                select(ReportArtifact)
                .where(ReportArtifact.revision_id == revision.id)
                .order_by(ReportArtifact.format)
            )
        )
    if detail:
        reviews = list(
            db.session.scalars(
                select(ReportReview)
                .where(ReportReview.report_id == report.id)
                .order_by(ReportReview.created_at)
            )
        )
        evidence = list(
            db.session.scalars(
                select(ReportSnapshotEvidence)
                .where(ReportSnapshotEvidence.report_id == report.id)
                .order_by(ReportSnapshotEvidence.evidence_id)
            )
        )
    return {
        "id": str(report.id),
        "dossier_id": str(report.dossier_id),
        "title": report.title,
        "status": report.status,
        "report_type": report.report_type,
        "template_key": report.template_key,
        "template_version": report.template_version,
        "generation_version": report.generation_version,
        "classification": report.classification,
        "confidentiality_label": report.confidentiality_label,
        "job_id": str(report.background_job_id) if report.background_job_id else None,
        "parent_report_id": str(report.parent_report_id) if report.parent_report_id else None,
        "ready_at": report.ready_at.isoformat() if report.ready_at else None,
        "reviewed_at": report.reviewed_at.isoformat() if report.reviewed_at else None,
        "published_at": report.published_at.isoformat() if report.published_at else None,
        "error_code": report.error_code,
        "generation": generation,
        "version": report.version,
        "revision": (
            {
                "id": str(revision.id),
                "revision_no": revision.revision_no,
                "status": revision.status,
                "title": revision.title,
                "content": _sanitize_report_content_for_ui(revision.content) if detail else None,
                "change_summary": revision.change_summary,
                "created_at": revision.created_at.isoformat(),
            }
            if revision
            else None
        ),
        "artifacts": [
            {
                "id": str(item.id),
                "format": item.format,
                "status": item.status,
                "byte_size": item.byte_size,
                "checksum": item.checksum.hex(),
                "media_type": item.media_type,
            }
            for item in artifacts
        ],
        "reviews": [
            {
                "id": str(item.id),
                "revision_id": str(item.revision_id),
                "decision": item.decision,
                "comment": item.comment,
                "reviewer_user_id": str(item.reviewer_user_id),
                "created_at": item.created_at.isoformat(),
            }
            for item in reviews
        ],
        "evidence": [
            {
                "id": str(item.evidence_id),
                "extract": item.extract,
                "locator": item.locator,
                "classification": item.classification,
                "source_label": item.source_label,
                "checksum": item.evidence_hash.hex(),
            }
            for item in evidence
        ],
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
    }
