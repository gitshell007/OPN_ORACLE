"""MDEV-06 · migration 0030 memory_signal evidence upgrade→downgrade→upgrade."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app
from tests.conftest import assert_integration_schema_head

pytestmark = pytest.mark.integration


def _env() -> tuple[str, str, str]:
    """Resolve canonical integration URLs; fail closed when integration is forced."""

    migration_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_MIGRATION_URL")
    # Canonical CI/local var is TEST_RUNTIME_DATABASE_URL (not TEST_DATABASE_RUNTIME_URL).
    runtime_url = (
        os.getenv("TEST_RUNTIME_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("TEST_DATABASE_RUNTIME_URL")  # legacy typo — last resort only
    )
    redis_url = os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/15"
    integration_forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url or not runtime_url:
        detail = (
            "missing canonical DB URLs for migration 0030: need TEST_DATABASE_URL "
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


@pytest.fixture
def migration_0030_state() -> Iterator[tuple[Any, Any, uuid.UUID, str, str]]:
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
    try:
        yield app, migrator, tenant_id, migration_url, migrations
    finally:
        # Restore the real checkout head and remove all rows owned by this test even
        # when its body fails at an intermediate migration revision.
        try:
            with app.app_context():
                upgrade(directory=migrations, revision="head")
            with migrator.begin() as connection:
                connection.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant_id})
            assert_integration_schema_head(migration_url, migrations)
        finally:
            migrator.dispose()


def test_memory_signal_0030_up_down_up_counts(
    migration_0030_state: tuple[Any, Any, uuid.UUID, str, str],
) -> None:
    app, migrator, tenant_id, _, migrations = migration_0030_state
    evidence_id = uuid.uuid4()
    with migrator.begin() as connection:
        # Minimal tenant for FK if required — evidence.tenant_id FK to tenants.
        connection.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES ("
                ":id, :slug, 'MDEV06', 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now()"
                ") ON CONFLICT DO NOTHING"
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


def test_migration_0030_finalizer_restores_head_after_consumer_failure() -> None:
    """Drive the yield fixture with a thrown exception and verify real DB cleanup."""

    fixture = migration_0030_state.__wrapped__()
    app, migrator, tenant_id, migration_url, migrations = next(fixture)
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                "created_at, updated_at) VALUES ("
                ":id, :slug, 'MDEV06-finalizer', 'active', 'es-ES', 'UTC', "
                "'{}'::jsonb, now(), now())"
            ),
            {"id": tenant_id, "slug": f"mdev06-finalizer-{tenant_id.hex[:8]}"},
        )
    with app.app_context():
        downgrade(directory=migrations, revision="20260802_0029")
    with pytest.raises(RuntimeError, match="simulated migration-test failure"):
        fixture.throw(RuntimeError("simulated migration-test failure"))

    assert_integration_schema_head(migration_url, migrations)
    verification = create_engine(migration_url)
    try:
        with verification.connect() as connection:
            residue = connection.scalar(
                text("SELECT count(*) FROM tenants WHERE id=:id"), {"id": tenant_id}
            )
    finally:
        verification.dispose()
    assert residue == 0
