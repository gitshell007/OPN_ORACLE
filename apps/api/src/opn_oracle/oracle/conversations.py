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
) -> dict[str, Any]:
    """Real job handler body: retrieve context (mock/disabled) and settle the message.

    Never mutates IntentRevision or promotes memory facts. Uses no paid providers.
    ``memory_adapter`` is injectable for tests; production resolves from Flask config.
    """

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
        from opn_oracle.integrations.memory_context import (
            MemoryContextDisabled,
            get_memory_context_adapter,
        )

        try:
            adapter = get_memory_context_adapter()
        except Exception as error:  # pragma: no cover - defensive config
            raise ConversationError("No se pudo resolver el adaptador de memoria.") from error
    else:
        from opn_oracle.integrations.memory_context import MemoryContextDisabled

    scope_hint = {
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
        "job_id": str(job.id),
    }
    try:
        retrieval = adapter.retrieve(
            scope_hint,
            message.content_text,
            "question",
            20,
        )
        coverage = dict(retrieval.get("coverage_manifest") or {})
        items = list(retrieval.get("items") or [])
        policy = str(retrieval.get("policy_version") or "unknown")
    except MemoryContextDisabled:
        from opn_oracle.integrations.memory_context import empty_coverage_manifest

        items = []
        coverage = empty_coverage_manifest(requested=["memory.disabled"])
        coverage["excluded"] = [{"source": "memory", "reason": "policy"}]
        policy = "disabled"
    except Exception as error:
        mark_message_failed(
            message,
            error_code="memory_context_error",
            error_message=str(error)[:500],
        )
        session.flush()
        raise ConversationError(f"Fallo al recuperar contexto: {error}") from error

    if job.cancel_requested:
        cancel_message(message)
        session.flush()
        return {"message_id": str(message.id), "status": "cancelled", "cancelled": True}

    # Deterministic grounded draft: no external LLM, no paid provider.
    if items:
        excerpts = []
        for item in items[:5]:
            text_bit = str(item.get("text") or "").strip()
            if text_bit:
                excerpts.append(text_bit[:400])
        body = (
            "Respuesta provisional a partir del contexto autorizado "
            f"({len(items)} fragmentos, policy={policy}):\n\n"
            + "\n".join(f"- {excerpt}" for excerpt in excerpts)
        )
        unknowns: list[str] = []
    else:
        body = (
            "No hay evidencia suficiente en la memoria autorizada del expediente "
            "para responder con citas. Reformula la pregunta o amplía las fuentes "
            f"del expediente (policy={policy})."
        )
        unknowns = ["evidencia_en_memoria"]

    apply_assistant_answer(
        message,
        answer_text=body,
        answer_payload={
            "policy_version": policy,
            "item_count": len(items),
            "unknowns": unknowns,
            "facts": [],
            "inferences": [],
            "recommendations": [],
            "job_id": str(job.id),
        },
        coverage_manifest=coverage,
    )
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
            "item_count": len(items),
            "mutates_intent": False,
            "mutates_memory_facts": False,
        },
    )
    session.flush()
    return {
        "message_id": str(message.id),
        "status": message.status,
        "item_count": len(items),
        "policy_version": policy,
        "mutates_intent": False,
        "mutates_memory_facts": False,
    }
