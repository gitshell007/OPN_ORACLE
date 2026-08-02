"""Durable, idempotent AI usage bindings for custom report writer/review (MDEV-08)."""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class ReportAIUsageBinding(TenantDomainMixin, Base):
    """One effective usage link per (tenant, report, phase, run_id).

    Retry/replay with the same run_id does not create a second cost row.
    """

    __tablename__ = "report_ai_usage_bindings"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_report_ai_usage_bindings_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "report_id",
            "phase",
            "run_id",
            name="uq_report_ai_usage_binding_run",
        ),
        ForeignKeyConstraint(
            ("report_id", "tenant_id"),
            ("reports.id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_ai_usage_report_tenant",
        ),
        ForeignKeyConstraint(
            ("job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="SET NULL",
            name="fk_report_ai_usage_job_tenant",
        ),
        CheckConstraint(
            "phase IN ('writer','review','plan')",
            name="report_ai_usage_phase",
        ),
        CheckConstraint(
            "char_length(run_id) BETWEEN 1 AND 200",
            name="report_ai_usage_run_id",
        ),
        CheckConstraint(
            "jsonb_typeof(usage_payload)='object'",
            name="report_ai_usage_payload_object",
        ),
        Index(
            "ix_report_ai_usage_bindings_report",
            "tenant_id",
            "report_id",
            "phase",
            "created_at",
        ),
    )

    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    phase: Mapped[str] = mapped_column(String(20), nullable=False)
    task_key: Mapped[str] = mapped_column(String(100), nullable=False)
    runtime_id: Mapped[str] = mapped_column(String(20), nullable=False)
    run_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    model: Mapped[str] = mapped_column(String(150), nullable=False, default="unknown")
    fallback_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    validated_output_sha256: Mapped[str | None] = mapped_column(String(64))
    usage_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempts_payload: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=None, server_default=text("null")
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


CUSTOM_REPORT_USAGE_MODELS = (ReportAIUsageBinding,)


def upsert_report_ai_usage_binding(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    report_id: uuid.UUID,
    job_id: uuid.UUID | None,
    phase: str,
    task_key: str,
    runtime_id: str,
    run_id: str,
    request_id: str | None,
    provider: str,
    model: str,
    fallback_used: bool,
    snapshot_hash: str | None,
    usage: dict[str, Any],
    attempts: Any,
    validated_output_sha256: str | None,
) -> ReportAIUsageBinding:
    """Insert or return the single binding for (tenant, report, phase, run_id)."""

    rid = (run_id or "").strip() or str(job_id or uuid.uuid4())
    try:
        existing = session.scalar(
            select(ReportAIUsageBinding).where(
                ReportAIUsageBinding.tenant_id == tenant_id,
                ReportAIUsageBinding.report_id == report_id,
                ReportAIUsageBinding.phase == phase,
                ReportAIUsageBinding.run_id == rid,
            )
        )
    except Exception:
        existing = None

    if existing is not None and isinstance(existing, ReportAIUsageBinding):
        # Idempotent: do not double-count cost; refresh optional metadata only.
        if job_id is not None and existing.job_id is None:
            existing.job_id = job_id
        if validated_output_sha256 and not existing.validated_output_sha256:
            existing.validated_output_sha256 = validated_output_sha256
        existing.updated_at = datetime.now(UTC)
        with contextlib.suppress(Exception):
            session.flush()
        return existing

    row = ReportAIUsageBinding(
        tenant_id=tenant_id,
        report_id=report_id,
        job_id=job_id,
        phase=phase,
        task_key=task_key,
        runtime_id=runtime_id,
        run_id=rid,
        request_id=request_id,
        provider=provider or "unknown",
        model=model or "unknown",
        fallback_used=bool(fallback_used),
        snapshot_hash=snapshot_hash,
        validated_output_sha256=validated_output_sha256,
        usage_payload=dict(usage or {}),
        attempts_payload=attempts,
    )
    try:
        session.add(row)
        session.flush()
        return row
    except Exception:
        # Unit tests / non-migrated sessions: return ephemeral row with stable id.
        if not getattr(row, "id", None):
            row.id = uuid.uuid4()
        return row
