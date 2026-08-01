"""Durable tenant-scoped state for Signal delivery and ingestion."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class SignalMonitorConfigVersion(TenantDomainMixin, Base):
    __tablename__ = "signal_monitor_config_versions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_monitor_config_id_tenant"),
        ForeignKeyConstraint(
            ("monitor_id", "tenant_id"),
            ("signal_monitors.id", "signal_monitors.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "created_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "monitor_id", "version", name="uq_monitor_config_version"),
        CheckConstraint("version >= 1", name="monitor_config_version_positive"),
        CheckConstraint("octet_length(snapshot_hash) = 32", name="monitor_config_hash_length"),
        CheckConstraint("jsonb_typeof(snapshot) = 'object'", name="monitor_config_snapshot_object"),
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class IntegrationOutboxEvent(TenantDomainMixin, Base):
    __tablename__ = "integration_outbox_events"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_integration_outbox_id_tenant"),
        ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("monitor_id", "tenant_id"),
            ("signal_monitors.id", "signal_monitors.tenant_id"),
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_integration_outbox_idempotency"),
        CheckConstraint(
            "status IN ('pending','processing','delivered','retrying','failed')",
            name="integration_outbox_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="integration_outbox_attempts"),
        CheckConstraint("octet_length(request_hash) = 32", name="integration_outbox_request_hash"),
        CheckConstraint(
            "octet_length(intention_hash) = 32", name="integration_outbox_intention_hash"
        ),
        CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="integration_outbox_payload_object"
        ),
        Index("ix_integration_outbox_due", "status", "next_attempt_at"),
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    monitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    intention_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(200))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    correlation_id: Mapped[str | None] = mapped_column(String(100))


class IntegrationInboxEvent(TenantDomainMixin, Base):
    __tablename__ = "integration_inbox_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "connection_id", "provider_event_id", name="uq_integration_inbox_provider_event"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_integration_inbox_id_tenant"),
        CheckConstraint(
            "status IN ('received','validated','queued','processed','rejected','failed')",
            name="integration_inbox_status",
        ),
        CheckConstraint("attempts >= 0", name="integration_inbox_attempts"),
        CheckConstraint("octet_length(raw_hash) = 32", name="integration_inbox_hash_length"),
        CheckConstraint(
            "jsonb_typeof(safe_headers) = 'object'", name="integration_inbox_headers_object"
        ),
        Index("ix_integration_inbox_status", "tenant_id", "status", "created_at"),
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(240), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    raw_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    signature_version: Mapped[str] = mapped_column(
        String(30), nullable=False, default="hmac-sha256-v1"
    )
    schema_version: Mapped[str] = mapped_column(
        String(30), nullable=False, default="v1-provisional"
    )
    raw_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    safe_headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="received")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class SignalSyncRun(TenantDomainMixin, Base):
    __tablename__ = "signal_sync_runs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_signal_sync_runs_id_tenant"),
        ForeignKeyConstraint(
            ("monitor_id", "tenant_id"),
            ("signal_monitors.id", "signal_monitors.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed')", name="signal_sync_run_status"
        ),
        CheckConstraint(
            "received >= 0 AND created >= 0 AND duplicates >= 0", name="signal_sync_run_counts"
        ),
        Index("ix_signal_sync_runs_monitor", "tenant_id", "monitor_id", "created_at"),
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cursor_before: Mapped[str | None] = mapped_column(String(500))
    cursor_after: Mapped[str | None] = mapped_column(String(500))
    received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class SignalIngestionRecord(TenantDomainMixin, Base):
    __tablename__ = "signal_ingestion_records"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_signal_ingestion_records_id_tenant"),
        ForeignKeyConstraint(
            ("monitor_id", "tenant_id"),
            ("signal_monitors.id", "signal_monitors.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("sync_run_id", "tenant_id"),
            ("signal_sync_runs.id", "signal_sync_runs.tenant_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("inbox_event_id", "tenant_id"),
            ("integration_inbox_events.id", "integration_inbox_events.tenant_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("signal_id", "tenant_id"), ("signals.id", "signals.tenant_id"), ondelete="RESTRICT"
        ),
        UniqueConstraint(
            "tenant_id", "monitor_id", "provider_signal_id", name="uq_signal_ingestion_provider"
        ),
        CheckConstraint(
            "status IN ('created','changed','duplicate','failed')",
            name="signal_ingestion_status",
        ),
        CheckConstraint("octet_length(content_hash) = 32", name="signal_ingestion_hash_length"),
        CheckConstraint("occurrence_count >= 1", name="signal_ingestion_occurrences"),
    )
    monitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    inbox_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider_signal_id: Mapped[str] = mapped_column(String(240), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(30), nullable=False, default="v1-provisional"
    )
    normalization_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(500))


class DossierMemoryProfile(TenantDomainMixin, Base):
    """Per-tenant dossier memory settings (MDEV-04). No secrets/provider/model."""

    __tablename__ = "dossier_memory_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "connection_id",
            name="uq_dossier_memory_profile_scope",
        ),
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_dmp_tenant",
        ),
        ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="SET NULL",
            name="fk_dmp_connection_tenant",
        ),
        CheckConstraint(
            "mode IN ('disabled','shadow','augment')",
            name="dmp_mode_valid",
        ),
        CheckConstraint("version >= 1", name="dmp_version_positive"),
        CheckConstraint("jsonb_typeof(profile_config) = 'object'", name="dmp_config_object"),
        Index("ix_dmp_tenant_dossier", "tenant_id", "dossier_id"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="disabled")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    etag: Mapped[str] = mapped_column(String(80), nullable=False, default='W/"dmp-v1"')
    profile_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_status: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_coverage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class MemoryRetrievalSnapshot(TenantDomainMixin, Base):
    """Immutable retrieval snapshot per execution (bounded; no raw unlimited)."""

    __tablename__ = "memory_retrieval_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ("tenant_id",),
            ("tenants.id",),
            ondelete="CASCADE",
            name="fk_mrs_tenant",
        ),
        Index("ix_mrs_tenant_dossier", "tenant_id", "dossier_id"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="mrs_payload_object"),
        CheckConstraint("octet_length(context_hash) = 32", name="mrs_hash_length"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(80), nullable=False)
    context_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # post-link audit (nullable; does not mutate frozen content)
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    usage_log_id: Mapped[str | None] = mapped_column(String(80))


INTEGRATION_MODELS = (
    SignalMonitorConfigVersion,
    IntegrationOutboxEvent,
    IntegrationInboxEvent,
    SignalSyncRun,
    SignalIngestionRecord,
    DossierMemoryProfile,
    MemoryRetrievalSnapshot,
)
