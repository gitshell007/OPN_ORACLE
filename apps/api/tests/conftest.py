from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from apiflask import APIFlask
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from opn_oracle import create_app

_INTEGRATION_MIGRATION_LOCK = 84_720_382
_integration_lock: tuple[Connection, Engine] | None = None


def pytest_sessionstart(session: pytest.Session) -> None:
    """Serialize suites that reset the shared disposable PostgreSQL schema."""

    del session
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        return
    migration_url = os.getenv("TEST_DATABASE_URL")
    if not migration_url:
        return
    engine = create_engine(migration_url, poolclass=NullPool)
    connection = engine.connect()
    connection.execute(
        text("SELECT pg_advisory_lock(:lock_id)"),
        {"lock_id": _INTEGRATION_MIGRATION_LOCK},
    )
    connection.commit()
    global _integration_lock
    _integration_lock = (connection, engine)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Release the advisory lock after the complete integration run ends."""

    del session, exitstatus
    global _integration_lock
    if _integration_lock is None:
        return
    connection, engine = _integration_lock
    try:
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": _INTEGRATION_MIGRATION_LOCK},
        )
        connection.commit()
    finally:
        connection.close()
        engine.dispose()
        _integration_lock = None


@pytest.fixture
def app() -> Iterator[APIFlask]:
    application = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "LOG_FORMAT": "console",
            "OPENAPI_ENABLED": True,
        }
    )
    application.extensions["readiness_probes"] = {
        "database": lambda: None,
        "redis": lambda: None,
    }
    yield application


@pytest.fixture
def client(app: APIFlask) -> Any:
    return app.test_client()
