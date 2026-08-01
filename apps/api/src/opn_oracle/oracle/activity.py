"""Read model de Actividad del expediente (MEMSOL-04).

Agrega intención, watchlists, monitores Signal, vigilancias de licitación y
jobs recientes sin fan-out del navegador. No crea monitores ni llama a Signal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.ai.models import AIArtifact
from opn_oracle.oracle.intent import (
    get_current_intent,
    list_offerings,
    list_requirements,
    serialize_intent_revision,
    serialize_offering,
    serialize_requirement,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import SignalMonitor, StrategicDossier, Watchlist
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.procurement_search_profiles import ProcurementSearchProfile
from opn_oracle.oracle.procurement_search_watch import ProcurementSearchWatch
from opn_oracle.oracle.service import ResourceNotFound
from opn_oracle.tenants.context import require_tenant_id

PRODUCT_STATES = frozenset(
    {
        "prepared",
        "active",
        "paused",
        "pending",
        "running",
        "retrying",
        "needs_attention",
        "finished",
    }
)

CADENCES = frozenset({"manual", "hourly", "daily", "weekly"})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _product_state_from_monitor(monitor: SignalMonitor) -> str:
    if monitor.observed_status == "error" or monitor.status == "error" or monitor.last_error:
        return "needs_attention"
    if monitor.desired_status == "paused" or monitor.status == "paused":
        return "paused"
    if monitor.observed_status == "pending":
        return "pending"
    if monitor.desired_status == "disabled":
        return "finished"
    if monitor.desired_status == "active" and monitor.observed_status == "active":
        return "active"
    return "prepared"


def _product_state_from_watchlist(watchlist: Watchlist) -> str:
    if watchlist.status == "paused":
        return "paused"
    if watchlist.status == "archived":
        return "finished"
    cfg = watchlist.query_config or {}
    if cfg.get("requires_review"):
        return "prepared"
    return "active" if watchlist.status == "active" else "prepared"


def _product_state_from_procurement(watch: ProcurementSearchWatch) -> str:
    if watch.deleted_at is not None:
        return "finished"
    if watch.last_error_code:
        return "needs_attention"
    if not watch.enabled:
        return "paused"
    return "active"


def _product_state_from_job(job: BackgroundJob) -> str:
    mapping = {
        "queued": "pending",
        "running": "running",
        "retrying": "retrying",
        "succeeded": "finished",
        "failed": "needs_attention",
        "cancelled": "finished",
    }
    return mapping.get(job.status, "pending")


def _safe_error(message: str | None, *, limit: int = 240) -> str | None:
    if not message:
        return None
    text = " ".join(str(message).split())
    return text[:limit] if text else None


def build_dossier_activity(
    session: Session,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Construye el read model de actividad (tenant de sesión)."""
    tenant_id = require_tenant_id()
    if limit < 1 or limit > 200:
        raise ValueError("limit debe estar entre 1 y 200.")
    if offset < 0:
        raise ValueError("offset no puede ser negativo.")

    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, actor_id, write=False):
        raise ResourceNotFound("Expediente no encontrado.")

    intent = get_current_intent(session, dossier_id)
    requirements = [serialize_requirement(row) for row in list_requirements(session, dossier_id)]
    offerings = [serialize_offering(row) for row in list_offerings(session, dossier_id)]

    items: list[dict[str, Any]] = []

    watchlists = list(
        session.scalars(
            select(Watchlist)
            .where(Watchlist.tenant_id == tenant_id, Watchlist.dossier_id == dossier_id)
            .order_by(Watchlist.name.asc())
        ).all()
    )
    watchlist_ids = [row.id for row in watchlists]
    monitors_by_watchlist: dict[uuid.UUID, list[SignalMonitor]] = {wid: [] for wid in watchlist_ids}
    if watchlist_ids:
        for monitor in session.scalars(
            select(SignalMonitor).where(
                SignalMonitor.tenant_id == tenant_id,
                SignalMonitor.watchlist_id.in_(watchlist_ids),
            )
        ).all():
            monitors_by_watchlist.setdefault(monitor.watchlist_id, []).append(monitor)

    for watchlist in watchlists:
        cfg = dict(watchlist.query_config or {})
        monitors = monitors_by_watchlist.get(watchlist.id, [])
        if not monitors:
            items.append(
                {
                    "kind": "watchlist",
                    "id": str(watchlist.id),
                    "title": watchlist.name,
                    "product_state": _product_state_from_watchlist(watchlist),
                    "desired_status": watchlist.status,
                    "observed_status": watchlist.status,
                    "cadence": watchlist.cadence,
                    "next_run_at": None,
                    "last_success_at": None,
                    "last_attempt_at": None,
                    "last_error": None,
                    "intent_revision_id": cfg.get("intent_revision_id"),
                    "requirement_id": cfg.get("requirement_id"),
                    "alignment_state": cfg.get("alignment_state")
                    or (cfg.get("requires_review") and "needs_review")
                    or "aligned",
                    "provider_ref": None,
                    "target": {
                        "keywords": cfg.get("keywords") or [],
                        "source_types": cfg.get("source_types") or [],
                    },
                }
            )
        for monitor in monitors:
            items.append(
                {
                    "kind": "signal_monitor",
                    "id": str(monitor.id),
                    "title": watchlist.name,
                    "product_state": _product_state_from_monitor(monitor),
                    "desired_status": monitor.desired_status,
                    "observed_status": monitor.observed_status,
                    "cadence": watchlist.cadence,
                    "next_run_at": _iso(monitor.next_sync_at),
                    "last_success_at": _iso(monitor.last_synced_at),
                    "last_attempt_at": _iso(monitor.last_sync_attempt_at),
                    "last_error": _safe_error(monitor.last_error),
                    "intent_revision_id": cfg.get("intent_revision_id"),
                    "requirement_id": cfg.get("requirement_id"),
                    "alignment_state": cfg.get("alignment_state") or "aligned",
                    "provider_ref": monitor.external_id,
                    "target": {
                        "watchlist_id": str(watchlist.id),
                        "provider": monitor.provider,
                    },
                }
            )

    # Perfiles de licitación son dossierless en v1; se asocian vía AIArtifact.dossier_id.
    profile_rows = list(
        session.scalars(
            select(ProcurementSearchProfile)
            .join(
                AIArtifact,
                (AIArtifact.id == ProcurementSearchProfile.ai_artifact_id)
                & (AIArtifact.tenant_id == ProcurementSearchProfile.tenant_id),
            )
            .where(
                ProcurementSearchProfile.tenant_id == tenant_id,
                AIArtifact.dossier_id == dossier_id,
            )
        ).all()
    )
    profiles = {row.id: row for row in profile_rows}
    if profiles:
        for watch in session.scalars(
            select(ProcurementSearchWatch).where(
                ProcurementSearchWatch.tenant_id == tenant_id,
                ProcurementSearchWatch.profile_id.in_(list(profiles.keys())),
                ProcurementSearchWatch.deleted_at.is_(None),
            )
        ).all():
            items.append(
                {
                    "kind": "procurement_watch",
                    "id": str(watch.id),
                    "title": watch.name,
                    "product_state": _product_state_from_procurement(watch),
                    "desired_status": "active" if watch.enabled else "paused",
                    "observed_status": (
                        "error"
                        if watch.last_error_code
                        else ("active" if watch.enabled else "paused")
                    ),
                    "cadence": "daily" if watch.cadence_seconds < 86400 * 6 else "weekly",
                    "next_run_at": None,
                    "last_success_at": _iso(watch.last_success_at),
                    "last_attempt_at": _iso(watch.last_attempt_at),
                    "last_error": _safe_error(watch.last_error_message),
                    "intent_revision_id": None,
                    "requirement_id": None,
                    "alignment_state": "aligned",
                    "provider_ref": watch.tender_search_id,
                    "target": {"profile_id": str(watch.profile_id)},
                }
            )

    jobs = list(
        session.scalars(
            select(BackgroundJob)
            .where(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.dossier_id == dossier_id,
            )
            .order_by(BackgroundJob.created_at.desc())
            .limit(50)
        ).all()
    )
    for job in jobs:
        items.append(
            {
                "kind": "background_job",
                "id": str(job.id),
                "title": job.job_type,
                "product_state": _product_state_from_job(job),
                "desired_status": job.status,
                "observed_status": job.status,
                "cadence": "manual",
                "next_run_at": _iso(job.not_before),
                "last_success_at": _iso(job.finished_at) if job.status == "succeeded" else None,
                "last_attempt_at": _iso(job.heartbeat_at or job.started_at),
                "last_error": _safe_error(job.error_message),
                "intent_revision_id": None,
                "requirement_id": None,
                "alignment_state": "aligned",
                "provider_ref": job.celery_task_id,
                "target": {
                    "stage": job.stage,
                    "resource_type": job.resource_type,
                    "resource_id": str(job.resource_id) if job.resource_id else None,
                },
            }
        )

    if kind:
        items = [item for item in items if item["kind"] == kind]

    # Orden estable: needs_attention primero, luego running/pending, resto por título
    priority = {
        "needs_attention": 0,
        "running": 1,
        "retrying": 1,
        "pending": 2,
        "active": 3,
        "prepared": 4,
        "paused": 5,
        "finished": 6,
    }
    items.sort(key=lambda item: (priority.get(item["product_state"], 9), item["title"] or ""))
    total = len(items)
    page = items[offset : offset + limit]

    return {
        "dossier_id": str(dossier_id),
        "intent": serialize_intent_revision(intent) if intent is not None else None,
        "requirements": requirements,
        "offerings": offerings,
        "summary": {
            "total": total,
            "by_state": {
                state: sum(1 for item in items if item["product_state"] == state)
                for state in sorted(PRODUCT_STATES)
            },
            "by_kind": {
                k: sum(1 for item in items if item["kind"] == k)
                for k in sorted({item["kind"] for item in items})
            },
        },
        "items": page,
        "pagination": {"limit": limit, "offset": offset, "total": total},
    }
