from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from flask import Flask

from opn_oracle import create_app
from opn_oracle.common.logging import JsonFormatter, RedactingFilter, SafeFormatter, redact
from opn_oracle.common.metrics import MetricsRegistry
from opn_oracle.common.request_context import request_log_fields
from opn_oracle.config import ConfigError, Settings
from opn_oracle.extensions import db


@pytest.mark.unit
def test_create_test_app(app: Flask) -> None:
    assert app.config["APP_ENV"] == "test"
    assert app.config["TESTING"] is True
    assert app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] is False


@pytest.mark.unit
def test_production_fails_fast_with_unsafe_config() -> None:
    with pytest.raises(ConfigError, match="producción incompleta"):
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "short",
                "DATABASE_URL": "sqlite:///unsafe.db",
                "REDIS_URL": "invalid",
                "FRONTEND_ORIGIN": "http://unsafe.example",
            }
        )


@pytest.mark.unit
def test_file_backed_secrets_are_loaded_without_changing_plain_settings(tmp_path: Path) -> None:
    secret = tmp_path / "secret-key"
    database = tmp_path / "database-url"
    secret.write_text("x" * 40 + "\n", encoding="utf-8")
    database.write_text("postgresql://oracle_app:opaque@db/oracle\n", encoding="utf-8")

    settings = Settings.load(
        {
            "APP_ENV": "test",
            "SECRET_KEY_FILE": str(secret),
            "DATABASE_URL_FILE": str(database),
            "REDIS_URL": "redis://127.0.0.1:6379/15",
        }
    )

    assert settings.secret_key == "x" * 40
    assert settings.database_url == "postgresql+psycopg://oracle_app:opaque@db/oracle"


@pytest.mark.unit
def test_file_backed_secret_rejects_conflicting_inline_value(tmp_path: Path) -> None:
    secret = tmp_path / "secret-key"
    secret.write_text("x" * 40, encoding="utf-8")

    with pytest.raises(ConfigError, match="no pueden configurarse a la vez"):
        Settings.load(
            {
                "APP_ENV": "test",
                "SECRET_KEY": "y" * 40,
                "SECRET_KEY_FILE": str(secret),
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )


@pytest.mark.unit
@pytest.mark.parametrize("raw_path", ["relative/secret", "/path/that/does/not/exist"])
def test_file_backed_secret_rejects_unsafe_path(raw_path: str) -> None:
    with pytest.raises(ConfigError, match="SECRET_KEY_FILE"):
        Settings.load(
            {
                "APP_ENV": "test",
                "SECRET_KEY_FILE": raw_path,
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            }
        )


@pytest.mark.unit
def test_valid_production_disables_openapi_by_default() -> None:
    app = create_app(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "x" * 40,
            "DATABASE_URL": "postgresql://user:password@db/oracle",
            "REDIS_URL": "rediss://redis.example/0",
            "FRONTEND_ORIGIN": "https://oracle.example",
            "LOG_FORMAT": "json",
            "MAIL_BACKEND": "smtp",
            "SMTP_HOST": "smtp.example",
            "MAIL_FROM": "oracle@example.test",
        }
    )
    assert app.config["OPENAPI_ENABLED"] is False
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql+psycopg://")
    with app.test_client() as client:
        response = client.get("/api/v1/meta")
        assert response.get_json()["capabilities"] == ["health"]
        assert response.headers["Content-Security-Policy"].startswith("default-src 'none'")
        assert "Strict-Transport-Security" not in response.headers


@pytest.mark.unit
def test_create_app_tolerates_local_storage_chmod_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = (tmp_path / "oracle-storage").resolve()
    original_chmod = os.chmod

    def readonly_chmod(path: str | os.PathLike[str], mode: int) -> None:
        if Path(path) == root:
            raise OSError(30, "Read-only file system", str(path))
        original_chmod(path, mode)

    monkeypatch.setattr("opn_oracle.documents.storage.os.chmod", readonly_chmod)

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "DOCUMENT_STORAGE_BACKEND": "local",
            "DOCUMENT_LOCAL_ROOT": str(root),
        }
    )

    assert app.extensions["object_storage"].root == root
    assert app.extensions["object_storage"].health() is True


@pytest.mark.unit
def test_create_app_tolerates_uncreatable_local_storage_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = (tmp_path / "missing-storage").resolve()
    original_mkdir = Path.mkdir

    def readonly_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == root:
            raise OSError(30, "Read-only file system", str(self))
        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr("opn_oracle.documents.storage.Path.mkdir", readonly_mkdir)

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "DOCUMENT_STORAGE_BACKEND": "local",
            "DOCUMENT_LOCAL_ROOT": str(root),
        }
    )

    assert app.extensions["object_storage"].root == root
    assert app.extensions["object_storage"].health() is False


@pytest.mark.unit
def test_api_security_headers_and_sensitive_cache_policy(client: Any) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Permissions-Policy"].startswith("accelerometer=()")
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"


@pytest.mark.unit
def test_hsts_requires_explicit_gate_and_https() -> None:
    hsts_app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "HSTS_ENABLED": True,
        }
    )
    with hsts_app.test_client() as hsts_client:
        plain = hsts_client.get("/health/live")
        secure = hsts_client.get("/health/live", base_url="https://oracle.example")
    assert "Strict-Transport-Security" not in plain.headers
    assert secure.headers["Strict-Transport-Security"] == ("max-age=31536000; includeSubDomains")


@pytest.mark.unit
def test_production_rejects_debug() -> None:
    with pytest.raises(ConfigError, match="FLASK_DEBUG=false"):
        create_app(
            {
                "APP_ENV": "production",
                "FLASK_DEBUG": True,
                "SECRET_KEY": "x" * 40,
                "DATABASE_URL": "postgresql://user:password@db/oracle",
                "REDIS_URL": "rediss://redis.example/0",
                "FRONTEND_ORIGIN": "https://oracle.example",
            }
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TRUSTED_PROXY_COUNT", "invalid"),
        ("DEPENDENCY_TIMEOUT_SECONDS", "invalid"),
        ("SQLALCHEMY_POOL_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_numeric_config_is_safe(name: str, value: str) -> None:
    with pytest.raises(ConfigError, match=name):
        create_app({"APP_ENV": "test", "DATABASE_URL": "sqlite:///:memory:", name: value})


@pytest.mark.unit
def test_request_id_is_propagated(client: Any) -> None:
    request_id = "req-test-12345678"
    response = client.get("/health/live", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["X-Correlation-ID"] == request_id


@pytest.mark.unit
def test_metrics_are_disabled_and_indistinguishable_by_default(client: Any) -> None:
    response = client.get("/internal/metrics", headers={"Authorization": "Bearer guessed"})
    assert response.status_code == 404


@pytest.mark.unit
def test_metrics_require_token_and_use_low_cardinality_routes() -> None:
    token = "metrics-test-token-with-at-least-32-characters"
    metrics_app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "test-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "METRICS_ENABLED": True,
            "METRICS_TOKEN": token,
        }
    )
    with metrics_app.test_client() as metrics_client:
        metrics_client.get("/health/live")
        assert metrics_client.get("/internal/metrics").status_code == 404
        response = metrics_client.get(
            "/internal/metrics", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
    body = response.get_data(as_text=True)
    assert 'route="/health/live"' in body
    assert "opn_http_request_duration_seconds_bucket" in body
    assert "opn_db_pool_checked_out" not in body  # SQLite StaticPool has no checkedout gauge.


@pytest.mark.unit
def test_metrics_configuration_fails_closed() -> None:
    with pytest.raises(ConfigError, match="METRICS_TOKEN"):
        create_app(
            {
                "APP_ENV": "test",
                "DATABASE_URL": "sqlite+pysqlite:///:memory:",
                "METRICS_ENABLED": True,
                "METRICS_TOKEN": "short",
            }
        )


@pytest.mark.unit
def test_metrics_histogram_memory_is_bounded() -> None:
    registry = MetricsRegistry()
    for index in range(10_000):
        registry.observe_request(
            method="GET",
            route="/api/v1/dossiers/<uuid:dossier_id>",
            status=200,
            duration_seconds=(index % 500) / 1000,
        )
    aggregate = registry.durations[("GET", "/api/v1/dossiers/<uuid:dossier_id>")]
    assert aggregate.count == 10_000
    assert len(aggregate.bucket_counts) == 9
    assert not any(isinstance(value, float) for value in aggregate.bucket_counts)
    output = registry.render()
    assert "opn_http_request_duration_seconds_count" in output
    assert " 10000" in output


@pytest.mark.unit
def test_invalid_request_id_is_replaced(client: Any) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "bad value"})
    generated = response.headers["X-Request-ID"]
    assert len(generated) == 32
    assert generated != "bad value"


@pytest.mark.unit
def test_request_logs_route_template_instead_of_secret_path(app: Flask) -> None:
    @app.get("/_test/invitations/<token>/accept")
    def invitation(token: str) -> str:
        del token
        fields = request_log_fields(app.response_class())
        return str(fields["path"])

    with app.test_client() as client:
        response = client.get("/_test/invitations/secret-canary/accept")

    assert response.get_data(as_text=True) == "/_test/invitations/<token>/accept"
    assert "secret-canary" not in response.get_data(as_text=True)


@pytest.mark.unit
def test_redaction_filter_removes_sensitive_values() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Authorization=Bearer-secret Cookie=session-value password=hunter2",
        (),
        None,
    )
    assert RedactingFilter().filter(record)
    message = record.getMessage()
    assert "Bearer-secret" not in message
    assert "session-value" not in message
    assert "hunter2" not in message
    assert message.count("[REDACTED]") == 3
    assert redact("token=abc") == "token=[REDACTED]"


@pytest.mark.unit
def test_exception_formatter_redacts_secret() -> None:
    try:
        raise RuntimeError("password=exception-canary")
    except RuntimeError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    output = SafeFormatter("%(message)s").format(record)
    assert "exception-canary" not in output
    assert "password=[REDACTED]" in output


@pytest.mark.unit
def test_json_logging_recursively_redacts_nested_canaries() -> None:
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "sync %s",
        ({"url": "https://user:dsn-canary@db/path?token=query-canary"},),
        None,
    )
    record.event_fields = {
        "integration": {
            "api_key": "nested-key-canary",
            "items": [{"password": "nested-password-canary"}],
        }
    }
    assert RedactingFilter().filter(record)
    output = JsonFormatter().format(record)
    for canary in (
        "dsn-canary",
        "query-canary",
        "nested-key-canary",
        "nested-password-canary",
    ):
        assert canary not in output
    assert output.count("[REDACTED]") >= 4


@pytest.mark.unit
def test_database_deadlines_are_configured(app: Flask) -> None:
    production = create_app(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "x" * 40,
            "DATABASE_URL": "postgresql://user:password@db/oracle",
            "REDIS_URL": "rediss://redis.example/0",
            "FRONTEND_ORIGIN": "https://oracle.example",
            "DEPENDENCY_TIMEOUT_SECONDS": "1.25",
            "SQLALCHEMY_POOL_TIMEOUT_SECONDS": "0.75",
            "MAIL_BACKEND": "smtp",
            "SMTP_HOST": "smtp.example",
            "MAIL_FROM": "oracle@example.test",
        }
    )
    options = production.config["SQLALCHEMY_ENGINE_OPTIONS"]
    assert options["pool_timeout"] == 0.75
    assert options["connect_args"]["connect_timeout"] == 2
    assert options["connect_args"]["options"] == "-c statement_timeout=1250"


@pytest.mark.unit
def test_unhandled_error_rolls_back_and_returns_safe_problem(
    app: Flask, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    rolled_back = False

    def rollback() -> None:
        nonlocal rolled_back
        rolled_back = True

    monkeypatch.setattr(db.session, "rollback", rollback)

    @app.get("/_test/error")
    def fail() -> None:
        raise RuntimeError("database-password=must-not-leak")

    response = client.get("/_test/error")
    body = response.get_json()
    assert response.status_code == 500
    assert response.content_type == "application/problem+json"
    assert body["code"] == "internal_error"
    assert "must-not-leak" not in response.get_data(as_text=True)
    assert rolled_back is True
