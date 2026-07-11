"""Signal Avanza provisional integration boundary.

Revision ID: 20260710_0007
Revises: 20260710_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0007"
down_revision: str | None = "20260710_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _tenant_columns() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def _secure_tenant_table(name: str) -> None:
    op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {name} USING "
        "(tenant_id=oracle_current_tenant()) WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute(f"""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON {name} TO oracle_app;
      END IF; END $$
    """)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_background_jobs_id_tenant", "background_jobs", ["id", "tenant_id"]
    )
    for column in (
        sa.Column("base_url", sa.String(1000)),
        sa.Column("api_version", sa.String(30), nullable=False, server_default="v1"),
        sa.Column("subscription_key", sa.String(100)),
        sa.Column("adapter_mode", sa.String(20), nullable=False, server_default="mock"),
        sa.Column("circuit_state", sa.String(20), nullable=False, server_default="closed"),
        sa.Column("circuit_opened_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    ):
        op.add_column("integration_connections", column)
    op.create_unique_constraint(
        "uq_integration_connections_subscription_key",
        "integration_connections",
        ["subscription_key"],
    )
    op.create_check_constraint(
        "integration_adapter_mode", "integration_connections", "adapter_mode IN ('mock','http')"
    )
    op.create_check_constraint(
        "integration_circuit_state",
        "integration_connections",
        "circuit_state IN ('closed','open','half_open')",
    )
    op.create_check_constraint(
        "integration_version_positive", "integration_connections", "version >= 1"
    )
    op.execute("""
      CREATE OR REPLACE FUNCTION oracle_resolve_signal_subscription(p_key text)
      RETURNS TABLE(tenant_id uuid, connection_id uuid)
      LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $$
        SELECT c.tenant_id, c.id
        FROM public.integration_connections c
        WHERE c.subscription_key = p_key
          AND c.provider = 'signal-avanza'
          AND c.status = 'active'
        LIMIT 1
      $$
    """)
    op.execute("REVOKE ALL ON FUNCTION oracle_resolve_signal_subscription(text) FROM PUBLIC")
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT EXECUTE ON FUNCTION oracle_resolve_signal_subscription(text) TO oracle_app;
      END IF; END $$
    """)

    op.drop_constraint("uq_credential_connection_version", "api_credentials", type_="unique")
    op.add_column(
        "api_credentials",
        sa.Column("credential_kind", sa.String(30), nullable=False, server_default="api_token"),
    )
    op.add_column(
        "api_credentials",
        sa.Column("algorithm", sa.String(30), nullable=False, server_default="AES-256-GCM"),
    )
    op.add_column(
        "api_credentials",
        sa.Column(
            "valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column("api_credentials", sa.Column("valid_until", sa.DateTime(timezone=True)))
    op.add_column("api_credentials", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint(
        "uq_credential_connection_kind_version",
        "api_credentials",
        ["connection_id", "credential_kind", "credential_version"],
    )
    op.create_check_constraint(
        "credential_kind", "api_credentials", "credential_kind IN ('api_token','webhook_secret')"
    )
    op.create_check_constraint(
        "credential_algorithm", "api_credentials", "algorithm = 'AES-256-GCM'"
    )

    for column in (
        sa.Column("connection_id", sa.UUID()),
        sa.Column("desired_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("observed_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("signal_monitors", column)
    op.create_foreign_key(
        "fk_monitors_connection_tenant",
        "signal_monitors",
        "integration_connections",
        ["connection_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "signal_monitor_desired_status",
        "signal_monitors",
        "desired_status IN ('active','paused','disabled')",
    )
    op.create_check_constraint(
        "signal_monitor_observed_status",
        "signal_monitors",
        "observed_status IN ('pending','active','paused','disabled','error')",
    )
    op.add_column("signals", sa.Column("provider_connection_id", sa.UUID()))
    op.drop_constraint("uq_signal_provider_external", "signals", type_="unique")
    op.create_foreign_key(
        "fk_signals_connection_tenant",
        "signals",
        "integration_connections",
        ["provider_connection_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_signal_connection_external",
        "signals",
        ["tenant_id", "provider_connection_id", "external_id"],
    )
    op.drop_constraint("uq_signal_raw_hash", "signals", type_="unique")
    op.create_unique_constraint(
        "uq_signal_connection_raw_hash",
        "signals",
        ["tenant_id", "provider_connection_id", "raw_hash"],
    )

    op.create_table(
        "signal_monitor_config_versions",
        *_tenant_columns(),
        sa.Column("monitor_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", JSONB, nullable=False),
        sa.Column("snapshot_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("created_by_user_id", sa.UUID()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["monitor_id", "tenant_id"],
            ["signal_monitors.id", "signal_monitors.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "created_by_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_monitor_config_id_tenant"),
        sa.UniqueConstraint("tenant_id", "monitor_id", "version", name="uq_monitor_config_version"),
        sa.CheckConstraint("version >= 1", name="monitor_config_version_positive"),
        sa.CheckConstraint("octet_length(snapshot_hash) = 32", name="monitor_config_hash_length"),
        sa.CheckConstraint(
            "jsonb_typeof(snapshot) = 'object'", name="monitor_config_snapshot_object"
        ),
    )
    op.create_table(
        "integration_outbox_events",
        *_tenant_columns(),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("monitor_id", sa.UUID()),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("request_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("intention_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.String(200)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.Column("correlation_id", sa.String(100)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["integration_connections.id", "integration_connections.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["monitor_id", "tenant_id"],
            ["signal_monitors.id", "signal_monitors.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_integration_outbox_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_integration_outbox_idempotency"
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','delivered','retrying','failed')",
            name="integration_outbox_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1", name="integration_outbox_attempts"
        ),
        sa.CheckConstraint(
            "octet_length(request_hash) = 32", name="integration_outbox_request_hash"
        ),
        sa.CheckConstraint(
            "octet_length(intention_hash) = 32", name="integration_outbox_intention_hash"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name="integration_outbox_payload_object"
        ),
    )
    op.create_index(
        "ix_integration_outbox_due", "integration_outbox_events", ["status", "next_attempt_at"]
    )
    op.create_table(
        "integration_inbox_events",
        *_tenant_columns(),
        sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("provider_event_id", sa.String(240), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("raw_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("raw_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column(
            "signature_version", sa.String(30), nullable=False, server_default="hmac-sha256-v1"
        ),
        sa.Column("schema_version", sa.String(30), nullable=False, server_default="v1-provisional"),
        sa.Column("raw_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("safe_headers", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(500)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["integration_connections.id", "integration_connections.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_integration_inbox_id_tenant"),
        sa.UniqueConstraint(
            "connection_id", "provider_event_id", name="uq_integration_inbox_provider_event"
        ),
        sa.CheckConstraint(
            "status IN ('received','validated','queued','processed','rejected','failed')",
            name="integration_inbox_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="integration_inbox_attempts"),
        sa.CheckConstraint("octet_length(raw_hash) = 32", name="integration_inbox_hash_length"),
        sa.CheckConstraint(
            "jsonb_typeof(safe_headers) = 'object'", name="integration_inbox_headers_object"
        ),
    )
    op.create_index(
        "ix_integration_inbox_status",
        "integration_inbox_events",
        ["tenant_id", "status", "created_at"],
    )
    op.create_table(
        "signal_sync_runs",
        *_tenant_columns(),
        sa.Column("monitor_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID()),
        sa.Column("cursor_before", sa.String(500)),
        sa.Column("cursor_after", sa.String(500)),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["monitor_id", "tenant_id"],
            ["signal_monitors.id", "signal_monitors.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "tenant_id"],
            ["background_jobs.id", "background_jobs.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_signal_sync_runs_id_tenant"),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed')", name="signal_sync_run_status"
        ),
        sa.CheckConstraint(
            "received >= 0 AND created >= 0 AND duplicates >= 0", name="signal_sync_run_counts"
        ),
    )
    op.create_index(
        "ix_signal_sync_runs_monitor",
        "signal_sync_runs",
        ["tenant_id", "monitor_id", "created_at"],
    )
    op.create_table(
        "signal_ingestion_records",
        *_tenant_columns(),
        sa.Column("monitor_id", sa.UUID(), nullable=False),
        sa.Column("sync_run_id", sa.UUID()),
        sa.Column("inbox_event_id", sa.UUID()),
        sa.Column("signal_id", sa.UUID()),
        sa.Column("provider_signal_id", sa.String(240), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False, server_default="v1-provisional"),
        sa.Column("normalization_version", sa.String(30), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.String(500)),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["monitor_id", "tenant_id"],
            ["signal_monitors.id", "signal_monitors.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["signal_sync_runs.id", "signal_sync_runs.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inbox_event_id", "tenant_id"],
            ["integration_inbox_events.id", "integration_inbox_events.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id", "tenant_id"], ["signals.id", "signals.tenant_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_signal_ingestion_records_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id", "monitor_id", "provider_signal_id", name="uq_signal_ingestion_provider"
        ),
        sa.CheckConstraint(
            "status IN ('created','changed','duplicate','failed')",
            name="signal_ingestion_status",
        ),
        sa.CheckConstraint("occurrence_count >= 1", name="signal_ingestion_occurrences"),
        sa.CheckConstraint("octet_length(content_hash) = 32", name="signal_ingestion_hash_length"),
    )
    for table in (
        "signal_monitor_config_versions",
        "integration_outbox_events",
        "integration_inbox_events",
        "signal_sync_runs",
        "signal_ingestion_records",
    ):
        _secure_tenant_table(table)
    op.execute("""
      CREATE OR REPLACE FUNCTION oracle_signal_outbox_due(p_limit integer DEFAULT 100)
      RETURNS TABLE(tenant_id uuid, event_id uuid)
      LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $$
        SELECT e.tenant_id, e.id
        FROM public.integration_outbox_events e
        WHERE (
          e.status IN ('pending','retrying')
          AND (e.next_attempt_at IS NULL OR e.next_attempt_at <= now())
        ) OR (
          e.status = 'processing' AND e.claimed_at < now() - interval '2 minutes'
        )
        ORDER BY e.created_at
        LIMIT LEAST(GREATEST(p_limit,1),500)
      $$
    """)
    op.execute("REVOKE ALL ON FUNCTION oracle_signal_outbox_due(integer) FROM PUBLIC")
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT EXECUTE ON FUNCTION oracle_signal_outbox_due(integer) TO oracle_app;
      END IF; END $$
    """)
    op.execute("""
      CREATE OR REPLACE FUNCTION oracle_signal_inbox_due(p_limit integer DEFAULT 100)
      RETURNS TABLE(tenant_id uuid, inbox_id uuid)
      LANGUAGE sql STABLE SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $$
        SELECT e.tenant_id, e.id
        FROM public.integration_inbox_events e
        WHERE e.status = 'queued'
           OR (e.status = 'failed' AND e.attempts < 5)
           OR (e.status = 'validated' AND e.updated_at < now() - interval '2 minutes')
        ORDER BY e.created_at
        LIMIT LEAST(GREATEST(p_limit,1),500)
      $$
    """)
    op.execute("REVOKE ALL ON FUNCTION oracle_signal_inbox_due(integer) FROM PUBLIC")
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT EXECUTE ON FUNCTION oracle_signal_inbox_due(integer) TO oracle_app;
      END IF; END $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS oracle_signal_inbox_due(integer)")
    op.execute("DROP FUNCTION IF EXISTS oracle_signal_outbox_due(integer)")
    op.execute("DROP FUNCTION IF EXISTS oracle_resolve_signal_subscription(text)")
    for table in (
        "signal_ingestion_records",
        "signal_sync_runs",
        "integration_inbox_events",
        "integration_outbox_events",
        "signal_monitor_config_versions",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_background_jobs_id_tenant", "background_jobs", type_="unique")
    op.execute("""
      UPDATE signals
      SET external_id = provider_connection_id::text || ':' || left(external_id, 203),
          raw_hash = decode(
            md5(provider_connection_id::text || encode(raw_hash,'hex')) ||
            md5(encode(raw_hash,'hex') || provider_connection_id::text),
            'hex'
          )
      WHERE provider_connection_id IS NOT NULL
    """)
    op.drop_constraint("uq_signal_connection_raw_hash", "signals", type_="unique")
    op.create_unique_constraint("uq_signal_raw_hash", "signals", ["tenant_id", "raw_hash"])
    op.drop_constraint("uq_signal_connection_external", "signals", type_="unique")
    op.drop_constraint("fk_signals_connection_tenant", "signals", type_="foreignkey")
    op.drop_column("signals", "provider_connection_id")
    op.create_unique_constraint(
        "uq_signal_provider_external", "signals", ["tenant_id", "provider", "external_id"]
    )
    op.drop_constraint("fk_monitors_connection_tenant", "signal_monitors", type_="foreignkey")
    op.drop_constraint("signal_monitor_observed_status", "signal_monitors", type_="check")
    op.drop_constraint("signal_monitor_desired_status", "signal_monitors", type_="check")
    for name in (
        "last_sync_attempt_at",
        "next_sync_at",
        "observed_status",
        "desired_status",
        "connection_id",
    ):
        op.drop_column("signal_monitors", name)
    op.drop_constraint("uq_credential_connection_kind_version", "api_credentials", type_="unique")
    op.drop_constraint("credential_algorithm", "api_credentials", type_="check")
    op.execute("""
      WITH ranked AS (
        SELECT id, row_number() OVER (
          PARTITION BY connection_id
          ORDER BY credential_kind, credential_version, id
        ) AS new_version
        FROM api_credentials
      )
      UPDATE api_credentials c
      SET credential_version = ranked.new_version
      FROM ranked
      WHERE c.id = ranked.id
    """)
    for name in ("retired_at", "valid_until", "valid_from", "algorithm", "credential_kind"):
        op.drop_column("api_credentials", name)
    op.create_unique_constraint(
        "uq_credential_connection_version",
        "api_credentials",
        ["connection_id", "credential_version"],
    )
    op.drop_constraint(
        "uq_integration_connections_subscription_key",
        "integration_connections",
        type_="unique",
    )
    for name in (
        "version",
        "last_error",
        "last_success_at",
        "last_health_at",
        "circuit_opened_at",
        "circuit_state",
        "adapter_mode",
        "subscription_key",
        "api_version",
        "base_url",
    ):
        op.drop_column("integration_connections", name)
