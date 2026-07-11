"""reports notifications exports

Revision ID: 20260711_0010
Revises: 20260711_0009
Create Date: 2026-07-11 03:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260711_0010"
down_revision: str | None = "20260711_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def _tenant_identity(table: str) -> tuple[sa.Constraint, ...]:
    return (
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f(f"fk_{table}_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}")),
        sa.UniqueConstraint("id", "tenant_id", name=f"uq_{table}_id_tenant"),
    )


def upgrade() -> None:
    op.drop_constraint("report_status", "reports", type_="check")
    op.execute(
        """
        UPDATE reports SET status = CASE status
          WHEN 'pending' THEN 'draft'
          WHEN 'completed' THEN 'ready'
          ELSE status
        END
        """
    )
    op.add_column(
        "reports",
        sa.Column("template_version", sa.String(length=30), server_default="v1", nullable=False),
    )
    op.add_column(
        "reports",
        sa.Column("generation_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("reports", sa.Column("idempotency_key", sa.String(length=200)))
    op.add_column("reports", sa.Column("request_hash", sa.LargeBinary(length=32)))
    op.add_column(
        "reports",
        sa.Column(
            "options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("reports", sa.Column("source_snapshot_hash", sa.LargeBinary(length=32)))
    op.add_column(
        "reports",
        sa.Column(
            "snapshot_hash_algorithm",
            sa.String(length=50),
            server_default="canonical-json-sha256-v1",
            nullable=False,
        ),
    )
    op.add_column(
        "reports",
        sa.Column(
            "classification", sa.String(length=20), server_default="internal", nullable=False
        ),
    )
    op.add_column(
        "reports",
        sa.Column(
            "confidentiality_label",
            sa.String(length=120),
            server_default="Uso interno",
            nullable=False,
        ),
    )
    op.add_column("reports", sa.Column("requested_by_user_id", sa.UUID()))
    op.add_column("reports", sa.Column("background_job_id", sa.UUID()))
    op.add_column("reports", sa.Column("ai_artifact_id", sa.UUID()))
    op.add_column("reports", sa.Column("parent_report_id", sa.UUID()))
    op.add_column("reports", sa.Column("reviewed_by_user_id", sa.UUID()))
    op.add_column("reports", sa.Column("published_by_user_id", sa.UUID()))
    op.add_column("reports", sa.Column("ready_at", sa.DateTime(timezone=True)))
    op.add_column("reports", sa.Column("reviewed_at", sa.DateTime(timezone=True)))
    op.add_column("reports", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("reports", sa.Column("superseded_at", sa.DateTime(timezone=True)))
    op.add_column("reports", sa.Column("error_code", sa.String(length=100)))
    op.add_column("reports", sa.Column("error_message", sa.String(length=500)))
    op.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (
            PARTITION BY tenant_id,dossier_id,template_key ORDER BY created_at,id
          ) AS generation_version
          FROM reports
        )
        UPDATE reports r SET generation_version=ranked.generation_version
        FROM ranked WHERE ranked.id=r.id
        """
    )
    op.execute(
        """
        UPDATE reports SET
          idempotency_key='legacy-report:' || id::text,
          request_hash=sha256(convert_to(id::text || ':' || source_snapshot::text,'UTF8'))
        """
    )
    op.execute(
        """
        UPDATE reports r SET requested_by_user_id = COALESCE(
          r.generated_by_user_id,
          d.owner_user_id,
          (
            SELECT tm.user_id FROM tenant_memberships tm
            WHERE tm.tenant_id=r.tenant_id AND tm.status='active'
            ORDER BY tm.created_at,tm.id LIMIT 1
          )
        )
        FROM strategic_dossiers d
        WHERE d.id=r.dossier_id AND d.tenant_id=r.tenant_id
        """
    )
    op.execute(
        """
        UPDATE reports SET
          source_snapshot_hash = sha256(convert_to(source_snapshot::text,'UTF8')),
          snapshot_hash_algorithm = 'postgres-jsonb-text-sha256-v1'
        """
    )
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM reports WHERE requested_by_user_id IS NULL) THEN
            RAISE EXCEPTION 'reports legacy rows require an active tenant member';
          END IF;
        END $$
        """
    )
    op.alter_column("reports", "requested_by_user_id", nullable=False)
    op.alter_column("reports", "source_snapshot_hash", nullable=False)
    op.alter_column("reports", "idempotency_key", nullable=False)
    op.alter_column("reports", "request_hash", nullable=False)
    op.create_check_constraint(
        "report_status",
        "reports",
        "status IN ('draft','generating','ready','reviewed','published','failed','superseded')",
    )
    op.create_check_constraint("report_version_positive", "reports", "version >= 1")
    op.create_check_constraint(
        "report_generation_version_positive", "reports", "generation_version >= 1"
    )
    op.create_check_constraint(
        "report_classification", "reports", "classification IN ('public','internal')"
    )
    op.create_check_constraint("report_options_object", "reports", "jsonb_typeof(options)='object'")
    op.create_check_constraint(
        "report_snapshot_object", "reports", "jsonb_typeof(source_snapshot)='object'"
    )
    op.create_check_constraint(
        "report_snapshot_hash_size", "reports", "octet_length(source_snapshot_hash)=32"
    )
    op.create_check_constraint(
        "report_snapshot_hash_algorithm",
        "reports",
        "snapshot_hash_algorithm IN ('canonical-json-sha256-v1','postgres-jsonb-text-sha256-v1')",
    )
    op.create_check_constraint(
        "report_request_hash_size", "reports", "octet_length(request_hash)=32"
    )
    op.create_unique_constraint(
        "uq_reports_id_dossier_tenant",
        "reports",
        ["id", "dossier_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_report_template_generation",
        "reports",
        ["tenant_id", "dossier_id", "template_key", "generation_version"],
    )
    op.create_unique_constraint(
        "uq_report_idempotency", "reports", ["tenant_id", "idempotency_key"]
    )
    op.create_index(
        "ix_reports_tenant_status_updated",
        "reports",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_reports_tenant_dossier_created",
        "reports",
        ["tenant_id", "dossier_id", "created_at"],
    )
    op.create_foreign_key(
        "fk_reports_requester_membership",
        "reports",
        "tenant_memberships",
        ["tenant_id", "requested_by_user_id"],
        ["tenant_id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reports_background_job_tenant",
        "reports",
        "background_jobs",
        ["background_job_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reports_ai_artifact_tenant",
        "reports",
        "ai_artifacts",
        ["ai_artifact_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reports_parent_tenant",
        "reports",
        "reports",
        ["parent_report_id", "dossier_id", "tenant_id"],
        ["id", "dossier_id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reports_reviewer_membership",
        "reports",
        "tenant_memberships",
        ["tenant_id", "reviewed_by_user_id"],
        ["tenant_id", "user_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_reports_publisher_membership",
        "reports",
        "tenant_memberships",
        ["tenant_id", "published_by_user_id"],
        ["tenant_id", "user_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "report_revisions",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=False),
        sa.Column("change_summary", sa.String(length=1000), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "revision_no >= 1", name=op.f("ck_report_revisions_report_revision_no_positive")
        ),
        sa.CheckConstraint(
            "status IN ('draft','ready','reviewed','published','superseded')",
            name=op.f("ck_report_revisions_report_revision_status"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content)='object'",
            name=op.f("ck_report_revisions_report_revision_content_object"),
        ),
        sa.CheckConstraint(
            "octet_length(content_hash)=32",
            name=op.f("ck_report_revisions_report_revision_hash_size"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["reports.id", "reports.tenant_id"],
            name="fk_report_revisions_report_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_report_revisions_creator_membership",
            ondelete="RESTRICT",
        ),
        *_tenant_identity("report_revisions"),
        sa.UniqueConstraint("id", "report_id", "tenant_id", name="uq_report_revisions_context"),
        sa.UniqueConstraint("tenant_id", "report_id", "revision_no", name="uq_report_revision_no"),
    )
    op.create_index(
        "ix_report_revisions_report",
        "report_revisions",
        ["tenant_id", "report_id", "revision_no"],
    )
    op.create_table(
        "report_snapshot_evidence",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("evidence_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("extract", sa.Text(), nullable=False),
        sa.Column("locator", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("classification", sa.String(length=20), nullable=False),
        sa.Column("source_label", sa.String(length=500), nullable=False),
        sa.CheckConstraint(
            "octet_length(evidence_hash)=32",
            name=op.f("ck_report_snapshot_evidence_report_evidence_hash_size"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(locator)='object'",
            name=op.f("ck_report_snapshot_evidence_report_evidence_locator_object"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "dossier_id", "tenant_id"],
            ["reports.id", "reports.dossier_id", "reports.tenant_id"],
            name="fk_report_snapshot_report_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "tenant_id"],
            ["evidence.id", "evidence.tenant_id"],
            name="fk_report_snapshot_evidence_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id", "dossier_id"],
            [
                "evidence_dossiers.tenant_id",
                "evidence_dossiers.evidence_id",
                "evidence_dossiers.dossier_id",
            ],
            name="fk_report_snapshot_evidence_dossier",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "report_id", "evidence_id", name=op.f("pk_report_snapshot_evidence")
        ),
    )
    op.create_table(
        "report_artifacts",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("checksum", sa.LargeBinary(length=32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "format IN ('html','pdf','json')",
            name=op.f("ck_report_artifacts_report_artifact_format"),
        ),
        sa.CheckConstraint(
            "status IN ('available','failed','purged')",
            name=op.f("ck_report_artifacts_report_artifact_status"),
        ),
        sa.CheckConstraint("byte_size >= 0", name=op.f("ck_report_artifacts_report_artifact_size")),
        sa.CheckConstraint(
            "octet_length(checksum)=32",
            name=op.f("ck_report_artifacts_report_artifact_checksum_size"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata)='object'",
            name=op.f("ck_report_artifacts_report_artifact_metadata_object"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["reports.id", "reports.tenant_id"],
            name="fk_report_artifacts_report_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "report_id", "tenant_id"],
            ["report_revisions.id", "report_revisions.report_id", "report_revisions.tenant_id"],
            name="fk_report_artifacts_revision_tenant",
            ondelete="CASCADE",
        ),
        *_tenant_identity("report_artifacts"),
        sa.UniqueConstraint(
            "tenant_id", "revision_id", "format", name="uq_report_artifact_revision_format"
        ),
    )
    op.create_index(
        "ix_report_artifacts_report",
        "report_artifacts",
        ["tenant_id", "report_id", "created_at"],
    )
    op.create_table(
        "report_reviews",
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("reviewer_user_id", sa.UUID(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "decision IN ('approved','changes_requested','comment')",
            name=op.f("ck_report_reviews_report_review_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["reports.id", "reports.tenant_id"],
            name="fk_report_reviews_report_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "report_id", "tenant_id"],
            ["report_revisions.id", "report_revisions.report_id", "report_revisions.tenant_id"],
            name="fk_report_reviews_revision_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_report_reviews_reviewer_membership",
            ondelete="RESTRICT",
        ),
        *_tenant_identity("report_reviews"),
    )
    op.create_table(
        "notifications",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("link", sa.String(length=1000)),
        sa.Column("in_app_visible", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("dossier_id", sa.UUID()),
        sa.Column("job_id", sa.UUID()),
        sa.Column("report_id", sa.UUID()),
        sa.Column("resource_type", sa.String(length=80)),
        sa.Column("resource_id", sa.UUID()),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        *_tenant_columns(),
        sa.CheckConstraint(
            "severity IN ('info','success','warning','critical')",
            name=op.f("ck_notifications_notification_severity"),
        ),
        sa.CheckConstraint(
            "length(title) BETWEEN 1 AND 200",
            name=op.f("ck_notifications_notification_title_length"),
        ),
        sa.CheckConstraint(
            "length(body) BETWEEN 1 AND 1000",
            name=op.f("ck_notifications_notification_body_length"),
        ),
        sa.CheckConstraint(
            "octet_length(request_hash)=32",
            name=op.f("ck_notifications_notification_request_hash_size"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name=op.f("ck_notifications_notification_expiry_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_notifications_membership",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_notifications_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            name="fk_notifications_job_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["reports.id", "reports.tenant_id"],
            name="fk_notifications_report_tenant",
            ondelete="CASCADE",
        ),
        *_tenant_identity("notifications"),
        sa.UniqueConstraint("tenant_id", "user_id", "dedupe_key", name="uq_notification_dedupe"),
    )
    op.create_index(
        "ix_notifications_user_inbox",
        "notifications",
        ["tenant_id", "user_id", "dismissed_at", "read_at", "created_at"],
    )
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("notification_type", sa.String(length=80), nullable=False),
        sa.Column(
            "channels",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("jsonb_build_object('in_app', true, 'email', false)"),
            nullable=False,
        ),
        sa.Column("digest_cadence", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("weekday", sa.Integer()),
        sa.Column("quiet_hours_start", sa.Time()),
        sa.Column("quiet_hours_end", sa.Time()),
        sa.Column("minimum_severity", sa.String(length=20), nullable=False),
        sa.Column("security_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "digest_cadence IN ('instant','daily','weekly','off')",
            name=op.f("ck_notification_preferences_notification_preference_cadence"),
        ),
        sa.CheckConstraint(
            "minimum_severity IN ('info','success','warning','critical')",
            name=op.f("ck_notification_preferences_notification_preference_severity"),
        ),
        sa.CheckConstraint(
            "weekday IS NULL OR weekday BETWEEN 0 AND 6",
            name=op.f("ck_notification_preferences_notification_weekday"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(channels)='object'",
            name=op.f("ck_notification_preferences_notification_channels_object"),
        ),
        sa.CheckConstraint(
            "channels ?& ARRAY['in_app','email'] AND "
            "channels - 'in_app' - 'email' = '{}'::jsonb AND "
            "jsonb_typeof(channels->'in_app')='boolean' AND "
            "jsonb_typeof(channels->'email')='boolean'",
            name=op.f("ck_notification_preferences_notification_channels_schema"),
        ),
        sa.CheckConstraint(
            "(digest_cadence='weekly' AND weekday IS NOT NULL) OR "
            "(digest_cadence<>'weekly' AND weekday IS NULL)",
            name=op.f("ck_notification_preferences_notification_cadence_shape"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f("ck_notification_preferences_notification_preference_version"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_notification_preferences_membership",
            ondelete="CASCADE",
        ),
        *_tenant_identity("notification_preferences"),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "notification_type", name="uq_notification_preference_type"
        ),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("notification_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID()),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("delivery_started_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("batch_snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("batch_sha256", sa.LargeBinary(length=32)),
        *_tenant_columns(),
        sa.CheckConstraint(
            "channel IN ('email')",
            name=op.f("ck_notification_deliveries_notification_delivery_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','sending','sent','failed','skipped')",
            name=op.f("ck_notification_deliveries_notification_delivery_status"),
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_notification_deliveries_notification_delivery_attempts")
        ),
        sa.CheckConstraint(
            "(batch_snapshot IS NULL AND batch_sha256 IS NULL) OR "
            "(jsonb_typeof(batch_snapshot)='object' AND octet_length(batch_sha256)=32)",
            name=op.f("ck_notification_deliveries_notification_delivery_batch_integrity"),
        ),
        sa.CheckConstraint(
            "(status='queued' AND delivery_started_at IS NULL AND delivered_at IS NULL) OR "
            "(status IN ('sending','failed') AND delivery_started_at IS NOT NULL "
            "AND delivered_at IS NULL) OR "
            "(status='sent' AND delivery_started_at IS NOT NULL AND delivered_at IS NOT NULL) OR "
            "(status='skipped' AND delivered_at IS NULL)",
            name=op.f("ck_notification_deliveries_notification_delivery_state"),
        ),
        sa.ForeignKeyConstraint(
            ["notification_id", "tenant_id"],
            ["notifications.id", "notifications.tenant_id"],
            name="fk_notification_deliveries_notification_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            name="fk_notification_deliveries_job_tenant",
            ondelete="RESTRICT",
        ),
        *_tenant_identity("notification_deliveries"),
        sa.UniqueConstraint(
            "tenant_id", "channel", "dedupe_key", name="uq_notification_delivery_dedupe"
        ),
    )
    op.create_index(
        "ix_notification_deliveries_pending",
        "notification_deliveries",
        ["tenant_id", "status", "created_at"],
    )
    op.create_table(
        "alert_policies",
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("dossier_id", sa.UUID()),
        sa.Column("signal_score_threshold", sa.Integer(), nullable=False),
        sa.Column("risk_score_threshold", sa.Integer(), nullable=False),
        sa.Column("opportunity_deadline_days", sa.Integer(), nullable=False),
        sa.Column("meeting_upcoming_hours", sa.Integer(), nullable=False),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False),
        sa.Column("enabled_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("severity_map", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quiet_hours_start", sa.Time()),
        sa.Column("quiet_hours_end", sa.Time()),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "signal_score_threshold BETWEEN 0 AND 100",
            name=op.f("ck_alert_policies_alert_signal_score"),
        ),
        sa.CheckConstraint(
            "risk_score_threshold BETWEEN 0 AND 100",
            name=op.f("ck_alert_policies_alert_risk_score"),
        ),
        sa.CheckConstraint(
            "cooldown_minutes BETWEEN 0 AND 10080",
            name=op.f("ck_alert_policies_alert_cooldown"),
        ),
        sa.CheckConstraint(
            "opportunity_deadline_days BETWEEN 0 AND 365 AND "
            "meeting_upcoming_hours BETWEEN 1 AND 720",
            name=op.f("ck_alert_policies_alert_horizons"),
        ),
        sa.CheckConstraint(
            "(scope='tenant' AND dossier_id IS NULL) OR "
            "(scope='dossier' AND dossier_id IS NOT NULL)",
            name=op.f("ck_alert_policies_alert_policy_scope"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(enabled_types)='object'",
            name=op.f("ck_alert_policies_alert_enabled_types_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(severity_map)='object'",
            name=op.f("ck_alert_policies_alert_severity_map_object"),
        ),
        sa.CheckConstraint(
            "enabled_types ?& ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] AND "
            "enabled_types - ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] = '{}'::jsonb "
            "AND NOT jsonb_path_exists(enabled_types, '$.* ? (@.type() != \"boolean\")')",
            name=op.f("ck_alert_policies_alert_enabled_types_schema"),
        ),
        sa.CheckConstraint(
            "severity_map - ARRAY['high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready'] = '{}'::jsonb "
            "AND NOT jsonb_path_exists(severity_map, "
            '\'$.* ? (@ != "info" && @ != "success" && @ != "warning" && '
            '@ != "critical")\')',
            name=op.f("ck_alert_policies_alert_severity_map_schema"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_alert_policies_alert_policy_version")),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_alert_policies_dossier_tenant",
            ondelete="CASCADE",
        ),
        *_tenant_identity("alert_policies"),
        sa.UniqueConstraint("tenant_id", "dossier_id", name="uq_alert_policy_dossier"),
    )
    op.create_index(
        "uq_alert_policy_tenant_default",
        "alert_policies",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("scope='tenant'"),
    )
    op.create_table(
        "alert_evaluations",
        sa.Column("policy_id", sa.UUID(), nullable=False),
        sa.Column("dossier_id", sa.UUID()),
        sa.Column("recipient_user_id", sa.UUID(), nullable=False),
        sa.Column("notification_id", sa.UUID()),
        sa.Column("alert_type", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("occurrence_key", sa.String(length=240), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        *_tenant_columns(),
        sa.CheckConstraint(
            "alert_type IN ('high_signal','high_risk','opportunity_deadline',"
            "'failed_integration','failed_job','meeting_upcoming','report_ready')",
            name=op.f("ck_alert_evaluations_alert_evaluation_type"),
        ),
        sa.CheckConstraint(
            "severity IN ('info','success','warning','critical')",
            name=op.f("ck_alert_evaluations_alert_evaluation_severity"),
        ),
        sa.CheckConstraint(
            "decision IN ('emitted','cooldown')",
            name=op.f("ck_alert_evaluations_alert_evaluation_decision"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata)='object'",
            name=op.f("ck_alert_evaluations_alert_evaluation_metadata"),
        ),
        sa.CheckConstraint(
            "(decision='emitted' AND notification_id IS NOT NULL) OR "
            "(decision<>'emitted' AND notification_id IS NULL)",
            name=op.f("ck_alert_evaluations_alert_evaluation_notification_state"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "tenant_id"],
            ["alert_policies.id", "alert_policies.tenant_id"],
            name="fk_alert_evaluations_policy_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_alert_evaluations_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "recipient_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_alert_evaluations_recipient_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["notification_id", "tenant_id"],
            ["notifications.id", "notifications.tenant_id"],
            name="fk_alert_evaluations_notification_tenant",
            ondelete="RESTRICT",
        ),
        *_tenant_identity("alert_evaluations"),
        sa.UniqueConstraint(
            "tenant_id",
            "recipient_user_id",
            "occurrence_key",
            name="uq_alert_evaluation_occurrence",
        ),
    )
    op.create_index(
        "ix_alert_evaluations_cooldown",
        "alert_evaluations",
        ["tenant_id", "recipient_user_id", "alert_type", "resource_id", "evaluated_at"],
    )
    op.create_table(
        "data_exports",
        sa.Column("requested_by_user_id", sa.UUID(), nullable=False),
        sa.Column("dossier_id", sa.UUID()),
        sa.Column("job_id", sa.UUID()),
        sa.Column("dataset", sa.String(length=80), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("columns", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("watermark", sa.String(length=300), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=300)),
        sa.Column("checksum", sa.LargeBinary(length=32)),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("media_type", sa.String(length=120)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("version", sa.Integer(), nullable=False),
        *_tenant_columns(),
        sa.CheckConstraint(
            "status IN ('queued','generating','ready','failed','expired','purged')",
            name=op.f("ck_data_exports_data_export_status"),
        ),
        sa.CheckConstraint("format IN ('csv')", name=op.f("ck_data_exports_data_export_format")),
        sa.CheckConstraint(
            "jsonb_typeof(filters)='object'",
            name=op.f("ck_data_exports_data_export_filters_object"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(columns)='array'", name=op.f("ck_data_exports_data_export_columns_array")
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0", name=op.f("ck_data_exports_data_export_size")
        ),
        sa.CheckConstraint(
            "checksum IS NULL OR octet_length(checksum)=32",
            name=op.f("ck_data_exports_data_export_checksum_size"),
        ),
        sa.CheckConstraint(
            "octet_length(request_hash)=32",
            name=op.f("ck_data_exports_data_export_request_hash_size"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_data_exports_data_export_version")),
        sa.CheckConstraint(
            "(status IN ('ready','expired') AND storage_key IS NOT NULL "
            "AND checksum IS NOT NULL AND byte_size IS NOT NULL AND media_type IS NOT NULL "
            "AND expires_at IS NOT NULL AND expires_at > created_at) OR "
            "(status IN ('queued','generating','failed') AND storage_key IS NULL "
            "AND checksum IS NULL AND byte_size IS NULL AND media_type IS NULL "
            "AND expires_at IS NULL) OR "
            "(status='purged' AND storage_key IS NULL AND checksum IS NULL "
            "AND byte_size IS NULL AND media_type IS NULL AND expires_at IS NOT NULL)",
            name=op.f("ck_data_exports_data_export_artifact_state"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "requested_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_data_exports_requester_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_data_exports_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            name="fk_data_exports_job_tenant",
            ondelete="RESTRICT",
        ),
        *_tenant_identity("data_exports"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_data_export_idempotency"),
    )
    op.create_index(
        "ix_data_exports_requester",
        "data_exports",
        ["tenant_id", "requested_by_user_id", "created_at"],
    )

    tenant_tables = (
        "report_revisions",
        "report_snapshot_evidence",
        "report_artifacts",
        "report_reviews",
        "notifications",
        "notification_preferences",
        "notification_deliveries",
        "alert_policies",
        "alert_evaluations",
        "data_exports",
    )
    for table in tenant_tables:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" USING '
            "(tenant_id=oracle_current_tenant()) WITH CHECK "
            "(tenant_id=oracle_current_tenant())"
        )
    op.execute(
        """
        DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON report_revisions,report_snapshot_evidence,
            report_artifacts,report_reviews,notifications,notification_preferences,
            notification_deliveries,alert_policies,alert_evaluations,data_exports TO oracle_app;
        END IF; END $$
        """
    )
    op.execute(
        """
        INSERT INTO permissions(key,description) VALUES
          ('report.review','Revisar y comentar informes'),
          ('report.publish','Publicar y sustituir informes'),
          ('notifications.read','Consultar notificaciones propias'),
          ('notifications.manage','Gestionar preferencias de notificación propias'),
          ('export.create','Solicitar exportaciones de datos autorizados'),
          ('audit.export','Exportar auditoría con marca de agua')
        ON CONFLICT (key) DO UPDATE SET description=EXCLUDED.description
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions(tenant_id,role_id,permission_key)
        SELECT r.tenant_id,r.id,p.key FROM roles r JOIN permissions p ON
          (r.key IN ('owner','admin') AND p.key IN (
            'report.review','report.publish','notifications.read','notifications.manage',
            'export.create','audit.export')) OR
          (r.key IN ('editor','analyst') AND p.key IN (
            'report.review','notifications.read','notifications.manage','export.create')) OR
          (r.key='viewer' AND p.key IN (
            'notifications.read','notifications.manage','export.create')) OR
          (r.key='auditor' AND p.key IN (
            'notifications.read','notifications.manage','export.create','audit.export'))
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_key IN "
        "('report.review','report.publish','notifications.read','notifications.manage',"
        "'export.create','audit.export')"
    )
    op.execute(
        "DELETE FROM permissions WHERE key IN "
        "('report.review','report.publish','notifications.read','notifications.manage',"
        "'export.create','audit.export')"
    )
    op.drop_index("ix_data_exports_requester", table_name="data_exports")
    op.drop_table("data_exports")
    op.drop_index("ix_alert_evaluations_cooldown", table_name="alert_evaluations")
    op.drop_table("alert_evaluations")
    op.drop_index("uq_alert_policy_tenant_default", table_name="alert_policies")
    op.drop_table("alert_policies")
    op.drop_index("ix_notification_deliveries_pending", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user_inbox", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("report_reviews")
    op.drop_index("ix_report_artifacts_report", table_name="report_artifacts")
    op.drop_table("report_artifacts")
    op.drop_table("report_snapshot_evidence")
    op.drop_index("ix_report_revisions_report", table_name="report_revisions")
    op.drop_table("report_revisions")

    for name in (
        "fk_reports_publisher_membership",
        "fk_reports_reviewer_membership",
        "fk_reports_parent_tenant",
        "fk_reports_ai_artifact_tenant",
        "fk_reports_background_job_tenant",
        "fk_reports_requester_membership",
    ):
        op.drop_constraint(name, "reports", type_="foreignkey")
    op.drop_index("ix_reports_tenant_dossier_created", table_name="reports")
    op.drop_index("ix_reports_tenant_status_updated", table_name="reports")
    op.drop_constraint("uq_report_template_generation", "reports", type_="unique")
    op.drop_constraint("uq_report_idempotency", "reports", type_="unique")
    op.drop_constraint("uq_reports_id_dossier_tenant", "reports", type_="unique")
    for name in (
        "report_snapshot_hash_algorithm",
        "report_request_hash_size",
        "report_snapshot_hash_size",
        "report_snapshot_object",
        "report_options_object",
        "report_classification",
        "report_generation_version_positive",
        "report_version_positive",
        "report_status",
    ):
        op.drop_constraint(name, "reports", type_="check")
    op.execute(
        """
        UPDATE reports SET status = CASE status
          WHEN 'draft' THEN 'pending'
          WHEN 'ready' THEN 'completed'
          WHEN 'reviewed' THEN 'completed'
          WHEN 'published' THEN 'completed'
          WHEN 'superseded' THEN 'completed'
          ELSE status
        END
        """
    )
    op.create_check_constraint(
        "report_status", "reports", "status IN ('pending','generating','completed','failed')"
    )
    for column in (
        "error_message",
        "error_code",
        "superseded_at",
        "published_at",
        "reviewed_at",
        "ready_at",
        "published_by_user_id",
        "reviewed_by_user_id",
        "parent_report_id",
        "ai_artifact_id",
        "background_job_id",
        "requested_by_user_id",
        "confidentiality_label",
        "classification",
        "snapshot_hash_algorithm",
        "source_snapshot_hash",
        "options",
        "generation_version",
        "request_hash",
        "idempotency_key",
        "template_version",
    ):
        op.drop_column("reports", column)
