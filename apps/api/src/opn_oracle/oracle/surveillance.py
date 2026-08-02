"""MDEV-07 · vigilancias de actor/oferta con confirmación humana y cadencias.

Reglas vinculantes:
- crear actor/intake no crea monitor ni job;
- cada tipo de vigilancia requiere confirmación explícita e idempotente;
- provenance completa en cada acción;
- nueva IntentRevision aceptada marca acciones previas needs_review (sin reactivar);
- el beat tick no equivale a la cadencia elegida: next_run_at se calcula aquí;
- un fallo programa retry/backoff sin consumir el intervalo normal.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import (
    Actor,
    DossierActor,
    SignalMonitor,
    StrategicDossier,
    TenantDomainMixin,
    Watchlist,
)
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.service import ResourceNotFound, VersionConflict
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

ACTION_TYPES = frozenset(
    {
        "news_mentions",
        "official_publications",
        "actor_tenders",
        "offering_tenders",
        "research_digest",
        "no_follow",
    }
)
ACTION_STATUSES = frozenset(
    {
        "prepared",
        "active",
        "paused",
        "pending",
        "running",
        "retrying",
        "needs_attention",
        "retired",
    }
)
ALIGNMENT_STATES = frozenset({"aligned", "needs_review", "overridden"})
CADENCES = frozenset({"manual", "hourly", "daily", "weekly"})
ORIGINS = frozenset({"user", "intake", "assistant", "signal", "system"})

# Retry/backoff independent of cadence interval (does not consume normal interval).
_RETRY_BACKOFF = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=4),
)
_MAX_RETRIES = 8

_CADENCE_DELTAS: dict[str, timedelta | None] = {
    "manual": None,
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}

ACTION_TYPE_LABELS = {
    "news_mentions": "Noticias y menciones web",
    "official_publications": "Publicaciones oficiales",
    "actor_tenders": "Licitaciones del actor",
    "offering_tenders": "Licitaciones compatibles con la oferta",
    "research_digest": "Investigación / digest recurrente",
    "no_follow": "Sin seguimiento (solo contexto)",
}


class SurveillanceValidationError(ValueError):
    """Payload o transición de vigilancia inválida."""

    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"surveillance": [message]})


class PreconditionRequired(RuntimeError):
    """If-Match ausente → HTTP 428."""


class DossierSurveillanceAction(TenantDomainMixin, Base):
    """Acción de vigilancia confirmada por el usuario (o no-seguimiento)."""

    __tablename__ = "dossier_surveillance_actions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dsa_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "dedupe_key",
            name="uq_dsa_dedupe",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dsa_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="SET NULL",
            name="fk_dsa_actor_tenant",
        ),
        CheckConstraint(
            "action_type IN ("
            "'news_mentions','official_publications','actor_tenders',"
            "'offering_tenders','research_digest','no_follow')",
            name="dsa_action_type",
        ),
        CheckConstraint(
            "status IN ("
            "'prepared','active','paused','pending','running','retrying',"
            "'needs_attention','retired')",
            name="dsa_status",
        ),
        CheckConstraint(
            "alignment_state IN ('aligned','needs_review','overridden')",
            name="dsa_alignment",
        ),
        CheckConstraint(
            "cadence IN ('manual','hourly','daily','weekly')",
            name="dsa_cadence",
        ),
        CheckConstraint(
            "origin IN ('user','intake','assistant','signal','system')",
            name="dsa_origin",
        ),
        CheckConstraint("row_version >= 1", name="dsa_row_version_positive"),
        CheckConstraint("retry_count >= 0", name="dsa_retry_nonneg"),
        Index("ix_dsa_tenant_dossier", "tenant_id", "dossier_id"),
        Index("ix_dsa_tenant_next_run", "tenant_id", "next_run_at"),
        Index("ix_dsa_tenant_actor", "tenant_id", "actor_id"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="prepared")
    alignment_state: Mapped[str] = mapped_column(String(20), nullable=False, default="aligned")
    cadence: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Madrid")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    offering_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    intent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    effective_scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    watchlist_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signal_monitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    procurement_watch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    degraded_reason: Mapped[str | None] = mapped_column(String(200))


# ---------------------------------------------------------------------------
# Cadence scheduler (pure)
# ---------------------------------------------------------------------------


def _resolve_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("Europe/Madrid")


def compute_next_run_at(
    *,
    cadence: str,
    timezone: str = "Europe/Madrid",
    from_time: datetime | None = None,
    last_run_at: datetime | None = None,
) -> datetime | None:
    """Compute the next scheduled run for a normal cadence interval.

    Beat tick frequency is irrelevant: only this timestamp marks due work.
    ``manual`` never auto-schedules (returns None).
    """

    if cadence not in CADENCES:
        raise SurveillanceValidationError(f"cadence no admitida: {cadence}")
    delta = _CADENCE_DELTAS[cadence]
    if delta is None:
        return None
    base = last_run_at or from_time or datetime.now(UTC)
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    # Align to wall-clock in the action timezone without inventing "tick == cadence".
    local = base.astimezone(_resolve_tz(timezone))
    nxt = local + delta
    return nxt.astimezone(UTC)


def compute_retry_after(
    *,
    retry_count: int,
    from_time: datetime | None = None,
) -> datetime | None:
    """Schedule retry/backoff without advancing the normal cadence interval."""

    if retry_count < 0:
        raise SurveillanceValidationError("retry_count no puede ser negativo.")
    if retry_count >= _MAX_RETRIES:
        return None  # terminal — needs_attention / stop infinite polling
    idx = min(retry_count, len(_RETRY_BACKOFF) - 1)
    now = from_time or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now + _RETRY_BACKOFF[idx]


def is_due(
    *,
    status: str,
    cadence: str,
    next_run_at: datetime | None,
    retry_after: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Whether a tick should execute this action (cadence due or retry due)."""

    if status in {"retired", "paused", "prepared"}:
        return False
    clock = now or datetime.now(UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    if status == "retrying" and retry_after is not None:
        return retry_after <= clock
    if cadence == "manual":
        # manual never auto-due; only explicit sync/retry path
        return False
    if next_run_at is None:
        return False
    return next_run_at <= clock and status in {"active", "pending"}


def effective_scope_hash(scope: Mapping[str, Any]) -> str:
    """Canonical SHA-256 of the effective surveillance scope."""

    payload = json.dumps(scope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Domain service
# ---------------------------------------------------------------------------


def _load_dossier(
    session: Session,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
    *,
    write: bool,
) -> StrategicDossier:
    tenant_id = require_tenant_id()
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, actor_id, write=write):
        raise ResourceNotFound("Expediente no encontrado.")
    return dossier


def count_monitors_for_actor(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> int:
    """Count SignalMonitor rows linked via watchlist config to this actor.

    Used to prove that actor create produces zero monitors.
    """

    tenant_id = require_tenant_id()
    watchlists = list(
        session.scalars(
            select(Watchlist).where(
                Watchlist.tenant_id == tenant_id,
                Watchlist.dossier_id == dossier_id,
            )
        ).all()
    )
    matching = [
        wl
        for wl in watchlists
        if str((wl.query_config or {}).get("actor_id") or "") == str(actor_id)
        or str(actor_id) in [str(x) for x in ((wl.query_config or {}).get("actor_ids") or [])]
    ]
    if not matching:
        return 0
    ids = [wl.id for wl in matching]
    return len(
        list(
            session.scalars(
                select(SignalMonitor).where(
                    SignalMonitor.tenant_id == tenant_id,
                    SignalMonitor.watchlist_id.in_(ids),
                )
            ).all()
        )
    )


def count_jobs_for_actor_surveillance(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> int:
    """Jobs created for confirmed actions of this actor (0 until confirm)."""

    from opn_oracle.oracle.jobs import BackgroundJob

    tenant_id = require_tenant_id()
    actions = list(
        session.scalars(
            select(DossierSurveillanceAction).where(
                DossierSurveillanceAction.tenant_id == tenant_id,
                DossierSurveillanceAction.dossier_id == dossier_id,
                DossierSurveillanceAction.actor_id == actor_id,
            )
        ).all()
    )
    if not actions:
        return 0
    action_ids = {str(a.id) for a in actions}
    jobs = list(
        session.scalars(
            select(BackgroundJob).where(
                BackgroundJob.tenant_id == tenant_id,
                BackgroundJob.dossier_id == dossier_id,
            )
        ).all()
    )
    count = 0
    for job in jobs:
        payload = job.payload if isinstance(getattr(job, "payload", None), dict) else {}
        if str(payload.get("surveillance_action_id") or "") in action_ids:
            count += 1
        elif str(payload.get("actor_id") or "") == str(actor_id) and str(
            payload.get("kind") or ""
        ).startswith("surveillance"):
            count += 1
    return count


def serialize_action(action: DossierSurveillanceAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "tenant_id": str(action.tenant_id),
        "dossier_id": str(action.dossier_id),
        "action_type": action.action_type,
        "title": action.title or ACTION_TYPE_LABELS.get(action.action_type, action.action_type),
        "status": action.status,
        "product_state": action.status,
        "alignment_state": action.alignment_state,
        "cadence": action.cadence,
        "timezone": action.timezone,
        "actor_id": str(action.actor_id) if action.actor_id else None,
        "offering_id": str(action.offering_id) if action.offering_id else None,
        "requirement_id": str(action.requirement_id) if action.requirement_id else None,
        "intent_revision_id": (
            str(action.intent_revision_id) if action.intent_revision_id else None
        ),
        "effective_scope_hash": action.effective_scope_hash,
        "origin": action.origin,
        "confirmed_by_user_id": (
            str(action.confirmed_by_user_id) if action.confirmed_by_user_id else None
        ),
        "confirmed_at": action.confirmed_at.isoformat() if action.confirmed_at else None,
        "manual_overrides": dict(action.manual_overrides or {}),
        "last_run_at": action.last_run_at.isoformat() if action.last_run_at else None,
        "next_run_at": action.next_run_at.isoformat() if action.next_run_at else None,
        "last_attempt_at": (
            action.last_attempt_at.isoformat() if action.last_attempt_at else None
        ),
        "last_error": action.last_error,
        "retry_count": action.retry_count,
        "retry_after": action.retry_after.isoformat() if action.retry_after else None,
        "row_version": action.row_version,
        "watchlist_id": str(action.watchlist_id) if action.watchlist_id else None,
        "signal_monitor_id": (
            str(action.signal_monitor_id) if action.signal_monitor_id else None
        ),
        "procurement_watch_id": (
            str(action.procurement_watch_id) if action.procurement_watch_id else None
        ),
        "degraded": bool(action.degraded),
        "degraded_reason": action.degraded_reason,
        "notes": action.notes or "",
    }


def list_actions(
    session: Session,
    dossier_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    action_type: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> list[DossierSurveillanceAction]:
    _load_dossier(session, dossier_id, actor_user_id, write=False)
    tenant_id = require_tenant_id()
    stmt = select(DossierSurveillanceAction).where(
        DossierSurveillanceAction.tenant_id == tenant_id,
        DossierSurveillanceAction.dossier_id == dossier_id,
    )
    if action_type:
        stmt = stmt.where(DossierSurveillanceAction.action_type == action_type)
    if actor_id is not None:
        stmt = stmt.where(DossierSurveillanceAction.actor_id == actor_id)
    stmt = stmt.order_by(
        DossierSurveillanceAction.updated_at.desc(),
        DossierSurveillanceAction.id.desc(),
    )
    return list(session.scalars(stmt).all())


def _get_action_for_update(
    session: Session,
    action_id: uuid.UUID,
) -> DossierSurveillanceAction:
    tenant_id = require_tenant_id()
    action = session.scalar(
        select(DossierSurveillanceAction)
        .where(
            DossierSurveillanceAction.id == action_id,
            DossierSurveillanceAction.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if action is None:
        raise ResourceNotFound("Acción de vigilancia no encontrada.")
    return action


def confirm_surveillance_action(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payload: Mapping[str, Any],
    request_id: str | None = None,
    create_backend_resources: bool = False,
) -> tuple[DossierSurveillanceAction, bool]:
    """Confirm a surveillance type. Idempotent on (dossier, type, actor, offering).

    Returns (action, created). Never auto-activates Signal jobs unless
    ``create_backend_resources`` is True AND type is not ``no_follow``.
    Default keeps prepared/active local state without remote auto-start.
    """

    dossier = _load_dossier(session, dossier_id, actor_user_id, write=True)
    if dossier.status == "archived":
        raise SurveillanceValidationError("Un expediente archivado es de solo lectura.")

    action_type = str(payload.get("action_type") or "").strip()
    if action_type not in ACTION_TYPES:
        raise SurveillanceValidationError(
            "action_type no es válido.",
            errors={
                "action_type": [
                    "Debe ser news_mentions, official_publications, actor_tenders, "
                    "offering_tenders, research_digest o no_follow."
                ]
            },
        )

    cadence = str(payload.get("cadence") or "manual").strip()
    if cadence not in CADENCES:
        raise SurveillanceValidationError(
            "cadence no es válida.",
            errors={"cadence": ["Debe ser manual, hourly, daily o weekly."]},
        )
    timezone = str(payload.get("timezone") or "Europe/Madrid").strip()[:64] or "Europe/Madrid"
    origin = str(payload.get("origin") or "user").strip()
    if origin not in ORIGINS:
        raise SurveillanceValidationError("origin no es válido.")

    actor_id: uuid.UUID | None = None
    raw_actor = payload.get("actor_id")
    if raw_actor not in (None, ""):
        try:
            actor_id = uuid.UUID(str(raw_actor))
        except (TypeError, ValueError) as error:
            raise SurveillanceValidationError(
                "actor_id debe ser UUID.",
                errors={"actor_id": ["Debe ser un UUID."]},
            ) from error
        actor = session.scalar(
            select(Actor).where(Actor.id == actor_id, Actor.tenant_id == dossier.tenant_id)
        )
        if actor is None:
            raise ResourceNotFound("Actor no encontrado.")
        link = session.scalar(
            select(DossierActor).where(
                DossierActor.tenant_id == dossier.tenant_id,
                DossierActor.dossier_id == dossier.id,
                DossierActor.actor_id == actor_id,
            )
        )
        if link is None:
            raise SurveillanceValidationError(
                "El actor debe estar vinculado al expediente.",
                errors={"actor_id": ["Vincula el actor al expediente antes de vigilarlo."]},
            )

    offering_id: uuid.UUID | None = None
    raw_offering = payload.get("offering_id")
    if raw_offering not in (None, ""):
        try:
            offering_id = uuid.UUID(str(raw_offering))
        except (TypeError, ValueError) as error:
            raise SurveillanceValidationError(
                "offering_id debe ser UUID.",
                errors={"offering_id": ["Debe ser un UUID."]},
            ) from error

    if action_type in {
        "news_mentions",
        "official_publications",
        "actor_tenders",
        "no_follow",
    } and actor_id is None:
        raise SurveillanceValidationError(
            "Este tipo de vigilancia requiere actor_id.",
            errors={"actor_id": ["Obligatorio para este tipo."]},
        )
    if action_type == "offering_tenders" and offering_id is None:
        raise SurveillanceValidationError(
            "offering_tenders requiere offering_id.",
            errors={"offering_id": ["Obligatorio para licitaciones de oferta."]},
        )

    requirement_id: uuid.UUID | None = None
    raw_req = payload.get("requirement_id")
    if raw_req not in (None, ""):
        try:
            requirement_id = uuid.UUID(str(raw_req))
        except (TypeError, ValueError) as error:
            raise SurveillanceValidationError(
                "requirement_id debe ser UUID.",
                errors={"requirement_id": ["Debe ser un UUID."]},
            ) from error

    intent_revision_id = dossier.current_intent_revision_id
    raw_intent = payload.get("intent_revision_id")
    if raw_intent not in (None, ""):
        try:
            intent_revision_id = uuid.UUID(str(raw_intent))
        except (TypeError, ValueError) as error:
            raise SurveillanceValidationError(
                "intent_revision_id debe ser UUID.",
                errors={"intent_revision_id": ["Debe ser un UUID."]},
            ) from error

    scope = {
        "dossier_id": str(dossier.id),
        "action_type": action_type,
        "actor_id": str(actor_id) if actor_id else None,
        "offering_id": str(offering_id) if offering_id else None,
        "requirement_id": str(requirement_id) if requirement_id else None,
        "intent_revision_id": str(intent_revision_id) if intent_revision_id else None,
        "cadence": cadence,
        "timezone": timezone,
        "keywords": list(payload.get("keywords") or []),
        "source_types": list(payload.get("source_types") or []),
    }
    scope_hash = effective_scope_hash(scope)
    title = str(payload.get("title") or ACTION_TYPE_LABELS.get(action_type, action_type))[:300]
    notes = str(payload.get("notes") or "")[:5000]
    manual_overrides = payload.get("manual_overrides") or {}
    if not isinstance(manual_overrides, Mapping):
        raise SurveillanceValidationError("manual_overrides debe ser un objeto.")

    tenant_id = dossier.tenant_id
    dedupe_key = build_dedupe_key(
        action_type=action_type, actor_id=actor_id, offering_id=offering_id
    )
    existing = session.scalar(
        select(DossierSurveillanceAction)
        .where(
            DossierSurveillanceAction.tenant_id == tenant_id,
            DossierSurveillanceAction.dossier_id == dossier.id,
            DossierSurveillanceAction.dedupe_key == dedupe_key,
        )
        .with_for_update()
    )

    now = datetime.now(UTC)
    if existing is not None:
        # Idempotent confirm: refresh cadence/scope if still not retired; no re-activation storm.
        if existing.status == "retired":
            existing.status = "prepared" if action_type == "no_follow" else "active"
        existing.cadence = cadence
        existing.timezone = timezone
        existing.effective_scope_hash = scope_hash
        existing.requirement_id = requirement_id
        existing.intent_revision_id = intent_revision_id
        existing.confirmed_by_user_id = actor_user_id
        existing.confirmed_at = now
        existing.manual_overrides = dict(manual_overrides)
        existing.title = title
        existing.notes = notes
        existing.alignment_state = "aligned"
        existing.origin = origin
        if action_type == "no_follow":
            existing.status = "retired" if existing.status != "retired" else existing.status
            # Product: no_follow is a deliberate non-monitor choice; keep as retired/context.
            existing.status = "retired"
            existing.next_run_at = None
        else:
            if existing.status in {"prepared", "retired"}:
                existing.status = "active"
            existing.next_run_at = compute_next_run_at(
                cadence=cadence, timezone=timezone, from_time=now
            )
        existing.row_version += 1
        # MDEV-05 debt: do not pretend durable remote activation.
        if create_backend_resources and action_type != "no_follow":
            existing.degraded = True
            existing.degraded_reason = "DUR-MDEV05-001: backend monitor no durable; fail-closed local"
        append_audit_event(
            session,
            action="surveillance.confirmed.idempotent",
            resource_type="dossier_surveillance_action",
            resource_id=existing.id,
            dossier_id=dossier.id,
            result="success",
            request_id=request_id,
            metadata={
                "action_type": action_type,
                "scope_hash": scope_hash,
                "duplicate": True,
            },
        )
        session.commit()
        return existing, False

    status = "retired" if action_type == "no_follow" else "active"
    next_run = None if action_type == "no_follow" else compute_next_run_at(
        cadence=cadence, timezone=timezone, from_time=now
    )
    degraded = False
    degraded_reason = None
    if create_backend_resources and action_type != "no_follow":
        # Explicit flag for tests that want to exercise fail-closed remote path.
        degraded = True
        degraded_reason = "DUR-MDEV05-001: backend monitor no durable; fail-closed local"

    action = DossierSurveillanceAction(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        action_type=action_type,
        dedupe_key=dedupe_key,
        status=status,
        alignment_state="aligned",
        cadence=cadence,
        timezone=timezone,
        actor_id=actor_id,
        offering_id=offering_id,
        requirement_id=requirement_id,
        intent_revision_id=intent_revision_id,
        effective_scope_hash=scope_hash,
        origin=origin,
        confirmed_by_user_id=actor_user_id,
        confirmed_at=now,
        manual_overrides=dict(manual_overrides),
        next_run_at=next_run,
        title=title,
        notes=notes,
        degraded=degraded,
        degraded_reason=degraded_reason,
        retry_count=0,
        row_version=1,
        # Intentionally no watchlist_id / signal_monitor_id until durable path exists.
        watchlist_id=None,
        signal_monitor_id=None,
        procurement_watch_id=None,
    )
    session.add(action)
    session.flush()
    append_audit_event(
        session,
        action="surveillance.confirmed",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={
            "action_type": action_type,
            "scope_hash": scope_hash,
            "cadence": cadence,
            "monitors_created": False,
            "jobs_created": False,
        },
    )
    session.commit()
    return action, True


def _require_if_match(action: DossierSurveillanceAction, expected_version: int | None) -> None:
    if expected_version is None or expected_version < 1:
        raise PreconditionRequired("If-Match es obligatorio.")
    if action.row_version != expected_version:
        raise VersionConflict("La vigilancia fue modificada por otro proceso.")


def build_dedupe_key(
    *,
    action_type: str,
    actor_id: uuid.UUID | None,
    offering_id: uuid.UUID | None,
) -> str:
    return (
        f"{action_type}|"
        f"actor={(str(actor_id) if actor_id else '-')}|"
        f"offering={(str(offering_id) if offering_id else '-')}"
    )


def pause_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    if action.status == "retired":
        raise SurveillanceValidationError("Una vigilancia retirada no se puede pausar.")
    if action.status == "paused":
        return action  # idempotent
    action.status = "paused"
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.paused",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": action.row_version},
    )
    session.commit()
    return action


def resume_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    if action.status == "retired":
        raise SurveillanceValidationError("Una vigilancia retirada no se puede reanudar.")
    if action.action_type == "no_follow":
        raise SurveillanceValidationError("no_follow no se reanuda; es solo contexto.")
    if action.status == "active" and action.retry_count == 0:
        return action
    now = datetime.now(UTC)
    action.status = "active"
    action.last_error = None
    action.retry_count = 0
    action.retry_after = None
    action.next_run_at = compute_next_run_at(
        cadence=action.cadence, timezone=action.timezone, from_time=now
    )
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.resumed",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": action.row_version, "next_run_at": action.next_run_at.isoformat() if action.next_run_at else None},
    )
    session.commit()
    return action


def sync_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    """Manual sync request. Marks pending; does not invent durable remote success."""

    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    if action.status == "retired" or action.action_type == "no_follow":
        raise SurveillanceValidationError("No hay sincronización para no_follow/retirada.")
    now = datetime.now(UTC)
    action.status = "pending"
    action.last_attempt_at = now
    action.degraded = True
    action.degraded_reason = action.degraded_reason or (
        "DUR-MDEV05-001/MON-MDEV05-004: sync local-only; Signal monitor no durable"
    )
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.sync_requested",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"degraded": True},
    )
    session.commit()
    return action


def retry_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    if action.status == "retired":
        raise SurveillanceValidationError("No se puede reintentar una vigilancia retirada.")
    now = datetime.now(UTC)
    # Preserve next_run_at (normal cadence); only schedule retry_after.
    action.retry_count += 1
    action.retry_after = compute_retry_after(retry_count=action.retry_count - 1, from_time=now)
    action.last_attempt_at = now
    if action.retry_after is None:
        action.status = "needs_attention"
        action.last_error = (action.last_error or "reintentos agotados")[:500]
    else:
        action.status = "retrying"
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.retry_scheduled",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={
            "retry_count": action.retry_count,
            "retry_after": action.retry_after.isoformat() if action.retry_after else None,
            "next_run_at_preserved": action.next_run_at.isoformat() if action.next_run_at else None,
        },
    )
    session.commit()
    return action


def retire_action(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    if action.status == "retired":
        return action
    action.status = "retired"
    action.next_run_at = None
    action.retry_after = None
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.retired",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": action.row_version},
    )
    session.commit()
    return action


def adopt_alignment(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    """Rebind action to current intent revision + scope; clear needs_review."""

    action = _get_action_for_update(session, action_id)
    dossier = _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    action.intent_revision_id = dossier.current_intent_revision_id
    scope = {
        "dossier_id": str(action.dossier_id),
        "action_type": action.action_type,
        "actor_id": str(action.actor_id) if action.actor_id else None,
        "offering_id": str(action.offering_id) if action.offering_id else None,
        "requirement_id": str(action.requirement_id) if action.requirement_id else None,
        "intent_revision_id": (
            str(action.intent_revision_id) if action.intent_revision_id else None
        ),
        "cadence": action.cadence,
        "timezone": action.timezone,
        "adopted_at": datetime.now(UTC).isoformat(),
    }
    action.effective_scope_hash = effective_scope_hash(scope)
    action.alignment_state = "aligned"
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.alignment.adopted",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"scope_hash": action.effective_scope_hash},
    )
    session.commit()
    return action


def keep_alignment(
    session: Session,
    *,
    action_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> DossierSurveillanceAction:
    """Keep existing scope as overridden after intent change."""

    action = _get_action_for_update(session, action_id)
    _load_dossier(session, action.dossier_id, actor_user_id, write=True)
    _require_if_match(action, expected_version)
    action.alignment_state = "overridden"
    action.row_version += 1
    append_audit_event(
        session,
        action="surveillance.alignment.kept",
        resource_type="dossier_surveillance_action",
        resource_id=action.id,
        dossier_id=action.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"alignment_state": "overridden"},
    )
    session.commit()
    return action


def mark_actions_needs_review_for_superseded_intent(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    previous_revision_id: uuid.UUID,
    new_revision_id: uuid.UUID,
) -> int:
    """Mark prior actions needs_review. Does not reconfigure or reactivate them."""

    tenant_id = require_tenant_id()
    rows = list(
        session.scalars(
            select(DossierSurveillanceAction)
            .where(
                DossierSurveillanceAction.tenant_id == tenant_id,
                DossierSurveillanceAction.dossier_id == dossier_id,
                DossierSurveillanceAction.status != "retired",
            )
            .with_for_update()
        ).all()
    )
    marked = 0
    for action in rows:
        # Mark when linked to previous revision OR any non-new revision.
        if action.intent_revision_id == new_revision_id:
            continue
        if (
            action.intent_revision_id == previous_revision_id
            or action.intent_revision_id is not None
            or action.intent_revision_id is None
        ):
            if action.alignment_state != "needs_review":
                action.alignment_state = "needs_review"
                action.row_version += 1
                marked += 1
    return marked


def record_run_failure(
    session: Session,
    *,
    action_id: uuid.UUID,
    error_message: str,
) -> DossierSurveillanceAction:
    """Apply failure: schedule retry without consuming normal cadence interval."""

    action = _get_action_for_update(session, action_id)
    now = datetime.now(UTC)
    preserved_next = action.next_run_at
    action.last_attempt_at = now
    action.last_error = (error_message or "error")[:500]
    action.retry_count += 1
    action.retry_after = compute_retry_after(retry_count=action.retry_count - 1, from_time=now)
    action.next_run_at = preserved_next  # do not consume normal interval
    if action.retry_after is None:
        action.status = "needs_attention"
    else:
        action.status = "retrying"
    action.row_version += 1
    session.flush()
    return action


def record_run_success(
    session: Session,
    *,
    action_id: uuid.UUID,
) -> DossierSurveillanceAction:
    action = _get_action_for_update(session, action_id)
    now = datetime.now(UTC)
    action.last_run_at = now
    action.last_attempt_at = now
    action.last_error = None
    action.retry_count = 0
    action.retry_after = None
    action.status = "active"
    action.next_run_at = compute_next_run_at(
        cadence=action.cadence,
        timezone=action.timezone,
        from_time=now,
        last_run_at=now,
    )
    action.row_version += 1
    session.flush()
    return action


def build_oracle_to_signal_scope(
    action: DossierSurveillanceAction,
    *,
    consumer_id: str,
    external_tenant_id: str,
) -> dict[str, Any]:
    """Contract payload Oracle→Signal: consumer+tenant+dossier+scope/provenance.

    No signal may enter memory without these links (MDEV-07 §4).
    """

    if not consumer_id or not external_tenant_id:
        raise SurveillanceValidationError(
            "consumer_id y external_tenant_id son obligatorios para el contrato Signal."
        )
    return {
        "api_version": "memory.v1",
        "consumer_id": consumer_id,
        "external_tenant_id": external_tenant_id,
        "tenant_id": str(action.tenant_id),
        "dossier_id": str(action.dossier_id),
        "scope": {
            "action_id": str(action.id),
            "action_type": action.action_type,
            "actor_id": str(action.actor_id) if action.actor_id else None,
            "offering_id": str(action.offering_id) if action.offering_id else None,
            "requirement_id": str(action.requirement_id) if action.requirement_id else None,
            "intent_revision_id": (
                str(action.intent_revision_id) if action.intent_revision_id else None
            ),
            "effective_scope_hash": action.effective_scope_hash,
            "cadence": action.cadence,
            "timezone": action.timezone,
        },
        "provenance": {
            "origin": action.origin,
            "confirmed_by_user_id": (
                str(action.confirmed_by_user_id) if action.confirmed_by_user_id else None
            ),
            "confirmed_at": action.confirmed_at.isoformat() if action.confirmed_at else None,
            "alignment_state": action.alignment_state,
            "manual_overrides": dict(action.manual_overrides or {}),
        },
    }
