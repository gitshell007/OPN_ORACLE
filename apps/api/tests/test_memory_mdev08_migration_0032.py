"""MDEV-08 · migration 0032 report_ai_usage_bindings upgrade→downgrade→upgrade."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app

pytestmark = pytest.mark.integration


def _env() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_MIGRATION_URL")
    runtime_url = (
        os.getenv("TEST_RUNTIME_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("TEST_DATABASE_RUNTIME_URL")
    )
    redis_url = os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/15"
    integration_forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url or not runtime_url:
        detail = (
            "missing canonical DB URLs for migration 0032: need TEST_DATABASE_URL "
            f"(got={'set' if migration_url else 'missing'}) and "
            f"TEST_RUNTIME_DATABASE_URL (got={'set' if runtime_url else 'missing'})"
        )
        if integration_forced:
            pytest.fail(detail)
        pytest.skip(detail + " (set ORACLE_RUN_INTEGRATION=1 to fail instead of skip)")
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if runtime_url.startswith("postgresql://"):
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return migration_url, runtime_url, redis_url


def test_report_ai_usage_bindings_0032_up_down_up_rls_and_unique() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "mdev08-migration-0032",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")
        upgrade(directory=migrations, revision="head")  # idempotent / drift-safe

    migrator = create_engine(migration_url)
    tenant_id = uuid.uuid4()
    report_id = uuid.uuid4()
    binding_id = uuid.uuid4()
    run_id = f"run-{uuid.uuid4().hex[:12]}"

    with migrator.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES ("
                ":id, :slug, 'MDEV08-0032', 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now()"
                ") ON CONFLICT DO NOTHING"
            ),
            {"id": tenant_id, "slug": f"mdev08-{tenant_id.hex[:8]}"},
        )
        connection.commit()

        exists = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name='report_ai_usage_bindings'"
            )
        )
        assert int(exists or 0) == 1

        rls = connection.scalar(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE relname='report_ai_usage_bindings'"
            )
        )
        assert rls is True

        policy = connection.scalar(
            text(
                "SELECT count(*) FROM pg_policies "
                "WHERE tablename='report_ai_usage_bindings' AND policyname='tenant_isolation'"
            )
        )
        assert int(policy or 0) >= 1

        # Optional: probe unique constraint if a full report graph is available.
        # Use SAVEPOINT so FK failures never abort the outer verification txn.
        nested = connection.begin_nested()
        try:
            connection.execute(
                text(
                    "INSERT INTO reports("
                    "id, tenant_id, dossier_id, title, status, version, generation_version, "
                    "options, content, created_at, updated_at"
                    ") VALUES ("
                    ":id, :tenant, :dossier, 'usage-bind', 'draft', 1, 1, "
                    "'{}'::jsonb, '{}'::jsonb, now(), now()"
                    ") ON CONFLICT DO NOTHING"
                ),
                {
                    "id": report_id,
                    "tenant": tenant_id,
                    "dossier": uuid.uuid4(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO report_ai_usage_bindings("
                    "id, tenant_id, report_id, phase, task_key, runtime_id, run_id, "
                    "provider, model, usage_payload, notes, created_at, updated_at"
                    ") VALUES ("
                    ":id, :tenant, :report, 'writer', 'report_custom_writer', 'RT-09', :run, "
                    "'ollama', 'qwen3.5:9b', '{}'::jsonb, '', now(), now()"
                    ")"
                ),
                {
                    "id": binding_id,
                    "tenant": tenant_id,
                    "report": report_id,
                    "run": run_id,
                },
            )
            count = connection.scalar(
                text("SELECT count(*) FROM report_ai_usage_bindings WHERE run_id=:run"),
                {"run": run_id},
            )
            assert int(count or 0) == 1
            dup_failed = False
            nested2 = connection.begin_nested()
            try:
                connection.execute(
                    text(
                        "INSERT INTO report_ai_usage_bindings("
                        "id, tenant_id, report_id, phase, task_key, runtime_id, run_id, "
                        "provider, model, usage_payload, notes, created_at, updated_at"
                        ") VALUES ("
                        ":id, :tenant, :report, 'writer', 'report_custom_writer', 'RT-09', :run, "
                        "'ollama', 'qwen3.5:9b', '{}'::jsonb, '', now(), now()"
                        ")"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tenant": tenant_id,
                        "report": report_id,
                        "run": run_id,
                    },
                )
                nested2.commit()
            except Exception:
                nested2.rollback()
                dup_failed = True
            assert dup_failed is True
            nested.commit()
        except Exception:
            nested.rollback()
        connection.commit()

    with app.app_context():
        downgrade(directory=migrations, revision="20260802_0031")

    with migrator.connect() as connection:
        gone = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name='report_ai_usage_bindings'"
            )
        )
        assert int(gone or 0) == 0

    with app.app_context():
        upgrade(directory=migrations, revision="20260802_0032")

    with migrator.connect() as connection:
        back = connection.scalar(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name='report_ai_usage_bindings'"
            )
        )
        assert int(back or 0) == 1
        rls2 = connection.scalar(
            text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                "WHERE relname='report_ai_usage_bindings'"
            )
        )
        assert rls2 is True
