from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import pytest
from apiflask import APIFlask
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from opn_oracle import create_app

_INTEGRATION_MIGRATION_LOCK = 84_720_382
_integration_lock: tuple[Connection, Engine] | None = None

# Disposable-DB name guard: only allow TEST_* URLs whose database name contains
# one of these markers. Blocks accidental wipe of oracle_dev / production.
_DISPOSABLE_DB_MARKERS = ("test", "aislados", "ci")


def _assert_disposable_database_url(url: str, *, env_name: str) -> None:
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0]
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "postgres", "pg"}:
        raise RuntimeError(
            f"{env_name} host={host!r} is not a local/CI disposable host; refusing to run"
        )
    if not db_name or not any(marker in db_name.lower() for marker in _DISPOSABLE_DB_MARKERS):
        raise RuntimeError(
            f"{env_name} database={db_name!r} is not unambiguously disposable "
            f"(must contain one of {_DISPOSABLE_DB_MARKERS}); refusing to run"
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    """Serialize suites that reset the shared disposable PostgreSQL schema."""

    del session
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        return
    migration_url = os.getenv("TEST_DATABASE_URL")
    if not migration_url:
        return
    _assert_disposable_database_url(migration_url, env_name="TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL")
    if runtime_url:
        _assert_disposable_database_url(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL")
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


@pytest.fixture(autouse=True)
def _isolate_process_local_test_state() -> Iterator[None]:
    """Reset process-local residue that would otherwise couple test order.

    Historical class (59318fb / SV2-TESTS-AISLADOS):
    - ``configure_logging`` does ``root.handlers.clear()`` when any app is built.
    - Celery workers call ``disable_existing_loggers`` and leave module loggers
      with ``disabled=True``.
    - Procurement / entity-intel keep process-local TTL caches.

    Clearing caches and re-enabling commonly polluted loggers after each test
    makes the report/procurement family order-independent without global wipes.
    """

    yield
    from opn_oracle.integrations import entity_intel, procurement
    from opn_oracle.oracle import procurement_items

    entity_intel._CACHE.clear()
    procurement._AWARDS_CACHE.clear()
    procurement._COMPARABLE_PROFILE_CACHE.clear()
    procurement._SUGGEST_CACHE.clear()
    procurement._TENDERS_CACHE.clear()

    for name in (
        procurement_items.__name__,
        procurement.__name__,
        entity_intel.__name__,
    ):
        logging.getLogger(name).disabled = False


@pytest.fixture
def app() -> Iterator[APIFlask]:
    application = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "SESSION_TYPE": "cachelib",
            "RATELIMIT_STORAGE_URL": "memory://",
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
