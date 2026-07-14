"""Durable hooks consumed by Celery and AI phases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class BackgroundJob(TenantDomainMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_background_jobs_id_tenant"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_background_job_idempotency"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_background_jobs_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "requested_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_background_job_requester_membership",
        ),
        Index("ix_background_jobs_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_background_jobs_not_before", "status", "not_before"),
        Index("ix_background_jobs_heartbeat", "status", "heartbeat_at"),
        Index("ix_background_jobs_lease_expiry", "status", "lease_expires_at"),
        Index("ix_background_jobs_celery_task_id", "celery_task_id", unique=True),
        CheckConstraint("progress BETWEEN 0 AND 100", name="background_job_progress"),
        CheckConstraint("version >= 1", name="background_job_version"),
        CheckConstraint(
            "jsonb_typeof(input_payload) = 'object'", name="background_job_input_object"
        ),
        CheckConstraint("jsonb_typeof(result_ref) = 'object'", name="background_job_result_object"),
        CheckConstraint(
            "(execution_lease_id IS NULL) = (lease_expires_at IS NULL)",
            name="background_job_lease_pair",
        ),
        CheckConstraint(
            "status IN ('queued','running','retrying','succeeded','failed','cancelled')",
            name="background_job_status",
        ),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="background_job_attempts"),
    )
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    queue: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(100))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stage: Mapped[str] = mapped_column(
        String(100), nullable=False, default="queued", server_default="queued"
    )
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    payload_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(String(100))
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publish_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_publish_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobSchedule(TenantDomainMixin, Base):
    __tablename__ = "job_schedules"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_job_schedules_id_tenant"),
        UniqueConstraint("tenant_id", "schedule_key", name="uq_job_schedule_key"),
        Index("ix_job_schedules_due", "enabled", "next_run_at"),
        CheckConstraint("cadence_seconds >= 60", name="job_schedule_cadence"),
        CheckConstraint("schedule_kind IN ('interval','daily','weekly')", name="job_schedule_kind"),
        CheckConstraint(
            "(schedule_kind='interval' AND local_time IS NULL AND weekday IS NULL) OR "
            "(schedule_kind='daily' AND local_time IS NOT NULL AND weekday IS NULL) OR "
            "(schedule_kind='weekly' AND local_time IS NOT NULL "
            "AND weekday BETWEEN 0 AND 6)",
            name="job_schedule_wall_clock",
        ),
    )
    schedule_key: Mapped[str] = mapped_column(String(150), nullable=False)
    task_name: Mapped[str] = mapped_column(String(150), nullable=False)
    queue: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cadence_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="UTC", server_default="UTC"
    )
    schedule_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="interval", server_default="interval"
    )
    local_time: Mapped[time | None] = mapped_column(Time())
    weekday: Mapped[int | None] = mapped_column(Integer)

    def advance(self, now: datetime | None = None) -> None:
        current = now or datetime.now(UTC)
        self.last_enqueued_at = current
        if (self.schedule_kind or "interval") == "interval":
            while self.next_run_at <= current:
                self.next_run_at += timedelta(seconds=self.cadence_seconds)
            return
        assert self.local_time is not None
        zone = ZoneInfo(self.timezone)
        local_now = current.astimezone(zone)
        for offset in range(9):
            candidate_date = local_now.date() + timedelta(days=offset)
            if self.schedule_kind == "weekly" and candidate_date.weekday() != self.weekday:
                continue
            candidate = datetime.combine(candidate_date, self.local_time, tzinfo=zone)
            candidate_utc = candidate.astimezone(UTC)
            if candidate_utc > current:
                self.next_run_at = candidate_utc
                return
        raise ValueError("No se pudo calcular la siguiente ejecución wall-clock.")


class AIAuditLog(TenantDomainMixin, Base):
    __tablename__ = "ai_audit_logs"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_ai_audit_logs_id_tenant"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_ai_audit_logs_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("background_job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_ai_audit_background_job_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "requested_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_ai_audit_requester_membership",
        ),
        Index("ix_ai_audit_tenant_dossier", "tenant_id", "dossier_id", "created_at"),
        Index("ix_ai_audit_tenant_status", "tenant_id", "status", "created_at"),
        Index("ix_ai_audit_job_agent", "tenant_id", "background_job_id", "agent", "created_at"),
        CheckConstraint("octet_length(prompt_hash) = 32", name="ai_audit_prompt_hash"),
        CheckConstraint("octet_length(input_hash) = 32", name="ai_audit_input_hash"),
        CheckConstraint(
            "output_hash IS NULL OR octet_length(output_hash) = 32", name="ai_audit_output_hash"
        ),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed','denied')",
            name="ai_audit_status",
        ),
        CheckConstraint(
            "human_review_state IN "
            "('not_required','pending','accepted','rejected','changes_requested')",
            name="ai_audit_review_state",
        ),
        CheckConstraint(
            "data_classification IN ('public','internal')", name="ai_audit_classification"
        ),
        CheckConstraint("jsonb_typeof(redaction_summary)='object'", name="ai_audit_redaction"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND actual_cost_micros >= 0 "
            "AND attempt_count >= 0 AND (latency_ms IS NULL OR latency_ms >= 0) "
            "AND (estimated_cost_micros IS NULL OR estimated_cost_micros >= 0)",
            name="ai_audit_metrics",
        ),
    )
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    background_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    use_case: Mapped[str] = mapped_column(String(100), nullable=False)
    agent: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    action: Mapped[str] = mapped_column(String(100), nullable=False, default="generate")
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(150), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(150), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    context_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    schema_name: Mapped[str] = mapped_column(String(150), nullable=False, default="unknown")
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    input_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    output_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    source_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    data_classification: Mapped[str] = mapped_column(String(30), nullable=False, default="internal")
    redaction_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actual_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_micros: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_review_state: Mapped[str] = mapped_column(
        String(30), nullable=False, default="not_required"
    )


JOB_MODELS = (BackgroundJob, JobSchedule, AIAuditLog)
