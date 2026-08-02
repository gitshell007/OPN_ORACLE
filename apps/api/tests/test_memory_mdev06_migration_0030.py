"""MDEV-06 · migration 0030 memory_signal evidence upgrade→downgrade→upgrade."""

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
    runtime_url = os.getenv("TEST_DATABASE_RUNTIME_URL") or os.getenv("DATABASE_URL")
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/15")
    if not migration_url or not runtime_url:
        pytest.skip("TEST_DATABASE_URL / DATABASE_URL required for migration 0030 roundtrip")
    if migration_url.startswith("postgresql://"):
        migration_url = migration_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if runtime_url.startswith("postgresql://"):
        runtime_url = runtime_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return migration_url, runtime_url, redis_url


def test_memory_signal_0030_up_down_up_counts() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "mdev06-migration-0030",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        # Ensure head includes 0030, then exercise down to 0029 and back.
        upgrade(directory=migrations, revision="head")
        upgrade(directory=migrations, revision="head")  # idempotent

    migrator = create_engine(migration_url)
    tenant_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    with migrator.begin() as connection:
        # Minimal tenant for FK if required — evidence.tenant_id FK to tenants.
        connection.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, created_at, updated_at) "
                "VALUES (:id, :slug, 'MDEV06', 'active', now(), now()) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": tenant_id, "slug": f"mdev06-{tenant_id.hex[:8]}"},
        )
        # Insert memory_signal row under V6 constraint.
        connection.execute(
            text(
                "INSERT INTO evidence("
                "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                "provenance, version, created_at, updated_at"
                ") VALUES ("
                ":id, :tenant, 'memory_signal', 'excerpt dual', '{}'::jsonb, "
                ":checksum, 'internal', "
                '\'{"source_kind":"memory_signal"}\'::jsonb, 1, now(), now()'
                ")"
            ),
            {"id": evidence_id, "tenant": tenant_id, "checksum": b"\xab" * 32},
        )
        count_v6 = connection.scalar(
            text("SELECT count(*) FROM evidence WHERE source_kind='memory_signal'")
        )
        assert count_v6 >= 1

    with app.app_context():
        downgrade(directory=migrations, revision="20260802_0029")

    with migrator.begin() as connection:
        # Downgrade quarantines memory_signal → legacy_unresolved
        mem = connection.scalar(
            text("SELECT count(*) FROM evidence WHERE source_kind='memory_signal'")
        )
        assert mem == 0
        quarantined = connection.scalar(
            text("SELECT count(*) FROM evidence WHERE id=:id AND source_kind='legacy_unresolved'"),
            {"id": evidence_id},
        )
        assert quarantined == 1

    with app.app_context():
        upgrade(directory=migrations, revision="20260802_0030")

    with migrator.begin() as connection:
        # After re-upgrade, shape V6 is back; quarantined row stays legacy unless re-materialized.
        can_insert = connection.execute(
            text(
                "INSERT INTO evidence("
                "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                "provenance, version, created_at, updated_at"
                ") VALUES ("
                ":id, :tenant, 'memory_signal', 'after re-up', '{}'::jsonb, "
                ":checksum, 'internal', "
                '\'{"source_kind":"memory_signal"}\'::jsonb, 1, now(), now()'
                ")"
            ),
            {
                "id": uuid.uuid4(),
                "tenant": tenant_id,
                "checksum": b"\xcd" * 32,
            },
        )
        assert can_insert.rowcount == 1
        count = connection.scalar(
            text("SELECT count(*) FROM evidence WHERE source_kind='memory_signal'")
        )
        assert count >= 1
