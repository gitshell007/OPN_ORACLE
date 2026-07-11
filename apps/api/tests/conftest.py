from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from apiflask import APIFlask

from opn_oracle import create_app


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
