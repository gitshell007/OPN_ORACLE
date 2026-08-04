"""Read model de Actividad del expediente (MEMSOL-04).

Agrega intención, watchlists, monitores Signal, vigilancias de licitación y
jobs recientes sin fan-out del navegador. No crea monitores.

Para honestidad de vigilancia (SV2-VIGILANCIA-VERDAD) consulta a Signal los
campos expuestos en GET /monitors/{id}: health.state y last_run_at. run_state
existe en oracle_monitors de Signal pero no se expone por API.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

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
from opn_oracle.oracle.surveillance import DossierSurveillanceAction
from opn_oracle.platform.models import IntegrationConnection
from opn_oracle.tenants.context import require_tenant_id

logger = logging.getLogger(__name__)

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

# Three honest collection states for surveillance (plus unknown when Signal is mute).
CollectionState = Literal["absent", "not_collecting", "collecting", "unknown"]

ABSENT_REASON = (
    "SIGNAL-MONITOR-ABSENT: confirmación local sin monitor en Signal; no vigila de verdad"
)
NEVER_RUN_REASON = (
    "SIGNAL-COLLECTION-NEVER: el monitor existe en Signal pero last_run_at es nulo; "
    "no ha recolectado nunca (recolección apagada o aún sin corrida)"
)
HEALTH_BAD_REASON = (
    "SIGNAL-COLLECTION-UNHEALTHY: health.state de Signal indica que no recolecta bien"
)
UNKNOWN_REASON = (
    "SIGNAL-COLLECTION-UNKNOWN: no se pudo leer health/last_run_at del monitor en Signal; "
    "no se afirma activo"
)


@dataclass(frozen=True, slots=True)
class CollectionHonesty:
    """Honestidad de recolección basada solo en datos que Signal expone (o su ausencia)."""

    collection_state: CollectionState
    degraded: bool
    degraded_reason: str | None
    provider_health_state: str | None = None
    provider_last_run_at: str | None = None
    provider_health_error_code: str | None = None
    provider_status: str | None = None


def assess_collection_honesty(
    *,
    has_monitor: bool,
    snapshot: dict[str, Any] | None,
    snapshot_available: bool,
) -> CollectionHonesty:
    """Deriva el estado de recolección a partir de lo que Signal expone.

    - absent: sin monitor local/Signal
    - not_collecting: monitor presente pero last_run_at nulo o health no ok
    - collecting: last_run_at presente y health.state == ok
    - unknown: monitor presente pero no hay snapshot fiable de Signal
    """
    if not has_monitor:
        return CollectionHonesty(
            collection_state="absent",
            degraded=True,
            degraded_reason=ABSENT_REASON,
        )
    if not snapshot_available:
        return CollectionHonesty(
            collection_state="unknown",
            degraded=True,
            degraded_reason=UNKNOWN_REASON,
        )
    if snapshot is None:
        return CollectionHonesty(
            collection_state="unknown",
            degraded=True,
            degraded_reason=UNKNOWN_REASON,
        )

    raw_health = snapshot.get("health")
    health = raw_health if isinstance(raw_health, dict) else {}
    health_state = health.get("state")
    if health_state is not None:
        health_state = str(health_state).strip().lower() or None
    error_code = health.get("last_error_code")
    if error_code is not None:
        error_code = str(error_code) or None
    last_run_raw = snapshot.get("last_run_at")
    last_run_at: str | None
    if last_run_raw is None or last_run_raw == "":
        last_run_at = None
    elif isinstance(last_run_raw, datetime):
        last_run_at = last_run_raw.isoformat()
    else:
        last_run_at = str(last_run_raw)
    status = snapshot.get("status")
    status_s = str(status) if status is not None else None

    base = {
        "provider_health_state": health_state,
        "provider_last_run_at": last_run_at,
        "provider_health_error_code": error_code,
        "provider_status": status_s,
    }

    # No inventar: si Signal no manda health.state, no se puede afirmar recolección.
    if health_state is None:
        return CollectionHonesty(
            collection_state="unknown",
            degraded=True,
            degraded_reason=UNKNOWN_REASON,
            **base,
        )

    if health_state in {"degraded", "error"}:
        reason = HEALTH_BAD_REASON
        if error_code:
            reason = f"{HEALTH_BAD_REASON} ({error_code})"
        return CollectionHonesty(
            collection_state="not_collecting",
            degraded=True,
            degraded_reason=reason,
            **base,
        )

    if last_run_at is None:
        return CollectionHonesty(
            collection_state="not_collecting",
            degraded=True,
            degraded_reason=NEVER_RUN_REASON,
            **base,
        )

    if health_state == "ok":
        return CollectionHonesty(
            collection_state="collecting",
            degraded=False,
            degraded_reason=None,
            **base,
        )

    # Estado de health no reconocido → desconocido (no «activo»).
    return CollectionHonesty(
        collection_state="unknown",
        degraded=True,
        degraded_reason=UNKNOWN_REASON,
        **base,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _provider_snapshot_for_monitor(
    session: Session, monitor: SignalMonitor | None
) -> tuple[dict[str, Any] | None, bool]:
    """GET Signal monitor health fields. Returns (snapshot, available).

    available=False means we could not obtain Signal data (fail closed → unknown).
    """
    if monitor is None or not monitor.external_id:
        return None, False
    if monitor.connection_id is None:
        return None, False
    connection = session.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == monitor.connection_id,
            IntegrationConnection.tenant_id == monitor.tenant_id,
            IntegrationConnection.status.in_(("active", "pending")),
        )
    )
    if connection is None:
        return None, False
    try:
        from opn_oracle.integrations.service import adapter_for_connection

        adapter = adapter_for_connection(connection)
        provider = adapter.get_monitor(monitor.external_id)
    except Exception:
        logger.info(
            "activity: no se pudo leer salud del monitor Signal %s",
            monitor.external_id,
            exc_info=True,
        )
        return None, False

    health = provider.health if isinstance(provider.health, dict) else {"state": provider.health}
    return (
        {
            "status": provider.status,
            "last_run_at": provider.last_run_at,
            "health": health,
        },
        True,
    )


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

    # Prefetch local SignalMonitor rows referenced by surveillance actions.
    surveillance_actions = list(
        session.scalars(
            select(DossierSurveillanceAction)
            .where(
                DossierSurveillanceAction.tenant_id == tenant_id,
                DossierSurveillanceAction.dossier_id == dossier_id,
            )
            .order_by(DossierSurveillanceAction.updated_at.desc())
        ).all()
    )
    monitor_ids = [
        action.signal_monitor_id
        for action in surveillance_actions
        if action.signal_monitor_id is not None
    ]
    monitors_by_id: dict[uuid.UUID, SignalMonitor] = {}
    if monitor_ids:
        for row in session.scalars(
            select(SignalMonitor).where(
                SignalMonitor.tenant_id == tenant_id,
                SignalMonitor.id.in_(monitor_ids),
            )
        ).all():
            monitors_by_id[row.id] = row
    # Cache provider snapshots per external_id (one GET per distinct Signal monitor).
    provider_cache: dict[str, tuple[dict[str, Any] | None, bool]] = {}

    def _snapshot_for(local: SignalMonitor | None) -> tuple[dict[str, Any] | None, bool]:
        if local is None or not local.external_id:
            return None, False
        key = local.external_id
        if key not in provider_cache:
            provider_cache[key] = _provider_snapshot_for_monitor(session, local)
        return provider_cache[key]

    # MDEV-07 confirmed surveillance actions (human opt-in).
    for action in surveillance_actions:
        product_state = action.status
        if product_state == "retired":
            product_state = "finished"
        watching_statuses = {"active", "pending", "running", "retrying"}
        is_watching = action.status in watching_statuses and action.action_type != "no_follow"
        has_monitor = action.signal_monitor_id is not None
        local_monitor = (
            monitors_by_id.get(action.signal_monitor_id) if action.signal_monitor_id else None
        )

        if not is_watching:
            honesty = CollectionHonesty(
                collection_state="collecting" if has_monitor else "absent",
                degraded=bool(action.degraded),
                degraded_reason=action.degraded_reason,
            )
        elif not has_monitor:
            honesty = assess_collection_honesty(
                has_monitor=False, snapshot=None, snapshot_available=False
            )
        else:
            snapshot, available = _snapshot_for(local_monitor)
            honesty = assess_collection_honesty(
                has_monitor=True, snapshot=snapshot, snapshot_available=available
            )

        # Persist-on-read honesty: never emit clean «active» without collection proof.
        degraded = bool(action.degraded) or honesty.degraded
        degraded_reason = honesty.degraded_reason or action.degraded_reason
        if is_watching and product_state == "active" and honesty.collection_state != "collecting":
            product_state = "needs_attention"
            degraded = True
            if not degraded_reason:
                degraded_reason = honesty.degraded_reason

        items.append(
            {
                "kind": "surveillance_action",
                "id": str(action.id),
                "title": action.title or action.action_type,
                "product_state": product_state if product_state in PRODUCT_STATES else "prepared",
                "desired_status": action.status,
                "observed_status": action.status,
                "cadence": action.cadence,
                "next_run_at": _iso(action.next_run_at),
                "last_success_at": honesty.provider_last_run_at or _iso(action.last_run_at),
                "last_attempt_at": _iso(action.last_attempt_at),
                "last_error": _safe_error(action.last_error)
                or (degraded_reason if degraded else None),
                "intent_revision_id": (
                    str(action.intent_revision_id) if action.intent_revision_id else None
                ),
                "requirement_id": (str(action.requirement_id) if action.requirement_id else None),
                "alignment_state": action.alignment_state,
                "provider_ref": (
                    (local_monitor.external_id if local_monitor else None)
                    or (str(action.signal_monitor_id) if action.signal_monitor_id else None)
                ),
                "target": {
                    "action_type": action.action_type,
                    "actor_id": str(action.actor_id) if action.actor_id else None,
                    "offering_id": str(action.offering_id) if action.offering_id else None,
                    "retry_count": action.retry_count,
                    "retry_after": _iso(action.retry_after),
                    "degraded": degraded,
                    "degraded_reason": degraded_reason,
                    "signal_monitor_id": (
                        str(action.signal_monitor_id) if action.signal_monitor_id else None
                    ),
                    "collection_state": honesty.collection_state,
                    "provider_health_state": honesty.provider_health_state,
                    "provider_last_run_at": honesty.provider_last_run_at,
                    "provider_health_error_code": honesty.provider_health_error_code,
                    "provider_status": honesty.provider_status,
                    "row_version": action.row_version,
                },
            }
        )

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
            product_state = _product_state_from_monitor(monitor)
            snapshot, available = _snapshot_for(monitor)
            honesty = assess_collection_honesty(
                has_monitor=True, snapshot=snapshot, snapshot_available=available
            )
            # Same honesty rule: local active without collection proof is not clean active.
            if product_state == "active" and honesty.collection_state != "collecting":
                product_state = "needs_attention"
            items.append(
                {
                    "kind": "signal_monitor",
                    "id": str(monitor.id),
                    "title": watchlist.name,
                    "product_state": product_state,
                    "desired_status": monitor.desired_status,
                    "observed_status": monitor.observed_status,
                    "cadence": watchlist.cadence,
                    "next_run_at": _iso(monitor.next_sync_at),
                    "last_success_at": honesty.provider_last_run_at or _iso(monitor.last_synced_at),
                    "last_attempt_at": _iso(monitor.last_sync_attempt_at),
                    "last_error": _safe_error(monitor.last_error)
                    or (honesty.degraded_reason if honesty.degraded else None),
                    "intent_revision_id": cfg.get("intent_revision_id"),
                    "requirement_id": cfg.get("requirement_id"),
                    "alignment_state": cfg.get("alignment_state") or "aligned",
                    "provider_ref": monitor.external_id,
                    "target": {
                        "watchlist_id": str(watchlist.id),
                        "provider": monitor.provider,
                        "degraded": honesty.degraded,
                        "degraded_reason": honesty.degraded_reason,
                        "collection_state": honesty.collection_state,
                        "provider_health_state": honesty.provider_health_state,
                        "provider_last_run_at": honesty.provider_last_run_at,
                        "provider_health_error_code": honesty.provider_health_error_code,
                        "provider_status": honesty.provider_status,
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
