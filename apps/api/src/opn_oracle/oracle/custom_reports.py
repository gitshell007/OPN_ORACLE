"""Minimal custom report brief intake (MEMSOL-07).

Creates a durable Report row + BackgroundJob in pending/queued state for a
free-text brief. Does NOT invoke Signal, report_writer, or plan generation.

plan_status lifecycle (product): draft | proposed | accepted
Report.status stays within existing constraint (draft while planning).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import Report, StrategicDossier
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

CUSTOM_BRIEF_TEMPLATE_KEY = "custom_assistant_brief"
CUSTOM_BRIEF_TEMPLATE_VERSION = "v1"
CUSTOM_BRIEF_REPORT_TYPE = "custom_assistant"
CUSTOM_BRIEF_JOB = "oracle.report.custom_brief.plan"
PLAN_STATUSES = frozenset({"draft", "proposed", "accepted"})
MAX_BRIEF_CHARS = 20_000
SNAPSHOT_HASH_ALG = "canonical-json-sha256-v1"


class CustomReportError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"custom_report": [message]})


class CustomReportNotFound(LookupError):
    pass


class CustomReportConflict(RuntimeError):
    pass


def _sha256(payload: Any) -> bytes:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).digest()


def _load_dossier(session: Session, dossier_id: uuid.UUID) -> StrategicDossier:
    tenant_id = require_tenant_id()
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
            StrategicDossier.status != "archived",
        )
    )
    if dossier is None:
        raise CustomReportNotFound("Expediente no encontrado.")
    return dossier


def serialize_custom_brief(report: Report) -> dict[str, Any]:
    options = dict(report.options or {})
    try:
        from opn_oracle.oracle.custom_report_lifecycle import serialize_lifecycle

        life = serialize_lifecycle(report)
    except Exception:
        life = {}
    return {
        "id": str(report.id),
        "tenant_id": str(report.tenant_id),
        "dossier_id": str(report.dossier_id),
        "title": report.title,
        "status": report.status,
        "report_type": report.report_type,
        "template_key": report.template_key,
        "template_version": report.template_version,
        "generation_version": report.generation_version,
        "version": getattr(report, "version", 1),
        "etag": f'W/"{getattr(report, "version", 1)}"',
        "brief_request": str(options.get("brief_request") or ""),
        "plan_status": str(options.get("plan_status") or "draft"),
        "lifecycle_state": life.get("lifecycle_state")
        or str(options.get("lifecycle_state") or "brief_draft"),
        "proposed_plan": options.get("proposed_plan"),
        "accepted_plan": options.get("accepted_plan"),
        "accepted_snapshot_hash": options.get("accepted_snapshot_hash")
        or life.get("accepted_snapshot_hash"),
        "memory_degraded": bool(options.get("memory_degraded", False)),
        "memory_degraded_reason": options.get("memory_degraded_reason"),
        "coverage": options.get("coverage") or life.get("coverage"),
        "ready_artifact": options.get("ready_artifact"),
        "downloadable": bool(life.get("downloadable")),
        "background_job_id": (
            str(report.background_job_id) if report.background_job_id is not None else None
        ),
        "error_code": getattr(report, "error_code", None),
        "error_message": getattr(report, "error_message", None),
        "requested_by_user_id": str(report.requested_by_user_id),
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
        "ready_at": (report.ready_at.isoformat() if getattr(report, "ready_at", None) else None),
    }


def get_custom_brief(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
) -> Report:
    """Load a custom brief report for the current tenant/dossier."""

    tenant_id = require_tenant_id()
    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
            Report.template_key == CUSTOM_BRIEF_TEMPLATE_KEY,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe de brief no encontrado.")
    return report


def create_custom_report_brief(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
    brief_request: str,
    idempotency_key: str,
    request_id: str | None = None,
    publish: bool = False,
) -> tuple[Report, BackgroundJob]:
    """Persist Report(brief) + BackgroundJob without Signal or report_writer."""

    if not 8 <= len(idempotency_key) <= 200:
        raise CustomReportError(
            "Idempotency-Key debe tener entre 8 y 200 caracteres.",
            errors={"idempotency_key": ["Debe tener entre 8 y 200 caracteres."]},
        )
    brief = str(brief_request or "").strip()
    if not 1 <= len(brief) <= MAX_BRIEF_CHARS:
        raise CustomReportError(
            f"brief_request debe contener entre 1 y {MAX_BRIEF_CHARS} caracteres.",
            errors={"brief_request": [f"Debe contener entre 1 y {MAX_BRIEF_CHARS} caracteres."]},
        )

    dossier = _load_dossier(session, dossier_id)
    tenant_id = require_tenant_id()

    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot,0))"),
        {"slot": f"custom-brief:{tenant_id}:{idempotency_key}"},
    )
    existing = session.scalar(
        select(Report).where(
            Report.tenant_id == tenant_id,
            Report.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        options = dict(existing.options or {})
        if (
            existing.template_key != CUSTOM_BRIEF_TEMPLATE_KEY
            or str(options.get("brief_request") or "") != brief
        ):
            raise CustomReportConflict("Idempotency-Key ya pertenece a otra solicitud.")
        if existing.background_job_id is None:
            raise CustomReportError("La solicitud idempotente no tiene job asociado.")
        job = session.get(BackgroundJob, existing.background_job_id)
        if job is None:
            raise CustomReportError("El job asociado no está disponible.")
        return existing, job

    generation_version = (
        int(
            session.scalar(
                select(func.coalesce(func.max(Report.generation_version), 0)).where(
                    Report.tenant_id == tenant_id,
                    Report.dossier_id == dossier.id,
                    Report.template_key == CUSTOM_BRIEF_TEMPLATE_KEY,
                )
            )
            or 0
        )
        + 1
    )

    options = {
        "brief_request": brief,
        "plan_status": "draft",
        "lifecycle_state": "brief_draft",
        "classification": "internal",
        "confidentiality_label": "Uso interno",
        "assistant_kind": "custom_report_brief",
        "mutates_intent": False,
        "mutates_memory_facts": False,
    }
    source_snapshot = {
        "kind": "custom_assistant_brief",
        "dossier_id": str(dossier.id),
        "intent_revision_id": (
            str(dossier.current_intent_revision_id)
            if dossier.current_intent_revision_id is not None
            else None
        ),
        "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest(),
    }
    request_payload = {
        "dossier_id": str(dossier.id),
        "template_key": CUSTOM_BRIEF_TEMPLATE_KEY,
        "template_version": CUSTOM_BRIEF_TEMPLATE_VERSION,
        "options": options,
        "job_type": CUSTOM_BRIEF_JOB,
    }
    report = Report(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        title=f"Informe personalizado · {dossier.title}"[:300],
        status="draft",
        content={},
        report_type=CUSTOM_BRIEF_REPORT_TYPE,
        template_key=CUSTOM_BRIEF_TEMPLATE_KEY,
        template_version=CUSTOM_BRIEF_TEMPLATE_VERSION,
        generation_version=generation_version,
        idempotency_key=idempotency_key,
        request_hash=_sha256(request_payload),
        version=1,
        options=options,
        source_snapshot=source_snapshot,
        source_snapshot_hash=_sha256(source_snapshot),
        snapshot_hash_algorithm=SNAPSHOT_HASH_ALG,
        classification="internal",
        confidentiality_label="Uso interno",
        requested_by_user_id=actor_id,
        generated_by_user_id=actor_id,
    )
    session.add(report)
    session.flush()

    job = stage_job(
        CUSTOM_BRIEF_JOB,
        payload={
            "report_id": str(report.id),
            "dossier_id": str(dossier.id),
            "purpose": "report",
        },
        idempotency_key=f"custom-brief-plan:{report.id}",
        requested_by_user_id=actor_id,
        dossier_id=dossier.id,
        resource_type="report",
        resource_id=report.id,
        request_id=request_id,
        max_attempts=3,
    )
    report.background_job_id = job.id
    append_audit_event(
        session,
        action="report.custom_brief.requested",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={
            "template_key": CUSTOM_BRIEF_TEMPLATE_KEY,
            "plan_status": "draft",
            "job_id": str(job.id),
            "generation_version": generation_version,
        },
    )
    session.flush()
    if publish:
        from opn_oracle.jobs.service import publish_job

        session.commit()
        publish_job(job)
    return report, job


def process_custom_brief_plan(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
) -> dict[str, Any]:
    """Settle custom brief planning without Signal or report_writer.

    Produces a revisable plan (plan_status=proposed). Does not mark the report ready
    and does not generate full report sections.
    """

    tenant_id = require_tenant_id()
    try:
        report_id = uuid.UUID(str(payload["report_id"]))
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise CustomReportError("Payload de brief incompleto o inválido.") from error

    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe de brief no encontrado.")
    if report.template_key != CUSTOM_BRIEF_TEMPLATE_KEY:
        raise CustomReportError("El informe no es un brief de asistente personalizado.")

    options = dict(report.options or {})
    plan_status = str(options.get("plan_status") or "draft")
    if plan_status == "proposed" and options.get("proposed_plan"):
        return {
            "report_id": str(report.id),
            "plan_status": "proposed",
            "idempotent": True,
        }

    if job.cancel_requested:
        options["plan_status"] = "draft"
        options["last_error"] = "cancelled"
        report.options = options
        report.error_code = "cancelled"
        report.error_message = "Planificación cancelada."
        session.flush()
        return {"report_id": str(report.id), "plan_status": "draft", "cancelled": True}

    brief = str(options.get("brief_request") or "").strip()
    signal_meta: dict[str, Any] = {}
    if _signal_ai_enabled():
        try:
            proposed_plan, signal_meta = _plan_via_signal(
                session,
                job=job,
                dossier_id=dossier_id,
                report=report,
                brief=brief,
            )
        except Exception as error:
            options["last_error"] = str(error)[:500]
            report.options = options
            report.error_code = "signal_ai_error"
            report.error_message = str(error)[:500]
            session.flush()
            raise CustomReportError(f"Fallo IA gobernada (Signal): {error}") from error
    else:
        # Deterministic plan proposal (no LLM) — tests / AI disabled.
        proposed_plan = {
            "version": "custom_brief_plan.v1",
            "audience": "equipo del expediente",
            "scope": "derivado del brief del usuario; sujeto a revisión humana",
            "period": "sin fijar — completar en aceptación",
            "sections": [
                {"id": "executive", "title": "Resumen ejecutivo", "required": True},
                {"id": "evidence", "title": "Evidencias y fuentes", "required": True},
                {"id": "risks", "title": "Riesgos e incertidumbres", "required": True},
                {"id": "next_actions", "title": "Siguientes acciones", "required": True},
            ],
            "formats": ["html", "json"],
            "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest() if brief else None,
            "notes": [
                "Plan propuesto automáticamente; requiere aceptación humana antes de redactar.",
                "No se ha invocado report_writer ni proveedores de pago.",
            ],
            "job_id": str(job.id),
            "provider_path": "deterministic",
        }
    options["plan_status"] = "proposed"
    options["lifecycle_state"] = "plan_proposed"
    options["proposed_plan"] = proposed_plan
    options["mutates_intent"] = False
    options["mutates_memory_facts"] = False
    report.options = options
    # Keep report.status=draft until a human accepts the plan (later phase).
    report.status = "draft"
    append_audit_event(
        session,
        action="report.custom_brief.plan_proposed",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "plan_status": "proposed",
            "job_id": str(job.id),
            "section_count": len(proposed_plan["sections"]),
            **signal_meta,
        },
    )
    session.flush()
    return {
        "report_id": str(report.id),
        "plan_status": "proposed",
        "section_count": len(proposed_plan["sections"]),
        "mutates_intent": False,
        "mutates_memory_facts": False,
        **signal_meta,
    }


def _signal_ai_enabled() -> bool:
    try:
        from flask import current_app

        return bool(
            current_app.config.get("AI_ENABLED")
            and str(current_app.config.get("AI_MODE") or "").lower() == "signal"
        )
    except Exception:
        return False


def _plan_via_signal(
    session: Session,
    *,
    job: BackgroundJob,
    dossier_id: uuid.UUID,
    report: Report,
    brief: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call Signal task_key report_custom_brief_plan via execute_agent (no model hardcode)."""

    from opn_oracle.ai.context import build_context
    from opn_oracle.ai.models import AIArtifact
    from opn_oracle.ai.service import execute_agent

    result = execute_agent(
        agent="report_custom_brief_plan",
        dossier_id=dossier_id,
        job=job,
        context_factory=lambda max_tokens: build_context(dossier_id, max_tokens=max_tokens),
        supplemental_context={"brief_request": brief, "report_id": str(report.id)},
        target_type="report",
        target_id=report.id,
    )
    artifact = session.get(AIArtifact, uuid.UUID(str(result["artifact_id"])))
    if artifact is None or not isinstance(artifact.output, dict):
        raise CustomReportError("Artefacto de plan IA no disponible.")
    output = dict(artifact.output)
    sections = output.get("sections") or []
    if not isinstance(sections, list) or not sections:
        raise CustomReportError("El plan IA no incluye sections.")
    proposed_plan = {
        "version": str(output.get("version") or "custom_brief_plan.v1"),
        "audience": str(output.get("audience") or "equipo del expediente"),
        "scope": str(output.get("scope") or ""),
        "period": str(output.get("period") or "sin fijar"),
        "sections": sections,
        "formats": list(output.get("formats") or ["html", "json"]),
        "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest() if brief else None,
        "notes": list(output.get("notes") or []),
        "open_questions": list(output.get("open_questions") or []),
        "warnings": list(output.get("warnings") or []),
        "confidence": output.get("confidence"),
        "job_id": str(job.id),
        "artifact_id": str(artifact.id),
        "audit_log_id": str(result.get("audit_log_id") or ""),
        "provider_path": "signal",
        "task_key": "report_custom_brief_plan",
    }
    meta = {
        "artifact_id": str(artifact.id),
        "task_key": "report_custom_brief_plan",
        "provider_path": "signal",
    }
    return proposed_plan, meta
