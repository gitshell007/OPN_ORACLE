"""Durable «Preguntar a Oracle» conversations (MEMSOL-06).

State machines (ADR-0009 §10):
  Conversation: open | archived
  Message: queued → running → succeeded | failed | cancelled

The user question is persisted before any BackgroundJob row is staged.
Accepting/enqueueing a message MUST NOT mutate IntentRevision or promote
memory facts (answers are read-side artifacts only).
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
from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import StrategicDossier, TenantDomainMixin
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

CONVERSATION_STATUSES = frozenset({"open", "archived"})
MESSAGE_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "cancelled"})
MESSAGE_ROLES = frozenset({"user", "assistant", "system"})
MESSAGE_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})
MESSAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"succeeded", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

DOSSIER_QUESTION_JOB = "oracle.dossier_question.answer"
MAX_QUESTION_CHARS = 8000
MAX_ANSWER_CHARS = 50_000


class ConversationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"conversation": [message]})


class ConversationNotFound(LookupError):
    pass


class ConversationConflict(RuntimeError):
    pass


class DossierConversation(TenantDomainMixin, Base):
    """One durable Q&A thread scoped to a strategic dossier."""

    __tablename__ = "dossier_conversations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_conversations_id_tenant"),
        UniqueConstraint(
            "id",
            "dossier_id",
            "tenant_id",
            name="uq_dossier_conversations_id_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_conversations_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "created_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_dossier_conversations_creator_membership",
        ),
        ForeignKeyConstraint(
            ("intent_revision_id", "tenant_id"),
            ("dossier_intent_revisions.id", "dossier_intent_revisions.tenant_id"),
            ondelete="SET NULL",
            name="fk_dossier_conversations_intent_tenant",
        ),
        CheckConstraint(
            "status IN ('open','archived')",
            name="dossier_conversation_status",
        ),
        CheckConstraint(
            "char_length(title) BETWEEN 0 AND 300",
            name="dossier_conversation_title",
        ),
        Index(
            "ix_dossier_conversations_dossier_updated",
            "tenant_id",
            "dossier_id",
            "updated_at",
        ),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    intent_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DossierMessage(TenantDomainMixin, Base):
    """One message in a dossier conversation (user question or assistant answer)."""

    __tablename__ = "dossier_messages"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_messages_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "sequence",
            name="uq_dossier_messages_sequence",
        ),
        ForeignKeyConstraint(
            ("conversation_id", "dossier_id", "tenant_id"),
            (
                "dossier_conversations.id",
                "dossier_conversations.dossier_id",
                "dossier_conversations.tenant_id",
            ),
            ondelete="CASCADE",
            name="fk_dossier_messages_conversation_tenant",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_messages_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("background_job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="SET NULL",
            name="fk_dossier_messages_background_job_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "created_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_dossier_messages_creator_membership",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','cancelled')",
            name="dossier_message_status",
        ),
        CheckConstraint(
            "role IN ('user','assistant','system')",
            name="dossier_message_role",
        ),
        CheckConstraint("sequence >= 1", name="dossier_message_sequence"),
        CheckConstraint(
            "char_length(content_text) BETWEEN 0 AND 50000",
            name="dossier_message_content_text",
        ),
        CheckConstraint(
            "jsonb_typeof(coverage_manifest)='object'",
            name="dossier_message_coverage_manifest",
        ),
        CheckConstraint(
            "jsonb_typeof(answer_payload)='object'",
            name="dossier_message_answer_payload",
        ),
        Index(
            "ix_dossier_messages_conversation_created",
            "tenant_id",
            "conversation_id",
            "created_at",
        ),
        Index(
            "ix_dossier_messages_status",
            "tenant_id",
            "status",
            "updated_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    coverage_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))


CONVERSATION_MODELS = (DossierConversation, DossierMessage)


def can_transition_message(from_status: str, to_status: str) -> bool:
    if from_status not in MESSAGE_STATUSES or to_status not in MESSAGE_STATUSES:
        return False
    return to_status in MESSAGE_TRANSITIONS.get(from_status, frozenset())


def transition_message_status(message: DossierMessage, to_status: str) -> DossierMessage:
    if not can_transition_message(message.status, to_status):
        raise ConversationConflict(
            f"Transición de mensaje no permitida: {message.status} → {to_status}."
        )
    message.status = to_status
    return message


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
        raise ConversationNotFound("Expediente no encontrado.")
    return dossier


def _load_conversation(
    session: Session,
    conversation_id: uuid.UUID,
    *,
    dossier_id: uuid.UUID | None = None,
    for_update: bool = False,
) -> DossierConversation:
    tenant_id = require_tenant_id()
    statement = select(DossierConversation).where(
        DossierConversation.id == conversation_id,
        DossierConversation.tenant_id == tenant_id,
    )
    if dossier_id is not None:
        statement = statement.where(DossierConversation.dossier_id == dossier_id)
    if for_update:
        statement = statement.with_for_update()
    conversation = session.scalar(statement)
    if conversation is None:
        raise ConversationNotFound("Conversación no encontrada.")
    return conversation


def serialize_conversation(conversation: DossierConversation) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "tenant_id": str(conversation.tenant_id),
        "dossier_id": str(conversation.dossier_id),
        "status": conversation.status,
        "title": conversation.title,
        "created_by_user_id": str(conversation.created_by_user_id),
        "intent_revision_id": (
            str(conversation.intent_revision_id)
            if conversation.intent_revision_id is not None
            else None
        ),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


def serialize_message(message: DossierMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "tenant_id": str(message.tenant_id),
        "dossier_id": str(message.dossier_id),
        "conversation_id": str(message.conversation_id),
        "role": message.role,
        "status": message.status,
        "sequence": message.sequence,
        "content_text": message.content_text,
        "answer_payload": dict(message.answer_payload or {}),
        "coverage_manifest": dict(message.coverage_manifest or {}),
        "background_job_id": (
            str(message.background_job_id) if message.background_job_id is not None else None
        ),
        "created_by_user_id": (
            str(message.created_by_user_id) if message.created_by_user_id is not None else None
        ),
        "error_code": message.error_code,
        "error_message": message.error_message,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,
    }


def create_conversation(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
    title: str = "",
) -> DossierConversation:
    """Open a conversation. Does not call Signal, memory or AI."""

    dossier = _load_dossier(session, dossier_id)
    cleaned_title = str(title or "").strip()[:300]
    conversation = DossierConversation(
        id=uuid.uuid4(),
        tenant_id=dossier.tenant_id,
        dossier_id=dossier.id,
        status="open",
        title=cleaned_title,
        created_by_user_id=actor_id,
        intent_revision_id=dossier.current_intent_revision_id,
    )
    session.add(conversation)
    append_audit_event(
        session,
        action="dossier.conversation.created",
        resource_type="dossier_conversation",
        resource_id=conversation.id,
        dossier_id=dossier.id,
        result="success",
        metadata={"status": "open"},
    )
    session.flush()
    return conversation


def enqueue_user_message(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    conversation_id: uuid.UUID,
    actor_id: uuid.UUID,
    content_text: str,
    idempotency_key: str,
    request_id: str | None = None,
    publish: bool = False,
) -> tuple[DossierMessage, BackgroundJob]:
    """Persist the user question first, then stage a BackgroundJob.

    HTTP routes commit then call ``publish_job`` so Celery can run
    ``oracle.dossier_question.answer``. Pass ``publish=True`` to commit+publish
    inside this helper (tests usually keep publish=False and commit themselves).
    """

    if not 8 <= len(idempotency_key) <= 200:
        raise ConversationError(
            "Idempotency-Key debe tener entre 8 y 200 caracteres.",
            errors={"idempotency_key": ["Debe tener entre 8 y 200 caracteres."]},
        )
    question = str(content_text or "").strip()
    if not 1 <= len(question) <= MAX_QUESTION_CHARS:
        raise ConversationError(
            f"La pregunta debe contener entre 1 y {MAX_QUESTION_CHARS} caracteres.",
            errors={"content_text": [f"Debe contener entre 1 y {MAX_QUESTION_CHARS} caracteres."]},
        )

    conversation = _load_conversation(
        session,
        conversation_id,
        dossier_id=dossier_id,
        for_update=True,
    )
    if conversation.status != "open":
        raise ConversationConflict("La conversación no admite nuevos mensajes.")

    tenant_id = require_tenant_id()
    existing_job = session.scalar(
        select(BackgroundJob).where(
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.idempotency_key == idempotency_key,
        )
    )
    if existing_job is not None:
        if existing_job.resource_type != "dossier_message" or existing_job.resource_id is None:
            raise ConversationConflict("La clave idempotente ya pertenece a otro recurso.")
        existing_message = session.scalar(
            select(DossierMessage).where(
                DossierMessage.id == existing_job.resource_id,
                DossierMessage.tenant_id == tenant_id,
            )
        )
        if existing_message is None:
            raise ConversationConflict("Mensaje idempotente no disponible.")
        return existing_message, existing_job

    max_seq = session.scalar(
        select(func.coalesce(func.max(DossierMessage.sequence), 0)).where(
            DossierMessage.tenant_id == tenant_id,
            DossierMessage.conversation_id == conversation_id,
        )
    )
    next_sequence = int(max_seq or 0) + 1

    message = DossierMessage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        conversation_id=conversation_id,
        role="user",
        status="queued",
        sequence=next_sequence,
        content_text=question,
        answer_payload={},
        coverage_manifest={},
        created_by_user_id=actor_id,
    )
    session.add(message)
    session.flush()

    payload = {
        "dossier_id": str(dossier_id),
        "conversation_id": str(conversation_id),
        "message_id": str(message.id),
        "purpose": "question",
    }
    job = stage_job(
        DOSSIER_QUESTION_JOB,
        payload=payload,
        idempotency_key=idempotency_key,
        requested_by_user_id=actor_id,
        dossier_id=dossier_id,
        resource_type="dossier_message",
        resource_id=message.id,
        request_id=request_id,
        max_attempts=3,
    )
    message.background_job_id = job.id
    # Keep conversation activity timestamp current so list-latest recovers the right thread.
    conversation.updated_at = datetime.now(UTC)
    append_audit_event(
        session,
        action="dossier.conversation.message.enqueued",
        resource_type="dossier_message",
        resource_id=message.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={
            "conversation_id": str(conversation_id),
            "job_id": str(job.id),
            "status": message.status,
            "content_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        },
    )
    session.flush()
    if publish:
        # Publishing is optional; worker answer execution is deferred.
        from opn_oracle.jobs.service import publish_job

        session.commit()
        publish_job(job)
    return message, job


def get_message(
    session: Session,
    message_id: uuid.UUID,
    *,
    dossier_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
) -> DossierMessage:
    tenant_id = require_tenant_id()
    statement = select(DossierMessage).where(
        DossierMessage.id == message_id,
        DossierMessage.tenant_id == tenant_id,
    )
    if dossier_id is not None:
        statement = statement.where(DossierMessage.dossier_id == dossier_id)
    if conversation_id is not None:
        statement = statement.where(DossierMessage.conversation_id == conversation_id)
    message = session.scalar(statement)
    if message is None:
        raise ConversationNotFound("Mensaje no encontrado.")
    return message


def list_conversations(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    limit: int = 20,
) -> list[DossierConversation]:
    """Return conversations for a dossier, most recently updated first.

    Used by the Ask UI to rehydrate after tab/session loss without relying on
    sessionStorage as source of truth.
    """

    tenant_id = require_tenant_id()
    capped = max(1, min(int(limit or 20), 100))
    rows = session.scalars(
        select(DossierConversation)
        .where(
            DossierConversation.tenant_id == tenant_id,
            DossierConversation.dossier_id == dossier_id,
        )
        .order_by(
            DossierConversation.updated_at.desc().nullslast(),
            DossierConversation.created_at.desc().nullslast(),
        )
        .limit(capped)
    ).all()
    return list(rows)


def list_messages(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    conversation_id: uuid.UUID,
    limit: int = 50,
) -> list[DossierMessage]:
    """Return messages in a conversation ordered by sequence descending (latest first)."""

    tenant_id = require_tenant_id()
    # Ensure conversation belongs to dossier/tenant before listing messages.
    _load_conversation(session, conversation_id, dossier_id=dossier_id)
    capped = max(1, min(int(limit or 50), 200))
    rows = session.scalars(
        select(DossierMessage)
        .where(
            DossierMessage.tenant_id == tenant_id,
            DossierMessage.dossier_id == dossier_id,
            DossierMessage.conversation_id == conversation_id,
        )
        .order_by(DossierMessage.sequence.desc(), DossierMessage.created_at.desc().nullslast())
        .limit(capped)
    ).all()
    return list(rows)


def apply_assistant_answer(
    message: DossierMessage,
    *,
    answer_text: str,
    answer_payload: Mapping[str, Any] | None = None,
    coverage_manifest: Mapping[str, Any] | None = None,
) -> DossierMessage:
    """Record a successful answer. Never mutates intent or memory facts."""

    if message.role != "user":
        raise ConversationError("Solo se responde a mensajes de usuario.")
    transition_message_status(message, "running")
    text_value = str(answer_text or "").strip()
    if len(text_value) > MAX_ANSWER_CHARS:
        raise ConversationError("La respuesta supera el tamaño máximo permitido.")
    message.answer_payload = {
        **dict(answer_payload or {}),
        "text": text_value,
        "mutates_intent": False,
        "mutates_memory_facts": False,
    }
    if coverage_manifest is not None:
        message.coverage_manifest = dict(coverage_manifest)
    transition_message_status(message, "succeeded")
    return message


def mark_message_failed(
    message: DossierMessage,
    *,
    error_code: str,
    error_message: str,
) -> DossierMessage:
    if message.status in MESSAGE_TERMINAL:
        raise ConversationConflict("El mensaje ya está en estado terminal.")
    if message.status == "queued":
        transition_message_status(message, "failed")
    else:
        transition_message_status(message, "failed")
    message.error_code = error_code[:100]
    message.error_message = error_message[:500]
    return message


def payload_digest_preview(payload: Mapping[str, Any]) -> str:
    """Stable hex digest for tests / audit without secret fields."""

    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def cancel_message(message: DossierMessage) -> DossierMessage:
    """Cooperative cancel to a terminal status without inventing an answer."""

    if message.status in MESSAGE_TERMINAL:
        return message
    if message.status == "queued":
        transition_message_status(message, "cancelled")
    else:
        transition_message_status(message, "cancelled")
    message.error_code = message.error_code or "cancelled"
    message.error_message = message.error_message or "Cancelado por el operador o el sistema."
    return message


def process_dossier_question_answer(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
    *,
    memory_adapter: Any | None = None,
    memory_mode: str | None = None,
) -> dict[str, Any]:
    """MDEV-06: retrieve dual memory, materialize citas, settle message.

    Never mutates IntentRevision or promotes memory facts. Uses no paid providers
    unless AI_MODE=signal. ``memory_adapter`` is injectable for tests.

    Memory mode SSOT (G-29): derived exclusively from
    ``resolve_effective_dossier_memory_profile`` (default profile or
    legacy_missing→disabled). ``payload.memory_mode`` is always ignored.
    The ``memory_mode`` kwarg is a unit-test inject only when TESTING=true;
    production jobs never pass it (see jobs/tasks.py).
    """

    from dataclasses import replace as dc_replace

    from opn_oracle.integrations.memory_ask_dual import (
        EvidenceMappingRow,
        MemoryMode,
        PermanentMemoryAskError,
        RetryableMemoryAskError,
        build_dual_ask_context,
        build_input_manifest,
        build_signal_factual_block,
        classify_error_code,
        dual_context_to_snapshot,
        format_allowlist_rejection,
        link_snapshot_run_usage,
        load_dossier_citable_evidence_ids,
        load_existing_memory_signal_mappings,
        load_oracle_authority_from_session,
        merge_ask_citation_allowlist,
        persist_memory_signal_evidence,
        validate_citations_allowlist,
    )
    from opn_oracle.integrations.memory_context import (
        MemoryContextDisabled,
        MemoryContextError,
        persist_snapshot_from_retrieve_result,
    )
    from opn_oracle.integrations.memory_http_client import MemoryHttpError

    tenant_id = require_tenant_id()
    try:
        message_id = uuid.UUID(str(payload["message_id"]))
        conversation_id = uuid.UUID(str(payload["conversation_id"]))
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ConversationError("Payload de pregunta incompleto o inválido.") from error

    if job.cancel_requested:
        message = get_message(
            session,
            message_id,
            dossier_id=dossier_id,
            conversation_id=conversation_id,
        )
        cancel_message(message)
        session.flush()
        return {
            "message_id": str(message.id),
            "status": message.status,
            "cancelled": True,
        }

    message = get_message(
        session,
        message_id,
        dossier_id=dossier_id,
        conversation_id=conversation_id,
    )
    if message.tenant_id != tenant_id:
        raise ConversationNotFound("Mensaje no encontrado.")
    if message.status in MESSAGE_TERMINAL:
        return {
            "message_id": str(message.id),
            "status": message.status,
            "idempotent": True,
        }
    if message.status != "queued":
        raise ConversationConflict(
            f"El mensaje no puede procesarse desde el estado {message.status}."
        )

    adapter = memory_adapter
    if adapter is None:
        from opn_oracle.integrations.memory_context import get_memory_context_adapter

        try:
            adapter = get_memory_context_adapter()
        except Exception as error:  # pragma: no cover - defensive config
            raise ConversationError("No se pudo resolver el adaptador de memoria.") from error

    # G-29 SSOT: effective mode from persisted default profile only.
    # payload.memory_mode is client/job-overridable noise — always ignored.
    import os as _os

    testing_active = False
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            testing_active = bool(
                current_app.config.get("TESTING") or current_app.config.get("APP_ENV") == "test"
            )
    except Exception:  # pragma: no cover - no app context
        testing_active = False
    if not testing_active:
        testing_active = str(_os.environ.get("TESTING") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
    # Pure unit tests (no Flask app) still run under pytest; Celery jobs never set this.
    if not testing_active:
        testing_active = bool(_os.environ.get("PYTEST_CURRENT_TEST"))

    from opn_oracle.integrations.memory_profile import (
        normalize_operational_mode,
        resolve_effective_dossier_memory_profile,
    )

    try:
        mem_resolution = resolve_effective_dossier_memory_profile(
            session, tenant_id=tenant_id, dossier_id=dossier_id
        )
    except Exception:
        # Fail-closed: never invent memory if resolution blows up.
        from opn_oracle.integrations.memory_profile import EffectiveMemoryResolution

        mem_resolution = EffectiveMemoryResolution(
            mode="disabled",
            profile_id=None,
            version=None,
            scope_type="dossier",
            resolution_source="legacy_missing",
            persisted=False,
            state="legacy_missing",
            profile_config={},
            reason_es="resolution_error_fail_closed",
        )

    profile_cfg: dict[str, Any] = dict(mem_resolution.profile_config or {})
    profile_version: int | None = mem_resolution.version
    profile_id: str | None = mem_resolution.profile_id
    resolution_source: str = mem_resolution.resolution_source
    effective_mode: str = mem_resolution.mode

    # Unit-test inject ONLY: kwarg memory_mode when TESTING=true.
    # Never honors payload.memory_mode (jobs could carry client-forged values).
    if testing_active and memory_mode is not None:
        injected = normalize_operational_mode(memory_mode)
        if str(memory_mode).strip().lower() == "mock":
            injected = "augment"
        effective_mode = injected
        resolution_source = "testing_inject"
    elif not testing_active and memory_mode is not None:
        # Defensive: ignore kwarg outside TESTING (jobs must not pass it).
        pass

    # Honesty: never report augment/shadow without a real profile identity,
    # unless this is an explicit unit-test inject (no DB profile needed).
    if (
        effective_mode in {"augment", "shadow"}
        and resolution_source != "testing_inject"
        and (not profile_id or profile_version is None or int(profile_version) < 1)
    ):
        effective_mode = "disabled"

    scope_hint: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "job_id": str(job.id),
        "mode": effective_mode,
        "memory_profile_id": profile_id,
        "memory_profile_version": profile_version,
        "resolution_source": resolution_source,
        "scope_type": "dossier",
    }
    if profile_cfg:
        if profile_cfg.get("token_budget") is not None:
            scope_hint["token_budget"] = profile_cfg.get("token_budget")
        if profile_cfg.get("kinds"):
            scope_hint["kinds"] = list(profile_cfg.get("kinds") or [])
        if profile_cfg.get("sources"):
            scope_hint["sources"] = list(profile_cfg.get("sources") or [])
        if profile_cfg.get("classifications_allowed"):
            scope_hint["classifications_allowed"] = list(
                profile_cfg.get("classifications_allowed") or []
            )
    snapshot_id = None
    items_observed: list[Any] = []
    coverage: dict[str, Any] = {}
    policy = "unknown"
    publisher_degraded = False

    try:
        retrieval = adapter.retrieve(
            scope_hint,
            message.content_text,
            "question",
            20,
        )
        coverage = dict(retrieval.get("coverage_manifest") or {})
        # Prefer items_for_prompt when present (empty list in shadow is intentional).
        if "items_for_prompt" in retrieval:
            items_observed = list(retrieval.get("items_observed") or retrieval.get("items") or [])
            prompt_seed = list(retrieval.get("items_for_prompt") or [])
        else:
            items_observed = list(retrieval.get("items") or [])
            prompt_seed = items_observed
        policy = str(retrieval.get("policy_version") or "unknown")
        publisher_degraded = bool(retrieval.get("publisher_degraded"))
        if retrieval.get("error") and classify_error_code(
            str((retrieval.get("error") or {}).get("code") or ""),
        ):
            # Retryable technical path returned as degraded response — re-raise for Celery.
            err = retrieval["error"]
            if err.get("retryable"):
                raise RetryableMemoryAskError(
                    str(err.get("detail") or err.get("code") or "memory_retryable"),
                    code=str(err.get("code") or "upstream_retryable"),
                )
        if isinstance(retrieval, dict) and retrieval.get("snapshot_meta"):
            meta = dict(retrieval["snapshot_meta"])
            meta.setdefault("tenant_id", str(tenant_id))
            meta.setdefault("dossier_id", str(dossier_id))
            retrieval = {**retrieval, "snapshot_meta": meta}
            # Dual context built below; snapshot enriched after materialization.
            _raw_retrieval = retrieval
        else:
            _raw_retrieval = retrieval
        _ = prompt_seed  # used via dual context from items_observed + mode
    except MemoryContextDisabled:
        from opn_oracle.integrations.memory_context import empty_coverage_manifest

        items_observed = []
        coverage = empty_coverage_manifest(requested=["memory.disabled"])
        coverage["excluded"] = [{"source": "memory", "reason": "policy"}]
        policy = "disabled"
        effective_mode = "disabled"
        _raw_retrieval = {}
    except MemoryHttpError as error:
        if classify_error_code(error.code) or bool(getattr(error, "retryable", False)):
            # Do not mark message failed yet — Celery will retry within deadline.
            raise RetryableMemoryAskError(str(error), code=str(error.code)) from error
        mark_message_failed(
            message,
            error_code=str(error.code)[:100] or "memory_http_error",
            error_message=str(error)[:500],
        )
        session.flush()
        raise PermanentMemoryAskError(str(error), code=str(error.code)) from error
    except (RetryableMemoryAskError, PermanentMemoryAskError):
        raise
    except MemoryContextError as error:
        mark_message_failed(
            message,
            error_code="memory_context_error",
            error_message=str(error)[:500],
        )
        session.flush()
        raise PermanentMemoryAskError(str(error), code="memory_context_error") from error
    except Exception as error:
        mark_message_failed(
            message,
            error_code="memory_context_error",
            error_message=str(error)[:500],
        )
        session.flush()
        raise ConversationError(f"Fallo al recuperar contexto: {error}") from error

    # Load real Oracle authority (tenant+dossier-scoped) from the same UoW session.
    oracle_authority = load_oracle_authority_from_session(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        question=message.content_text,
    )

    typed_mode: MemoryMode
    if effective_mode == "augment":
        typed_mode = "augment"
    elif effective_mode == "shadow":
        typed_mode = "shadow"
    else:
        typed_mode = "disabled"
        effective_mode = "disabled"

    # Reuse durable memory_signal Evidence by source_ref+checksum across turns
    # so Preguntar does not mint a fresh uuid4 row per fact on every ask.
    existing_ms_mappings: list[dict[str, Any]] = []
    if typed_mode == "augment":
        try:
            existing_ms_mappings = load_existing_memory_signal_mappings(
                session, tenant_id=tenant_id, dossier_id=dossier_id
            )
        except Exception:
            # Fail-open for reuse only: materialize still works (may grow rows).
            existing_ms_mappings = []

    # Build dual blocks + materialize allowlist (shadow injects zero items).
    dual = build_dual_ask_context(
        mode=typed_mode,
        tenant_id=str(tenant_id),
        dossier_id=str(dossier_id),
        question=message.content_text,
        retrieval_items=[it for it in items_observed if isinstance(it, dict)],
        coverage_manifest=coverage,
        memory_policy=policy,
        oracle_authority=oracle_authority,
        existing_mappings=existing_ms_mappings,
        job_id=str(job.id),
        message_id=str(message.id),
    )
    coverage = dict(dual.coverage)
    items_for_prompt = list(dual.signal_factual.get("items") or [])
    # Dual-only is incomplete: build_context + oracle_authority also teach dossier
    # Evidence (procurement PLACSP, documents, …). Merge before any model call so
    # RT-07, provider, and conversation-layer validators share one allowlist.
    dossier_citable_ids = load_dossier_citable_evidence_ids(
        session, tenant_id=tenant_id, dossier_id=dossier_id
    )
    allowed_ids = merge_ask_citation_allowlist(
        list(dual.allowed_evidence_ids),
        oracle_authority=dual.oracle_authority,
        extra_dossier_evidence_ids=dossier_citable_ids,
    )
    evidence_persisted: list[str] = []
    persist_degraded = False

    # Persist Evidence rows when augment + citations. Failures must not leave
    # phantom allowed_evidence_ids: only successfully persisted+linked IDs remain.
    if typed_mode == "augment" and dual.citations:
        try:
            persist_result = persist_memory_signal_evidence(
                session,
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                citations=dual.citations,
                job_id=str(job.id),
            )
            # Real impl returns dict[str,str]; tests may still stub list[str].
            if isinstance(persist_result, dict):
                id_map = {str(k): str(v) for k, v in persist_result.items()}
            else:
                id_map = {str(x): str(x) for x in list(persist_result or [])}
            evidence_persisted = list(dict.fromkeys(id_map.values()))
        except Exception as persist_error:
            # Visible failure: exclude all materialised IDs, mark coverage failed.
            evidence_persisted = []
            id_map = {}
            persist_degraded = True
            failed = list(coverage.get("failed") or [])
            failed.append(
                {
                    "source": "memory_signal_evidence",
                    "reason": "persist_failed",
                    "detail": str(persist_error)[:300],
                }
            )
            coverage["failed"] = failed
            excluded = list(coverage.get("excluded") or [])
            for c in dual.citations:
                excluded.append(
                    {
                        "source": "signal_item",
                        "reason": "persist_failed",
                        "id": c.signal_item_id,
                        "oracle_evidence_id": c.oracle_evidence_id,
                    }
                )
            coverage["excluded"] = excluded

        persisted_set = {str(x) for x in evidence_persisted}
        if not persisted_set and dual.citations:
            # Persist returned empty without exception (constraint skip / mismatch).
            persist_degraded = True
            failed = list(coverage.get("failed") or [])
            failed.append(
                {
                    "source": "memory_signal_evidence",
                    "reason": "persist_empty",
                    "detail": "no evidence rows durable after materialize",
                }
            )
            coverage["failed"] = failed

        # Rebuild allowlist/items/manifest from durable ids only. Remap citation
        # ids when content-identity reuse returned an older Evidence row.
        kept_citations_list = []
        for c in dual.citations:
            durable = id_map.get(c.oracle_evidence_id)
            if not durable:
                continue
            if durable != c.oracle_evidence_id:
                kept_citations_list.append(dc_replace(c, oracle_evidence_id=durable))
            else:
                kept_citations_list.append(c)
        kept_citations = tuple(kept_citations_list)
        kept_mappings = tuple(
            EvidenceMappingRow(
                signal_item_id=m.signal_item_id,
                oracle_evidence_id=id_map.get(m.oracle_evidence_id, m.oracle_evidence_id),
                source_ref=m.source_ref,
                source_version=m.source_version,
                checksum=m.checksum,
                classification=m.classification,
                locator=m.locator,
                mapping_version=m.mapping_version,
            )
            for m in dual.mappings
            if m.oracle_evidence_id in id_map
        )
        dropped = [
            c.oracle_evidence_id for c in dual.citations if c.oracle_evidence_id not in id_map
        ]
        if dropped:
            excluded = list(coverage.get("excluded") or [])
            for eid in dropped:
                excluded.append(
                    {
                        "source": "signal_item",
                        "reason": "not_persisted",
                        "oracle_evidence_id": eid,
                    }
                )
            coverage["excluded"] = excluded
            persist_degraded = True
        coverage["used"] = [c.oracle_evidence_id for c in kept_citations]
        signal_block = build_signal_factual_block(
            mode=typed_mode,
            citations=kept_citations,
            observed_count=len(items_observed),
        )
        dual_only_ids = [c.oracle_evidence_id for c in kept_citations]
        # Keep dossier-citable IDs after dual rematerialize filter; only drop
        # dual IDs that failed to persist (phantom memory_signal).
        allowed_ids = merge_ask_citation_allowlist(
            dual_only_ids,
            oracle_authority=dual.oracle_authority,
            extra_dossier_evidence_ids=dossier_citable_ids,
        )
        manifest, digest = build_input_manifest(
            mode=typed_mode,
            oracle_authority=dual.oracle_authority,
            signal_factual=signal_block,
            allowed_evidence_ids=allowed_ids,
            coverage=coverage,
            memory_policy=policy,
            job_id=str(job.id),
            message_id=str(message.id),
        )
        dual = dc_replace(
            dual,
            citations=kept_citations,
            mappings=kept_mappings,
            allowed_evidence_ids=tuple(allowed_ids),
            signal_factual=signal_block,
            coverage=coverage,
            input_manifest=manifest,
            input_manifest_hash=digest,
            excluded=tuple(coverage.get("excluded") or []),
        )
        items_for_prompt = list(signal_block.get("items") or [])

    snapshot_payload = dual_context_to_snapshot(dual)
    if isinstance(snapshot_payload, dict):
        snapshot_payload = {
            **snapshot_payload,
            "profile_version": profile_version,
            "profile_id": profile_id,
            "scope_type": "dossier",
            "resolution_source": resolution_source,
            "tenant_id": str(tenant_id),
            "dossier_id": str(dossier_id),
        }
    if _raw_retrieval and isinstance(_raw_retrieval, dict) and _raw_retrieval.get("snapshot_meta"):
        enriched = {
            **_raw_retrieval,
            "snapshot": snapshot_payload,
            "snapshot_meta": {
                **dict(_raw_retrieval["snapshot_meta"]),
                "mode": effective_mode,
                "profile_version": profile_version,
                "profile_id": profile_id,
                "resolution_source": resolution_source,
                "scope_type": "dossier",
            },
        }
        # Snapshot failures must not be silent: mark coverage, rebuild effective
        # coverage/manifest from what is actually durable, and continue degraded.
        try:
            snapshot_id = persist_snapshot_from_retrieve_result(session, enriched)
        except Exception as snap_error:
            snapshot_id = None
            persist_degraded = True
            failed = list(coverage.get("failed") or [])
            failed.append(
                {
                    "source": "memory_retrieval_snapshot",
                    "reason": "snapshot_persist_failed",
                    "detail": str(snap_error)[:300],
                }
            )
            coverage["failed"] = failed
            # Rebuild audit-grade input_manifest so it matches the effective
            # allowlist + coverage (no half-linked snapshot IDs, no phantom evidence).
            rebuilt_manifest, rebuilt_digest = build_input_manifest(
                mode=typed_mode,
                oracle_authority=dual.oracle_authority,
                signal_factual=dual.signal_factual,
                allowed_evidence_ids=list(dual.allowed_evidence_ids),
                coverage=coverage,
                memory_policy=policy,
                job_id=str(job.id),
                message_id=str(message.id),
            )
            dual = dc_replace(
                dual,
                coverage=coverage,
                input_manifest=rebuilt_manifest,
                input_manifest_hash=rebuilt_digest,
            )

    # Cancellation after retrieval / before model (fencing).
    session.refresh(job, attribute_names=["cancel_requested"])
    if bool(job.cancel_requested):
        cancel_message(message)
        session.flush()
        return {
            "message_id": str(message.id),
            "status": "cancelled",
            "cancelled": True,
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
            "input_manifest_hash": dual.input_manifest_hash,
        }

    signal_meta: dict[str, Any] = {}
    body: str
    unknowns: list[str] = []
    answer_payload: dict[str, Any]
    coverage_failed = list(coverage.get("failed") or [])
    degraded = publisher_degraded or persist_degraded or bool(coverage_failed)
    # Honest reasons only — never invent "memory coverage failed" when failed=[].
    degraded_reasons: list[str] = []
    if publisher_degraded:
        degraded_reasons.append("publicador de memoria degradado")
    if persist_degraded:
        degraded_reasons.append("persistencia de evidencia degradada")
    if coverage_failed:
        degraded_reasons.append(f"cobertura de memoria reportó {len(coverage_failed)} fallo(s)")
    degraded_reason = "; ".join(degraded_reasons) if degraded_reasons else None

    if _signal_ai_enabled():
        try:
            signal_result = _answer_via_signal(
                session,
                job=job,
                dossier_id=dossier_id,
                message=message,
                memory_items=items_for_prompt,
                coverage=coverage,
                memory_policy=policy,
                allowed_evidence_ids=allowed_ids,
                dual_blocks={
                    "oracle_authority": dual.oracle_authority,
                    "signal_factual": dual.signal_factual,
                },
                input_manifest=dual.input_manifest,
            )
            body = str(signal_result["answer_text"])
            answer_payload = dict(signal_result["answer_payload"])
            signal_meta = dict(signal_result.get("meta") or {})
            # Deterministic completion: if the model already named a tender present in
            # dual-memory, copy missing humanized amount/deadline from authorized extracts
            # (never invent formats; only reuse prose already in signal_factual items).
            from opn_oracle.integrations.memory_ask_dual import (
                complete_answer_with_grounded_tender_facts as _complete_tender_facts,
            )

            body, grounded_citations = _complete_tender_facts(
                body,
                signal_items=items_for_prompt,
                citations=list(answer_payload.get("citations") or []),
            )
            answer_payload["citations"] = grounded_citations
            answer_payload["text"] = body
            # Allowlist 100%: any foreign citation or material Evidence fails closed.
            accepted, rejected = validate_citations_allowlist(
                list(answer_payload.get("citations") or []),
                allowed_ids,
            )
            if rejected:
                raise ConversationError(format_allowlist_rejection(rejected, allowed_ids))
            answer_payload["citations"] = accepted
            from opn_oracle.integrations.memory_ask_dual import (
                validate_material_evidence_allowlist as _v_material,
            )

            mat_bad = _v_material(
                list(answer_payload.get("facts") or []), allowed_ids, kind="facts"
            ) + _v_material(list(answer_payload.get("claims") or []), allowed_ids, kind="claims")
            if mat_bad:
                raise ConversationError(
                    format_allowlist_rejection(
                        mat_bad, allowed_ids, kind="facts/claims evidence_ids"
                    )
                )
        except Exception as error:
            mark_message_failed(
                message,
                error_code="signal_ai_error",
                error_message=str(error)[:500],
            )
            session.flush()
            raise ConversationError(f"Fallo IA gobernada (Signal): {error}") from error
    else:
        # Deterministic grounded draft: no external LLM (tests / AI disabled).
        if items_for_prompt:
            excerpts = []
            citations_out = []
            for item in items_for_prompt[:5]:
                text_bit = str(item.get("text") or "").strip()
                eid = str(item.get("evidence_id") or "")
                if text_bit:
                    excerpts.append(text_bit[:400])
                if eid and text_bit:
                    citations_out.append({"evidence_id": eid, "quote": text_bit[:300]})
            body = (
                "Respuesta provisional a partir del contexto autorizado "
                f"({len(items_for_prompt)} fragmentos, mode={effective_mode}, "
                f"policy={policy}):\n\n" + "\n".join(f"- {excerpt}" for excerpt in excerpts)
            )
            unknowns = []
        else:
            body = (
                "No hay evidencia suficiente en la memoria autorizada del expediente "
                "para responder con citas. Reformula la pregunta o amplía las fuentes "
                f"del expediente (mode={effective_mode}, policy={policy})."
            )
            unknowns = ["evidencia_en_memoria"]
            citations_out = []
        answer_payload = {
            "policy_version": policy,
            "memory_mode": effective_mode,
            "memory_profile_version": profile_version,
            "memory_profile_id": profile_id,
            "memory_scope_type": "dossier",
            "resolution_source": resolution_source,
            "item_count": len(items_for_prompt),
            "items_observed": len(items_observed),
            "unknowns": unknowns,
            "claims": [],
            "conflicts": [],
            "facts": [],
            "inferences": [],
            "recommendations": [],
            "citations": citations_out,
            "allowed_evidence_ids": allowed_ids,
            "evidence_mapping": [
                {
                    "signal_item_id": m.signal_item_id,
                    "oracle_evidence_id": m.oracle_evidence_id,
                    "checksum": m.checksum,
                    "source_ref": m.source_ref,
                    "source_version": m.source_version,
                }
                for m in dual.mappings
            ],
            "input_manifest_hash": dual.input_manifest_hash,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "job_id": str(job.id),
            "provider_path": "deterministic",
            "evidence_persisted": evidence_persisted,
        }

    answer_payload.setdefault("memory_mode", effective_mode)
    answer_payload.setdefault("memory_profile_version", profile_version)
    answer_payload.setdefault("memory_profile_id", profile_id)
    answer_payload.setdefault("memory_scope_type", "dossier")
    answer_payload.setdefault("resolution_source", resolution_source)
    answer_payload.setdefault("allowed_evidence_ids", allowed_ids)
    answer_payload.setdefault("input_manifest_hash", dual.input_manifest_hash)
    # Always own degraded flags from measured path (publisher/persist/coverage.failed).
    answer_payload["degraded"] = degraded
    answer_payload["degraded_reason"] = degraded_reason
    answer_payload.setdefault("items_observed", len(items_observed))
    answer_payload.setdefault(
        "coverage_summary",
        {
            "requested": coverage.get("requested"),
            "used": coverage.get("used"),
            "failed": coverage.get("failed"),
            "excluded": coverage.get("excluded"),
            "truncated": coverage.get("truncated"),
        },
    )

    # Late fencing: cancel after answer generation but before publish.
    session.refresh(job, attribute_names=["cancel_requested"])
    if bool(job.cancel_requested):
        cancel_message(message)
        session.flush()
        return {
            "message_id": str(message.id),
            "status": "cancelled",
            "cancelled": True,
            "late_response_suppressed": True,
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
        }

    apply_assistant_answer(
        message,
        answer_text=body,
        answer_payload=answer_payload,
        coverage_manifest=coverage,
    )

    # Link run/usage/attempts without rewriting frozen snapshot core.
    if snapshot_id is not None:
        from opn_oracle.integrations.models import MemoryRetrievalSnapshot

        snapshot_row = session.get(MemoryRetrievalSnapshot, snapshot_id)
        if snapshot_row is not None:
            linked = link_snapshot_run_usage(
                dict(snapshot_row.payload or {}),
                run_id=str(signal_meta.get("artifact_id") or job.id),
                usage_log_id=str(signal_meta.get("audit_log_id") or "") or None,
                attempts=int(
                    getattr(job, "attempt_count", None) or getattr(job, "attempts", 1) or 1
                ),
            )
            # payload core already frozen at insert; only post_links + ids columns.
            try:
                snapshot_row.run_id = (
                    uuid.UUID(str(signal_meta.get("artifact_id") or job.id))
                    if (signal_meta.get("artifact_id") or job.id)
                    else None
                )
            except (TypeError, ValueError):
                snapshot_row.run_id = None
            if signal_meta.get("audit_log_id"):
                snapshot_row.usage_log_id = str(signal_meta["audit_log_id"])[:80]
            # Keep payload immutable core: merge post_links only if payload had dual keys.
            payload = dict(snapshot_row.payload or {})
            payload["post_links"] = linked.get("post_links") or {}
            snapshot_row.payload = payload

    append_audit_event(
        session,
        action="dossier.conversation.message.answered",
        resource_type="dossier_message",
        resource_id=message.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "job_id": str(job.id),
            "policy_version": policy,
            "memory_mode": effective_mode,
            "memory_profile_version": profile_version,
            "memory_profile_id": profile_id,
            "memory_scope_type": "dossier",
            "resolution_source": resolution_source,
            "item_count": len(items_for_prompt),
            "items_observed": len(items_observed),
            "allowed_evidence_count": len(allowed_ids),
            "input_manifest_hash": dual.input_manifest_hash,
            "mutates_intent": False,
            "mutates_memory_facts": False,
            "snapshot_id": str(snapshot_id) if snapshot_id else None,
            "degraded": degraded,
            **signal_meta,
        },
    )
    session.flush()
    return {
        "message_id": str(message.id),
        "status": message.status,
        "item_count": len(items_for_prompt),
        "items_observed": len(items_observed),
        "policy_version": policy,
        "memory_mode": effective_mode,
        "memory_profile_version": profile_version,
        "memory_profile_id": profile_id,
        "memory_scope_type": "dossier",
        "resolution_source": resolution_source,
        "allowed_evidence_ids": allowed_ids,
        "input_manifest_hash": dual.input_manifest_hash,
        "mutates_intent": False,
        "mutates_memory_facts": False,
        "snapshot_id": str(snapshot_id) if snapshot_id else None,
        "degraded": degraded,
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


def _answer_via_signal(
    session: Session,
    *,
    job: BackgroundJob,
    dossier_id: uuid.UUID,
    message: DossierMessage,
    memory_items: list[Any],
    coverage: Mapping[str, Any],
    memory_policy: str,
    allowed_evidence_ids: list[str] | None = None,
    dual_blocks: Mapping[str, Any] | None = None,
    input_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Call Signal task_key dossier_question_answer via execute_agent (no model hardcode)."""

    from opn_oracle.ai.context import build_context
    from opn_oracle.ai.models import AIArtifact
    from opn_oracle.ai.service import execute_agent
    from opn_oracle.integrations.memory_ask_dual import (
        PROMPT_RUNTIME_ID,
        PROMPT_RUNTIME_VERSION,
        SCHEMA_RUNTIME_VERSION,
        validate_citations_allowlist,
    )

    allowed = list(allowed_evidence_ids or [])
    result = execute_agent(
        agent="dossier_question_answer",
        dossier_id=dossier_id,
        job=job,
        context_factory=lambda max_tokens: build_context(dossier_id, max_tokens=max_tokens),
        supplemental_context={
            "question": message.content_text,
            "oracle_authority": dict((dual_blocks or {}).get("oracle_authority") or {}),
            "signal_factual": dict((dual_blocks or {}).get("signal_factual") or {}),
            "memory_items": memory_items[:20],
            "memory_policy": memory_policy,
            "coverage_manifest": dict(coverage),
            "allowed_evidence_ids": allowed,
            "input_manifest": dict(input_manifest or {}),
            "prompt_runtime_id": PROMPT_RUNTIME_ID,
            "prompt_runtime_version": PROMPT_RUNTIME_VERSION,
            "schema_runtime_version": SCHEMA_RUNTIME_VERSION,
            "untrusted_external_content": True,
        },
        target_type="dossier_message",
        target_id=message.id,
    )
    artifact = session.get(AIArtifact, uuid.UUID(str(result["artifact_id"])))
    if artifact is None or not isinstance(artifact.output, dict):
        raise ConversationError("Artefacto de respuesta IA no disponible.")
    output = dict(artifact.output)
    answer_text = str(output.get("answer_text") or "").strip()
    if not answer_text:
        raise ConversationError("La respuesta IA no incluye answer_text.")
    from opn_oracle.integrations.memory_ask_dual import (
        format_allowlist_rejection,
        merge_ask_citation_allowlist,
        validate_material_evidence_allowlist,
    )

    # Align with provider merge: dual IDs + dossier evidence taught via dual_blocks.
    allowed = merge_ask_citation_allowlist(
        allowed,
        oracle_authority=dict((dual_blocks or {}).get("oracle_authority") or {}),
    )
    raw_citations = list(output.get("citations") or [])
    accepted, rejected = validate_citations_allowlist(raw_citations, allowed)
    # Fail-closed: any rejected citation fails, including empty allowlist.
    # Oracle must not depend solely on remote RT-07 for this local defense.
    if rejected:
        raise ConversationError(format_allowlist_rejection(rejected, allowed))
    facts_out = list(output.get("facts") or [])
    claims_out = list(output.get("claims") or [])
    material_rejected = validate_material_evidence_allowlist(
        facts_out, allowed, kind="facts"
    ) + validate_material_evidence_allowlist(claims_out, allowed, kind="claims")
    if material_rejected:
        raise ConversationError(
            format_allowlist_rejection(material_rejected, allowed, kind="facts/claims evidence_ids")
        )
    # G06-CITA-RESPALDO: allowlist ≠ respaldo. Exige solape afirmación ↔ span citado.
    from opn_oracle.integrations.citation_support import (
        build_evidence_text_index,
        enforce_citation_support,
        format_support_rejection_summary,
        issue_to_public,
    )

    evidence_index = build_evidence_text_index(
        memory_items=memory_items,
        signal_factual=dict((dual_blocks or {}).get("signal_factual") or {}),
        oracle_authority=dict((dual_blocks or {}).get("oracle_authority") or {}),
        citations=accepted,
    )
    support = enforce_citation_support(
        facts=facts_out,
        claims=claims_out,
        evidence_text_by_id=evidence_index,
    )
    facts_out = support.facts
    claims_out = support.claims
    warnings_out = list(output.get("warnings") or [])
    for warning in support.warnings:
        if warning not in warnings_out:
            warnings_out.append(warning)
    support_summary = format_support_rejection_summary(support)
    if support_summary and support_summary not in warnings_out:
        warnings_out.append(support_summary)
    # Material degradado sin evidence_ids: claims OK; facts con schema estricto
    # ya no están en support.facts si se retiraron. Los degradados (no person-role)
    # salen de claims con evidence_ids=[] — permitido en DossierQuestionClaim.
    validated_hash = (
        str(output.get("validated_output_sha256") or "").strip()
        or str((artifact.output or {}).get("validated_output_sha256") or "").strip()
        or None
    )
    return {
        "answer_text": answer_text,
        "answer_payload": {
            "policy_version": memory_policy,
            "item_count": len(memory_items),
            "unknowns": list(output.get("open_questions") or output.get("unknowns") or []),
            "claims": claims_out,
            "conflicts": list(output.get("conflicts") or []),
            "facts": facts_out,
            "inferences": output.get("inferences") or [],
            "recommendations": output.get("recommendations") or [],
            "citations": accepted,
            "allowed_evidence_ids": allowed,
            "confidence": output.get("confidence"),
            "warnings": warnings_out,
            "citation_support": {
                "withdrawn": support.withdrawn_count,
                "degraded": support.degraded_count,
                "kept": support.kept_count,
                # Público: sin path JSON ni missing_anchors crudos (telemetría interna).
                "issues": [issue_to_public(issue) for issue in support.issues],
            },
            "job_id": str(job.id),
            "artifact_id": str(artifact.id),
            "audit_log_id": str(result.get("audit_log_id") or ""),
            "provider_path": "signal",
            "task_key": "dossier_question_answer",
            "prompt_runtime_id": PROMPT_RUNTIME_ID,
            "prompt_runtime_version": PROMPT_RUNTIME_VERSION,
            "schema_runtime_version": SCHEMA_RUNTIME_VERSION,
            "signal_provider": getattr(artifact, "provider", None)
            or (artifact.output or {}).get("provider"),
            "signal_model": getattr(artifact, "model", None),
            "validated_output_sha256": validated_hash,
        },
        "meta": {
            "artifact_id": str(artifact.id),
            "audit_log_id": str(result.get("audit_log_id") or ""),
            "task_key": "dossier_question_answer",
            "provider_path": "signal",
            "validated_output_sha256": validated_hash,
            "citation_support_withdrawn": support.withdrawn_count,
            "citation_support_degraded": support.degraded_count,
        },
    }
