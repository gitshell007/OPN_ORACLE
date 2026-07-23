"""Durable, deterministic vigilance for human-saved tender searches.

Signal v1 has neither a stable remote cursor nor a useful change feed.  The
only honest notion of novelty is therefore local: an unseen ``folder_id`` or a
materially different payload for an already seen folder.  This module owns that
memory; it never asks an LLM to classify a tender or a change.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base, db
from opn_oracle.integrations.procurement import ProcurementProviderError, run_tender_search
from opn_oracle.oracle.jobs import JobSchedule
from opn_oracle.oracle.models import TenantDomainMixin
from opn_oracle.oracle.procurement_search_preview import saved_search_payload
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfile,
    ProcurementSearchProfileValidationError,
    ProcurementSearchProfileVersionConflict,
)
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.notifications import create_notification, publish_notification_job
from opn_oracle.tenants.context import require_tenant_id

WATCH_CADENCE_SECONDS = 900
WATCH_PAGE_SIZE = 200
WATCH_MAX_REMOTE_REQUESTS = 4
WATCH_MAX_ITEMS_PER_SCAN = WATCH_PAGE_SIZE * WATCH_MAX_REMOTE_REQUESTS
WATCH_MAX_ENABLED_PER_TENANT = 12
WATCH_ALLOWED_CADENCES = (900, 3600, 86_400)
WATCH_RETENTION_DAYS = 90
WATCH_SCHEDULE_PREFIX = "procurement-watch:"
WATCH_NOTIFICATION_TYPE = "procurement.watch"


class ProcurementSearchWatch(TenantDomainMixin, Base):
    """One explicit Oracle vigilance for one saved Signal tender search."""

    __tablename__ = "procurement_search_watches"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_procurement_search_watches_id_tenant"),
        UniqueConstraint(
            "tenant_id", "profile_id", name="uq_procurement_search_watches_profile_tenant"
        ),
        UniqueConstraint(
            "tenant_id", "tender_search_id", name="uq_procurement_search_watches_search_tenant"
        ),
        ForeignKeyConstraint(
            ("profile_id", "tenant_id"),
            ("procurement_search_profiles.id", "procurement_search_profiles.tenant_id"),
            ondelete="CASCADE",
            name="fk_procurement_search_watches_profile_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "notification_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_procurement_search_watches_notification_membership",
        ),
        CheckConstraint("cadence_seconds >= 900", name="procurement_search_watch_cadence"),
        Index("ix_procurement_search_watches_tenant_active", "tenant_id", "enabled", "deleted_at"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tender_search_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cadence_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=WATCH_CADENCE_SECONDS
    )
    notification_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcurementSearchWatchItem(TenantDomainMixin, Base):
    """Seen-state and material content fingerprint for a tender in one watch."""

    __tablename__ = "procurement_search_watch_items"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_procurement_search_watch_items_id_tenant"),
        UniqueConstraint(
            "tenant_id", "watch_id", "folder_id", name="uq_procurement_search_watch_items_folder"
        ),
        ForeignKeyConstraint(
            ("watch_id", "tenant_id"),
            ("procurement_search_watches.id", "procurement_search_watches.tenant_id"),
            ondelete="CASCADE",
            name="fk_procurement_search_watch_items_watch_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewed_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_procurement_search_watch_items_reviewer_membership",
        ),
        CheckConstraint("octet_length(content_hash)=32", name="procurement_search_watch_item_hash"),
        CheckConstraint(
            "jsonb_typeof(snapshot)='object'", name="procurement_search_watch_item_snapshot"
        ),
        CheckConstraint(
            "jsonb_typeof(last_change_fields)='array'",
            name="procurement_search_watch_item_change_fields",
        ),
        Index(
            "ix_procurement_search_watch_items_unreviewed",
            "tenant_id",
            "watch_id",
            "reviewed_at",
        ),
        Index("ix_procurement_search_watch_items_retention", "tenant_id", "last_seen_at"),
    )

    watch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    folder_id: Mapped[str] = mapped_column(String(300), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_change_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ProcurementSearchWatchNotFound(LookupError):
    pass


class ProcurementSearchWatchConflict(RuntimeError):
    pass


class ProcurementSearchWatchScanError(RuntimeError):
    """A public, retryable or permanent failure for the durable scan handler."""

    def __init__(self, message: str, *, retryable: bool, code: str) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.code = code


TenderSearchRunner = Callable[..., dict[str, Any]]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _decimal_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, ValueError):
        return _clean_text(value) or None


def _cpvs(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    return sorted({_clean_text(item) for item in raw if _clean_text(item)})


def material_tender_snapshot(item: Mapping[str, Any]) -> dict[str, Any]:
    """Only analyst-relevant content participates in novelty, never feed time."""

    return {
        "title": _clean_text(item.get("title")),
        "object": _clean_text(item.get("summary_feed") or item.get("object")),
        "buyer": _clean_text(item.get("buyer")),
        "amount": _decimal_text(item.get("amount")),
        "deadline": _clean_text(item.get("deadline")) or None,
        "canonical_status": _clean_text(item.get("canonical_status")) or "unknown",
        "cpvs": _cpvs(item.get("cpv")),
    }


def material_tender_hash(snapshot: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(
        json.dumps(
            dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).digest()


def material_change_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    return [key for key in after if before.get(key) != after.get(key)]


def _watch_schedule_key(watch_id: uuid.UUID) -> str:
    return f"{WATCH_SCHEDULE_PREFIX}{watch_id}"


def _get_watch(
    session: Session, watch_id: uuid.UUID, *, for_update: bool = False
) -> ProcurementSearchWatch:
    tenant_id = require_tenant_id()
    statement = select(ProcurementSearchWatch).where(
        ProcurementSearchWatch.id == watch_id,
        ProcurementSearchWatch.tenant_id == tenant_id,
        ProcurementSearchWatch.deleted_at.is_(None),
    )
    if for_update:
        statement = statement.with_for_update()
    watch = session.scalar(statement)
    if watch is None:
        raise ProcurementSearchWatchNotFound("Vigilancia de licitaciones no encontrada.")
    return watch


def get_watch_for_profile(session: Session, profile_id: uuid.UUID) -> ProcurementSearchWatch | None:
    tenant_id = require_tenant_id()
    return session.scalar(
        select(ProcurementSearchWatch).where(
            ProcurementSearchWatch.tenant_id == tenant_id,
            ProcurementSearchWatch.profile_id == profile_id,
            ProcurementSearchWatch.deleted_at.is_(None),
        )
    )


def list_procurement_search_watches(session: Session) -> list[ProcurementSearchWatch]:
    tenant_id = require_tenant_id()
    return list(
        session.scalars(
            select(ProcurementSearchWatch)
            .where(
                ProcurementSearchWatch.tenant_id == tenant_id,
                ProcurementSearchWatch.deleted_at.is_(None),
            )
            .order_by(ProcurementSearchWatch.created_at.desc(), ProcurementSearchWatch.id.desc())
        )
    )


def _upsert_schedule(session: Session, watch: ProcurementSearchWatch, *, now: datetime) -> None:
    schedule = session.scalar(
        select(JobSchedule)
        .where(
            JobSchedule.tenant_id == watch.tenant_id,
            JobSchedule.schedule_key == _watch_schedule_key(watch.id),
        )
        .with_for_update()
    )
    if schedule is None:
        schedule = JobSchedule(
            tenant_id=watch.tenant_id,
            schedule_key=_watch_schedule_key(watch.id),
            task_name="oracle.procurement_watch.scan",
            queue="signals",
            payload={"watch_id": str(watch.id)},
            cadence_seconds=watch.cadence_seconds,
            next_run_at=now,
            enabled=watch.enabled,
            timezone="UTC",
            schedule_kind="interval",
        )
        session.add(schedule)
        return
    schedule.task_name = "oracle.procurement_watch.scan"
    schedule.queue = "signals"
    schedule.payload = {"watch_id": str(watch.id)}
    schedule.cadence_seconds = watch.cadence_seconds
    schedule.enabled = watch.enabled
    if watch.enabled and schedule.next_run_at < now:
        schedule.next_run_at = now


def create_watch_for_saved_profile(
    session: Session,
    profile: ProcurementSearchProfile,
    *,
    name: str,
    tender_search_id: str,
) -> ProcurementSearchWatch:
    """Persist an inactive watch beside the user-created Signal saved search."""

    existing = get_watch_for_profile(session, profile.id)
    if existing is not None:
        return existing
    watch = ProcurementSearchWatch(
        tenant_id=profile.tenant_id,
        profile_id=profile.id,
        tender_search_id=tender_search_id,
        name=_clean_text(name)[:120],
        enabled=False,
        notifications_enabled=False,
        cadence_seconds=WATCH_CADENCE_SECONDS,
    )
    session.add(watch)
    session.flush()
    _upsert_schedule(session, watch, now=datetime.now(UTC))
    return watch


def configure_procurement_search_watch(
    session: Session,
    watch_id: uuid.UUID,
    *,
    enabled: bool,
    notifications_enabled: bool,
    cadence_seconds: int | None = None,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> ProcurementSearchWatch:
    watch = _get_watch(session, watch_id, for_update=True)
    if enabled:
        enabled_count = session.scalar(
            select(func.count(ProcurementSearchWatch.id)).where(
                ProcurementSearchWatch.tenant_id == watch.tenant_id,
                ProcurementSearchWatch.enabled.is_(True),
                ProcurementSearchWatch.deleted_at.is_(None),
                ProcurementSearchWatch.id != watch.id,
            )
        )
        if int(enabled_count or 0) >= WATCH_MAX_ENABLED_PER_TENANT:
            raise ProcurementSearchWatchConflict(
                "El tenant ya tiene el máximo de 12 vigilancias incrementales activas."
            )
    watch.enabled = enabled
    watch.notifications_enabled = notifications_enabled if enabled else False
    watch.notification_user_id = actor_id if watch.notifications_enabled else None
    if cadence_seconds is not None:
        if cadence_seconds not in WATCH_ALLOWED_CADENCES:
            raise ProcurementSearchProfileValidationError(
                "La frecuencia debe ser 15 minutos, una hora o un día.",
                errors={"cadence_seconds": ["Selecciona una frecuencia admitida."]},
            )
        watch.cadence_seconds = cadence_seconds
    _upsert_schedule(session, watch, now=datetime.now(UTC))
    append_audit_event(
        session,
        action="procurement.search_watch.configure",
        resource_type="procurement_search_watch",
        resource_id=watch.id,
        result="success",
        request_id=request_id,
        metadata={
            "enabled": watch.enabled,
            "notifications_enabled": watch.notifications_enabled,
            "cadence_seconds": watch.cadence_seconds,
        },
    )
    session.commit()
    return watch


def _watch_item_state(item: ProcurementSearchWatchItem) -> tuple[str, list[str]]:
    if item.reviewed_at is not None:
        return "reviewed", []
    if item.first_seen_at == item.last_changed_at:
        return "new", ["new"]
    return "changed", list(item.last_change_fields)


def serialize_procurement_search_watch(watch: ProcurementSearchWatch) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    unread = int(
        db.session.scalar(
            select(func.count(ProcurementSearchWatchItem.id)).where(
                ProcurementSearchWatchItem.tenant_id == tenant_id,
                ProcurementSearchWatchItem.watch_id == watch.id,
                ProcurementSearchWatchItem.reviewed_at.is_(None),
            )
        )
        or 0
    )
    return {
        "id": str(watch.id),
        "profile_id": str(watch.profile_id),
        "tender_search_id": watch.tender_search_id,
        "name": watch.name,
        "enabled": watch.enabled,
        "notifications_enabled": watch.notifications_enabled,
        "cadence_seconds": watch.cadence_seconds,
        "new_count": unread,
        "last_success_at": watch.last_success_at.isoformat() if watch.last_success_at else None,
        "last_attempt_at": watch.last_attempt_at.isoformat() if watch.last_attempt_at else None,
        "last_error_code": watch.last_error_code,
        "last_error_message": watch.last_error_message,
        "created_at": watch.created_at.isoformat(),
        "updated_at": watch.updated_at.isoformat(),
    }


def list_procurement_search_watch_items(
    session: Session, watch_id: uuid.UUID
) -> list[dict[str, Any]]:
    watch = _get_watch(session, watch_id)
    rows = list(
        session.scalars(
            select(ProcurementSearchWatchItem)
            .where(
                ProcurementSearchWatchItem.tenant_id == watch.tenant_id,
                ProcurementSearchWatchItem.watch_id == watch.id,
            )
            .order_by(
                ProcurementSearchWatchItem.reviewed_at.is_not(None),
                ProcurementSearchWatchItem.last_changed_at.desc(),
                ProcurementSearchWatchItem.folder_id,
            )
        )
    )
    output: list[dict[str, Any]] = []
    for row in rows:
        state, fields = _watch_item_state(row)
        output.append(
            {
                "id": str(row.id),
                "folder_id": row.folder_id,
                "snapshot": dict(row.snapshot),
                "state": state,
                "changed_fields": fields,
                "first_seen_at": row.first_seen_at.isoformat(),
                "last_changed_at": row.last_changed_at.isoformat(),
                "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            }
        )
    return output


def mark_watch_items_reviewed(
    session: Session,
    watch_id: uuid.UUID,
    *,
    folder_ids: list[str],
    actor_id: uuid.UUID,
    reviewed: bool,
    request_id: str | None = None,
) -> list[ProcurementSearchWatchItem]:
    watch = _get_watch(session, watch_id, for_update=True)
    clean_ids = list(
        dict.fromkeys(_clean_text(value) for value in folder_ids if _clean_text(value))
    )
    if not clean_ids or len(clean_ids) > 200:
        raise ProcurementSearchProfileValidationError(
            "Indica entre una y 200 licitaciones de esta vigilancia.",
            errors={"folder_ids": ["Indica entre una y 200 licitaciones."]},
        )
    rows = list(
        session.scalars(
            select(ProcurementSearchWatchItem)
            .where(
                ProcurementSearchWatchItem.tenant_id == watch.tenant_id,
                ProcurementSearchWatchItem.watch_id == watch.id,
                ProcurementSearchWatchItem.folder_id.in_(clean_ids),
            )
            .with_for_update()
        )
    )
    if len(rows) != len(clean_ids):
        raise ProcurementSearchWatchNotFound("Una licitación no pertenece a esta vigilancia.")
    now = datetime.now(UTC)
    for row in rows:
        row.reviewed_at = now if reviewed else None
        row.reviewed_by_user_id = actor_id if reviewed else None
    append_audit_event(
        session,
        action=(
            "procurement.search_watch.reviewed"
            if reviewed
            else "procurement.search_watch.review_restored"
        ),
        resource_type="procurement_search_watch",
        resource_id=watch.id,
        result="success",
        request_id=request_id,
        metadata={"count": len(rows), "folder_ids": clean_ids},
    )
    session.commit()
    return rows


def mark_feedback_folder_seen(
    session: Session,
    profile_id: uuid.UUID,
    folder_id: str,
    *,
    actor_id: uuid.UUID,
) -> None:
    """Feedback is an intentional review, so it closes any matching unseen item."""

    watch = get_watch_for_profile(session, profile_id)
    if watch is None:
        return
    row = session.scalar(
        select(ProcurementSearchWatchItem)
        .where(
            ProcurementSearchWatchItem.tenant_id == watch.tenant_id,
            ProcurementSearchWatchItem.watch_id == watch.id,
            ProcurementSearchWatchItem.folder_id == folder_id,
        )
        .with_for_update()
    )
    if row is not None:
        row.reviewed_at = datetime.now(UTC)
        row.reviewed_by_user_id = actor_id


def _collect_tenders(
    watch: ProcurementSearchWatch, runner: TenderSearchRunner
) -> list[dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    expected_total: int | None = None
    for page in range(WATCH_MAX_REMOTE_REQUESTS):
        try:
            payload = runner(
                search_id=watch.tender_search_id,
                limit=WATCH_PAGE_SIZE,
                offset=page * WATCH_PAGE_SIZE,
            )
        except ProcurementProviderError as error:
            raise ProcurementSearchWatchScanError(
                error.detail, retryable=error.retryable, code=error.code
            ) from error
        results = payload.get("results") if isinstance(payload, Mapping) else None
        if not isinstance(results, Mapping):
            raise ProcurementSearchWatchScanError(
                "Signal devolvió una vigilancia sin resultados válidos.",
                retryable=False,
                code="procurement_watch_invalid_payload",
            )
        raw_items = results.get("items")
        if not isinstance(raw_items, list):
            raise ProcurementSearchWatchScanError(
                "Signal devolvió elementos de vigilancia no válidos.",
                retryable=False,
                code="procurement_watch_invalid_items",
            )
        if expected_total is None and isinstance(results.get("total"), int):
            expected_total = int(results["total"])
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                continue
            folder_id = _clean_text(raw.get("folder_id"))
            if folder_id:
                items[folder_id] = dict(raw)
        if len(raw_items) < WATCH_PAGE_SIZE:
            break
    if expected_total is not None and expected_total > WATCH_MAX_ITEMS_PER_SCAN:
        raise ProcurementSearchWatchScanError(
            "La vigilancia supera el presupuesto de 800 resultados por ciclo.",
            retryable=False,
            code="procurement_watch_result_budget_exceeded",
        )
    return [items[key] for key in sorted(items)]


def _notification_body(
    new_rows: list[ProcurementSearchWatchItem],
    changed_rows: list[tuple[ProcurementSearchWatchItem, list[str]]],
) -> str:
    parts: list[str] = []

    def detail(row: ProcurementSearchWatchItem) -> str:
        snapshot = row.snapshot
        return " · ".join(
            value
            for value in (
                _clean_text(snapshot.get("title")) or row.folder_id,
                _clean_text(snapshot.get("buyer")) or None,
                f"{snapshot['amount']} €" if snapshot.get("amount") else None,
                f"Cierre {snapshot['deadline']}" if snapshot.get("deadline") else None,
                _clean_text(snapshot.get("canonical_status")) or None,
            )
            if value
        )

    for row in new_rows:
        parts.append(f"Nuevo (vigilancia guardada): {detail(row)}")
    for row, fields in changed_rows:
        label = ", ".join(fields) or "contenido"
        parts.append(f"Cambió ({label}): {detail(row)}")
    return " · ".join(parts)[:1000]


def scan_procurement_search_watch(
    session: Session,
    watch_id: uuid.UUID,
    *,
    job_id: uuid.UUID,
    runner: TenderSearchRunner = run_tender_search,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically persist one scan; replays see the same hashes and stay silent."""

    current = now or datetime.now(UTC)
    watch = _get_watch(session, watch_id, for_update=True)
    if not watch.enabled:
        return {"status": "disabled", "new": 0, "changed": 0, "seen": 0}
    watch.last_attempt_at = current
    try:
        remote_items = _collect_tenders(watch, runner)
    except ProcurementSearchWatchScanError as error:
        watch.last_error_code = error.code
        watch.last_error_message = str(error)[:500]
        session.commit()
        raise
    existing = {
        row.folder_id: row
        for row in session.scalars(
            select(ProcurementSearchWatchItem)
            .where(
                ProcurementSearchWatchItem.tenant_id == watch.tenant_id,
                ProcurementSearchWatchItem.watch_id == watch.id,
            )
            .with_for_update()
        )
    }
    new_rows: list[ProcurementSearchWatchItem] = []
    changed_rows: list[tuple[ProcurementSearchWatchItem, list[str]]] = []
    unchanged = 0
    for remote in remote_items:
        folder_id = _clean_text(remote.get("folder_id"))
        snapshot = material_tender_snapshot(remote)
        digest = material_tender_hash(snapshot)
        row = existing.get(folder_id)
        if row is None:
            row = ProcurementSearchWatchItem(
                tenant_id=watch.tenant_id,
                watch_id=watch.id,
                folder_id=folder_id,
                content_hash=digest,
                snapshot=snapshot,
                first_seen_at=current,
                last_seen_at=current,
                last_changed_at=current,
                last_change_fields=["new"],
            )
            session.add(row)
            new_rows.append(row)
            continue
        row.last_seen_at = current
        if row.content_hash == digest:
            unchanged += 1
            continue
        fields = material_change_fields(row.snapshot, snapshot)
        row.content_hash = digest
        row.snapshot = snapshot
        row.last_changed_at = current
        row.last_change_fields = fields
        row.reviewed_at = None
        row.reviewed_by_user_id = None
        changed_rows.append((row, fields))
    watch.last_success_at = current
    watch.last_error_code = watch.last_error_message = None
    created = None
    if (new_rows or changed_rows) and watch.notifications_enabled and watch.notification_user_id:
        total = len(new_rows) + len(changed_rows)
        created = create_notification(
            user_id=watch.notification_user_id,
            notification_type=WATCH_NOTIFICATION_TYPE,
            severity="info",
            title=f"{total} licitaciones nuevas o cambiadas en {watch.name}",
            body=_notification_body(new_rows, changed_rows),
            dedupe_key=f"procurement-watch:{watch.id}:{job_id}",
            link="/app/procurement",
            resource_type="procurement_search_watch",
            resource_id=watch.id,
        )
    session.commit()
    if created is not None:
        publish_notification_job(created)
    return {
        "status": "succeeded",
        "new": len(new_rows),
        "changed": len(changed_rows),
        "seen": unchanged,
        "notified": created is not None,
        "result_count": len(remote_items),
    }


def purge_retired_procurement_search_watch_memory(
    session: Session, *, now: datetime | None = None
) -> int:
    """Delete seen memory only for explicitly retired watches after 90 days."""

    tenant_id = require_tenant_id()
    threshold = (now or datetime.now(UTC)) - timedelta(days=WATCH_RETENTION_DAYS)
    result = session.execute(
        delete(ProcurementSearchWatchItem).where(
            ProcurementSearchWatchItem.tenant_id == tenant_id,
            ProcurementSearchWatchItem.watch_id.in_(
                select(ProcurementSearchWatch.id).where(
                    ProcurementSearchWatch.tenant_id == tenant_id,
                    ProcurementSearchWatch.deleted_at.is_not(None),
                    ProcurementSearchWatch.deleted_at <= threshold,
                )
            ),
        )
    )
    session.commit()
    return int(cast(Any, result).rowcount or 0)


def retire_procurement_search_watch_for_tender_search(
    session: Session,
    *,
    tender_search_id: str,
    request_id: str | None = None,
) -> bool:
    """Stop a deleted Signal search without prematurely deleting its seen memory."""

    tenant_id = require_tenant_id()
    watch = session.scalar(
        select(ProcurementSearchWatch)
        .where(
            ProcurementSearchWatch.tenant_id == tenant_id,
            ProcurementSearchWatch.tender_search_id == tender_search_id,
            ProcurementSearchWatch.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if watch is None:
        return False
    watch.enabled = False
    watch.notifications_enabled = False
    watch.notification_user_id = None
    watch.deleted_at = datetime.now(UTC)
    schedule = session.scalar(
        select(JobSchedule)
        .where(
            JobSchedule.tenant_id == tenant_id,
            JobSchedule.schedule_key == _watch_schedule_key(watch.id),
        )
        .with_for_update()
    )
    if schedule is not None:
        schedule.enabled = False
    append_audit_event(
        session,
        action="procurement.search_watch.retired",
        resource_type="procurement_search_watch",
        resource_id=watch.id,
        result="success",
        request_id=request_id,
        metadata={"tender_search_id": tender_search_id, "retention_days": WATCH_RETENTION_DAYS},
    )
    session.commit()
    return True


def save_profile_watch(
    session: Session,
    profile: ProcurementSearchProfile,
    *,
    expected_version: int,
    name: str,
    create_search: Callable[..., dict[str, Any]],
    request_id: str | None = None,
) -> tuple[ProcurementSearchProfile, dict[str, Any]]:
    """Create one active-only Signal search and its initially inactive Oracle watch."""

    if profile.version != expected_version:
        raise ProcurementSearchProfileVersionConflict("El perfil cambió desde la última lectura.")
    if profile.tender_search_id:
        raise ProcurementSearchProfileVersionConflict("El perfil ya tiene una vigilancia guardada.")
    clean_name = _clean_text(name)
    if not 2 <= len(clean_name) <= 120:
        raise ProcurementSearchProfileValidationError(
            "El nombre de la vigilancia debe tener entre 2 y 120 caracteres.",
            errors={"name": ["Debe contener entre 2 y 120 caracteres."]},
        )
    payload = saved_search_payload(name=clean_name, plan=profile.accepted_plan)
    created = create_search(payload=payload)
    external_id = created.get("id")
    if not isinstance(external_id, str) or not external_id.strip():
        raise ProcurementSearchProfileValidationError(
            "Signal no devolvió el identificador de la vigilancia creada.",
            errors={
                "saved_search": ["Signal no devolvió el identificador de la vigilancia creada."]
            },
        )
    profile.tender_search_id = external_id.strip()[:120]
    watch = create_watch_for_saved_profile(
        session,
        profile,
        name=clean_name,
        tender_search_id=profile.tender_search_id,
    )
    append_audit_event(
        session,
        action="procurement.search_profile.watch_saved",
        resource_type="procurement_search_profile",
        resource_id=profile.id,
        result="success",
        request_id=request_id,
        metadata={
            "version": profile.version,
            "tender_search_id": profile.tender_search_id,
            "scope": "active",
            "watch_id": str(watch.id),
            "enabled": False,
        },
    )
    session.commit()
    return profile, created


PROCUREMENT_SEARCH_WATCH_MODELS = (ProcurementSearchWatch, ProcurementSearchWatchItem)


__all__ = [
    "PROCUREMENT_SEARCH_WATCH_MODELS",
    "WATCH_CADENCE_SECONDS",
    "WATCH_RETENTION_DAYS",
    "ProcurementSearchWatch",
    "ProcurementSearchWatchConflict",
    "ProcurementSearchWatchItem",
    "ProcurementSearchWatchNotFound",
    "ProcurementSearchWatchScanError",
    "configure_procurement_search_watch",
    "get_watch_for_profile",
    "list_procurement_search_watch_items",
    "list_procurement_search_watches",
    "mark_feedback_folder_seen",
    "mark_watch_items_reviewed",
    "material_change_fields",
    "material_tender_hash",
    "material_tender_snapshot",
    "purge_retired_procurement_search_watch_memory",
    "save_profile_watch",
    "scan_procurement_search_watch",
    "serialize_procurement_search_watch",
]
