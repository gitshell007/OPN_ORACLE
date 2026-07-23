"""Deterministic, tenant-scoped feedback memory for procurement search results."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.comparable_procurement import (
    TITLE_TERM_METHOD_VERSION,
    title_terms,
)
from opn_oracle.oracle.cpv_taxonomy import (
    load_cpv_taxonomy,
    normalize_cpv_code,
)
from opn_oracle.oracle.models import TenantDomainMixin
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfile,
    get_procurement_search_profile,
)
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

PROCUREMENT_SEARCH_FEEDBACK_DIGEST_SCHEMA = "procurement-search-feedback-digest-v1"
FEEDBACK_REASONS = ("wrong_sector", "amount", "region", "buyer", "other")
FEEDBACK_VERDICTS = ("relevant", "not_relevant")
FEEDBACK_CANDIDATE_LIMIT = 30


class ProcurementSearchFeedback(TenantDomainMixin, Base):
    """One immutable verdict revision; only the non-superseded row is current."""

    __tablename__ = "procurement_search_feedback"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_procurement_search_feedback_id_tenant"),
        ForeignKeyConstraint(
            ("profile_id", "tenant_id"),
            ("procurement_search_profiles.id", "procurement_search_profiles.tenant_id"),
            name="fk_procurement_search_feedback_profile_tenant",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "actor_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_procurement_search_feedback_actor_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "char_length(folder_id) BETWEEN 1 AND 240",
            name="procurement_search_feedback_folder",
        ),
        CheckConstraint(
            "plan_version >= 1",
            name="procurement_search_feedback_plan_version",
        ),
        CheckConstraint(
            "verdict IN ('relevant','not_relevant')",
            name="procurement_search_feedback_verdict",
        ),
        CheckConstraint(
            "(verdict='relevant' AND reason IS NULL) OR "
            "(verdict='not_relevant' AND reason IN "
            "('wrong_sector','amount','region','buyer','other'))",
            name="procurement_search_feedback_reason",
        ),
        CheckConstraint(
            "char_length(note) <= 2000",
            name="procurement_search_feedback_note",
        ),
        CheckConstraint(
            "char_length(tender_title) <= 2000",
            name="procurement_search_feedback_title",
        ),
        CheckConstraint(
            "jsonb_typeof(tender_cpvs)='array'",
            name="procurement_search_feedback_cpvs",
        ),
        Index(
            "uq_procurement_search_feedback_current",
            "tenant_id",
            "profile_id",
            "actor_user_id",
            "folder_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL AND withdrawn_at IS NULL"),
        ),
        Index(
            "ix_procurement_search_feedback_profile_updated",
            "tenant_id",
            "profile_id",
            "updated_at",
            "id",
        ),
        Index(
            "ix_procurement_search_feedback_digest",
            "tenant_id",
            "profile_id",
            "plan_version",
            "verdict",
            "reason",
            postgresql_where=text("superseded_at IS NULL AND withdrawn_at IS NULL"),
        ),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    folder_id: Mapped[str] = mapped_column(String(240), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tender_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tender_cpvs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProcurementSearchFeedbackValidationError(ValueError):
    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.errors = {path: [message]}


class ProcurementSearchFeedbackNotFound(LookupError):
    pass


class ProcurementSearchFeedbackConflict(RuntimeError):
    pass


def _bounded_text(
    value: Any,
    *,
    path: str,
    maximum: int,
    required: bool = False,
    collapse_whitespace: bool = False,
) -> str:
    clean = str(value or "").strip()
    if collapse_whitespace:
        clean = " ".join(clean.split())
    if required and not clean:
        raise ProcurementSearchFeedbackValidationError(
            "Este campo es obligatorio.",
            path=path,
        )
    if len(clean) > maximum:
        raise ProcurementSearchFeedbackValidationError(
            f"Admite como máximo {maximum} caracteres.",
            path=path,
        )
    return clean


def _plan_version(value: Any, *, profile: ProcurementSearchProfile) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ProcurementSearchFeedbackValidationError(
            "Debe ser un entero positivo.",
            path="plan_version",
        )
    if value > profile.version:
        raise ProcurementSearchFeedbackValidationError(
            "No puede ser posterior a la versión aceptada del perfil.",
            path="plan_version",
        )
    return value


def _verdict_and_reason(payload: Mapping[str, Any]) -> tuple[str, str | None]:
    verdict = str(payload.get("verdict") or "").strip()
    if verdict not in FEEDBACK_VERDICTS:
        raise ProcurementSearchFeedbackValidationError(
            "Usa relevant o not_relevant.",
            path="verdict",
        )
    raw_reason = payload.get("reason")
    reason = str(raw_reason).strip() if raw_reason not in (None, "") else None
    if verdict == "relevant" and reason is not None:
        raise ProcurementSearchFeedbackValidationError(
            "Una licitación relevante no lleva motivo de descarte.",
            path="reason",
        )
    if verdict == "not_relevant" and reason not in FEEDBACK_REASONS:
        raise ProcurementSearchFeedbackValidationError(
            "Selecciona un motivo de descarte válido.",
            path="reason",
        )
    return verdict, reason


def _tender_snapshot(payload: Mapping[str, Any]) -> tuple[str, list[str]]:
    raw_snapshot = payload.get("tender")
    if not isinstance(raw_snapshot, Mapping):
        raise ProcurementSearchFeedbackValidationError(
            "Incluye el snapshot de título y CPV mostrado al usuario.",
            path="tender",
        )
    title = _bounded_text(
        raw_snapshot.get("title"),
        path="tender.title",
        maximum=2000,
        collapse_whitespace=True,
    )
    raw_cpvs = raw_snapshot.get("cpvs", [])
    if not isinstance(raw_cpvs, list) or len(raw_cpvs) > 20:
        raise ProcurementSearchFeedbackValidationError(
            "Debe ser una lista de hasta 20 códigos.",
            path="tender.cpvs",
        )
    taxonomy = load_cpv_taxonomy()
    cpvs: list[str] = []
    for index, raw_cpv in enumerate(raw_cpvs):
        code = normalize_cpv_code(raw_cpv)
        if code is None or code not in taxonomy.codes:
            raise ProcurementSearchFeedbackValidationError(
                "No es un código CPV de la taxonomía local.",
                path=f"tender.cpvs.{index}",
            )
        if code not in cpvs:
            cpvs.append(code)
    cpvs.sort()
    return title, cpvs


def _same_feedback(
    feedback: ProcurementSearchFeedback,
    *,
    plan_version: int,
    verdict: str,
    reason: str | None,
    note: str,
    tender_title: str,
    tender_cpvs: Sequence[str],
) -> bool:
    return (
        feedback.plan_version == plan_version
        and feedback.verdict == verdict
        and feedback.reason == reason
        and feedback.note == note
        and feedback.tender_title == tender_title
        and list(feedback.tender_cpvs) == list(tender_cpvs)
    )


def register_procurement_search_feedback(
    session: Session,
    profile_id: uuid.UUID,
    payload: Mapping[str, Any],
    *,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> tuple[ProcurementSearchFeedback, bool]:
    """Store one current verdict without calling Signal or an AI provider."""

    profile = get_procurement_search_profile(session, profile_id, for_update=True)
    tenant_id = require_tenant_id()
    folder_id = _bounded_text(
        payload.get("folder_id"),
        path="folder_id",
        maximum=240,
        required=True,
    )
    plan_version = _plan_version(payload.get("plan_version"), profile=profile)
    verdict, reason = _verdict_and_reason(payload)
    note = _bounded_text(payload.get("note"), path="note", maximum=2000)
    tender_title, tender_cpvs = _tender_snapshot(payload)
    current = session.scalar(
        select(ProcurementSearchFeedback).where(
            ProcurementSearchFeedback.tenant_id == tenant_id,
            ProcurementSearchFeedback.profile_id == profile.id,
            ProcurementSearchFeedback.actor_user_id == actor_id,
            ProcurementSearchFeedback.folder_id == folder_id,
            ProcurementSearchFeedback.superseded_at.is_(None),
            ProcurementSearchFeedback.withdrawn_at.is_(None),
        )
    )
    if current is not None and _same_feedback(
        current,
        plan_version=plan_version,
        verdict=verdict,
        reason=reason,
        note=note,
        tender_title=tender_title,
        tender_cpvs=tender_cpvs,
    ):
        return current, False

    now = datetime.now(UTC)
    if current is not None:
        current.superseded_at = now
        session.flush()
    feedback = ProcurementSearchFeedback(
        tenant_id=tenant_id,
        profile_id=profile.id,
        plan_version=plan_version,
        folder_id=folder_id,
        verdict=verdict,
        reason=reason,
        note=note,
        actor_user_id=actor_id,
        tender_title=tender_title,
        tender_cpvs=tender_cpvs,
    )
    session.add(feedback)
    session.flush()
    # El feedback es una acción humana explícita sobre el resultado: si la
    # vigilancia ya lo conoce, deja de contar como novedad sin esperar al
    # siguiente barrido. No crea filas ni llama a Signal/IA si aún no existe
    # memoria de vistos para este perfil.
    from opn_oracle.oracle.procurement_search_watch import mark_feedback_folder_seen

    mark_feedback_folder_seen(session, profile.id, folder_id, actor_id=actor_id)
    append_audit_event(
        session,
        action="procurement.search_feedback.register",
        resource_type="procurement_search_feedback",
        resource_id=feedback.id,
        result="success",
        request_id=request_id,
        metadata={
            "profile_id": str(profile.id),
            "plan_version": plan_version,
            "folder_id": folder_id,
            "verdict": verdict,
            "reason": reason,
            "supersedes_id": str(current.id) if current is not None else None,
        },
    )
    session.commit()
    return feedback, True


def withdraw_procurement_search_feedback(
    session: Session,
    profile_id: uuid.UUID,
    feedback_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> None:
    """Withdraw the caller's feedback; repeated withdrawal is a no-op."""

    profile = get_procurement_search_profile(session, profile_id, for_update=True)
    tenant_id = require_tenant_id()
    feedback = session.scalar(
        select(ProcurementSearchFeedback).where(
            ProcurementSearchFeedback.id == feedback_id,
            ProcurementSearchFeedback.tenant_id == tenant_id,
            ProcurementSearchFeedback.profile_id == profile.id,
            ProcurementSearchFeedback.actor_user_id == actor_id,
        )
    )
    if feedback is None:
        raise ProcurementSearchFeedbackNotFound("Feedback no encontrado.")
    if feedback.superseded_at is not None:
        raise ProcurementSearchFeedbackConflict(
            "Ese feedback ya fue sustituido por un veredicto posterior."
        )
    if feedback.withdrawn_at is not None:
        return
    feedback.withdrawn_at = datetime.now(UTC)
    append_audit_event(
        session,
        action="procurement.search_feedback.withdraw",
        resource_type="procurement_search_feedback",
        resource_id=feedback.id,
        result="success",
        request_id=request_id,
        metadata={
            "profile_id": str(profile.id),
            "plan_version": feedback.plan_version,
            "folder_id": feedback.folder_id,
        },
    )
    session.commit()


def list_procurement_search_feedback(
    session: Session,
    profile_id: uuid.UUID,
    *,
    include_history: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ProcurementSearchFeedback], int]:
    profile = get_procurement_search_profile(session, profile_id)
    tenant_id = require_tenant_id()
    criteria = [
        ProcurementSearchFeedback.tenant_id == tenant_id,
        ProcurementSearchFeedback.profile_id == profile.id,
    ]
    if not include_history:
        criteria.extend(
            [
                ProcurementSearchFeedback.superseded_at.is_(None),
                ProcurementSearchFeedback.withdrawn_at.is_(None),
            ]
        )
    total = int(
        session.scalar(select(func.count(ProcurementSearchFeedback.id)).where(*criteria)) or 0
    )
    rows = list(
        session.scalars(
            select(ProcurementSearchFeedback)
            .where(*criteria)
            .order_by(
                ProcurementSearchFeedback.updated_at.desc(),
                ProcurementSearchFeedback.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def serialize_procurement_search_feedback(
    feedback: ProcurementSearchFeedback,
) -> dict[str, Any]:
    state = (
        "withdrawn"
        if feedback.withdrawn_at is not None
        else "superseded"
        if feedback.superseded_at is not None
        else "current"
    )
    return {
        "id": str(feedback.id),
        "profile_id": str(feedback.profile_id),
        "plan_version": feedback.plan_version,
        "folder_id": feedback.folder_id,
        "verdict": feedback.verdict,
        "reason": feedback.reason,
        "note": feedback.note or None,
        "user_id": str(feedback.actor_user_id),
        "tender": {
            "title": feedback.tender_title,
            "cpvs": list(feedback.tender_cpvs),
        },
        "state": state,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat(),
    }


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_rows(
    rejected: Counter[str],
    relevant: Counter[str],
    *,
    reinforce: bool,
) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for value in sorted(set(rejected) | set(relevant)):
        rejected_count = rejected[value]
        relevant_count = relevant[value]
        delta = rejected_count - relevant_count
        if (reinforce and delta >= 0) or (not reinforce and delta <= 0):
            continue
        rows.append(
            {
                "value": value,
                "count": relevant_count if reinforce else rejected_count,
                "relevant_count": relevant_count,
                "rejected_count": rejected_count,
                "delta": delta,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -abs(int(row["delta"])),
            -int(row["count"]),
            str(row["value"]),
        ),
    )[:FEEDBACK_CANDIDATE_LIMIT]


def _active_feedback(
    rows: Sequence[ProcurementSearchFeedback],
) -> list[ProcurementSearchFeedback]:
    return [row for row in rows if row.superseded_at is None and row.withdrawn_at is None]


def procurement_search_feedback_digest_payload(
    profile: ProcurementSearchProfile,
    rows: Sequence[ProcurementSearchFeedback],
) -> dict[str, Any]:
    """Build the same digest for the same active feedback, independent of row order."""

    active = _active_feedback(rows)
    taxonomy = load_cpv_taxonomy()
    state = sorted(
        (
            {
                "plan_version": row.plan_version,
                "folder_id": row.folder_id,
                "user_id": str(row.actor_user_id),
                "verdict": row.verdict,
                "reason": row.reason,
                "note": row.note,
                "title": row.tender_title,
                "cpvs": sorted(set(str(code) for code in row.tender_cpvs)),
            }
            for row in active
        ),
        key=lambda item: (
            item["folder_id"],
            item["user_id"],
            item["plan_version"],
            item["verdict"],
            item["reason"] or "",
            item["note"],
            item["title"],
            item["cpvs"],
        ),
    )
    feedback_state_hash = _canonical_hash(state)
    verdict_counts = Counter(row.verdict for row in active)
    reason_counts = Counter(row.reason for row in active if row.reason is not None)
    rejected_terms: Counter[str] = Counter()
    relevant_terms: Counter[str] = Counter()
    rejected_cpvs: Counter[str] = Counter()
    relevant_cpvs: Counter[str] = Counter()
    for row in active:
        term_counter = relevant_terms if row.verdict == "relevant" else rejected_terms
        cpv_counter = relevant_cpvs if row.verdict == "relevant" else rejected_cpvs
        term_counter.update(title_terms(row.tender_title))
        cpv_counter.update(set(str(code) for code in row.tender_cpvs))

    excluded_terms = _candidate_rows(
        rejected_terms,
        relevant_terms,
        reinforce=False,
    )
    reinforced_terms = _candidate_rows(
        rejected_terms,
        relevant_terms,
        reinforce=True,
    )

    def cpv_rows(
        rejected: Counter[str],
        relevant: Counter[str],
        *,
        reinforce: bool,
    ) -> list[dict[str, Any]]:
        return [
            {
                "code": row["value"],
                "label": taxonomy.codes.get(str(row["value"])),
                **{key: value for key, value in row.items() if key != "value"},
            }
            for row in _candidate_rows(
                rejected,
                relevant,
                reinforce=reinforce,
            )
        ]

    digest_material = {
        "schema": PROCUREMENT_SEARCH_FEEDBACK_DIGEST_SCHEMA,
        "profile_id": str(profile.id),
        "feedback_state_hash": feedback_state_hash,
        "tokenizer_version": TITLE_TERM_METHOD_VERSION,
        "taxonomy_version": taxonomy.version,
        "counts": {
            "total": len(active),
            "distinct_folders": len({row.folder_id for row in active}),
            "relevant": verdict_counts["relevant"],
            "not_relevant": verdict_counts["not_relevant"],
        },
        "reasons": {reason: reason_counts[reason] for reason in FEEDBACK_REASONS},
        "exclusion_candidates": {
            "terms": excluded_terms,
            "cpvs": cpv_rows(
                rejected_cpvs,
                relevant_cpvs,
                reinforce=False,
            ),
        },
        "reinforcement_candidates": {
            "terms": reinforced_terms,
            "cpvs": cpv_rows(
                rejected_cpvs,
                relevant_cpvs,
                reinforce=True,
            ),
        },
    }
    return {
        **digest_material,
        "plan_version": profile.version,
        "new_feedback_count": sum(row.plan_version == profile.version for row in active),
        "digest_hash": _canonical_hash(digest_material),
    }


def build_procurement_search_feedback_digest(
    session: Session,
    profile_id: uuid.UUID,
) -> dict[str, Any]:
    profile = get_procurement_search_profile(session, profile_id)
    tenant_id = require_tenant_id()
    rows = list(
        session.scalars(
            select(ProcurementSearchFeedback).where(
                ProcurementSearchFeedback.tenant_id == tenant_id,
                ProcurementSearchFeedback.profile_id == profile.id,
                ProcurementSearchFeedback.superseded_at.is_(None),
                ProcurementSearchFeedback.withdrawn_at.is_(None),
            )
        )
    )
    return procurement_search_feedback_digest_payload(profile, rows)


PROCUREMENT_SEARCH_FEEDBACK_MODELS = (ProcurementSearchFeedback,)


__all__ = [
    "PROCUREMENT_SEARCH_FEEDBACK_DIGEST_SCHEMA",
    "PROCUREMENT_SEARCH_FEEDBACK_MODELS",
    "ProcurementSearchFeedback",
    "ProcurementSearchFeedbackConflict",
    "ProcurementSearchFeedbackNotFound",
    "ProcurementSearchFeedbackValidationError",
    "build_procurement_search_feedback_digest",
    "list_procurement_search_feedback",
    "procurement_search_feedback_digest_payload",
    "register_procurement_search_feedback",
    "serialize_procurement_search_feedback",
    "withdraw_procurement_search_feedback",
]
