from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from opn_oracle.api.health import probe_database
from opn_oracle.extensions import db


@pytest.mark.unit
def test_live_does_not_call_dependencies(app: Flask, client: Any) -> None:
    def must_not_run() -> None:
        raise AssertionError("liveness called a dependency")

    app.extensions["readiness_probes"] = {"database": must_not_run, "redis": must_not_run}
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


@pytest.mark.unit
def test_ready_reports_dependencies(client: Any) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "dependencies": {"database": {"status": "ok"}, "redis": {"status": "ok"}},
    }


@pytest.mark.unit
def test_ready_redacts_dependency_failure(app: Flask, client: Any) -> None:
    def fail() -> None:
        raise RuntimeError("postgresql://user:secret@private-host/oracle")

    app.extensions["readiness_probes"] = {"database": fail, "redis": lambda: None}
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.get_json()["dependencies"] == {
        "database": {"status": "unavailable"},
        "redis": {"status": "ok"},
    }
    assert "private-host" not in response.get_data(as_text=True)


@pytest.mark.unit
def test_database_probe_sets_transaction_statement_timeout(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []

    def execute(statement: object, params: object = None) -> None:
        calls.append((str(statement), params))

    with app.app_context():
        monkeypatch.setattr(db.session, "execute", execute)
        probe_database()

    assert calls[0] == (
        "SELECT set_config('statement_timeout', :timeout, true)",
        {"timeout": "1000ms"},
    )
    assert calls[1] == ("SELECT 1", None)


@pytest.mark.unit
def test_database_probe_rolls_back_after_timeout(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    rolled_back = False

    def execute(statement: object, params: object = None) -> None:
        raise TimeoutError("password=deadline-canary")

    def rollback() -> None:
        nonlocal rolled_back
        rolled_back = True

    with app.app_context():
        monkeypatch.setattr(db.session, "execute", execute)
        monkeypatch.setattr(db.session, "rollback", rollback)
        with pytest.raises(TimeoutError):
            probe_database()

    assert rolled_back is True
