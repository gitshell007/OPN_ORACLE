"""Tenant-scoped reporting, notification and export records."""

from __future__ import annotations

import uuid
from datetime import datetime, time
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
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin


class ReportRevision(TenantDomainMixin, Base):
    __tablename__ = "report_revisions"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_report_revisions_id_tenant"),
        UniqueConstraint("id", "report_id", "tenant_id", name="uq_report_revisions_context"),
        UniqueConstraint("tenant_id", "report_id", "revision_no", name="uq_report_revision_no"),
        ForeignKeyConstraint(
            ("report_id", "tenant_id"),
            ("reports.id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_revisions_report_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "created_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_report_revisions_creator_membership",
        ),
        CheckConstraint("revision_no >= 1", name="report_revision_no_positive"),
        CheckConstraint(
            "status IN ('draft','ready','reviewed','published','superseded')",
            name="report_revision_status",
        ),
        CheckConstraint("jsonb_typeof(content)='object'", name="report_revision_content_object"),
        CheckConstraint("octet_length(content_hash)=32", name="report_revision_hash_size"),
        Index("ix_report_revisions_report", "tenant_id", "report_id", "revision_no"),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    change_summary: Mapped[str] = mapped_column(String(1000), nullable=False, default="")


class ReportSnapshotEvidence(Base):
    __tablename__ = "report_snapshot_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ("report_id", "dossier_id", "tenant_id"),
            ("reports.id", "reports.dossier_id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_snapshot_report_tenant",
        ),
        ForeignKeyConstraint(
            ("evidence_id", "tenant_id"),
            ("evidence.id", "evidence.tenant_id"),
            ondelete="RESTRICT",
            name="fk_report_snapshot_evidence_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "evidence_id", "dossier_id"),
            (
                "evidence_dossiers.tenant_id",
                "evidence_dossiers.evidence_id",
                "evidence_dossiers.dossier_id",
            ),
            ondelete="RESTRICT",
            name="fk_report_snapshot_evidence_dossier",
        ),
        CheckConstraint("octet_length(evidence_hash)=32", name="report_evidence_hash_size"),
        CheckConstraint("jsonb_typeof(locator)='object'", name="report_evidence_locator_object"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evidence_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    extract: Mapped[str] = mapped_column(Text, nullable=False)
    locator: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    classification: Mapped[str] = mapped_column(String(20), nullable=False)
    source_label: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class ReportArtifact(TenantDomainMixin, Base):
    __tablename__ = "report_artifacts"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_report_artifacts_id_tenant"),
        UniqueConstraint(
            "tenant_id", "revision_id", "format", name="uq_report_artifact_revision_format"
        ),
        ForeignKeyConstraint(
            ("report_id", "tenant_id"),
            ("reports.id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_artifacts_report_tenant",
        ),
        ForeignKeyConstraint(
            ("revision_id", "report_id", "tenant_id"),
            ("report_revisions.id", "report_revisions.report_id", "report_revisions.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_artifacts_revision_tenant",
        ),
        CheckConstraint("format IN ('html','pdf','json')", name="report_artifact_format"),
        CheckConstraint("status IN ('available','failed','purged')", name="report_artifact_status"),
        CheckConstraint("byte_size >= 0", name="report_artifact_size"),
        CheckConstraint("octet_length(checksum)=32", name="report_artifact_checksum_size"),
        CheckConstraint("jsonb_typeof(metadata)='object'", name="report_artifact_metadata_object"),
        Index("ix_report_artifacts_report", "tenant_id", "report_id", "created_at"),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    checksum: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class ReportReview(TenantDomainMixin, Base):
    __tablename__ = "report_reviews"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_report_reviews_id_tenant"),
        ForeignKeyConstraint(
            ("report_id", "tenant_id"),
            ("reports.id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_reviews_report_tenant",
        ),
        ForeignKeyConstraint(
            ("revision_id", "report_id", "tenant_id"),
            ("report_revisions.id", "report_revisions.report_id", "report_revisions.tenant_id"),
            ondelete="CASCADE",
            name="fk_report_reviews_revision_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "reviewer_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_report_reviews_reviewer_membership",
        ),
        CheckConstraint(
            "decision IN ('approved','changes_requested','comment')",
            name="report_review_decision",
        ),
    )
    report_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")


class Notification(TenantDomainMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_notifications_id_tenant"),
        UniqueConstraint("tenant_id", "user_id", "dedupe_key", name="uq_notification_dedupe"),
        ForeignKeyConstraint(
            ("tenant_id", "user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="CASCADE",
            name="fk_notifications_membership",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_notifications_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_notifications_job_tenant",
        ),
        ForeignKeyConstraint(
            ("report_id", "tenant_id"),
            ("reports.id", "reports.tenant_id"),
            ondelete="CASCADE",
            name="fk_notifications_report_tenant",
        ),
        CheckConstraint(
            "severity IN ('info','success','warning','critical')", name="notification_severity"
        ),
        CheckConstraint("length(title) BETWEEN 1 AND 200", name="notification_title_length"),
        CheckConstraint("length(body) BETWEEN 1 AND 1000", name="notification_body_length"),
        CheckConstraint("octet_length(request_hash)=32", name="notification_request_hash_size"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at", name="notification_expiry_order"
        ),
        Index(
            "ix_notifications_user_inbox",
            "tenant_id",
            "user_id",
            "dismissed_at",
            "read_at",
            "created_at",
        ),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    link: Mapped[str | None] = mapped_column(String(1000))
    in_app_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationPreference(TenantDomainMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_notification_preferences_id_tenant"),
        UniqueConstraint(
            "tenant_id", "user_id", "notification_type", name="uq_notification_preference_type"
        ),
        ForeignKeyConstraint(
            ("tenant_id", "user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="CASCADE",
            name="fk_notification_preferences_membership",
        ),
        CheckConstraint(
            "digest_cadence IN ('instant','daily','weekly','off')",
            name="notification_preference_cadence",
        ),
        CheckConstraint(
            "minimum_severity IN ('info','success','warning','critical')",
            name="notification_preference_severity",
        ),
        CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="notification_weekday"),
        CheckConstraint("jsonb_typeof(channels)='object'", name="notification_channels_object"),
        CheckConstraint(
            "channels ?& ARRAY['in_app','email'] AND "
            "channels - 'in_app' - 'email' = '{}'::jsonb AND "
            "jsonb_typeof(channels->'in_app')='boolean' AND "
            "jsonb_typeof(channels->'email')='boolean'",
            name="notification_channels_schema",
        ),
        CheckConstraint(
            "(digest_cadence='weekly' AND weekday IS NOT NULL) OR "
            "(digest_cadence<>'weekly' AND weekday IS NULL)",
            name="notification_cadence_shape",
        ),
        CheckConstraint("version >= 1", name="notification_preference_version"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False, default="*")
    channels: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda: {"in_app": True, "email": False},
        server_default=text("jsonb_build_object('in_app', true, 'email', false)"),
    )
    digest_cadence: Mapped[str] = mapped_column(String(20), nullable=False, default="instant")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Europe/Madrid")
    local_time: Mapped[time] = mapped_column(Time(), nullable=False, default=time(8, 0))
    weekday: Mapped[int | None] = mapped_column(Integer)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time())
    quiet_hours_end: Mapped[time | None] = mapped_column(Time())
    minimum_severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    security_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class NotificationDelivery(TenantDomainMixin, Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_notification_deliveries_id_tenant"),
        UniqueConstraint(
            "tenant_id", "channel", "dedupe_key", name="uq_notification_delivery_dedupe"
        ),
        ForeignKeyConstraint(
            ("notification_id", "tenant_id"),
            ("notifications.id", "notifications.tenant_id"),
            ondelete="CASCADE",
            name="fk_notification_deliveries_notification_tenant",
        ),
        ForeignKeyConstraint(
            ("job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_notification_deliveries_job_tenant",
        ),
        CheckConstraint("channel IN ('email')", name="notification_delivery_channel"),
        CheckConstraint(
            "status IN ('queued','sending','sent','failed','skipped')",
            name="notification_delivery_status",
        ),
        CheckConstraint("attempts >= 0", name="notification_delivery_attempts"),
        CheckConstraint(
            "(batch_snapshot IS NULL AND batch_sha256 IS NULL) OR "
            "(jsonb_typeof(batch_snapshot)='object' AND octet_length(batch_sha256)=32)",
            name="notification_delivery_batch_integrity",
        ),
        CheckConstraint(
            "(status='queued' AND delivery_started_at IS NULL AND delivered_at IS NULL) OR "
            "(status IN ('sending','failed') AND delivery_started_at IS NOT NULL "
            "AND delivered_at IS NULL) OR "
            "(status='sent' AND delivery_started_at IS NOT NULL AND delivered_at IS NOT NULL) OR "
            "(status='skipped' AND delivered_at IS NULL)",
            name="notification_delivery_state",
        ),
        Index("ix_notification_deliveries_pending", "tenant_id", "status", "created_at"),
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="email")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    dedupe_key: Mapped[str] = mapped_column(String(240), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    batch_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    batch_sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))


class AlertPolicy(TenantDomainMixin, Base):
    __tablename__ = "alert_policies"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_alert_policies_id_tenant"),
        UniqueConstraint("tenant_id", "dossier_id", name="uq_alert_policy_dossier"),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_alert_policies_dossier_tenant",
        ),
        CheckConstraint("signal_score_threshold BETWEEN 0 AND 100", name="alert_signal_score"),
        CheckConstraint("risk_score_threshold BETWEEN 0 AND 100", name="alert_risk_score"),
        CheckConstraint("cooldown_minutes BETWEEN 0 AND 10080", name="alert_cooldown"),
        CheckConstraint(
            "opportunity_deadline_days BETWEEN 0 AND 365 AND "
            "meeting_upcoming_hours BETWEEN 1 AND 720",
            name="alert_horizons",
        ),
        CheckConstraint(
            "(scope='tenant' AND dossier_id IS NULL) OR "
            "(scope='dossier' AND dossier_id IS NOT NULL)",
            name="alert_policy_scope",
        ),
        CheckConstraint("jsonb_typeof(enabled_types)='object'", name="alert_enabled_types_object"),
        CheckConstraint("jsonb_typeof(severity_map)='object'", name="alert_severity_map_object"),
        CheckConstraint(
            "enabled_types ?& ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] AND "
            "enabled_types - ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] = '{}'::jsonb "
            "AND NOT jsonb_path_exists(enabled_types, '$.* ? (@.type() != \"boolean\")')",
            name="alert_enabled_types_schema",
        ),
        CheckConstraint(
            "severity_map - ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] = '{}'::jsonb "
            "AND NOT jsonb_path_exists(severity_map, "
            '\'$.* ? (@ != "info" && @ != "success" && @ != "warning" && '
            '@ != "critical")\')',
            name="alert_severity_map_schema",
        ),
        CheckConstraint("version >= 1", name="alert_policy_version"),
        Index(
            "uq_alert_policy_tenant_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("scope='tenant'"),
        ),
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="dossier")
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    signal_score_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    risk_score_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=75)
    opportunity_deadline_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    meeting_upcoming_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled_types: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    severity_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time())
    quiet_hours_end: Mapped[time | None] = mapped_column(Time())
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Europe/Madrid")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AlertEvaluation(TenantDomainMixin, Base):
    """Immutable per-recipient ledger for alert decisions and delivery linkage."""

    __tablename__ = "alert_evaluations"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_alert_evaluations_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "occurrence_key",
            name="uq_alert_evaluation_occurrence",
        ),
        ForeignKeyConstraint(
            ("policy_id", "tenant_id"),
            ("alert_policies.id", "alert_policies.tenant_id"),
            ondelete="RESTRICT",
            name="fk_alert_evaluations_policy_tenant",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_alert_evaluations_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "recipient_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_alert_evaluations_recipient_membership",
        ),
        ForeignKeyConstraint(
            ("notification_id", "tenant_id"),
            ("notifications.id", "notifications.tenant_id"),
            ondelete="RESTRICT",
            name="fk_alert_evaluations_notification_tenant",
        ),
        CheckConstraint(
            "alert_type IN ('high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready')",
            name="alert_evaluation_type",
        ),
        CheckConstraint(
            "severity IN ('info','success','warning','critical')",
            name="alert_evaluation_severity",
        ),
        CheckConstraint("decision IN ('emitted','cooldown')", name="alert_evaluation_decision"),
        CheckConstraint("jsonb_typeof(metadata)='object'", name="alert_evaluation_metadata"),
        CheckConstraint(
            "(decision='emitted' AND notification_id IS NOT NULL) OR "
            "(decision<>'emitted' AND notification_id IS NULL)",
            name="alert_evaluation_notification_state",
        ),
        Index(
            "ix_alert_evaluations_cooldown",
            "tenant_id",
            "recipient_user_id",
            "alert_type",
            "resource_id",
            "evaluated_at",
        ),
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurrence_key: Mapped[str] = mapped_column(String(240), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evaluation_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class DataExport(TenantDomainMixin, Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_data_exports_id_tenant"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_data_export_idempotency"),
        ForeignKeyConstraint(
            ("tenant_id", "requested_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_data_exports_requester_membership",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_data_exports_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("job_id", "tenant_id"),
            ("background_jobs.id", "background_jobs.tenant_id"),
            ondelete="RESTRICT",
            name="fk_data_exports_job_tenant",
        ),
        CheckConstraint(
            "status IN ('queued','generating','ready','failed','expired','purged')",
            name="data_export_status",
        ),
        CheckConstraint("format IN ('csv')", name="data_export_format"),
        CheckConstraint("jsonb_typeof(filters)='object'", name="data_export_filters_object"),
        CheckConstraint("jsonb_typeof(columns)='array'", name="data_export_columns_array"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="data_export_size"),
        CheckConstraint(
            "checksum IS NULL OR octet_length(checksum)=32", name="data_export_checksum_size"
        ),
        CheckConstraint("octet_length(request_hash)=32", name="data_export_request_hash_size"),
        CheckConstraint("version >= 1", name="data_export_version"),
        CheckConstraint(
            "(status IN ('ready','expired') AND storage_key IS NOT NULL "
            "AND checksum IS NOT NULL AND byte_size IS NOT NULL AND media_type IS NOT NULL "
            "AND expires_at IS NOT NULL AND expires_at > created_at) OR "
            "(status IN ('queued','generating','failed') AND storage_key IS NULL "
            "AND checksum IS NULL AND byte_size IS NULL AND media_type IS NULL "
            "AND expires_at IS NULL) OR "
            "(status='purged' AND storage_key IS NULL AND checksum IS NULL "
            "AND byte_size IS NULL AND media_type IS NULL AND expires_at IS NOT NULL)",
            name="data_export_artifact_state",
        ),
        Index("ix_data_exports_requester", "tenant_id", "requested_by_user_id", "created_at"),
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dossier_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dataset: Mapped[str] = mapped_column(String(80), nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="csv")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    watermark: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(300))
    checksum: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    media_type: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


REPORTING_MODELS = (
    ReportRevision,
    ReportSnapshotEvidence,
    ReportArtifact,
    ReportReview,
    Notification,
    NotificationPreference,
    NotificationDelivery,
    AlertPolicy,
    AlertEvaluation,
    DataExport,
)
