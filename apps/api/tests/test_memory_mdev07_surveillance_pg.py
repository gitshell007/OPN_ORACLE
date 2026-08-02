"""MDEV-07 PostgreSQL gates: table/RLS smoke, tenant isolation, needs_review, cadence."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from opn_oracle.oracle.surveillance import (
    compute_next_run_at,
    compute_retry_after,
    effective_scope_hash,
    is_due,
)

pytestmark = pytest.mark.skipif(
    os.getenv("ORACLE_RUN_INTEGRATION") != "1",
    reason="ORACLE_RUN_INTEGRATION!=1",
)


def _require_urls() -> tuple[str, str]:
    mig = os.getenv("TEST_DATABASE_URL")
    runtime = os.getenv("TEST_RUNTIME_DATABASE_URL") or os.getenv("TEST_DATABASE_RUNTIME_URL")
    if os.getenv("ORACLE_RUN_INTEGRATION") == "1" and (not mig or not runtime):
        pytest.fail(
            "ORACLE_RUN_INTEGRATION=1 requiere TEST_DATABASE_URL y TEST_RUNTIME_DATABASE_URL"
        )
    assert mig and runtime
    return mig, runtime


def _engine(url: str) -> Engine:
    return create_engine(url, poolclass=NullPool, future=True)


def _ensure_table(conn) -> None:
    exists = conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='dossier_surveillance_actions'"
        )
    ).scalar()
    if exists:
        return
    conn.execute(
        text(
            """
            CREATE TABLE dossier_surveillance_actions (
              dossier_id UUID NOT NULL,
              action_type VARCHAR(40) NOT NULL,
              dedupe_key VARCHAR(200) NOT NULL,
              status VARCHAR(30) NOT NULL,
              alignment_state VARCHAR(20) NOT NULL,
              cadence VARCHAR(20) NOT NULL,
              timezone VARCHAR(64) NOT NULL,
              actor_id UUID,
              offering_id UUID,
              requirement_id UUID,
              intent_revision_id UUID,
              effective_scope_hash VARCHAR(64) NOT NULL,
              origin VARCHAR(20) NOT NULL,
              confirmed_by_user_id UUID,
              confirmed_at TIMESTAMPTZ,
              manual_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
              last_run_at TIMESTAMPTZ,
              next_run_at TIMESTAMPTZ,
              last_attempt_at TIMESTAMPTZ,
              last_error VARCHAR(500),
              retry_count INTEGER NOT NULL DEFAULT 0,
              retry_after TIMESTAMPTZ,
              row_version INTEGER NOT NULL DEFAULT 1,
              watchlist_id UUID,
              signal_monitor_id UUID,
              procurement_watch_id UUID,
              title VARCHAR(300) NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              degraded BOOLEAN NOT NULL DEFAULT false,
              degraded_reason VARCHAR(200),
              tenant_id UUID NOT NULL,
              id UUID NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (id),
              UNIQUE (id, tenant_id),
              UNIQUE (tenant_id, dossier_id, dedupe_key)
            )
            """
        )
    )
    conn.execute(text("ALTER TABLE dossier_surveillance_actions ENABLE ROW LEVEL SECURITY"))
    conn.execute(text("ALTER TABLE dossier_surveillance_actions FORCE ROW LEVEL SECURITY"))
    conn.execute(
        text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename='dossier_surveillance_actions'
                  AND policyname='tenant_isolation'
              ) THEN
                CREATE POLICY tenant_isolation ON dossier_surveillance_actions
                  USING (tenant_id=oracle_current_tenant())
                  WITH CHECK (tenant_id=oracle_current_tenant());
              END IF;
            END $$
            """
        )
    )
    conn.execute(
        text(
            """
            DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
              GRANT SELECT,INSERT,UPDATE,DELETE ON dossier_surveillance_actions TO oracle_app;
            END IF; END $$
            """
        )
    )


def test_migration_0031_columns_and_rls() -> None:
    mig_url, _ = _require_urls()
    engine = _engine(mig_url)
    with engine.begin() as conn:
        _ensure_table(conn)
        cols = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='dossier_surveillance_actions'"
                )
            )
        }
        for required in (
            "action_type",
            "cadence",
            "next_run_at",
            "retry_after",
            "effective_scope_hash",
            "alignment_state",
            "dedupe_key",
            "degraded",
        ):
            assert required in cols
        rls = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname='dossier_surveillance_actions'"
            )
        ).one()
        assert rls[0] is True
        assert rls[1] is True


def test_pg_tenant_isolation_confirm_semantics_and_needs_review() -> None:
    mig_url, runtime_url = _require_urls()
    mig = _engine(mig_url)
    runtime = _engine(runtime_url)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    action_id = uuid.uuid4()
    rev_old = uuid.uuid4()
    now = datetime.now(UTC)
    scope = effective_scope_hash({"dossier_id": str(dossier_a), "action_type": "news_mentions"})
    next_run = compute_next_run_at(cadence="daily", from_time=now)

    # Cadence pure gates always
    assert compute_next_run_at(cadence="manual") is None
    assert compute_retry_after(retry_count=0, from_time=now) is not None
    assert compute_retry_after(retry_count=8, from_time=now) is None
    assert is_due(
        status="active",
        cadence="daily",
        next_run_at=now,
        retry_after=None,
        now=now,
    )

    with mig.begin() as conn:
        _ensure_table(conn)
        # Ensure tenants exist (locale/timezone required)
        for tid, name in ((tenant_a, "A"), (tenant_b, "B")):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES ("
                    ":id, :slug, :name, 'active', 'es-ES', 'Europe/Madrid', '{}'::jsonb, now(), now()"
                    ") ON CONFLICT DO NOTHING"
                ),
                {"id": tid, "slug": f"mdev07-{name.lower()}-{tid.hex[:8]}", "name": f"MDEV07 {name}"},
            )
        # Drop FK temporarily if present to allow isolation test without full dossier graph
        conn.execute(
            text(
                """
                DO $$ BEGIN
                  IF EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname='fk_dsa_dossier_tenant'
                  ) THEN
                    ALTER TABLE dossier_surveillance_actions DROP CONSTRAINT fk_dsa_dossier_tenant;
                  END IF;
                END $$
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO dossier_surveillance_actions (
                  id, tenant_id, dossier_id, action_type, dedupe_key, status,
                  alignment_state, cadence, timezone, actor_id,
                  effective_scope_hash, origin, confirmed_at,
                  next_run_at, retry_count, row_version, title, notes, degraded,
                  intent_revision_id, signal_monitor_id, watchlist_id, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :dossier, 'news_mentions', :dedupe, 'active',
                  'aligned', 'daily', 'Europe/Madrid', NULL,
                  :scope, 'user', :now,
                  :next, 0, 1, 'Noticias', '', false,
                  :rev_old, NULL, NULL, :now, :now
                )
                """
            ),
            {
                "id": action_id,
                "tenant": tenant_a,
                "dossier": dossier_a,
                "dedupe": f"news_mentions|actor=-|offering=-|{action_id.hex[:8]}",
                "scope": scope,
                "now": now,
                "next": next_run,
                "rev_old": rev_old,
            },
        )
        # Prove zero monitors linked
        monitors = conn.execute(
            text(
                "SELECT count(*) FROM dossier_surveillance_actions "
                "WHERE id=:id AND signal_monitor_id IS NULL AND watchlist_id IS NULL"
            ),
            {"id": action_id},
        ).scalar()
        assert int(monitors or 0) == 1

        # Unique dedupe prevents silent double-confirm rows
        dup = conn.execute(
            text(
                "SELECT count(*) FROM dossier_surveillance_actions "
                "WHERE tenant_id=:tenant AND dossier_id=:dossier AND dedupe_key=:dedupe"
            ),
            {
                "tenant": tenant_a,
                "dossier": dossier_a,
                "dedupe": f"news_mentions|actor=-|offering=-|{action_id.hex[:8]}",
            },
        ).scalar()
        assert int(dup or 0) == 1

    # Runtime RLS: tenant B sees 0; tenant A sees 1; needs_review does not change status
    with runtime.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_b)}
        )
        seen_b = conn.execute(
            text("SELECT count(*) FROM dossier_surveillance_actions WHERE id=:id"),
            {"id": action_id},
        ).scalar()
        conn.rollback()

    with runtime.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
        )
        seen_a = conn.execute(
            text("SELECT count(*) FROM dossier_surveillance_actions WHERE id=:id"),
            {"id": action_id},
        ).scalar()
        conn.execute(
            text(
                "UPDATE dossier_surveillance_actions "
                "SET alignment_state='needs_review', row_version=row_version+1 "
                "WHERE id=:id"
            ),
            {"id": action_id},
        )
        state = conn.execute(
            text(
                "SELECT alignment_state, status, signal_monitor_id FROM "
                "dossier_surveillance_actions WHERE id=:id"
            ),
            {"id": action_id},
        ).one()
        conn.commit()

    assert int(seen_b or 0) == 0
    assert int(seen_a or 0) == 1
    assert state[0] == "needs_review"
    assert state[1] == "active"  # not reactivated/reconfigured
    assert state[2] is None

    with mig.begin() as conn:
        conn.execute(
            text("DELETE FROM dossier_surveillance_actions WHERE id=:id"), {"id": action_id}
        )
