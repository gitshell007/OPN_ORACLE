"""MDEV-04: migration 0028↔0029 roundtrip, RLS, grants, unique NULL scope, FKs."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from opn_oracle import create_app

pytestmark = pytest.mark.integration


def _env() -> tuple[str, str, str]:
    migration_url = os.environ.get("TEST_DATABASE_URL")
    runtime_url = os.environ.get("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not migration_url or not runtime_url or not redis_url:
        pytest.skip("define TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL")
    if "test" not in migration_url.lower() or "test" not in runtime_url.lower():
        pytest.fail("Las URLs de integración deben apuntar a una base desechable con 'test'")
    return migration_url, runtime_url, redis_url


def _set_tenant(connection: object, tenant_id: uuid.UUID) -> None:
    connection.execute(  # type: ignore[attr-defined]
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )


def _seed_tenant_dossier(
    connection: object,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    slug: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (workspace_id, dossier_id)."""
    workspace_id = uuid.uuid4()
    dossier_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO tenants("
            "id,slug,name,status,locale,timezone,settings,created_at,updated_at"
            ") VALUES (:tenant,:slug,:name,'active','es-ES','UTC','{}',now(),now())"
        ),
        {"tenant": tenant_id, "slug": slug, "name": slug.upper()},
    )
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO tenant_memberships("
            "id,tenant_id,user_id,status,settings,created_at,updated_at"
            ") VALUES (:m,:tenant,:user,'active','{}',now(),now())"
        ),
        {"m": membership_id, "tenant": tenant_id, "user": user_id},
    )
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO workspaces("
            "id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at"
            ") VALUES (:w,:tenant,:slug,:name,'active',true,'{}',now(),now())"
        ),
        {"w": workspace_id, "tenant": tenant_id, "slug": f"ws-{slug}", "name": f"WS {slug}"},
    )
    connection.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO strategic_dossiers("
            "id,tenant_id,workspace_id,title,description,dossier_type,status,"
            "strategic_goal,geography,sectors,languages,scoring_config,"
            "health_score,opportunity_score,risk_score,score_explanation,"
            "version,synthetic_data,created_at,updated_at"
            ") VALUES ("
            ":id,:tenant,:workspace,:title,'','custom','draft','','[]','[]','[]','{}',"
            "0,0,0,'{}',1,false,now(),now())"
        ),
        {
            "id": dossier_id,
            "tenant": tenant_id,
            "workspace": workspace_id,
            "title": f"Dossier {slug}",
        },
    )
    return workspace_id, dossier_id


def test_mdev04_0029_up_down_up_rls_grants_unique_and_fk() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "mdev04-memory-migration",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")

    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations, revision="20260731_0028")

    migrator = create_engine(migration_url)
    runtime = create_engine(runtime_url)

    with migrator.connect() as connection:
        before_tables = {
            row
            for row in connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            ).scalars()
        }
    assert "dossier_memory_profiles" not in before_tables
    assert "memory_retrieval_snapshots" not in before_tables

    # 0028 → 0029
    with app.app_context():
        upgrade(directory=migrations, revision="20260802_0029")

    with migrator.connect() as connection:
        for table in ("dossier_memory_profiles", "memory_retrieval_snapshots"):
            assert connection.scalar(text("SELECT to_regclass(:t)"), {"t": table}) is not None
            row = connection.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relname=:t"
                ),
                {"t": table},
            ).one()
            assert row[0] is True and row[1] is True, f"{table} must FORCE RLS"
            pol = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_policies "
                    "WHERE schemaname='public' AND tablename=:t "
                    "AND policyname='tenant_isolation'"
                ),
                {"t": table},
            )
            assert pol == 1
            # runtime role grants
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                has = connection.scalar(
                    text("SELECT has_table_privilege('oracle_app', :t, :priv)"),
                    {"t": f"public.{table}", "priv": priv},
                )
                assert has is True, f"oracle_app missing {priv} on {table}"

    user_id = uuid.uuid4()
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,status,created_at,updated_at) "
                "VALUES (:user,'mdev04-mig@example.test','MDEV04','active',now(),now())"
            ),
            {"user": user_id},
        )
        _, dossier_a = _seed_tenant_dossier(
            connection, tenant_id=tenant_a, user_id=user_id, slug="mdev04-a"
        )
        _, dossier_b = _seed_tenant_dossier(
            connection, tenant_id=tenant_b, user_id=user_id, slug="mdev04-b"
        )

    # Runtime: closed without context
    with runtime.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM dossier_memory_profiles")) == 0
        assert connection.scalar(text("SELECT count(*) FROM memory_retrieval_snapshots")) == 0

    # Tenant A write + read
    profile_a = uuid.uuid4()
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_a)
        connection.execute(
            text(
                "INSERT INTO dossier_memory_profiles("
                "id,tenant_id,dossier_id,connection_id,mode,version,etag,profile_config,"
                "created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'shadow',1,'W/\"v1\"','{}'::jsonb,now(),now())"
            ),
            {"id": profile_a, "tenant": tenant_a, "dossier": dossier_a},
        )
        assert connection.scalar(text("SELECT count(*) FROM dossier_memory_profiles")) == 1

    # Tenant B cannot see A
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_b)
        assert connection.scalar(text("SELECT count(*) FROM dossier_memory_profiles")) == 0
        connection.execute(
            text(
                "INSERT INTO dossier_memory_profiles("
                "id,tenant_id,dossier_id,connection_id,mode,version,etag,profile_config,"
                "created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'augment',1,'W/\"v1\"','{}'::jsonb,now(),now())"
            ),
            {"id": uuid.uuid4(), "tenant": tenant_b, "dossier": dossier_b},
        )

    # Cross-tenant insert rejected by RLS WITH CHECK
    with pytest.raises(DBAPIError), runtime.begin() as connection:
        _set_tenant(connection, tenant_a)
        connection.execute(
            text(
                "INSERT INTO dossier_memory_profiles("
                "id,tenant_id,dossier_id,connection_id,mode,version,etag,profile_config,"
                "created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'shadow',1,'W/\"x\"','{}'::jsonb,now(),now())"
            ),
            {"id": uuid.uuid4(), "tenant": tenant_b, "dossier": dossier_b},
        )

    # Cross-tenant dossier FK: dossier of B under tenant A must fail
    with pytest.raises((DBAPIError, IntegrityError)), migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO dossier_memory_profiles("
                "id,tenant_id,dossier_id,connection_id,mode,version,etag,profile_config,"
                "created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'shadow',1,'W/\"fk\"','{}'::jsonb,now(),now())"
            ),
            {"id": uuid.uuid4(), "tenant": tenant_a, "dossier": dossier_b},
        )

    # Unique scope with connection_id NULL (NULLS NOT DISTINCT)
    with pytest.raises((DBAPIError, IntegrityError)), migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO dossier_memory_profiles("
                "id,tenant_id,dossier_id,connection_id,mode,version,etag,profile_config,"
                "created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'disabled',1,'W/\"dup\"','{}'::jsonb,now(),now())"
            ),
            {"id": uuid.uuid4(), "tenant": tenant_a, "dossier": dossier_a},
        )

    # Snapshot isolation A/B
    snap_a = uuid.uuid4()
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_a)
        connection.execute(
            text(
                "INSERT INTO memory_retrieval_snapshots("
                "id,tenant_id,dossier_id,connection_id,mode,correlation_id,context_hash,"
                "payload,created_at,updated_at"
                ") VALUES ("
                ":id,:tenant,:dossier,NULL,'shadow','corr-a',"
                ':hash,\'{"mode":"shadow"}\'::jsonb,now(),now())'
            ),
            {
                "id": snap_a,
                "tenant": tenant_a,
                "dossier": dossier_a,
                "hash": b"\x01" * 32,
            },
        )
        assert connection.scalar(text("SELECT count(*) FROM memory_retrieval_snapshots")) == 1
    with runtime.begin() as connection:
        _set_tenant(connection, tenant_b)
        assert connection.scalar(text("SELECT count(*) FROM memory_retrieval_snapshots")) == 0

    # 0029 → 0028 → 0029 roundtrip
    with app.app_context():
        downgrade(directory=migrations, revision="20260731_0028")
    with migrator.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('dossier_memory_profiles')")) is None
        assert connection.scalar(text("SELECT to_regclass('memory_retrieval_snapshots')")) is None
    with app.app_context():
        upgrade(directory=migrations, revision="20260802_0029")
    with migrator.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('dossier_memory_profiles')")) is not None
        assert (
            connection.scalar(
                text(
                    "SELECT relforcerowsecurity FROM pg_class WHERE relname="
                    "'dossier_memory_profiles'"
                )
            )
            is True
        )

    # Cleanup
    with migrator.begin() as connection:
        connection.execute(text("DELETE FROM memory_retrieval_snapshots"))
        connection.execute(text("DELETE FROM dossier_memory_profiles"))
        connection.execute(
            text("DELETE FROM strategic_dossiers WHERE title LIKE 'Dossier mdev04%'")
        )
        connection.execute(text("DELETE FROM workspaces WHERE slug LIKE 'ws-mdev04%'"))
        connection.execute(text("DELETE FROM tenant_memberships"))
        connection.execute(text("DELETE FROM tenants WHERE slug LIKE 'mdev04-%'"))
        connection.execute(text("DELETE FROM users WHERE email='mdev04-mig@example.test'"))
