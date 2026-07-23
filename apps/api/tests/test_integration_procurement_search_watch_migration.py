from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app
from tests.test_integration_procurement_search_feedback_migration import (
    _env,
    _seed_profile_with_feedback,
    _set_tenant,
)

pytestmark = pytest.mark.integration


def test_procurement_search_watch_0024_up_down_up_and_rls() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "procurement-watch-migration",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations, revision="20260723_0023")

    migrator = create_engine(migration_url)
    runtime = create_engine(runtime_url)
    tenant_a, tenant_b, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,status,created_at,updated_at) "
                "VALUES (:user,'watch-migration@example.test','Watch migration',"
                "'active',now(),now())"
            ),
            {"user": user_id},
        )
        profile_a, _ = _seed_profile_with_feedback(
            connection, tenant_id=tenant_a, user_id=user_id, slug="watch-a"
        )
        profile_b, _ = _seed_profile_with_feedback(
            connection, tenant_id=tenant_b, user_id=user_id, slug="watch-b"
        )
        connection.execute(
            text("UPDATE procurement_search_profiles SET tender_search_id=:search WHERE id=:id"),
            {"search": "signal-watch-a", "id": profile_a},
        )
        connection.execute(
            text("UPDATE procurement_search_profiles SET tender_search_id=:search WHERE id=:id"),
            {"search": "signal-watch-b", "id": profile_b},
        )

    with app.app_context():
        upgrade(directory=migrations, revision="20260724_0024")

    with runtime.begin() as connection:
        _set_tenant(connection, tenant_a)
        assert connection.scalar(text("SELECT count(*) FROM procurement_search_watches")) == 1
        assert (
            connection.scalar(
                text(
                    "SELECT profile_id FROM procurement_search_watches "
                    "WHERE tender_search_id='signal-watch-a'"
                )
            )
            == profile_a
        )
        assert connection.scalar(text("SELECT count(*) FROM procurement_search_watch_items")) == 0
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_b)
        assert connection.scalar(text("SELECT count(*) FROM procurement_search_watches")) == 1
        assert (
            connection.scalar(
                text(
                    "SELECT profile_id FROM procurement_search_watches "
                    "WHERE tender_search_id='signal-watch-b'"
                )
            )
            == profile_b
        )

    with app.app_context():
        downgrade(directory=migrations, revision="20260723_0023")
    with migrator.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('procurement_search_watches')")) is None
        assert (
            connection.scalar(text("SELECT to_regclass('procurement_search_watch_items')")) is None
        )
    with app.app_context():
        upgrade(directory=migrations, revision="20260724_0024")
    with migrator.connect() as connection:
        for table in ("procurement_search_watches", "procurement_search_watch_items"):
            assert (
                connection.scalar(
                    text("SELECT relrowsecurity FROM pg_class WHERE relname=:table"),
                    {"table": table},
                )
                is True
            )

    with migrator.begin() as connection:
        connection.execute(text("DELETE FROM procurement_search_watch_items"))
        connection.execute(text("DELETE FROM procurement_search_watches"))
        connection.execute(text("DELETE FROM procurement_search_feedback"))
        connection.execute(text("DELETE FROM procurement_search_profiles"))
        connection.execute(text("DELETE FROM ai_artifacts WHERE dossier_id IS NULL"))
        connection.execute(text("DELETE FROM ai_audit_logs WHERE dossier_id IS NULL"))
        connection.execute(text("DELETE FROM tenant_memberships"))
        connection.execute(text("DELETE FROM tenants"))
        connection.execute(text("DELETE FROM users WHERE email='watch-migration@example.test'"))
    runtime.dispose()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")
