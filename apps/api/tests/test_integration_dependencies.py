"""Opt-in integration tests against a disposable PostgreSQL database and Redis DB."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from apiflask import APIFlask
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from opn_oracle import create_app
from opn_oracle.extensions import db

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def integration_app() -> Iterator[APIFlask]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 para ejecutar integración local")
    database_url = os.environ.get("TEST_DATABASE_URL")
    redis_url = os.environ.get("TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.fail("TEST_DATABASE_URL y TEST_REDIS_URL son obligatorias")
    database_name = make_url(database_url).database or ""
    if "test" not in database_name.lower():
        pytest.fail(
            "TEST_DATABASE_URL debe apuntar a una base desechable cuyo nombre contenga test"
        )

    app = create_app(
        {
            "APP_ENV": "test",
            "DATABASE_URL": database_url,
            "REDIS_URL": redis_url,
            "DEPENDENCY_TIMEOUT_SECONDS": 1,
            "SQLALCHEMY_POOL_TIMEOUT_SECONDS": 1,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    legacy_tenant, legacy_job = uuid.uuid4(), uuid.uuid4()
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations, revision="20260710_0005")
        db.session.execute(
            text(
                "INSERT INTO tenants"
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) "
                "VALUES (:tenant,'legacy-jobs','Legacy Jobs','active','es-ES','UTC','{}',"
                "now(),now())"
            ),
            {"tenant": legacy_tenant},
        )
        db.session.execute(
            text(
                "INSERT INTO background_jobs"
                "(id,tenant_id,job_type,status,queue,idempotency_key,progress,result_ref,"
                "created_at,updated_at) "
                "VALUES (:job,:tenant,'signal.promote','completed','default',"
                "'legacy-completed',100,'{}',now(),now())"
            ),
            {"job": legacy_job, "tenant": legacy_tenant},
        )
        db.session.commit()
        upgrade(directory=migrations)
        assert (
            db.session.scalar(
                text("SELECT status FROM background_jobs WHERE id=:job"), {"job": legacy_job}
            )
            == "succeeded"
        )
        assert "system_metadata" in inspect(db.engine).get_table_names()
    yield app
    with app.app_context():
        downgrade(directory=migrations, revision="base")


def test_real_postgres_redis_readiness(integration_app: APIFlask) -> None:
    with integration_app.test_client() as client:
        response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.get_json()["dependencies"] == {
        "database": {"status": "ok"},
        "redis": {"status": "ok"},
    }
