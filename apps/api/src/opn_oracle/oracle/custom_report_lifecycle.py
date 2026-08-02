"""MDEV-08 provisional · lifecycle durable de informe libre con snapshot congelado.

Estados product:
  brief_draft → plan_proposed → plan_accepted → generating → reviewing → ready
                                                             ↘ failed | cancelled

CAS vía Report.version + If-Match (428 sin header, 409 conflicto).
Una versión ready nunca se sobrescribe: nueva generación crea generation_version+1.
Memoria durable MDEV-05 ausente → degraded/disabled explícito; no store in-process.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.custom_reports import (
    CustomReportConflict,
    CustomReportError,
    CustomReportNotFound,
    _sha256,
    get_custom_brief,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import Report, StrategicDossier
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

LIFECYCLE_STATES = frozenset(
    {
        "brief_draft",
        "plan_proposed",
        "plan_accepted",
        "generating",
        "reviewing",
        "ready",
        "failed",
        "cancelled",
    }
)

# Legal transitions (from → allowed tos)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "brief_draft": frozenset({"plan_proposed", "cancelled", "failed"}),
    "plan_proposed": frozenset(
        {"plan_accepted", "plan_proposed", "brief_draft", "cancelled", "failed"}
    ),
    "plan_accepted": frozenset({"generating", "cancelled", "failed"}),
    "generating": frozenset({"reviewing", "failed", "cancelled"}),
    "reviewing": frozenset({"ready", "failed", "cancelled"}),
    "ready": frozenset(),  # immutable; new version = new report generation
    "failed": frozenset({"plan_proposed", "generating", "cancelled"}),  # retry paths
    "cancelled": frozenset(),
}

CUSTOM_WRITE_JOB = "oracle.report.custom_brief.write"
CUSTOM_REVIEW_JOB = "oracle.report.custom_brief.review"
SNAPSHOT_HASH_ALG = "canonical-json-sha256-v1"


class PreconditionRequired(RuntimeError):
    """If-Match ausente → HTTP 428."""


class IllegalTransition(CustomReportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, errors={"lifecycle": [message]})


def _memory_durable_ready() -> bool:
    return os.getenv("MEMORY_DURABLE_STORE_READY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _lifecycle_of(report: Report) -> str:
    options = dict(report.options or {})
    raw = str(options.get("lifecycle_state") or "").strip()
    if raw in LIFECYCLE_STATES:
        return raw
    # Back-compat from plan_status
    plan = str(options.get("plan_status") or "draft")
    if report.status == "ready":
        return "ready"
    if report.status == "failed":
        return "failed"
    if report.status == "generating":
        return "generating"
    if plan == "accepted":
        return "plan_accepted"
    if plan == "proposed":
        return "plan_proposed"
    return "brief_draft"


def _require_if_match(report: Report, expected_version: int | None) -> None:
    if expected_version is None:
        raise PreconditionRequired("If-Match es obligatorio.")
    if int(report.version) != int(expected_version):
        raise CustomReportConflict(
            f"Conflicto de versión: esperada {expected_version}, actual {report.version}."
        )


def _assert_transition(current: str, target: str) -> None:
    allowed = _TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransition(
            f"Transición ilegal: {current} → {target}."
        )


def serialize_lifecycle(report: Report) -> dict[str, Any]:
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)
    accepted = options.get("accepted_snapshot")
    artifact = options.get("ready_artifact")
    return {
        "id": str(report.id),
        "tenant_id": str(report.tenant_id),
        "dossier_id": str(report.dossier_id),
        "title": report.title,
        "status": report.status,
        "lifecycle_state": lifecycle,
        "plan_status": str(options.get("plan_status") or "draft"),
        "version": report.version,
        "generation_version": report.generation_version,
        "brief_request": str(options.get("brief_request") or ""),
        "proposed_plan": options.get("proposed_plan"),
        "accepted_plan": options.get("accepted_plan"),
        "accepted_snapshot": accepted,
        "accepted_snapshot_hash": (
            options.get("accepted_snapshot_hash")
            if isinstance(options.get("accepted_snapshot_hash"), str)
            else (
                report.source_snapshot_hash.hex()
                if report.source_snapshot_hash is not None
                and options.get("accepted_snapshot")
                else None
            )
        ),
        "memory_mode": (accepted or {}).get("memory_mode") if isinstance(accepted, dict) else None,
        "memory_degraded": bool(options.get("memory_degraded", False)),
        "memory_degraded_reason": options.get("memory_degraded_reason"),
        "coverage": options.get("coverage"),
        "ready_artifact": artifact,
        "downloadable": bool(
            lifecycle == "ready"
            and isinstance(artifact, dict)
            and artifact.get("status") == "available"
            and artifact.get("sha256")
            and int(artifact.get("byte_size") or 0) > 0
        ),
        "background_job_id": (
            str(report.background_job_id) if report.background_job_id is not None else None
        ),
        "error_code": getattr(report, "error_code", None),
        "error_message": getattr(report, "error_message", None),
        "etag": f'W/"{report.version}"',
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
        "ready_at": report.ready_at.isoformat() if report.ready_at else None,
    }


def _build_accepted_snapshot(
    session: Session,
    *,
    report: Report,
    dossier: StrategicDossier,
    accepted_plan: dict[str, Any],
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    """Freeze immutable snapshot at plan acceptance.

    Never uses in-process memory as authoritative store (MDEV-05 debt).
    """
    durable = _memory_durable_ready()
    memory_mode = "durable" if durable else "disabled"
    memory_policy = {
        "mode": memory_mode,
        "authoritative_store": "signal_durable" if durable else None,
        "in_process_forbidden": True,
    }
    # Materialized evidence allowlist — only from durable path when ready.
    evidence_items: list[dict[str, Any]] = []
    allowlist: list[str] = []
    watermark: str | None = None
    coverage: dict[str, Any] = {
        "evidence_count": 0,
        "durable": durable,
        "gaps": [] if durable else ["DUR-MDEV05-001: store durable no disponible"],
    }
    if not durable:
        # Explicit degraded — flow may continue with empty allowlist (citations must be empty).
        pass
    else:
        # Placeholder structure for when MDEV-05 is PASS; still no in-process fallback.
        coverage["note"] = "durable path reserved; retrieval materialization pending MDEV-05 PASS"

    options = dict(report.options or {})
    brief = str(options.get("brief_request") or "")
    prompt_versions = {
        "plan_task_key": "report_custom_brief_plan",
        "writer_task_key": "report_custom_writer",
        "review_task_key": "report_custom_review",
        "runtime_plan": "RT-08",
        "runtime_writer": "RT-09",
        "runtime_review": "RT-10",
        "prompt_version": "1.0.0",
        "schema_version": "custom_report.v1",
    }
    # SHA of frozen plan text for integrity
    plan_canonical = json.dumps(accepted_plan, sort_keys=True, separators=(",", ":"))
    plan_sha = hashlib.sha256(plan_canonical.encode("utf-8")).hexdigest()
    snapshot = {
        "kind": "custom_assistant_accepted_v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "frozen_by_user_id": str(actor_id),
        "report_id": str(report.id),
        "generation_version": report.generation_version,
        "dossier_id": str(dossier.id),
        "intent_revision_id": (
            str(dossier.current_intent_revision_id)
            if getattr(dossier, "current_intent_revision_id", None) is not None
            else None
        ),
        "requirements": options.get("requirements") or [],
        "offering": options.get("offering"),
        "brief_request": brief,
        "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest() if brief else None,
        "accepted_plan": accepted_plan,
        "accepted_plan_sha256": plan_sha,
        "memory_mode": memory_mode,
        "memory_policy": memory_policy,
        "watermark": watermark,
        "evidence_items": evidence_items,
        "allowlist": allowlist,
        "coverage": coverage,
        "prompt_schema_runtime": prompt_versions,
        "runtime_sha256": {
            "plan": options.get("plan_runtime_sha256"),
            "writer": None,
            "review": None,
        },
    }
    return snapshot


def accept_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    plan_override: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    auto_start_generation: bool = True,
) -> Report:
    """Human accepts plan → freeze snapshot. Never auto-accept without call."""

    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    _assert_transition(current, "plan_accepted")

    options = dict(report.options or {})
    proposed = plan_override or options.get("proposed_plan")
    if not isinstance(proposed, dict) or not proposed.get("sections"):
        raise CustomReportError(
            "No hay plan propuesto válido para aceptar.",
            errors={"plan": ["proposed_plan.sections requerido"]},
        )

    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == require_tenant_id(),
        )
    )
    if dossier is None:
        raise CustomReportNotFound("Expediente no encontrado.")

    accepted_plan = dict(proposed)
    accepted_plan["accepted_at"] = datetime.now(UTC).isoformat()
    accepted_plan["accepted_by_user_id"] = str(actor_id)
    snapshot = _build_accepted_snapshot(
        session,
        report=report,
        dossier=dossier,
        accepted_plan=accepted_plan,
        actor_id=actor_id,
    )
    snap_hash = _sha256(snapshot)
    snap_hash_hex = snap_hash.hex()

    options["plan_status"] = "accepted"
    options["lifecycle_state"] = "plan_accepted"
    options["accepted_plan"] = accepted_plan
    options["accepted_snapshot"] = snapshot
    options["accepted_snapshot_hash"] = snap_hash_hex
    options["coverage"] = snapshot.get("coverage")
    durable = _memory_durable_ready()
    options["memory_degraded"] = not durable
    if not durable:
        options["memory_degraded_reason"] = (
            "DUR-MDEV05-001: memoria durable no disponible; flujo degraded, "
            "allowlist vacía, sin store in-process"
        )
    report.options = options
    report.source_snapshot = snapshot
    report.source_snapshot_hash = snap_hash
    report.snapshot_hash_algorithm = SNAPSHOT_HASH_ALG
    report.version = int(report.version) + 1
    report.status = "draft"
    report.error_code = None
    report.error_message = None

    append_audit_event(
        session,
        action="report.custom_brief.plan_accepted",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={
            "version": report.version,
            "snapshot_hash": snap_hash_hex,
            "memory_degraded": not durable,
            "generation_version": report.generation_version,
        },
    )
    session.flush()

    if auto_start_generation:
        return start_generation(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=report.version,
            request_id=request_id,
            publish=False,
        )
    return report


def edit_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    proposed_plan: Mapping[str, Any],
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current not in {"plan_proposed", "brief_draft"}:
        raise IllegalTransition(f"No se puede editar el plan en estado {current}.")
    if not isinstance(proposed_plan, dict) or not proposed_plan.get("sections"):
        raise CustomReportError(
            "proposed_plan.sections es obligatorio.",
            errors={"plan": ["sections requerido"]},
        )
    options = dict(report.options or {})
    options["proposed_plan"] = dict(proposed_plan)
    options["plan_status"] = "proposed"
    options["lifecycle_state"] = "plan_proposed"
    options["plan_edited_by"] = str(actor_id)
    options["plan_edited_at"] = datetime.now(UTC).isoformat()
    report.options = options
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.plan_edited",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version},
    )
    session.flush()
    return report


def reject_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    reason: str | None = None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    _assert_transition(current, "brief_draft")
    options = dict(report.options or {})
    options["plan_status"] = "draft"
    options["lifecycle_state"] = "brief_draft"
    options["rejected_plan"] = options.get("proposed_plan")
    options["proposed_plan"] = None
    options["reject_reason"] = (reason or "")[:500]
    options["rejected_by"] = str(actor_id)
    report.options = options
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.plan_rejected",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version, "reason": (reason or "")[:200]},
    )
    session.flush()
    return report


def start_generation(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
    publish: bool = False,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current == "generating":
        # idempotent
        return report
    _assert_transition(current, "generating")
    options = dict(report.options or {})
    if not options.get("accepted_snapshot"):
        raise CustomReportError(
            "Snapshot no congelado: acepte el plan antes de generar.",
            errors={"snapshot": ["accepted_snapshot required"]},
        )
    # Fence: bind job to snapshot hash
    snap_hash = str(options.get("accepted_snapshot_hash") or "")
    job = stage_job(
        CUSTOM_WRITE_JOB,
        payload={
            "report_id": str(report.id),
            "dossier_id": str(dossier_id),
            "purpose": "report",
            "snapshot_hash": snap_hash,
            "generation_version": report.generation_version,
            "fence_token": str(uuid.uuid4()),
        },
        idempotency_key=f"custom-brief-write:{report.id}:{report.generation_version}:{snap_hash[:16]}",
        requested_by_user_id=actor_id,
        dossier_id=dossier_id,
        resource_type="report",
        resource_id=report.id,
        request_id=request_id,
        max_attempts=3,
    )
    options["lifecycle_state"] = "generating"
    options["write_job_id"] = str(job.id)
    fence = job.payload.get("fence_token") if isinstance(job.payload, dict) else None
    options["fence_token"] = fence
    report.options = options
    report.background_job_id = job.id
    report.status = "generating"
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.generating",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"job_id": str(job.id), "snapshot_hash": snap_hash, "version": report.version},
    )
    session.flush()
    if publish:
        from opn_oracle.jobs.service import publish_job

        session.commit()
        publish_job(job)
        # re-attach
        session.refresh(report)
    return report


def cancel_report(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current in {"ready", "cancelled"}:
        raise IllegalTransition(f"No se puede cancelar en estado {current}.")
    _assert_transition(current, "cancelled")
    options = dict(report.options or {})
    options["lifecycle_state"] = "cancelled"
    options["cancelled_by"] = str(actor_id)
    options["cancelled_at"] = datetime.now(UTC).isoformat()
    report.options = options
    report.status = "failed"
    report.error_code = "cancelled"
    report.error_message = "Informe cancelado por el usuario."
    report.version = int(report.version) + 1
    # Best-effort cancel of background job
    if report.background_job_id is not None:
        job = session.get(BackgroundJob, report.background_job_id)
        if job is not None and hasattr(job, "cancel_requested"):
            job.cancel_requested = True
    append_audit_event(
        session,
        action="report.custom_brief.cancelled",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version},
    )
    session.flush()
    return report


def retry_report(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current != "failed":
        raise IllegalTransition(f"Retry solo desde failed; actual={current}.")
    options = dict(report.options or {})
    if options.get("accepted_snapshot"):
        # Resume generation with same frozen snapshot
        options["lifecycle_state"] = "plan_accepted"
        options["plan_status"] = "accepted"
        report.options = options
        report.status = "draft"
        report.error_code = None
        report.error_message = None
        report.version = int(report.version) + 1
        session.flush()
        return start_generation(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=report.version,
            request_id=request_id,
        )
    # Re-propose plan path
    options["lifecycle_state"] = "brief_draft"
    options["plan_status"] = "draft"
    report.options = options
    report.status = "draft"
    report.error_code = None
    report.error_message = None
    report.version = int(report.version) + 1
    session.flush()
    return report


def validate_citations_against_snapshot(
    snapshot: Mapping[str, Any],
    citations: list[Any],
) -> list[str]:
    """Return foreign evidence ids (empty list = ok). Empty allowlist rejects all citations."""
    allow = {str(x) for x in (snapshot.get("allowlist") or []) if str(x).strip()}
    foreign: list[str] = []
    for raw in citations or []:
        if not isinstance(raw, dict):
            foreign.append("<non-object>")
            continue
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid or eid not in allow:
            foreign.append(eid or "<missing>")
    return foreign


def process_custom_brief_write(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
) -> dict[str, Any]:
    """Writer uses EXACTLY accepted_snapshot. Late results after cancel/fence drop."""

    tenant_id = require_tenant_id()
    try:
        report_id = uuid.UUID(str(payload["report_id"]))
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
        expected_snap = str(payload.get("snapshot_hash") or "")
        fence = str(payload.get("fence_token") or "")
    except (KeyError, TypeError, ValueError) as error:
        raise CustomReportError("Payload de write incompleto.") from error

    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe no encontrado.")
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)

    if job.cancel_requested or lifecycle == "cancelled":
        return {"report_id": str(report.id), "dropped": True, "reason": "cancelled"}

    snap = options.get("accepted_snapshot")
    if not isinstance(snap, dict):
        raise CustomReportError("Snapshot no congelado.")
    current_hash = str(options.get("accepted_snapshot_hash") or "")
    if expected_snap and current_hash and expected_snap != current_hash:
        # Late / fenced out — do not publish
        return {
            "report_id": str(report.id),
            "dropped": True,
            "reason": "snapshot_fence_mismatch",
        }
    if fence and options.get("fence_token") and str(options.get("fence_token")) != fence:
        return {"report_id": str(report.id), "dropped": True, "reason": "fence_token_mismatch"}

    if lifecycle == "ready":
        # Never overwrite ready
        return {"report_id": str(report.id), "dropped": True, "reason": "already_ready"}

    # Deterministic structured writer output (no paid LLM in tests/dev without Signal)
    sections_out: list[dict[str, Any]] = []
    plan = options.get("accepted_plan") or snap.get("accepted_plan") or {}
    for sec in plan.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        sections_out.append(
            {
                "id": sec.get("id") or sec.get("title") or "section",
                "title": sec.get("title") or "Sección",
                "facts": [],
                "claims": [],
                "conflicts": [],
                "inferences": [],
                "recommendations": [],
                "body": f"[borrador a partir del plan] {sec.get('title') or ''}",
                "citations": [],
            }
        )
    writer_output = {
        "version": "custom_report_writer.v1",
        "task_key": "report_custom_writer",
        "runtime_id": "RT-09",
        "sections": sections_out,
        "citations": [],
        "snapshot_hash": current_hash,
        "facts": [],
        "claims": [],
        "conflicts": [],
        "inferences": [],
        "recommendations": [],
    }
    # Citation allowlist enforcement
    foreign = validate_citations_against_snapshot(snap, writer_output["citations"])
    if foreign:
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "citation_foreign"
        report.error_message = f"Citas fuera de allowlist: {foreign[:5]}"
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "foreign": foreign}

    options["writer_output"] = writer_output
    options["lifecycle_state"] = "reviewing"
    report.options = options
    report.status = "generating"
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.reviewing",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={"snapshot_hash": current_hash, "section_count": len(sections_out)},
    )
    session.flush()

    # Inline review+assemble for deterministic path (Signal RT-10 optional)
    return process_custom_brief_review(
        session,
        {
            "report_id": str(report.id),
            "dossier_id": str(dossier_id),
            "snapshot_hash": current_hash,
            "fence_token": fence,
        },
        job,
    )


def process_custom_brief_review(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
) -> dict[str, Any]:
    """Review + atomic ready artifact. Partial never becomes ready."""

    tenant_id = require_tenant_id()
    report_id = uuid.UUID(str(payload["report_id"]))
    dossier_id = uuid.UUID(str(payload["dossier_id"]))
    expected_snap = str(payload.get("snapshot_hash") or "")

    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe no encontrado.")
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)
    if job.cancel_requested or lifecycle == "cancelled":
        return {"report_id": str(report.id), "dropped": True, "reason": "cancelled"}
    if lifecycle == "ready":
        return {"report_id": str(report.id), "idempotent": True, "lifecycle_state": "ready"}

    snap = options.get("accepted_snapshot")
    if not isinstance(snap, dict):
        raise CustomReportError("Snapshot no congelado en review.")
    current_hash = str(options.get("accepted_snapshot_hash") or "")
    if expected_snap and current_hash and expected_snap != current_hash:
        return {"report_id": str(report.id), "dropped": True, "reason": "snapshot_fence_mismatch"}

    writer_output = options.get("writer_output")
    if not isinstance(writer_output, dict) or not writer_output.get("sections"):
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "writer_output_missing"
        report.error_message = "Salida del writer ausente o incompleta."
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "reason": "writer_output_missing"}

    # Assemble artifact body (Oracle owns render)
    content = {
        "kind": "custom_assistant_report",
        "title": report.title,
        "snapshot_hash": current_hash,
        "accepted_plan": options.get("accepted_plan"),
        "sections": writer_output.get("sections"),
        "facts": writer_output.get("facts") or [],
        "claims": writer_output.get("claims") or [],
        "conflicts": writer_output.get("conflicts") or [],
        "inferences": writer_output.get("inferences") or [],
        "recommendations": writer_output.get("recommendations") or [],
        "citations": writer_output.get("citations") or [],
        "coverage": snap.get("coverage"),
        "memory_mode": snap.get("memory_mode"),
        "runtime": {
            "writer": "RT-09",
            "review": "RT-10",
            "plan": "RT-08",
        },
        "assembled_at": datetime.now(UTC).isoformat(),
    }
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    sha = hashlib.sha256(raw).hexdigest()
    byte_size = len(raw)
    if byte_size <= 0:
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "artifact_empty"
        report.error_message = "Artefacto vacío; no se publica ready."
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "reason": "artifact_empty"}

    # Atomic publish: only set ready after hash/size validation
    artifact = {
        "status": "available",
        "format": "json",
        "sha256": sha,
        "byte_size": byte_size,
        "content": content,
        "generation_version": report.generation_version,
        "snapshot_hash": current_hash,
        "published_at": datetime.now(UTC).isoformat(),
    }
    # Preserve previous ready artifact if any under versions[]
    versions = list(options.get("artifact_versions") or [])
    prev = options.get("ready_artifact")
    if isinstance(prev, dict) and prev.get("status") == "available":
        versions.append(prev)
    options["artifact_versions"] = versions
    options["ready_artifact"] = artifact
    options["lifecycle_state"] = "ready"
    report.options = options
    report.content = content
    report.status = "ready"
    report.ready_at = datetime.now(UTC)
    report.version = int(report.version) + 1
    report.error_code = None
    report.error_message = None
    append_audit_event(
        session,
        action="report.custom_brief.ready",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=getattr(job, "correlation_id", None),
        metadata={
            "sha256": sha,
            "byte_size": byte_size,
            "snapshot_hash": current_hash,
            "version": report.version,
        },
    )
    session.flush()
    return {
        "report_id": str(report.id),
        "lifecycle_state": "ready",
        "sha256": sha,
        "byte_size": byte_size,
        "snapshot_hash": current_hash,
    }


def get_downloadable_artifact(report: Report) -> dict[str, Any] | None:
    """Only ready+validated artifacts are downloadable."""
    if _lifecycle_of(report) != "ready":
        return None
    options = dict(report.options or {})
    art = options.get("ready_artifact")
    if not isinstance(art, dict):
        return None
    if art.get("status") != "available":
        return None
    if not art.get("sha256") or int(art.get("byte_size") or 0) <= 0:
        return None
    return art
