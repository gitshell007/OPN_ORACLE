"""Tenant-scoped immutable AI runtime records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class AIAttempt(TenantDomainMixin, Base):
    __tablename__ = "ai_attempts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_attempts_id_tenant"),
        UniqueConstraint("tenant_id", "audit_log_id", "attempt_number", name="uq_ai_attempt_no"),
        ForeignKeyConstraint(
            ("audit_log_id", "tenant_id"),
            ("ai_audit_logs.id", "ai_audit_logs.tenant_id"),
            ondelete="CASCADE",
        ),
        CheckConstraint("attempt_number >= 1", name="ai_attempt_number"),
        CheckConstraint("octet_length(request_hash)=32", name="ai_attempt_request_hash"),
        CheckConstraint(
            "response_hash IS NULL OR octet_length(response_hash)=32",
            name="ai_attempt_response_hash",
        ),
        CheckConstraint("kind IN ('generate','repair','reviewer')", name="ai_attempt_kind"),
        CheckConstraint(
            "status IN ('reserved','running','succeeded','failed','abandoned')",
            name="ai_attempt_status",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_micros >= 0 "
            "AND (latency_ms IS NULL OR latency_ms >= 0)",
            name="ai_attempt_metrics",
        ),
    )
    audit_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="generate")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    response_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIContextSnapshot(TenantDomainMixin, Base):
    __tablename__ = "ai_context_snapshots"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_context_id_tenant"),
        UniqueConstraint("tenant_id", "audit_log_id", name="uq_ai_context_audit"),
        ForeignKeyConstraint(
            ("audit_log_id", "tenant_id"),
            ("ai_audit_logs.id", "ai_audit_logs.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
        ),
        CheckConstraint("octet_length(context_hash)=32", name="ai_context_hash"),
        CheckConstraint("jsonb_typeof(source_manifest)='object'", name="ai_context_manifest"),
        CheckConstraint("jsonb_typeof(redaction_summary)='object'", name="ai_context_redaction"),
        CheckConstraint(
            "jsonb_typeof(injection_indicators)='array'", name="ai_context_injection_indicators"
        ),
        CheckConstraint(
            "classification IN ('public','internal')", name="ai_context_classification"
        ),
        CheckConstraint("estimated_tokens >= 0", name="ai_context_estimated_tokens"),
    )
    audit_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    context_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    source_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    classification: Mapped[str] = mapped_column(String(30), nullable=False)
    redaction_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    injection_indicators: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)


class AIContextEvidence(Base):
    __tablename__ = "ai_context_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("snapshot_id", "tenant_id"),
            ("ai_context_snapshots.id", "ai_context_snapshots.tenant_id"),
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint("octet_length(evidence_hash)=32", name="ai_context_evidence_hash"),
        ForeignKeyConstraint(
            ("tenant_id", "evidence_id", "dossier_id"),
            (
                "evidence_dossiers.tenant_id",
                "evidence_dossiers.evidence_id",
                "evidence_dossiers.dossier_id",
            ),
            ondelete="RESTRICT",
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)


class AIArtifact(TenantDomainMixin, Base):
    __tablename__ = "ai_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_artifacts_id_tenant"),
        UniqueConstraint("tenant_id", "audit_log_id", name="uq_ai_artifact_audit"),
        ForeignKeyConstraint(
            ("audit_log_id", "tenant_id"),
            ("ai_audit_logs.id", "ai_audit_logs.tenant_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('candidate','valid','rejected','superseded')", name="ai_artifact_status"
        ),
        CheckConstraint("octet_length(output_hash)=32", name="ai_artifact_output_hash"),
        CheckConstraint("jsonb_typeof(output)='object'", name="ai_artifact_output_object"),
        CheckConstraint("version >= 1", name="ai_artifact_version"),
        Index("ix_ai_artifact_target", "tenant_id", "target_type", "target_id", "created_at"),
    )
    audit_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    agent: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(150), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="candidate")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AIHumanReview(TenantDomainMixin, Base):
    __tablename__ = "ai_human_reviews"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_reviews_id_tenant"),
        ForeignKeyConstraint(
            ("artifact_id", "tenant_id"),
            ("ai_artifacts.id", "ai_artifacts.tenant_id"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewer_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "decision IN ('accepted','rejected','changes_requested')", name="ai_review_decision"
        ),
        CheckConstraint("jsonb_typeof(override)='object'", name="ai_review_override"),
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    override: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AITenantPolicy(TenantDomainMixin, Base):
    __tablename__ = "ai_tenant_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_ai_policy_tenant"),
        CheckConstraint(
            "provider IN ('disabled','mock','ollama','signal')", name="ai_policy_provider"
        ),
        CheckConstraint("jsonb_typeof(allowed_models)='array'", name="ai_policy_models"),
        CheckConstraint(
            "max_classification IN ('public','internal')", name="ai_policy_classification"
        ),
        CheckConstraint("jsonb_typeof(redaction_profile)='object'", name="ai_policy_redaction"),
        CheckConstraint(
            "monthly_soft_budget_micros >= 0 AND monthly_hard_budget_micros >= 0 "
            "AND (monthly_hard_budget_micros = 0 OR "
            "monthly_soft_budget_micros <= monthly_hard_budget_micros) "
            "AND daily_call_limit >= 0 AND max_context_tokens >= 1 AND max_output_tokens >= 1",
            name="ai_policy_limits",
        ),
        CheckConstraint("max_concurrency >= 1", name="ai_policy_concurrency"),
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="disabled")
    allowed_models: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    max_classification: Mapped[str] = mapped_column(String(30), nullable=False, default="public")
    monthly_soft_budget_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monthly_hard_budget_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_call_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=8000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=6500)
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    redaction_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AIUsageLedger(TenantDomainMixin, Base):
    __tablename__ = "ai_usage_ledger"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_usage_id_tenant"),
        ForeignKeyConstraint(
            ("audit_log_id", "tenant_id"),
            ("ai_audit_logs.id", "ai_audit_logs.tenant_id"),
            ondelete="RESTRICT",
        ),
        Index("ix_ai_usage_period", "tenant_id", "period", "created_at"),
        CheckConstraint(
            "reserved_cost_micros >= 0 AND actual_cost_micros >= 0", name="ai_usage_cost"
        ),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ai_usage_tokens"),
        CheckConstraint("period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'", name="ai_usage_period"),
        CheckConstraint("status IN ('reserved','settled','released')", name="ai_usage_status"),
        UniqueConstraint("tenant_id", "audit_log_id", name="uq_ai_usage_audit"),
    )
    audit_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="reserved")
    execution_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


AI_MODELS = (
    AIAttempt,
    AIContextSnapshot,
    AIContextEvidence,
    AIArtifact,
    AIHumanReview,
    AITenantPolicy,
    AIUsageLedger,
)
