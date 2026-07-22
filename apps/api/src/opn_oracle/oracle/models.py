"""Persistent tenant-scoped strategic intelligence domain."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.platform.models import TimestampMixin, UUIDPrimaryKeyMixin


class TenantDomainMixin(UUIDPrimaryKeyMixin, TimestampMixin):
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


class StrategicDossier(TenantDomainMixin, Base):
    __tablename__ = "strategic_dossiers"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_strategic_dossiers_id_tenant"),
        ForeignKeyConstraint(
            ("workspace_id", "tenant_id"),
            ("workspaces.id", "workspaces.tenant_id"),
            ondelete="RESTRICT",
            name="fk_dossiers_workspace_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "owner_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_dossiers_owner_membership",
        ),
        CheckConstraint("status IN ('draft','active','paused','archived')", name="dossier_status"),
        CheckConstraint("version >= 1", name="dossier_version_positive"),
        CheckConstraint("jsonb_typeof(profile_config)='object'", name="dossier_profile_config"),
        CheckConstraint(
            "health_score BETWEEN 0 AND 100 AND opportunity_score BETWEEN 0 AND 100 "
            "AND risk_score BETWEEN 0 AND 100",
            name="dossier_scores_range",
        ),
        Index("ix_dossiers_tenant_status_updated", "tenant_id", "status", "updated_at"),
        Index("ix_dossiers_tenant_owner", "tenant_id", "owner_user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dossier_type: Mapped[str] = mapped_column(String(50), nullable=False, default="custom")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    strategic_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    geography: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    sectors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    languages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    scoring_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    profile_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    health_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunity_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_explanation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    synthetic_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DossierObjective(TenantDomainMixin, Base):
    __tablename__ = "dossier_objectives"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_objectives_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_objectives_dossier_tenant",
        ),
        CheckConstraint(
            "status IN ('open','in_progress','achieved','cancelled')", name="objective_status"
        ),
        UniqueConstraint("tenant_id", "dossier_id", "position", name="uq_objective_position"),
        CheckConstraint("version >= 1", name="objective_version_positive"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    target_date: Mapped[date | None] = mapped_column(Date)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Hypothesis(TenantDomainMixin, Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_hypotheses_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_hypotheses_dossier_tenant",
        ),
        CheckConstraint(
            "status IN ('open','supported','contradicted','discarded')", name="hypothesis_status"
        ),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="hypothesis_confidence"),
        UniqueConstraint("tenant_id", "dossier_id", "position", name="uq_hypothesis_position"),
        CheckConstraint("version >= 1", name="hypothesis_version_positive"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Watchlist(TenantDomainMixin, Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_watchlists_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_watchlists_dossier_tenant",
        ),
        CheckConstraint("status IN ('active','paused','archived')", name="watchlist_status"),
        CheckConstraint("version >= 1", name="watchlist_version_positive"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    query_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cadence: Mapped[str] = mapped_column(String(50), nullable=False, default="daily")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SignalMonitor(TenantDomainMixin, Base):
    __tablename__ = "signal_monitors"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_signal_monitors_id_tenant"),
        ForeignKeyConstraint(
            ("watchlist_id", "tenant_id"),
            ("watchlists.id", "watchlists.tenant_id"),
            ondelete="CASCADE",
            name="fk_monitors_watchlist_tenant",
        ),
        ForeignKeyConstraint(
            ("connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="RESTRICT",
            name="fk_monitors_connection_tenant",
        ),
        UniqueConstraint(
            "tenant_id", "provider", "external_id", name="uq_monitor_provider_external"
        ),
        CheckConstraint("status IN ('active','paused','error')", name="signal_monitor_status"),
        CheckConstraint(
            "desired_status IN ('active','paused','disabled')",
            name="signal_monitor_desired_status",
        ),
        CheckConstraint(
            "observed_status IN ('pending','active','paused','disabled','error')",
            name="signal_monitor_observed_status",
        ),
        CheckConstraint("version >= 1", name="signal_monitor_version_positive"),
    )
    watchlist_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    desired_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    observed_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    cursor: Mapped[str | None] = mapped_column(String(500))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Signal(TenantDomainMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_signals_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "provider_connection_id",
            "external_id",
            name="uq_signal_connection_external",
        ),
        ForeignKeyConstraint(
            ("provider_connection_id", "tenant_id"),
            ("integration_connections.id", "integration_connections.tenant_id"),
            ondelete="RESTRICT",
            name="fk_signals_connection_tenant",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider_connection_id",
            "raw_hash",
            name="uq_signal_connection_raw_hash",
        ),
        CheckConstraint("credibility BETWEEN 0 AND 100", name="signal_credibility"),
        Index("ix_signals_tenant_published", "tenant_id", "published_at"),
        Index(
            "ix_signals_tenant_connection_dedupe",
            "tenant_id",
            "provider_connection_id",
            "dedupe_key",
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    external_id: Mapped[str] = mapped_column(String(240), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_name: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    canonical_source_url: Mapped[str | None] = mapped_column(String(1500))
    dedupe_key: Mapped[str | None] = mapped_column(String(2000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    language: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    entities: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    categories: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    raw_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    credibility: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DossierSignal(TenantDomainMixin, Base):
    __tablename__ = "dossier_signals"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_signals_id_tenant"),
        UniqueConstraint(
            "id", "dossier_id", "tenant_id", name="uq_dossier_signals_id_dossier_tenant"
        ),
        UniqueConstraint(
            "signal_id",
            "dossier_id",
            "tenant_id",
            name="uq_dossier_signals_signal_dossier_tenant",
        ),
        UniqueConstraint("tenant_id", "dossier_id", "signal_id", name="uq_dossier_signal_link"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_signals_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("signal_id", "tenant_id"),
            ("signals.id", "signals.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_signals_signal_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewer_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_dossier_signals_reviewer_membership",
        ),
        CheckConstraint(
            "status IN ('new','reviewed','dismissed','promoted')", name="dossier_signal_status"
        ),
        CheckConstraint(
            "relevance BETWEEN 0 AND 100 AND novelty BETWEEN 0 AND 100 "
            "AND confidence BETWEEN 0 AND 100 AND strategic_impact BETWEEN 0 AND 100 "
            "AND overall_score BETWEEN 0 AND 100",
            name="dossier_signal_scores",
        ),
        Index("ix_dossier_signals_inbox", "tenant_id", "dossier_id", "status", "updated_at"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    relevance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    novelty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategic_impact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    triage_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promoted_resource_type: Mapped[str | None] = mapped_column(String(30))
    promoted_resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DossierProcurementItem(TenantDomainMixin, Base):
    __tablename__ = "dossier_procurement_items"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_procurement_items_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "kind",
            "folder_id",
            name="uq_dossier_procurement_item_folder",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_procurement_items_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="RESTRICT",
            name="fk_dossier_procurement_items_evidence_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "pinned_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_dossier_procurement_items_pinner_membership",
        ),
        ForeignKeyConstraint(
            ("linked_opportunity_id", "tenant_id"),
            ("opportunities.id", "opportunities.tenant_id"),
            ondelete="RESTRICT",
            name="fk_dossier_procurement_items_opportunity_tenant",
        ),
        CheckConstraint("kind IN ('tender','award')", name="dossier_procurement_item_kind"),
        CheckConstraint("jsonb_typeof(snapshot)='object'", name="procurement_snapshot_object"),
        Index("ix_dossier_procurement_items_dossier", "tenant_id", "dossier_id"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    folder_id: Mapped[str] = mapped_column(String(240), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_url: Mapped[str | None] = mapped_column(String(1500))
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    pinned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    linked_opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Evidence(TenantDomainMixin, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_evidence_id_tenant"),
        ForeignKeyConstraint(
            ("signal_id", "tenant_id"),
            ("signals.id", "signals.tenant_id"),
            ondelete="RESTRICT",
            name="fk_evidence_signal_tenant",
        ),
        ForeignKeyConstraint(
            ("document_id", "tenant_id"),
            ("documents.id", "documents.tenant_id"),
            ondelete="RESTRICT",
            name="fk_evidence_document_tenant",
        ),
        ForeignKeyConstraint(
            ("document_version_id", "document_id", "tenant_id"),
            (
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.tenant_id",
            ),
            ondelete="RESTRICT",
            name="fk_evidence_document_version_context",
        ),
        ForeignKeyConstraint(
            ("document_chunk_id", "document_version_id", "tenant_id"),
            (
                "document_chunks.id",
                "document_chunks.document_version_id",
                "document_chunks.tenant_id",
            ),
            ondelete="RESTRICT",
            name="fk_evidence_document_chunk_context",
        ),
        CheckConstraint("classification IN ('public','internal')", name="evidence_classification"),
        CheckConstraint("version >= 1", name="evidence_version_positive"),
        CheckConstraint(
            "(source_kind='signal' AND signal_id IS NOT NULL AND document_id IS NULL "
            "AND document_version_id IS NULL AND document_chunk_id IS NULL) OR "
            "(source_kind='document' AND signal_id IS NULL AND document_id IS NOT NULL "
            "AND document_version_id IS NOT NULL AND document_chunk_id IS NOT NULL) OR "
            "(source_kind='legacy_unresolved' AND signal_id IS NULL AND document_id IS NULL "
            "AND document_version_id IS NULL AND document_chunk_id IS NULL "
            'AND provenance @> \'{"migration_status":"quarantined_missing_source"}\'::jsonb) OR '
            "(source_kind='procurement' AND signal_id IS NULL AND document_id IS NULL "
            'AND provenance @> \'{"source_kind":"procurement"}\'::jsonb) OR '
            "(source_kind='entity_intel' AND signal_id IS NULL AND document_id IS NULL "
            "AND document_version_id IS NULL AND document_chunk_id IS NULL "
            'AND provenance @> \'{"source_kind":"entity_intel"}\'::jsonb)',
            name="evidence_source_shape",
        ),
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="signal")
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_url: Mapped[str | None] = mapped_column(String(1500))
    extract: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    checksum: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ScoredResourceMixin:
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    score_override: Mapped[int | None] = mapped_column(Integer)
    score_override_reason: Mapped[str | None] = mapped_column(String(1000))
    score_override_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Opportunity(ScoredResourceMixin, TenantDomainMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_opportunities_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_opportunities_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("source_dossier_signal_id", "dossier_id", "tenant_id"),
            ("dossier_signals.id", "dossier_signals.dossier_id", "dossier_signals.tenant_id"),
            name="fk_opportunities_source_signal_context",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "owner_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_opportunities_owner_membership",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "score_override_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_opportunities_override_membership",
        ),
        CheckConstraint(
            "strategic_fit BETWEEN 0 AND 100 AND urgency BETWEEN 0 AND 100 "
            "AND expected_value BETWEEN 0 AND 100 AND actionability BETWEEN 0 AND 100 "
            "AND relationship_leverage BETWEEN 0 AND 100 AND timing BETWEEN 0 AND 100 "
            "AND confidence BETWEEN 0 AND 100 AND effort BETWEEN 0 AND 100 "
            "AND blocking_risk BETWEEN 0 AND 100 AND overall_score BETWEEN 0 AND 100",
            name="opportunity_scores",
        ),
        CheckConstraint(
            "status IN ('identified','qualified','pursuing','won','lost','dismissed')",
            name="opportunity_status",
        ),
        CheckConstraint("version >= 1", name="opportunity_version_positive"),
        CheckConstraint(
            "score_override IS NULL OR (score_override_reason IS NOT NULL "
            "AND score_override_by_user_id IS NOT NULL)",
            name="opportunity_override_attribution",
        ),
        Index("ix_opportunities_tenant_dossier_status", "tenant_id", "dossier_id", "status"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(80), nullable=False, default="custom")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="identified")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    strategic_fit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    urgency: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expected_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actionability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationship_leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocking_risk: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deadline: Mapped[date | None] = mapped_column(Date)
    next_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    source_dossier_signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class RiskItem(ScoredResourceMixin, TenantDomainMixin, Base):
    __tablename__ = "risk_items"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_risk_items_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_risks_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("source_dossier_signal_id", "dossier_id", "tenant_id"),
            ("dossier_signals.id", "dossier_signals.dossier_id", "dossier_signals.tenant_id"),
            name="fk_risks_source_signal_context",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "owner_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_risks_owner_membership",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "score_override_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_risks_override_membership",
        ),
        CheckConstraint(
            "likelihood BETWEEN 0 AND 100 AND impact BETWEEN 0 AND 100 "
            "AND velocity BETWEEN 0 AND 100 AND exposure BETWEEN 0 AND 100 "
            "AND uncertainty BETWEEN 0 AND 100 AND controllability BETWEEN 0 AND 100 "
            "AND confidence BETWEEN 0 AND 100 AND overall_score BETWEEN 0 AND 100",
            name="risk_scores",
        ),
        CheckConstraint(
            "status IN ('open','monitoring','mitigated','accepted','closed')",
            name="risk_status",
        ),
        CheckConstraint("version >= 1", name="risk_version_positive"),
        CheckConstraint(
            "score_override IS NULL OR (score_override_reason IS NOT NULL "
            "AND score_override_by_user_id IS NOT NULL)",
            name="risk_override_attribution",
        ),
        Index("ix_risks_tenant_dossier_status", "tenant_id", "dossier_id", "status"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="strategic")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    likelihood: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    impact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    velocity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exposure: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uncertainty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    controllability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    source_dossier_signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Actor(TenantDomainMixin, Base):
    __tablename__ = "actors"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_actors_id_tenant"),
        UniqueConstraint("tenant_id", "canonical_key", name="uq_actor_canonical_key"),
        Index("ix_actors_tenant_name", "tenant_id", "canonical_name"),
        CheckConstraint("version >= 1", name="actor_version_positive"),
    )
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False)
    aliases: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    identifiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    actor_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DossierActor(TenantDomainMixin, Base):
    __tablename__ = "dossier_actors"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_dossier_actors_id_tenant"),
        UniqueConstraint("tenant_id", "dossier_id", "actor_id", name="uq_dossier_actor_link"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_actors_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_dossier_actors_actor_tenant",
        ),
        CheckConstraint(
            "influence BETWEEN 0 AND 100 AND relevance_to_dossier BETWEEN 0 AND 100 "
            "AND relationship_strength BETWEEN 0 AND 100 AND accessibility BETWEEN 0 AND 100 "
            "AND strategic_alignment BETWEEN 0 AND 100 AND recent_activity BETWEEN 0 AND 100 "
            "AND priority BETWEEN 0 AND 100",
            name="dossier_actor_scores",
        ),
        CheckConstraint("version >= 1", name="dossier_actor_version_positive"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    influence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_to_dossier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relationship_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accessibility: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    strategic_alignment: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_activity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ActorCandidateReview(TenantDomainMixin, Base):
    __tablename__ = "actor_candidate_reviews"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_actor_candidate_reviews_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "canonical_key",
            name="uq_actor_candidate_review_key",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_actor_candidate_reviews_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewed_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_actor_candidate_reviews_reviewer_membership",
        ),
        CheckConstraint("status IN ('dismissed','imported')", name="actor_candidate_review_status"),
        CheckConstraint("version >= 1", name="actor_candidate_review_version_positive"),
        Index(
            "ix_actor_candidate_reviews_dossier_status",
            "tenant_id",
            "dossier_id",
            "status",
        ),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(320), nullable=False)
    candidate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source_signal_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    review_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    reviewed_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Relationship(TenantDomainMixin, Base):
    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_relationships_id_tenant"),
        ForeignKeyConstraint(
            ("from_actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_relationship_from_actor_tenant",
        ),
        ForeignKeyConstraint(
            ("to_actor_id", "tenant_id"),
            ("actors.id", "actors.tenant_id"),
            ondelete="CASCADE",
            name="fk_relationship_to_actor_tenant",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_relationship_dossier_tenant",
        ),
        CheckConstraint("from_actor_id <> to_actor_id", name="relationship_distinct_actors"),
        CheckConstraint("version >= 1", name="relationship_version_positive"),
    )
    from_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    relationship_type: Mapped[str] = mapped_column(String(80), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="directed")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SimpleDossierResourceMixin(TenantDomainMixin):
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Meeting(SimpleDossierResourceMixin, Base):
    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_meetings_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_meetings_dossier_tenant",
        ),
        CheckConstraint("status IN ('planned','completed','cancelled')", name="meeting_status"),
        CheckConstraint("version >= 1", name="meeting_version_positive"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Briefing(TenantDomainMixin, Base):
    __tablename__ = "briefings"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_briefings_id_tenant"),
        ForeignKeyConstraint(
            ("meeting_id", "tenant_id"),
            ("meetings.id", "meetings.tenant_id"),
            ondelete="CASCADE",
            name="fk_briefing_meeting_tenant",
        ),
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Decision(SimpleDossierResourceMixin, Base):
    __tablename__ = "decisions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_decisions_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_decisions_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "decided_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_decisions_actor_membership",
        ),
        CheckConstraint(
            "status IN ('proposed','approved','rejected','superseded')", name="decision_status"
        ),
        CheckConstraint("version >= 1", name="decision_version_positive"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Task(SimpleDossierResourceMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_tasks_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_tasks_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "owner_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_tasks_owner_membership",
        ),
        CheckConstraint(
            "status IN ('open','in_progress','blocked','done','cancelled')", name="task_status"
        ),
        CheckConstraint("version >= 1", name="task_version_positive"),
        Index("ix_tasks_tenant_owner_due", "tenant_id", "owner_user_id", "due_date"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    linked_resource_type: Mapped[str | None] = mapped_column(String(80))
    linked_resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")


class Insight(SimpleDossierResourceMixin, Base):
    __tablename__ = "insights"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_insights_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_insights_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("ai_audit_log_id", "tenant_id"),
            ("ai_audit_logs.id", "ai_audit_logs.tenant_id"),
            name="fk_insights_ai_audit_tenant",
        ),
        CheckConstraint("status IN ('draft','valid','rejected')", name="insight_status"),
        CheckConstraint("version >= 1", name="insight_version_positive"),
    )
    insight_type: Mapped[str] = mapped_column(String(80), nullable=False)
    facts: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    inferences: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_audit_log_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Feedback(TenantDomainMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_feedback_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_feedback_dossier_tenant",
        ),
        CheckConstraint("version >= 1", name="feedback_version_positive"),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    correction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Report(SimpleDossierResourceMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_reports_id_tenant"),
        UniqueConstraint("id", "dossier_id", "tenant_id", name="uq_reports_id_dossier_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_reports_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "generated_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_reports_generator_membership",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "requested_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_reports_requester_membership",
        ),
        ForeignKeyConstraint(
            ("background_job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_reports_background_job_tenant",
        ),
        ForeignKeyConstraint(
            ("ai_artifact_id", "tenant_id"),
            ("ai_artifacts.id", "ai_artifacts.tenant_id"),
            ondelete="RESTRICT",
            name="fk_reports_ai_artifact_tenant",
        ),
        ForeignKeyConstraint(
            ("parent_report_id", "dossier_id", "tenant_id"),
            ("reports.id", "reports.dossier_id", "reports.tenant_id"),
            ondelete="RESTRICT",
            name="fk_reports_parent_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewed_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_reports_reviewer_membership",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "published_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_reports_publisher_membership",
        ),
        CheckConstraint(
            "status IN ('draft','generating','ready','reviewed','published','failed','superseded')",
            name="report_status",
        ),
        CheckConstraint("version >= 1", name="report_version_positive"),
        CheckConstraint("generation_version >= 1", name="report_generation_version_positive"),
        CheckConstraint("classification IN ('public','internal')", name="report_classification"),
        CheckConstraint("jsonb_typeof(options)='object'", name="report_options_object"),
        CheckConstraint("jsonb_typeof(source_snapshot)='object'", name="report_snapshot_object"),
        CheckConstraint("octet_length(source_snapshot_hash)=32", name="report_snapshot_hash_size"),
        CheckConstraint(
            "snapshot_hash_algorithm IN "
            "('canonical-json-sha256-v1','postgres-jsonb-text-sha256-v1')",
            name="report_snapshot_hash_algorithm",
        ),
        UniqueConstraint(
            "tenant_id",
            "dossier_id",
            "template_key",
            "generation_version",
            name="uq_report_template_generation",
        ),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_report_idempotency"),
        CheckConstraint("octet_length(request_hash)=32", name="report_request_hash_size"),
        Index("ix_reports_tenant_status_updated", "tenant_id", "status", "updated_at"),
        Index("ix_reports_tenant_dossier_created", "tenant_id", "dossier_id", "created_at"),
    )
    report_type: Mapped[str] = mapped_column(String(80), nullable=False)
    template_key: Mapped[str] = mapped_column(String(100), nullable=False)
    template_version: Mapped[str] = mapped_column(String(30), nullable=False, default="v1")
    generation_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_snapshot_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    snapshot_hash_algorithm: Mapped[str] = mapped_column(
        String(50), nullable=False, default="canonical-json-sha256-v1"
    )
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    confidentiality_label: Mapped[str] = mapped_column(
        String(120), nullable=False, default="Uso interno"
    )
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ai_artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    parent_report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(500))


class LivingSummary(TenantDomainMixin, Base):
    __tablename__ = "living_summaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dossier_id", name="uq_living_summary_dossier"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_living_summary_dossier_tenant",
        ),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScoreHistory(TenantDomainMixin, Base):
    __tablename__ = "score_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            name="fk_score_history_dossier_tenant",
            ondelete="CASCADE",
        ),
        Index(
            "ix_score_history_resource", "tenant_id", "resource_type", "resource_id", "created_at"
        ),
    )
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class StatusHistory(TenantDomainMixin, Base):
    __tablename__ = "status_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_status_history_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "actor_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_status_history_actor_membership",
        ),
        Index(
            "ix_status_history_resource", "tenant_id", "resource_type", "resource_id", "created_at"
        ),
    )
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_status: Mapped[str] = mapped_column(String(40), nullable=False)
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False, default="")


ORACLE_MODELS = (
    StrategicDossier,
    DossierObjective,
    Hypothesis,
    Watchlist,
    SignalMonitor,
    Signal,
    DossierSignal,
    Evidence,
    Opportunity,
    RiskItem,
    Actor,
    DossierActor,
    Relationship,
    Meeting,
    Briefing,
    Decision,
    Task,
    Insight,
    Feedback,
    Report,
    LivingSummary,
    ScoreHistory,
    StatusHistory,
)
