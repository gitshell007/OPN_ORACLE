"""G-16 integration: migration, partial unique, backfill Capgemini, concurrent assign."""

from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from opn_oracle import create_app
from opn_oracle.oracle.actor_tax_id import (
    TaxIdConflictError,
    assign_actor_tax_id,
    backfill_actor_tax_ids_from_identifiers,
    resolve_or_create_actor,
    usable_company_tax_id,
)
from opn_oracle.oracle.models import Actor, ActorTaxIdConflict

pytestmark = pytest.mark.integration


def _env() -> tuple[str, str, str]:
    migration_url = os.environ.get("TEST_DATABASE_URL")
    runtime_url = os.environ.get("TEST_RUNTIME_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    if not migration_url or not runtime_url or not redis_url:
        pytest.skip("define TEST_DATABASE_URL, TEST_RUNTIME_DATABASE_URL y TEST_REDIS_URL")
    if "test" not in migration_url.lower() or "test" not in runtime_url.lower():
        pytest.fail("Las URLs de integración deben apuntar a una base desechable con 'test'")
    return migration_url, runtime_url, redis_url


def _seed_tenant(connection: Any, *, tenant_id: uuid.UUID, slug: str) -> None:
    connection.execute(
        text(
            "INSERT INTO tenants("
            "id,slug,name,status,locale,timezone,settings,created_at,updated_at"
            ") VALUES ("
            ":id,:slug,:name,'active','es-ES','UTC','{}',now(),now()"
            ") ON CONFLICT DO NOTHING"
        ),
        {"id": tenant_id, "slug": slug, "name": slug.upper()},
    )


def test_g16_migration_up_down_up_and_capgemini_backfill() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g16-tax-id-identity",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        # Ensure we exercise the G-16 upgrade path even if a prior test left head.
        upgrade(directory=migrations, revision="head")
        downgrade(directory=migrations, revision="20260806_0036")

    migrator = create_engine(migration_url)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    actor_w = uuid.uuid4()
    actor_l = uuid.uuid4()
    actor_other_tenant = uuid.uuid4()
    actor_clean = uuid.uuid4()
    t0 = datetime(2026, 3, 1, tzinfo=UTC)

    with migrator.begin() as connection:
        _seed_tenant(connection, tenant_id=tenant_a, slug=f"g16a-{tenant_a.hex[:8]}")
        _seed_tenant(connection, tenant_id=tenant_b, slug=f"g16b-{tenant_b.hex[:8]}")
        for actor_id, name, key, declared, created, tenant in (
            (
                actor_w,
                "Capgemini España S.L.",
                "capgemini-espana-s-l",
                "B08377715",
                t0,
                tenant_a,
            ),
            (
                actor_l,
                "CAPGEMINI ESPAÑA SL",
                "capgemini-espana-sl",
                "b-08.377.715",
                t0 + timedelta(hours=2),
                tenant_a,
            ),
            (
                actor_clean,
                "Inetum España S.A.",
                "inetum-espana-s-a",
                "A28855260",
                t0,
                tenant_a,
            ),
            (
                actor_other_tenant,
                "Capgemini España S.L.",
                "capgemini-espana-s-l",
                "B08377715",
                t0,
                tenant_b,
            ),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO actors(
                        id, tenant_id, actor_type, canonical_name, canonical_key,
                        aliases, identifiers, metadata, provenance, version,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant, 'organization', :name, :key,
                        '[]'::jsonb,
                        CAST(:identifiers AS jsonb),
                        '{}'::jsonb, '{}'::jsonb, 1,
                        :created, :created
                    )
                    """
                ),
                {
                    "id": actor_id,
                    "tenant": tenant,
                    "name": name,
                    "key": key,
                    "identifiers": f'{{"tax_id": "{declared}", "tax_id_scheme": "ES_CIF"}}',
                    "created": created,
                },
            )

    with app.app_context():
        upgrade(directory=migrations, revision="20260806_0037")
        upgrade(directory=migrations, revision="20260806_0037")

    with migrator.begin() as connection:
        idx = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='actors' AND indexname='uq_actors_tenant_tax_id_active'"
            )
        ).scalar()
        assert idx == "uq_actors_tenant_tax_id_active"

        winner_tax = (
            connection.execute(
                text(
                    "SELECT tax_id, tax_id_scheme, tax_id_country, canonical_key "
                    "FROM actors WHERE id=:id"
                ),
                {"id": actor_w},
            )
            .mappings()
            .one()
        )
        assert winner_tax["tax_id"] == "B08377715"
        assert winner_tax["tax_id_scheme"] == "ES_CIF"
        assert winner_tax["tax_id_country"] == "ES"
        assert winner_tax["canonical_key"] == "tax:es:B08377715"

        loser_tax = (
            connection.execute(
                text("SELECT tax_id, identifiers->>'tax_id' AS declared FROM actors WHERE id=:id"),
                {"id": actor_l},
            )
            .mappings()
            .one()
        )
        assert loser_tax["tax_id"] is None
        assert loser_tax["declared"] == "b-08.377.715"

        assert (
            connection.execute(
                text("SELECT tax_id FROM actors WHERE id=:id"), {"id": actor_clean}
            ).scalar()
            == "A28855260"
        )
        assert (
            connection.execute(
                text("SELECT tax_id FROM actors WHERE id=:id"),
                {"id": actor_other_tenant},
            ).scalar()
            == "B08377715"
        )

        conflicts = (
            connection.execute(
                text(
                    "SELECT tax_id, winner_actor_id, loser_actor_id, declared_tax_id, status "
                    "FROM actor_tax_id_conflicts WHERE tenant_id=:t"
                ),
                {"t": tenant_a},
            )
            .mappings()
            .all()
        )
        assert len(conflicts) == 1
        assert conflicts[0]["tax_id"] == "B08377715"
        assert conflicts[0]["winner_actor_id"] == actor_w
        assert conflicts[0]["loser_actor_id"] == actor_l
        assert conflicts[0]["declared_tax_id"] == "b-08.377.715"
        assert conflicts[0]["status"] == "open"

        count = connection.execute(
            text("SELECT count(*) FROM actors WHERE tenant_id=:t"), {"t": tenant_a}
        ).scalar()
        assert count == 3

    # Service backfill rerun is idempotent (still one open conflict, no deletes).
    SessionLocal = sessionmaker(bind=migrator)
    with SessionLocal() as session:
        counts = backfill_actor_tax_ids_from_identifiers(session, tenant_id=tenant_a)
        session.commit()
        assert counts["groups"] == 2  # Capgemini + Inetum
        rows = list(
            session.scalars(
                select(ActorTaxIdConflict).where(
                    ActorTaxIdConflict.tenant_id == tenant_a,
                    ActorTaxIdConflict.status == "open",
                )
            )
        )
        assert len(rows) == 1

    with app.app_context():
        downgrade(directory=migrations, revision="20260806_0036")
        with migrator.begin() as connection:
            cols = [
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name='actors' AND column_name LIKE 'tax_id%'"
                    )
                )
            ]
        assert cols == []
        upgrade(directory=migrations, revision="20260806_0037")

    with migrator.begin() as connection:
        holders = connection.execute(
            text("SELECT count(*) FROM actors WHERE tenant_id=:t AND tax_id='B08377715'"),
            {"t": tenant_a},
        ).scalar()
        assert holders == 1


def test_g16_partial_unique_and_concurrent_assign() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g16-race",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    tenant_id = uuid.uuid4()
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        _seed_tenant(connection, tenant_id=tenant_id, slug=f"g16r-{tenant_id.hex[:8]}")

    SessionLocal = sessionmaker(bind=migrator)

    def make_actor(name: str) -> uuid.UUID:
        actor_id = uuid.uuid4()
        with SessionLocal() as session:
            session.execute(
                text(
                    """
                    INSERT INTO actors(
                        id, tenant_id, actor_type, canonical_name, canonical_key,
                        aliases, identifiers, metadata, provenance, version,
                        created_at, updated_at
                    ) VALUES (
                        :id, :tenant, 'organization', :name, :key,
                        '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, '{}'::jsonb, 1,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": actor_id,
                    "tenant": tenant_id,
                    "name": name,
                    "key": "-".join(name.casefold().split())[:320],
                },
            )
            session.commit()
        return actor_id

    a_id = make_actor("Race Actor Alpha")
    b_id = make_actor("Race Actor Beta")
    barrier = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def assign_one(actor_id: uuid.UUID) -> None:
        session = SessionLocal()
        try:
            actor = session.get(Actor, actor_id)
            assert actor is not None
            barrier.wait(timeout=10)
            try:
                assign_actor_tax_id(session, actor, "B08377715")
                session.commit()
                with lock:
                    results.append("win")
            except TaxIdConflictError:
                session.rollback()
                with lock:
                    results.append("conflict")
            except Exception:
                session.rollback()
                with lock:
                    results.append("error")
                raise
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(assign_one, a_id), pool.submit(assign_one, b_id)]
        for fut in futs:
            fut.result(timeout=30)

    assert results.count("win") == 1, results
    assert results.count("conflict") == 1, results
    assert "error" not in results

    with SessionLocal() as session:
        holders = session.execute(
            text("SELECT id FROM actors WHERE tenant_id = :t AND tax_id = 'B08377715'"),
            {"t": tenant_id},
        ).fetchall()
        assert len(holders) == 1

    # Cross-tenant same CIF allowed.
    tenant_2 = uuid.uuid4()
    with migrator.begin() as connection:
        _seed_tenant(connection, tenant_id=tenant_2, slug=f"g16r2-{tenant_2.hex[:8]}")
    other_id = uuid.uuid4()
    with SessionLocal() as session:
        session.execute(
            text(
                """
                INSERT INTO actors(
                    id, tenant_id, actor_type, canonical_name, canonical_key,
                    tax_id, tax_id_scheme, tax_id_country,
                    aliases, identifiers, metadata, provenance, version,
                    created_at, updated_at
                ) VALUES (
                    :id, :tenant, 'organization', 'Other Tenant Capgemini',
                    'tax:es:B08377715',
                    'B08377715', 'ES_CIF', 'ES',
                    '[]'::jsonb, '{"tax_id":"B08377715"}'::jsonb,
                    '{}'::jsonb, '{}'::jsonb, 1,
                    now(), now()
                )
                """
            ),
            {"id": other_id, "tenant": tenant_2},
        )
        session.commit()
        assert (
            session.execute(
                text("SELECT tax_id FROM actors WHERE id=:id"), {"id": other_id}
            ).scalar()
            == "B08377715"
        )


def test_g16_resolve_or_create_tax_id_authority() -> None:
    migration_url, runtime_url, redis_url = _env()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g16-http",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    tenant_id = uuid.uuid4()
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        _seed_tenant(connection, tenant_id=tenant_id, slug=f"g16h-{tenant_id.hex[:8]}")

    SessionLocal = sessionmaker(bind=migrator)
    with SessionLocal() as session:
        first = resolve_or_create_actor(
            session,
            tenant_id=tenant_id,
            canonical_name="Capgemini España S.L.",
            identifiers={"tax_id": "B08377715"},
        )
        session.commit()
        assert first.tax_id == "B08377715"
        assert first.canonical_key == "tax:es:B08377715"

        second = resolve_or_create_actor(
            session,
            tenant_id=tenant_id,
            canonical_name="CAPGEMINI ESPAÑA SL",
            identifiers={"tax_id": "B08377715"},
        )
        session.commit()
        assert second.id == first.id

        third = resolve_or_create_actor(
            session,
            tenant_id=tenant_id,
            canonical_name="Nexus Tech SL",
            identifiers={},
        )
        session.commit()
        assert third.tax_id is None
        assert third.canonical_key == "nexus-tech-sl"
        assert usable_company_tax_id("***1234**") is None
        assert usable_company_tax_id("12345678Z") is None
