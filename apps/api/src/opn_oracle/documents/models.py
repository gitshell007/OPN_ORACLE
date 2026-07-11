"""Tenant-scoped document lifecycle and immutable extracted content."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class Document(TenantDomainMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_documents_id_tenant"),
        UniqueConstraint("tenant_id", "storage_key", name="uq_documents_tenant_storage_key"),
        UniqueConstraint("id", "dossier_id", "tenant_id", name="uq_documents_context"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_documents_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "uploaded_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_documents_uploader_membership",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "deleted_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_documents_deleter_membership",
        ),
        ForeignKeyConstraint(
            ("current_version_id", "id", "tenant_id"),
            (
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.tenant_id",
            ),
            name="fk_documents_current_version_context",
            use_alter=True,
        ),
        CheckConstraint(
            "status IN ('uploaded','queued','processing','ready','failed','quarantined','deleted')",
            name="document_status",
        ),
        CheckConstraint("classification IN ('public','internal')", name="document_classification"),
        CheckConstraint("version >= 1 AND byte_size >= 0", name="document_version_size"),
        CheckConstraint(
            "octet_length(checksum)=32 AND length(storage_key) BETWEEN 1 AND 600",
            name="document_storage_integrity",
        ),
        CheckConstraint(
            "jsonb_typeof(scan_result)='object' AND jsonb_typeof(metadata)='object'",
            name="document_json_objects",
        ),
        CheckConstraint(
            "scan_status IN ('pending','clean','infected','error','not_configured')",
            name="document_scan_status",
        ),
        CheckConstraint(
            "(status='deleted') = (deleted_at IS NOT NULL)", name="document_deleted_state"
        ),
        Index("ix_documents_dossier_status", "tenant_id", "dossier_id", "status", "updated_at"),
        Index("ix_documents_retention", "tenant_id", "deleted_at", "purge_after"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scan_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    scan_result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DocumentVersion(TenantDomainMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_document_versions_id_tenant"),
        UniqueConstraint("id", "document_id", "tenant_id", name="uq_document_versions_context"),
        UniqueConstraint(
            "tenant_id", "document_id", "version_number", name="uq_document_version_no"
        ),
        ForeignKeyConstraint(
            ("document_id", "dossier_id", "tenant_id"),
            ("documents.id", "documents.dossier_id", "documents.tenant_id"),
            ondelete="CASCADE",
            name="fk_document_versions_document_context",
        ),
        CheckConstraint("version_number >= 1", name="document_version_number"),
        CheckConstraint(
            "status IN ('queued','scanning','processing','ready','failed',"
            "'quarantined','superseded','purged')",
            name="document_version_status",
        ),
        CheckConstraint("octet_length(source_checksum)=32", name="document_version_checksum"),
        CheckConstraint("jsonb_typeof(provenance)='object'", name="document_version_provenance"),
        Index("ix_document_versions_document", "tenant_id", "document_id", "version_number"),
    )
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    parser_name: Mapped[str | None] = mapped_column(String(80))
    parser_version: Mapped[str | None] = mapped_column(String(40))
    chunker_version: Mapped[str | None] = mapped_column(String(40))
    source_checksum: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    processing_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(TenantDomainMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_document_chunks_id_tenant"),
        UniqueConstraint(
            "id", "document_version_id", "tenant_id", name="uq_document_chunks_context"
        ),
        UniqueConstraint(
            "tenant_id", "document_version_id", "sequence", name="uq_document_chunk_sequence"
        ),
        ForeignKeyConstraint(
            ("document_version_id", "document_id", "tenant_id"),
            (
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.tenant_id",
            ),
            ondelete="CASCADE",
            name="fk_document_chunks_version_context",
        ),
        ForeignKeyConstraint(
            ("document_id", "dossier_id", "tenant_id"),
            ("documents.id", "documents.dossier_id", "documents.tenant_id"),
            ondelete="CASCADE",
            name="fk_document_chunks_document_context",
        ),
        CheckConstraint(
            "sequence >= 0 AND char_start >= 0 AND char_end > char_start",
            name="document_chunk_offsets",
        ),
        CheckConstraint("octet_length(checksum)=32", name="document_chunk_checksum"),
        CheckConstraint(
            "jsonb_typeof(locator)='object' AND jsonb_typeof(provenance)='object'",
            name="document_chunk_json_objects",
        ),
        Index("ix_document_chunks_dossier", "tenant_id", "dossier_id", "document_id", "sequence"),
        Index("ix_document_chunks_search", "search_vector", postgresql_using="gin"),
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    paragraph_number: Mapped[int | None] = mapped_column(Integer)
    time_start_ms: Mapped[int | None] = mapped_column(Integer)
    time_end_ms: Mapped[int | None] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(160))
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', coalesce(text_content, ''))", persisted=True)
    )


class DocumentProcessingAttempt(TenantDomainMixin, Base):
    __tablename__ = "document_processing_attempts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_document_attempts_id_tenant"),
        UniqueConstraint(
            "tenant_id", "document_version_id", "attempt_number", name="uq_document_attempt_no"
        ),
        ForeignKeyConstraint(
            ("document_version_id", "tenant_id"),
            ("document_versions.id", "document_versions.tenant_id"),
            ondelete="CASCADE",
            name="fk_document_attempt_version_tenant",
        ),
        ForeignKeyConstraint(
            ("background_job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_document_attempt_job_tenant",
        ),
        CheckConstraint("attempt_number >= 1", name="document_attempt_number"),
        CheckConstraint(
            "status IN ('reserved','scanning','parsing','chunking','succeeded',"
            "'failed','abandoned')",
            name="document_attempt_status",
        ),
        Index("ix_document_attempt_lease", "tenant_id", "status", "lease_expires_at"),
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    background_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="reserved")
    execution_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentRetentionPolicy(TenantDomainMixin, Base):
    __tablename__ = "document_retention_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_document_retention_tenant"),
        CheckConstraint(
            "retention_days >= 1 AND purge_grace_days >= 0", name="document_retention_days"
        ),
    )
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=365)
    purge_grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    preserve_metadata: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


DOCUMENT_MODELS = (
    Document,
    DocumentVersion,
    DocumentChunk,
    DocumentProcessingAttempt,
    DocumentRetentionPolicy,
)
