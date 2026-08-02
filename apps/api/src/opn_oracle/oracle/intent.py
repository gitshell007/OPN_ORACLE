"""Versioned dossier intent (IntentRevision), requirements and offerings.

Accepting an intent MUST NOT create Signal monitors or other external resources.
Automation remains a separate, explicit user action (ADR-0009 §6).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
from opn_oracle.oracle.models import StrategicDossier, TenantDomainMixin
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

INTENT_SCHEMA_KEYS = frozenset(
    {
        "market",
        "procurement",
        "research",
        "competitive-intelligence",
        "custom",
    }
)
INTENT_STATUSES = frozenset({"draft", "accepted", "superseded", "rejected"})
REQUIREMENT_CLASSES = frozenset(
    {
        "market_scan",
        "competitive_watch",
        "procurement_fit",
        "actor_monitor",
        "research_question",
        "risk_watch",
        "custom",
    }
)
REQUIREMENT_PRIORITIES = frozenset({"low", "medium", "high", "critical"})
REQUIREMENT_STATUSES = frozenset({"active", "paused", "needs_review", "retired"})
ALIGNMENT_STATES = frozenset({"aligned", "needs_review", "overridden"})
OFFERING_STATUSES = frozenset({"active", "retired"})


class IntentValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"intent": [message]})


class IntentNotFound(LookupError):
    pass


class IntentConflict(RuntimeError):
    pass


class DossierIntentRevision(TenantDomainMixin, Base):
    """One versioned proposal or acceptance of strategic intent for a dossier."""

    __tablename__ = "dossier_intent_revisions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_intent_revisions_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "version",
            name="uq_dossier_intent_revisions_version",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_intent_revisions_dossier_tenant",
        ),
        CheckConstraint(
            "status IN ('draft','accepted','superseded','rejected')",
            name="dossier_intent_revision_status",
        ),
        CheckConstraint(
            "schema_key IN ('market','procurement','research','competitive-intelligence','custom')",
            name="dossier_intent_revision_schema_key",
        ),
        CheckConstraint(
            "schema_version ~ '^v[0-9]+$'",
            name="dossier_intent_revision_schema_version",
        ),
        CheckConstraint("version >= 1", name="dossier_intent_revision_version"),
        CheckConstraint("row_version >= 1", name="dossier_intent_revision_row_version"),
        CheckConstraint(
            "char_length(request_text) BETWEEN 1 AND 20000",
            name="dossier_intent_revision_request_text",
        ),
        CheckConstraint(
            "char_length(content_hash)=64 AND content_hash ~ '^[a-f0-9]{64}$'",
            name="dossier_intent_revision_content_hash",
        ),
        CheckConstraint(
            "jsonb_typeof(structured_spec)='object'",
            name="dossier_intent_revision_structured_spec",
        ),
        CheckConstraint(
            "jsonb_typeof(source_refs)='array'",
            name="dossier_intent_revision_source_refs",
        ),
        Index(
            "uq_dossier_intent_revisions_one_accepted",
            "tenant_id",
            "dossier_id",
            unique=True,
            postgresql_where=text("status = 'accepted'"),
        ),
        Index(
            "ix_dossier_intent_revisions_dossier_updated",
            "tenant_id",
            "dossier_id",
            "updated_at",
        ),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_key: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_refs: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    proposed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class IntelligenceRequirement(TenantDomainMixin, Base):
    """A bounded intelligence need derived from or attached to an intent revision."""

    __tablename__ = "intelligence_requirements"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_intelligence_requirements_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_intelligence_requirements_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("intent_revision_id", "tenant_id"),
            ("dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"),
            ondelete="SET NULL",
            name="fk_intelligence_requirements_intent_tenant",
        ),
        CheckConstraint(
            "class IN ("
            "'market_scan','competitive_watch','procurement_fit',"
            "'actor_monitor','research_question','risk_watch','custom'"
            ")",
            name="intelligence_requirement_class",
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','critical')",
            name="intelligence_requirement_priority",
        ),
        CheckConstraint(
            "status IN ('active','paused','needs_review','retired')",
            name="intelligence_requirement_status",
        ),
        CheckConstraint(
            "alignment_state IN ('aligned','needs_review','overridden')",
            name="intelligence_requirement_alignment",
        ),
        CheckConstraint(
            "char_length(question) BETWEEN 1 AND 2000",
            name="intelligence_requirement_question",
        ),
        CheckConstraint(
            "char_length(decision_to_support) <= 2000",
            name="intelligence_requirement_decision",
        ),
        CheckConstraint(
            "jsonb_typeof(scope)='object'",
            name="intelligence_requirement_scope",
        ),
        CheckConstraint(
            "jsonb_typeof(exclusions)='object'",
            name="intelligence_requirement_exclusions",
        ),
        CheckConstraint(
            "jsonb_typeof(success_criteria)='array'",
            name="intelligence_requirement_success_criteria",
        ),
        Index(
            "ix_intelligence_requirements_dossier_status",
            "tenant_id",
            "dossier_id",
            "status",
            "updated_at",
        ),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requirement_class: Mapped[str] = mapped_column("class", String(40), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    decision_to_support: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    exclusions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    success_criteria: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    alignment_state: Mapped[str] = mapped_column(String(20), nullable=False, default="aligned")


class DossierOffering(TenantDomainMixin, Base):
    """Dossier-scoped strategic offering (no tenant global catalog in v1)."""

    __tablename__ = "dossier_offerings"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_offerings_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_offerings_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("intent_revision_id", "tenant_id"),
            ("dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"),
            ondelete="SET NULL",
            name="fk_dossier_offerings_intent_tenant",
        ),
        CheckConstraint(
            "status IN ('active','retired')",
            name="dossier_offering_status",
        ),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 300",
            name="dossier_offering_name",
        ),
        CheckConstraint(
            "char_length(description) <= 5000",
            name="dossier_offering_description",
        ),
        CheckConstraint("jsonb_typeof(aliases)='array'", name="dossier_offering_aliases"),
        CheckConstraint("jsonb_typeof(taxonomies)='object'", name="dossier_offering_taxonomies"),
        Index(
            "ix_dossier_offerings_dossier_status",
            "tenant_id",
            "dossier_id",
            "status",
            "updated_at",
        ),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    taxonomies: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


INTENT_MODELS = (DossierIntentRevision, IntelligenceRequirement, DossierOffering)


def compute_intent_content_hash(
    *,
    schema_key: str,
    schema_version: str,
    request_text: str,
    structured_spec: Mapping[str, Any],
) -> str:
    """SHA-256 of the canonical intent payload (hex, lowercase)."""

    payload = {
        "schema_key": schema_key,
        "schema_version": schema_version,
        "request_text": request_text,
        "structured_spec": structured_spec,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _bounded_request_text(value: Any) -> str:
    text_value = str(value or "").strip()
    if not 1 <= len(text_value) <= 20000:
        raise IntentValidationError(
            "request_text debe contener entre 1 y 20000 caracteres.",
            errors={"request_text": ["Debe contener entre 1 y 20000 caracteres."]},
        )
    return text_value


def _schema_key(value: Any) -> str:
    key = str(value or "").strip()
    if key not in INTENT_SCHEMA_KEYS:
        raise IntentValidationError(
            "schema_key no es válido.",
            errors={
                "schema_key": [
                    "Debe ser market, procurement, research, competitive-intelligence o custom."
                ]
            },
        )
    return key


def _schema_version(value: Any) -> str:
    version = str(value or "").strip()
    if not version or not version.startswith("v") or not version[1:].isdigit():
        raise IntentValidationError(
            "schema_version debe seguir el patrón vN.",
            errors={"schema_version": ["Debe seguir el patrón vN (p. ej. v1)."]},
        )
    return version


def _structured_spec(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise IntentValidationError(
            "structured_spec debe ser un objeto.",
            errors={"structured_spec": ["Debe ser un objeto."]},
        )
    return dict(value)


def _source_refs(value: Any) -> list[dict[str, str]]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise IntentValidationError(
            "source_refs debe ser una lista.",
            errors={"source_refs": ["Debe ser una lista."]},
        )
    if len(value) > 50:
        raise IntentValidationError(
            "source_refs admite como máximo 50 referencias.",
            errors={"source_refs": ["Admite como máximo 50 referencias."]},
        )
    cleaned: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise IntentValidationError(
                "Cada source_ref debe ser un objeto.",
                errors={f"source_refs.{index}": ["Debe ser un objeto."]},
            )
        kind = str(item.get("kind") or "").strip()
        ref = str(item.get("ref") or "").strip()
        if not kind or not ref:
            raise IntentValidationError(
                "Cada source_ref requiere kind y ref.",
                errors={f"source_refs.{index}": ["Requiere kind y ref."]},
            )
        entry: dict[str, str] = {"kind": kind[:120], "ref": ref[:500]}
        label = item.get("label")
        if label not in (None, ""):
            entry["label"] = str(label).strip()[:300]
        cleaned.append(entry)
    return cleaned


def _parse_draft_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema_key = _schema_key(payload.get("schema_key"))
    schema_version = _schema_version(payload.get("schema_version"))
    request_text = _bounded_request_text(payload.get("request_text"))
    structured_spec = _structured_spec(payload.get("structured_spec"))
    source_refs = _source_refs(payload.get("source_refs"))
    content_hash = compute_intent_content_hash(
        schema_key=schema_key,
        schema_version=schema_version,
        request_text=request_text,
        structured_spec=structured_spec,
    )
    return {
        "schema_key": schema_key,
        "schema_version": schema_version,
        "request_text": request_text,
        "structured_spec": structured_spec,
        "source_refs": source_refs,
        "content_hash": content_hash,
    }


def _load_dossier(
    session: Session,
    dossier_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> StrategicDossier:
    tenant_id = require_tenant_id()
    statement = select(StrategicDossier).where(
        StrategicDossier.id == dossier_id,
        StrategicDossier.tenant_id == tenant_id,
        StrategicDossier.status != "archived",
    )
    if for_update:
        statement = statement.with_for_update()
    dossier = session.scalar(statement)
    if dossier is None:
        raise IntentNotFound("Expediente no encontrado.")
    return dossier


def _next_version(session: Session, *, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> int:
    current = session.scalar(
        select(func.coalesce(func.max(DossierIntentRevision.version), 0)).where(
            DossierIntentRevision.tenant_id == tenant_id,
            DossierIntentRevision.dossier_id == dossier_id,
        )
    )
    return int(current or 0) + 1


def get_revision(
    session: Session,
    revision_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> DossierIntentRevision:
    tenant_id = require_tenant_id()
    statement = select(DossierIntentRevision).where(
        DossierIntentRevision.id == revision_id,
        DossierIntentRevision.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    revision = session.scalar(statement)
    if revision is None:
        raise IntentNotFound("Revisión de intención no encontrada.")
    return revision


def get_current_intent(session: Session, dossier_id: uuid.UUID) -> DossierIntentRevision | None:
    tenant_id = require_tenant_id()
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        raise IntentNotFound("Expediente no encontrado.")
    if dossier.current_intent_revision_id is None:
        return None
    return session.scalar(
        select(DossierIntentRevision).where(
            DossierIntentRevision.id == dossier.current_intent_revision_id,
            DossierIntentRevision.tenant_id == tenant_id,
            DossierIntentRevision.dossier_id == dossier_id,
            DossierIntentRevision.status == "accepted",
        )
    )


def list_intent_revisions(
    session: Session,
    dossier_id: uuid.UUID,
    *,
    limit: int = 20,
) -> list[DossierIntentRevision]:
    tenant_id = require_tenant_id()
    size = max(1, min(int(limit), 100))
    return list(
        session.scalars(
            select(DossierIntentRevision)
            .where(
                DossierIntentRevision.tenant_id == tenant_id,
                DossierIntentRevision.dossier_id == dossier_id,
            )
            .order_by(DossierIntentRevision.version.desc(), DossierIntentRevision.id.desc())
            .limit(size)
        )
    )


def create_draft(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    payload: Mapping[str, Any],
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> DossierIntentRevision:
    tenant_id = require_tenant_id()
    dossier = _load_dossier(session, dossier_id, for_update=True)
    fields = _parse_draft_fields(payload)
    revision = DossierIntentRevision(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        version=_next_version(session, tenant_id=tenant_id, dossier_id=dossier.id),
        schema_key=fields["schema_key"],
        schema_version=fields["schema_version"],
        request_text=fields["request_text"],
        structured_spec=fields["structured_spec"],
        status="draft",
        content_hash=fields["content_hash"],
        source_refs=fields["source_refs"],
        proposed_by_user_id=actor_id,
        accepted_by_user_id=None,
        accepted_at=None,
        row_version=1,
    )
    session.add(revision)
    session.flush()
    append_audit_event(
        session,
        action="intent.draft_created",
        resource_type="dossier_intent_revision",
        resource_id=revision.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={
            "version": revision.version,
            "schema_key": revision.schema_key,
            "schema_version": revision.schema_version,
            "content_hash": revision.content_hash,
        },
    )
    session.commit()
    return revision


def update_draft(
    session: Session,
    *,
    revision_id: uuid.UUID,
    payload: Mapping[str, Any],
    expected_row_version: int,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> DossierIntentRevision:
    del actor_id  # reserved for future ACL of proposer-only edits
    revision = get_revision(session, revision_id, for_update=True)
    if revision.status != "draft":
        raise IntentConflict("Solo se pueden editar revisiones en estado draft.")
    if expected_row_version != revision.row_version:
        raise IntentConflict("La revisión cambió desde la última lectura.")
    fields = _parse_draft_fields(
        {
            "schema_key": payload.get("schema_key", revision.schema_key),
            "schema_version": payload.get("schema_version", revision.schema_version),
            "request_text": payload.get("request_text", revision.request_text),
            "structured_spec": payload.get("structured_spec", revision.structured_spec),
            "source_refs": payload.get("source_refs", revision.source_refs),
        }
    )
    revision.schema_key = fields["schema_key"]
    revision.schema_version = fields["schema_version"]
    revision.request_text = fields["request_text"]
    revision.structured_spec = fields["structured_spec"]
    revision.source_refs = fields["source_refs"]
    revision.content_hash = fields["content_hash"]
    revision.row_version += 1
    append_audit_event(
        session,
        action="intent.draft_updated",
        resource_type="dossier_intent_revision",
        resource_id=revision.id,
        dossier_id=revision.dossier_id,
        result="success",
        request_id=request_id,
        metadata={
            "version": revision.version,
            "row_version": revision.row_version,
            "content_hash": revision.content_hash,
        },
    )
    session.commit()
    return revision


def accept_revision(
    session: Session,
    *,
    revision_id: uuid.UUID,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> DossierIntentRevision:
    """Promote a draft to accepted. Does not create monitors or external resources."""

    revision = get_revision(session, revision_id, for_update=True)
    if revision.status != "draft":
        raise IntentConflict("Solo se pueden aceptar revisiones en estado draft.")
    dossier = _load_dossier(session, revision.dossier_id, for_update=True)
    previous = session.scalar(
        select(DossierIntentRevision)
        .where(
            DossierIntentRevision.tenant_id == revision.tenant_id,
            DossierIntentRevision.dossier_id == revision.dossier_id,
            DossierIntentRevision.status == "accepted",
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    previous_id: uuid.UUID | None = None
    if previous is not None and previous.id != revision.id:
        previous.status = "superseded"
        previous_id = previous.id
        append_audit_event(
            session,
            action="intent.superseded",
            resource_type="dossier_intent_revision",
            resource_id=previous.id,
            dossier_id=dossier.id,
            result="success",
            request_id=request_id,
            metadata={
                "version": previous.version,
                "superseded_by": str(revision.id),
            },
        )
    revision.status = "accepted"
    revision.accepted_by_user_id = actor_id
    revision.accepted_at = now
    dossier.current_intent_revision_id = revision.id
    # MDEV-07: mark prior surveillance actions needs_review; never reconfigure/reactivate.
    needs_review_count = 0
    if previous_id is not None:
        from opn_oracle.oracle.surveillance import (
            mark_actions_needs_review_for_superseded_intent,
        )

        needs_review_count = mark_actions_needs_review_for_superseded_intent(
            session,
            dossier_id=dossier.id,
            previous_revision_id=previous_id,
            new_revision_id=revision.id,
        )
    append_audit_event(
        session,
        action="intent.accepted",
        resource_type="dossier_intent_revision",
        resource_id=revision.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={
            "version": revision.version,
            "schema_key": revision.schema_key,
            "content_hash": revision.content_hash,
            "previous_revision_id": str(previous.id) if previous is not None else None,
            "monitors_created": False,
            "surveillance_needs_review_count": needs_review_count,
        },
    )
    session.commit()
    return revision


def reject_revision(
    session: Session,
    *,
    revision_id: uuid.UUID,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> DossierIntentRevision:
    del actor_id
    revision = get_revision(session, revision_id, for_update=True)
    if revision.status != "draft":
        raise IntentConflict("Solo se pueden rechazar revisiones en estado draft.")
    revision.status = "rejected"
    append_audit_event(
        session,
        action="intent.rejected",
        resource_type="dossier_intent_revision",
        resource_id=revision.id,
        dossier_id=revision.dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": revision.version},
    )
    session.commit()
    return revision


def _bounded_question(value: Any) -> str:
    question = " ".join(str(value or "").strip().split())
    if not 1 <= len(question) <= 2000:
        raise IntentValidationError(
            "question debe contener entre 1 y 2000 caracteres.",
            errors={"question": ["Debe contener entre 1 y 2000 caracteres."]},
        )
    return question


def create_requirement(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    payload: Mapping[str, Any],
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> IntelligenceRequirement:
    del actor_id
    tenant_id = require_tenant_id()
    dossier = _load_dossier(session, dossier_id)
    requirement_class = str(payload.get("class") or "").strip()
    if requirement_class not in REQUIREMENT_CLASSES:
        raise IntentValidationError(
            "class de requisito no es válido.",
            errors={"class": ["Clase de requisito no válida."]},
        )
    priority = str(payload.get("priority") or "medium").strip()
    if priority not in REQUIREMENT_PRIORITIES:
        raise IntentValidationError(
            "priority no es válido.",
            errors={"priority": ["Debe ser low, medium, high o critical."]},
        )
    status = str(payload.get("status") or "active").strip()
    if status not in REQUIREMENT_STATUSES:
        raise IntentValidationError(
            "status no es válido.",
            errors={"status": ["Debe ser active, paused, needs_review o retired."]},
        )
    alignment = str(payload.get("alignment_state") or "aligned").strip()
    if alignment not in ALIGNMENT_STATES:
        raise IntentValidationError(
            "alignment_state no es válido.",
            errors={"alignment_state": ["Debe ser aligned, needs_review u overridden."]},
        )
    decision = str(payload.get("decision_to_support") or "").strip()
    if len(decision) > 2000:
        raise IntentValidationError(
            "decision_to_support admite como máximo 2000 caracteres.",
            errors={"decision_to_support": ["Admite como máximo 2000 caracteres."]},
        )
    scope = payload.get("scope") or {}
    exclusions = payload.get("exclusions") or {}
    if not isinstance(scope, Mapping) or not isinstance(exclusions, Mapping):
        raise IntentValidationError(
            "scope y exclusions deben ser objetos.",
            errors={"scope": ["Debe ser un objeto."]},
        )
    criteria_raw = payload.get("success_criteria") or []
    if not isinstance(criteria_raw, list) or len(criteria_raw) > 20:
        raise IntentValidationError(
            "success_criteria debe ser una lista de hasta 20 elementos.",
            errors={"success_criteria": ["Lista de hasta 20 cadenas."]},
        )
    criteria = [str(item).strip()[:500] for item in criteria_raw if str(item).strip()]
    intent_revision_id: uuid.UUID | None = None
    raw_intent = payload.get("intent_revision_id")
    if raw_intent not in (None, ""):
        try:
            intent_revision_id = uuid.UUID(str(raw_intent))
        except (TypeError, ValueError) as error:
            raise IntentValidationError(
                "intent_revision_id debe ser UUID.",
                errors={"intent_revision_id": ["Debe ser un UUID."]},
            ) from error
        get_revision(session, intent_revision_id)
    elif dossier.current_intent_revision_id is not None:
        intent_revision_id = dossier.current_intent_revision_id
    requirement = IntelligenceRequirement(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        intent_revision_id=intent_revision_id,
        requirement_class=requirement_class,
        priority=priority,
        question=_bounded_question(payload.get("question")),
        decision_to_support=decision,
        scope=dict(scope),
        exclusions=dict(exclusions),
        success_criteria=criteria,
        status=status,
        alignment_state=alignment,
    )
    session.add(requirement)
    session.flush()
    append_audit_event(
        session,
        action="requirement.created",
        resource_type="intelligence_requirement",
        resource_id=requirement.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={"class": requirement.requirement_class, "priority": requirement.priority},
    )
    session.commit()
    return requirement


def list_requirements(
    session: Session,
    dossier_id: uuid.UUID,
) -> list[IntelligenceRequirement]:
    tenant_id = require_tenant_id()
    return list(
        session.scalars(
            select(IntelligenceRequirement)
            .where(
                IntelligenceRequirement.tenant_id == tenant_id,
                IntelligenceRequirement.dossier_id == dossier_id,
            )
            .order_by(
                IntelligenceRequirement.updated_at.desc(),
                IntelligenceRequirement.id.desc(),
            )
        )
    )


def create_offering(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    payload: Mapping[str, Any],
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> DossierOffering:
    del actor_id
    tenant_id = require_tenant_id()
    dossier = _load_dossier(session, dossier_id)
    name = " ".join(str(payload.get("name") or "").strip().split())
    if not 1 <= len(name) <= 300:
        raise IntentValidationError(
            "name debe contener entre 1 y 300 caracteres.",
            errors={"name": ["Debe contener entre 1 y 300 caracteres."]},
        )
    description = str(payload.get("description") or "").strip()
    if len(description) > 5000:
        raise IntentValidationError(
            "description admite como máximo 5000 caracteres.",
            errors={"description": ["Admite como máximo 5000 caracteres."]},
        )
    aliases_raw = payload.get("aliases") or []
    if not isinstance(aliases_raw, list):
        raise IntentValidationError(
            "aliases debe ser una lista.",
            errors={"aliases": ["Debe ser una lista."]},
        )
    aliases = [str(item).strip()[:200] for item in aliases_raw if str(item).strip()][:50]
    taxonomies = payload.get("taxonomies") or {}
    if not isinstance(taxonomies, Mapping):
        raise IntentValidationError(
            "taxonomies debe ser un objeto.",
            errors={"taxonomies": ["Debe ser un objeto."]},
        )
    status = str(payload.get("status") or "active").strip()
    if status not in OFFERING_STATUSES:
        raise IntentValidationError(
            "status no es válido.",
            errors={"status": ["Debe ser active o retired."]},
        )
    intent_revision_id: uuid.UUID | None = None
    raw_intent = payload.get("intent_revision_id")
    if raw_intent not in (None, ""):
        try:
            intent_revision_id = uuid.UUID(str(raw_intent))
        except (TypeError, ValueError) as error:
            raise IntentValidationError(
                "intent_revision_id debe ser UUID.",
                errors={"intent_revision_id": ["Debe ser un UUID."]},
            ) from error
        get_revision(session, intent_revision_id)
    elif dossier.current_intent_revision_id is not None:
        intent_revision_id = dossier.current_intent_revision_id
    offering = DossierOffering(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        intent_revision_id=intent_revision_id,
        name=name,
        aliases=aliases,
        taxonomies=dict(taxonomies),
        description=description,
        status=status,
    )
    session.add(offering)
    session.flush()
    append_audit_event(
        session,
        action="offering.created",
        resource_type="dossier_offering",
        resource_id=offering.id,
        dossier_id=dossier.id,
        result="success",
        request_id=request_id,
        metadata={"name": offering.name, "status": offering.status},
    )
    session.commit()
    return offering


def list_offerings(session: Session, dossier_id: uuid.UUID) -> list[DossierOffering]:
    tenant_id = require_tenant_id()
    return list(
        session.scalars(
            select(DossierOffering)
            .where(
                DossierOffering.tenant_id == tenant_id,
                DossierOffering.dossier_id == dossier_id,
            )
            .order_by(DossierOffering.updated_at.desc(), DossierOffering.id.desc())
        )
    )


def serialize_intent_revision(revision: DossierIntentRevision) -> dict[str, Any]:
    return {
        "id": str(revision.id),
        "tenant_id": str(revision.tenant_id),
        "dossier_id": str(revision.dossier_id),
        "version": revision.version,
        "schema_key": revision.schema_key,
        "schema_version": revision.schema_version,
        "request_text": revision.request_text,
        "structured_spec": dict(revision.structured_spec or {}),
        "status": revision.status,
        "content_hash": revision.content_hash,
        "source_refs": list(revision.source_refs or []),
        "proposed_by_user_id": (
            str(revision.proposed_by_user_id) if revision.proposed_by_user_id else None
        ),
        "accepted_by_user_id": (
            str(revision.accepted_by_user_id) if revision.accepted_by_user_id else None
        ),
        "accepted_at": revision.accepted_at.isoformat() if revision.accepted_at else None,
        "row_version": revision.row_version,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "updated_at": revision.updated_at.isoformat() if revision.updated_at else None,
    }


def serialize_requirement(requirement: IntelligenceRequirement) -> dict[str, Any]:
    return {
        "id": str(requirement.id),
        "tenant_id": str(requirement.tenant_id),
        "dossier_id": str(requirement.dossier_id),
        "intent_revision_id": (
            str(requirement.intent_revision_id) if requirement.intent_revision_id else None
        ),
        "class": requirement.requirement_class,
        "priority": requirement.priority,
        "question": requirement.question,
        "decision_to_support": requirement.decision_to_support,
        "scope": dict(requirement.scope or {}),
        "exclusions": dict(requirement.exclusions or {}),
        "success_criteria": list(requirement.success_criteria or []),
        "status": requirement.status,
        "alignment_state": requirement.alignment_state,
        "created_at": requirement.created_at.isoformat() if requirement.created_at else None,
        "updated_at": requirement.updated_at.isoformat() if requirement.updated_at else None,
    }


def serialize_offering(offering: DossierOffering) -> dict[str, Any]:
    return {
        "id": str(offering.id),
        "tenant_id": str(offering.tenant_id),
        "dossier_id": str(offering.dossier_id),
        "intent_revision_id": (
            str(offering.intent_revision_id) if offering.intent_revision_id else None
        ),
        "name": offering.name,
        "aliases": list(offering.aliases or []),
        "taxonomies": dict(offering.taxonomies or {}),
        "description": offering.description,
        "status": offering.status,
        "created_at": offering.created_at.isoformat() if offering.created_at else None,
        "updated_at": offering.updated_at.isoformat() if offering.updated_at else None,
    }


def intent_overview(
    session: Session,
    dossier_id: uuid.UUID,
    *,
    history_limit: int = 10,
) -> dict[str, Any]:
    current = get_current_intent(session, dossier_id)
    history = list_intent_revisions(session, dossier_id, limit=history_limit)
    return {
        "current": serialize_intent_revision(current) if current is not None else None,
        "revisions": [serialize_intent_revision(item) for item in history],
    }


__all__ = [
    "ALIGNMENT_STATES",
    "INTENT_MODELS",
    "INTENT_SCHEMA_KEYS",
    "OFFERING_STATUSES",
    "REQUIREMENT_CLASSES",
    "REQUIREMENT_PRIORITIES",
    "REQUIREMENT_STATUSES",
    "DossierIntentRevision",
    "DossierOffering",
    "IntelligenceRequirement",
    "IntentConflict",
    "IntentNotFound",
    "IntentValidationError",
    "accept_revision",
    "compute_intent_content_hash",
    "create_draft",
    "create_offering",
    "create_requirement",
    "get_current_intent",
    "get_revision",
    "intent_overview",
    "list_intent_revisions",
    "list_offerings",
    "list_requirements",
    "reject_revision",
    "serialize_intent_revision",
    "serialize_offering",
    "serialize_requirement",
    "update_draft",
]
