"""Typed environment configuration with production fail-fast validation."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import ceil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(RuntimeError):
    """Raised when application configuration is unsafe or incomplete."""


TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

# Only settings that are credentials or embed credentials may be loaded from files. Keeping the
# list explicit prevents an unexpected ``*_FILE`` variable from changing non-secret behaviour.
FILE_BACKED_SETTINGS = frozenset(
    {
        "SECRET_KEY",
        "DATABASE_URL",
        "DATABASE_MIGRATION_URL",
        "REDIS_URL",
        "SESSION_REDIS_URL",
        "RATELIMIT_STORAGE_URL",
        "METRICS_TOKEN",
        "SMTP_PASSWORD",
        "GRAPH_CLIENT_SECRET",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "INTEGRATION_ENCRYPTION_KEYS",
        "SIGNAL_AI_API_KEY",
        "DOCUMENT_S3_ACCESS_KEY_ID",
        "DOCUMENT_S3_SECRET_ACCESS_KEY",
    }
)
MAX_SECRET_FILE_BYTES = 64 * 1024


def _load_file_backed_settings(values: dict[str, Any]) -> None:
    """Resolve allowlisted ``NAME_FILE`` settings without logging their contents."""

    for name in FILE_BACKED_SETTINGS:
        file_name = f"{name}_FILE"
        raw_path = values.get(file_name)
        if raw_path in {None, ""}:
            continue
        if name in values and values[name] not in {None, ""}:
            raise ConfigError(f"{name} y {file_name} no pueden configurarse a la vez.")

        path = Path(str(raw_path))
        if not path.is_absolute():
            raise ConfigError(f"{file_name} debe ser una ruta absoluta.")
        try:
            stat = path.stat()
            if not path.is_file():
                raise ConfigError(f"{file_name} debe apuntar a un archivo regular.")
            if stat.st_size > MAX_SECRET_FILE_BYTES:
                raise ConfigError(f"{file_name} supera el tamaño máximo permitido.")
            value = path.read_text(encoding="utf-8").rstrip("\r\n")
        except ConfigError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ConfigError(f"No se pudo leer {file_name}.") from exc
        if not value or "\x00" in value:
            raise ConfigError(f"{file_name} está vacío o no es válido.")
        values[name] = value


def _as_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() in TRUE_VALUES


def _as_int(value: str | int, *, name: str, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} debe ser un entero.") from exc
    if parsed < minimum:
        raise ConfigError(f"{name} debe ser mayor o igual que {minimum}.")
    return parsed


def _as_float(value: str | float, *, name: str, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} debe ser un número.") from exc
    if parsed <= minimum:
        raise ConfigError(f"{name} debe ser mayor que {minimum}.")
    return parsed


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings loaded from environment or explicit test overrides."""

    app_env: str
    flask_debug: bool
    secret_key: str
    database_url: str
    database_migration_url: str
    rls_enabled: bool
    redis_url: str
    session_redis_url: str
    ratelimit_storage_url: str
    log_level: str
    log_format: str
    metrics_enabled: bool
    metrics_token: str
    hsts_enabled: bool
    trusted_proxy_count: int
    frontend_origin: str
    openapi_enabled: bool
    app_version: str
    release: str
    sqlalchemy_pool_size: int
    sqlalchemy_max_overflow: int
    sqlalchemy_pool_timeout_seconds: float
    dependency_timeout_seconds: float
    session_cookie_name: str
    session_idle_minutes: int
    session_absolute_hours: int
    password_min_length: int
    password_max_bytes: int
    auth_max_failures: int
    auth_lock_seconds: int
    invitation_ttl_hours: int
    password_reset_ttl_minutes: int
    revoke_other_sessions_on_password_change: bool
    sensitive_reauth_minutes: int
    mail_backend: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_use_tls: bool
    mail_from: str
    graph_tenant_id: str
    graph_client_id: str
    graph_client_secret: str
    graph_sender_mailbox: str
    graph_timeout_seconds: float
    celery_broker_url: str
    celery_result_backend: str
    celery_task_always_eager: bool
    celery_task_eager_propagates: bool
    celery_acks_late: bool
    celery_worker_prefetch_multiplier: int
    celery_task_soft_time_limit: int
    celery_task_time_limit: int
    celery_result_expires: int
    celery_default_queue: str
    celery_timezone: str
    nightly_summaries_enabled: bool
    nightly_summaries_hour: int
    nightly_summaries_minute: int
    signal_avanza_enabled: bool
    signal_avanza_mode: str
    signal_avanza_contract_confirmed: bool
    signal_avanza_base_url: str
    signal_avanza_api_version: str
    signal_avanza_allowed_hosts: str
    ai_enabled: bool
    ai_mode: str
    ai_default_model: str
    ai_mock_seed: str
    ollama_base_url: str
    ollama_allowed_hosts: str
    ollama_timeout_seconds: float
    signal_ai_base_url: str
    signal_ai_api_key: str
    signal_ai_allowed_hosts: str
    signal_ai_timeout_seconds: float
    signal_connect_timeout_seconds: float
    signal_read_timeout_seconds: float
    signal_webhook_tolerance_seconds: int
    signal_webhook_max_body_bytes: int
    signal_sync_max_pages: int
    integration_encryption_keys: str
    integration_primary_key_version: int
    document_storage_backend: str
    documents_enabled: bool
    document_local_root: str
    document_max_bytes: int
    document_tenant_quota_bytes: int
    document_scanner_mode: str
    document_allow_official_unscanned: bool
    document_clamav_host: str
    document_clamav_port: int
    document_clamav_timeout_seconds: float
    document_s3_endpoint_url: str
    document_s3_region: str
    document_s3_bucket: str
    document_s3_access_key_id: str
    document_s3_secret_access_key: str
    document_s3_allowed_hosts: str
    report_pdf_mode: str
    report_max_artifact_bytes: int
    report_download_ttl_seconds: int
    export_max_rows: int
    export_ttl_hours: int
    backup_storage_path: str
    backup_retention_days: int

    @classmethod
    def load(cls, overrides: Mapping[str, Any] | None = None) -> Settings:
        values: dict[str, Any] = dict(os.environ)
        if overrides:
            values.update(overrides)
        _load_file_backed_settings(values)

        app_env = str(values.get("APP_ENV", "development")).strip().lower()
        if app_env not in {"development", "test", "production"}:
            raise ConfigError("APP_ENV debe ser development, test o production.")

        local_db = "postgresql+psycopg://oracle@127.0.0.1:5432/oracle"
        local_redis = "redis://127.0.0.1:6379/0"
        secret_key = str(values.get("SECRET_KEY", "local-development-only-change-me"))
        database_url = str(values.get("DATABASE_URL", local_db))
        database_migration_url = str(values.get("DATABASE_MIGRATION_URL", database_url))
        redis_url = str(values.get("REDIS_URL", local_redis))

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        if database_migration_url.startswith("postgres://"):
            database_migration_url = database_migration_url.replace(
                "postgres://", "postgresql+psycopg://", 1
            )
        elif database_migration_url.startswith("postgresql://"):
            database_migration_url = database_migration_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            )

        settings = cls(
            app_env=app_env,
            flask_debug=_as_bool(values.get("FLASK_DEBUG", app_env == "development")),
            secret_key=secret_key,
            database_url=database_url,
            database_migration_url=database_migration_url,
            rls_enabled=_as_bool(values.get("RLS_ENABLED", True)),
            redis_url=redis_url,
            session_redis_url=str(values.get("SESSION_REDIS_URL", redis_url)),
            ratelimit_storage_url=str(values.get("RATELIMIT_STORAGE_URL", redis_url)),
            log_level=str(values.get("LOG_LEVEL", "INFO")).upper(),
            log_format=str(
                values.get("LOG_FORMAT", "json" if app_env == "production" else "console")
            ).lower(),
            metrics_enabled=_as_bool(values.get("METRICS_ENABLED", False)),
            metrics_token=str(values.get("METRICS_TOKEN", "")),
            hsts_enabled=_as_bool(values.get("HSTS_ENABLED", False)),
            trusted_proxy_count=_as_int(
                values.get("TRUSTED_PROXY_COUNT", 0), name="TRUSTED_PROXY_COUNT"
            ),
            frontend_origin=str(values.get("FRONTEND_ORIGIN", "http://localhost:3000")),
            openapi_enabled=_as_bool(values.get("OPENAPI_ENABLED", app_env != "production")),
            app_version=str(values.get("APP_VERSION", "0.1.0")),
            release=str(values.get("RELEASE", "development")),
            sqlalchemy_pool_size=_as_int(
                values.get("SQLALCHEMY_POOL_SIZE", 5), name="SQLALCHEMY_POOL_SIZE", minimum=1
            ),
            sqlalchemy_max_overflow=_as_int(
                values.get("SQLALCHEMY_MAX_OVERFLOW", 10),
                name="SQLALCHEMY_MAX_OVERFLOW",
            ),
            sqlalchemy_pool_timeout_seconds=_as_float(
                values.get("SQLALCHEMY_POOL_TIMEOUT_SECONDS", 1.0),
                name="SQLALCHEMY_POOL_TIMEOUT_SECONDS",
            ),
            dependency_timeout_seconds=_as_float(
                values.get("DEPENDENCY_TIMEOUT_SECONDS", 1.0),
                name="DEPENDENCY_TIMEOUT_SECONDS",
            ),
            session_cookie_name=str(values.get("SESSION_COOKIE_NAME", "opn_oracle_session")),
            session_idle_minutes=_as_int(
                values.get("SESSION_IDLE_MINUTES", 30), name="SESSION_IDLE_MINUTES", minimum=5
            ),
            session_absolute_hours=_as_int(
                values.get("SESSION_ABSOLUTE_HOURS", 12), name="SESSION_ABSOLUTE_HOURS", minimum=1
            ),
            password_min_length=_as_int(
                values.get("PASSWORD_MIN_LENGTH", 12), name="PASSWORD_MIN_LENGTH", minimum=10
            ),
            password_max_bytes=_as_int(
                values.get("PASSWORD_MAX_BYTES", 1024), name="PASSWORD_MAX_BYTES", minimum=64
            ),
            auth_max_failures=_as_int(
                values.get("AUTH_MAX_FAILURES", 5), name="AUTH_MAX_FAILURES", minimum=2
            ),
            auth_lock_seconds=_as_int(
                values.get("AUTH_LOCK_SECONDS", 300), name="AUTH_LOCK_SECONDS", minimum=30
            ),
            invitation_ttl_hours=_as_int(
                values.get("INVITATION_TTL_HOURS", 72), name="INVITATION_TTL_HOURS", minimum=1
            ),
            password_reset_ttl_minutes=_as_int(
                values.get("PASSWORD_RESET_TTL_MINUTES", 30),
                name="PASSWORD_RESET_TTL_MINUTES",
                minimum=5,
            ),
            revoke_other_sessions_on_password_change=_as_bool(
                values.get("REVOKE_OTHER_SESSIONS_ON_PASSWORD_CHANGE", True)
            ),
            sensitive_reauth_minutes=_as_int(
                values.get("SENSITIVE_REAUTH_MINUTES", 10),
                name="SENSITIVE_REAUTH_MINUTES",
                minimum=1,
            ),
            mail_backend=str(values.get("MAIL_BACKEND", "capture")).lower(),
            smtp_host=str(values.get("SMTP_HOST", "")),
            smtp_port=_as_int(values.get("SMTP_PORT", 587), name="SMTP_PORT", minimum=1),
            smtp_username=str(values.get("SMTP_USERNAME", "")),
            smtp_password=str(values.get("SMTP_PASSWORD", "")),
            smtp_use_tls=_as_bool(values.get("SMTP_USE_TLS", True)),
            mail_from=str(values.get("MAIL_FROM", "oracle@localhost")),
            graph_tenant_id=str(values.get("GRAPH_TENANT_ID", "")).strip(),
            graph_client_id=str(values.get("GRAPH_CLIENT_ID", "")).strip(),
            graph_client_secret=str(values.get("GRAPH_CLIENT_SECRET", "")),
            graph_sender_mailbox=str(values.get("GRAPH_SENDER_MAILBOX", "")).strip(),
            graph_timeout_seconds=_as_float(
                values.get("GRAPH_TIMEOUT_SECONDS", 10.0),
                name="GRAPH_TIMEOUT_SECONDS",
            ),
            celery_broker_url=str(values.get("CELERY_BROKER_URL", redis_url)),
            celery_result_backend=str(values.get("CELERY_RESULT_BACKEND", redis_url)),
            celery_task_always_eager=_as_bool(
                values.get("CELERY_TASK_ALWAYS_EAGER", app_env == "test")
            ),
            celery_task_eager_propagates=_as_bool(
                values.get("CELERY_TASK_EAGER_PROPAGATES", app_env == "test")
            ),
            celery_acks_late=_as_bool(values.get("CELERY_ACKS_LATE", True)),
            celery_worker_prefetch_multiplier=_as_int(
                values.get("CELERY_WORKER_PREFETCH_MULTIPLIER", 1),
                name="CELERY_WORKER_PREFETCH_MULTIPLIER",
                minimum=1,
            ),
            celery_task_soft_time_limit=_as_int(
                values.get("CELERY_TASK_SOFT_TIME_LIMIT", 690),
                name="CELERY_TASK_SOFT_TIME_LIMIT",
                minimum=1,
            ),
            celery_task_time_limit=_as_int(
                values.get("CELERY_TASK_TIME_LIMIT", 720),
                name="CELERY_TASK_TIME_LIMIT",
                minimum=1,
            ),
            celery_result_expires=_as_int(
                values.get("CELERY_RESULT_EXPIRES", 3600),
                name="CELERY_RESULT_EXPIRES",
                minimum=60,
            ),
            celery_default_queue=str(values.get("CELERY_DEFAULT_QUEUE", "default")),
            celery_timezone=str(
                values.get(
                    "CELERY_TIMEZONE",
                    "Europe/Madrid" if app_env == "production" else "UTC",
                )
            ),
            nightly_summaries_enabled=_as_bool(values.get("NIGHTLY_SUMMARIES_ENABLED", True)),
            nightly_summaries_hour=_as_int(
                values.get("NIGHTLY_SUMMARIES_HOUR", 3),
                name="NIGHTLY_SUMMARIES_HOUR",
            ),
            nightly_summaries_minute=_as_int(
                values.get("NIGHTLY_SUMMARIES_MINUTE", 15),
                name="NIGHTLY_SUMMARIES_MINUTE",
            ),
            signal_avanza_enabled=_as_bool(values.get("SIGNAL_AVANZA_ENABLED", False)),
            signal_avanza_mode=str(values.get("SIGNAL_AVANZA_MODE", "mock")).lower(),
            signal_avanza_contract_confirmed=_as_bool(
                values.get("SIGNAL_AVANZA_CONTRACT_CONFIRMED", False)
            ),
            signal_avanza_base_url=str(values.get("SIGNAL_AVANZA_BASE_URL", "")),
            signal_avanza_api_version=str(values.get("SIGNAL_AVANZA_API_VERSION", "2026-07-01")),
            signal_avanza_allowed_hosts=str(values.get("SIGNAL_AVANZA_ALLOWED_HOSTS", "")),
            ai_enabled=_as_bool(values.get("AI_ENABLED", False)),
            ai_mode=str(values.get("AI_MODE", "disabled")).lower(),
            ai_default_model=str(values.get("AI_DEFAULT_MODEL", "mock-oracle-v1")),
            ai_mock_seed=str(values.get("AI_MOCK_SEED", "opn-oracle-deterministic")),
            ollama_base_url=str(values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")),
            ollama_allowed_hosts=str(
                values.get("OLLAMA_ALLOWED_HOSTS", "127.0.0.1,localhost,ollama")
            ),
            ollama_timeout_seconds=_as_float(
                values.get("OLLAMA_TIMEOUT_SECONDS", 60.0),
                name="OLLAMA_TIMEOUT_SECONDS",
            ),
            signal_ai_base_url=str(values.get("SIGNAL_AI_BASE_URL", "")),
            signal_ai_api_key=str(values.get("SIGNAL_AI_API_KEY", "")),
            signal_ai_allowed_hosts=str(values.get("SIGNAL_AI_ALLOWED_HOSTS", "")),
            signal_ai_timeout_seconds=_as_float(
                values.get("SIGNAL_AI_TIMEOUT_SECONDS", 300.0),
                name="SIGNAL_AI_TIMEOUT_SECONDS",
            ),
            signal_connect_timeout_seconds=_as_float(
                values.get("SIGNAL_CONNECT_TIMEOUT_SECONDS", 2.0),
                name="SIGNAL_CONNECT_TIMEOUT_SECONDS",
            ),
            signal_read_timeout_seconds=_as_float(
                values.get("SIGNAL_READ_TIMEOUT_SECONDS", 10.0),
                name="SIGNAL_READ_TIMEOUT_SECONDS",
            ),
            signal_webhook_tolerance_seconds=_as_int(
                values.get("SIGNAL_WEBHOOK_TOLERANCE_SECONDS", 300),
                name="SIGNAL_WEBHOOK_TOLERANCE_SECONDS",
                minimum=30,
            ),
            signal_webhook_max_body_bytes=_as_int(
                values.get("SIGNAL_WEBHOOK_MAX_BODY_BYTES", 1_048_576),
                name="SIGNAL_WEBHOOK_MAX_BODY_BYTES",
                minimum=1024,
            ),
            signal_sync_max_pages=_as_int(
                values.get("SIGNAL_SYNC_MAX_PAGES", 20),
                name="SIGNAL_SYNC_MAX_PAGES",
                minimum=1,
            ),
            integration_encryption_keys=str(values.get("INTEGRATION_ENCRYPTION_KEYS", "")),
            integration_primary_key_version=_as_int(
                values.get("INTEGRATION_PRIMARY_KEY_VERSION", 1),
                name="INTEGRATION_PRIMARY_KEY_VERSION",
                minimum=1,
            ),
            documents_enabled=_as_bool(values.get("DOCUMENTS_ENABLED", app_env != "production")),
            document_storage_backend=str(values.get("DOCUMENT_STORAGE_BACKEND", "local")).lower(),
            document_local_root=str(values.get("DOCUMENT_LOCAL_ROOT", ".oracle-storage")),
            document_max_bytes=_as_int(
                values.get("DOCUMENT_MAX_BYTES", 25 * 1024 * 1024),
                name="DOCUMENT_MAX_BYTES",
                minimum=1024,
            ),
            document_tenant_quota_bytes=_as_int(
                values.get("DOCUMENT_TENANT_QUOTA_BYTES", 1024 * 1024 * 1024),
                name="DOCUMENT_TENANT_QUOTA_BYTES",
                minimum=1024,
            ),
            document_scanner_mode=str(values.get("DOCUMENT_SCANNER_MODE", "noop")).lower(),
            document_allow_official_unscanned=_as_bool(
                values.get("DOCUMENT_ALLOW_OFFICIAL_UNSCANNED", False)
            ),
            document_clamav_host=str(values.get("DOCUMENT_CLAMAV_HOST", "")),
            document_clamav_port=_as_int(
                values.get("DOCUMENT_CLAMAV_PORT", 3310),
                name="DOCUMENT_CLAMAV_PORT",
                minimum=1,
            ),
            document_clamav_timeout_seconds=_as_float(
                values.get("DOCUMENT_CLAMAV_TIMEOUT_SECONDS", 15.0),
                name="DOCUMENT_CLAMAV_TIMEOUT_SECONDS",
            ),
            document_s3_endpoint_url=str(values.get("DOCUMENT_S3_ENDPOINT_URL", "")),
            document_s3_region=str(values.get("DOCUMENT_S3_REGION", "")),
            document_s3_bucket=str(values.get("DOCUMENT_S3_BUCKET", "")),
            document_s3_access_key_id=str(values.get("DOCUMENT_S3_ACCESS_KEY_ID", "")),
            document_s3_secret_access_key=str(values.get("DOCUMENT_S3_SECRET_ACCESS_KEY", "")),
            document_s3_allowed_hosts=str(values.get("DOCUMENT_S3_ALLOWED_HOSTS", "")),
            report_pdf_mode=str(values.get("REPORT_PDF_MODE", "disabled")).lower(),
            report_max_artifact_bytes=_as_int(
                values.get("REPORT_MAX_ARTIFACT_BYTES", 5 * 1024 * 1024),
                name="REPORT_MAX_ARTIFACT_BYTES",
                minimum=64 * 1024,
            ),
            report_download_ttl_seconds=_as_int(
                values.get("REPORT_DOWNLOAD_TTL_SECONDS", 60),
                name="REPORT_DOWNLOAD_TTL_SECONDS",
                minimum=10,
            ),
            export_max_rows=_as_int(
                values.get("EXPORT_MAX_ROWS", 10_000), name="EXPORT_MAX_ROWS", minimum=1
            ),
            export_ttl_hours=_as_int(
                values.get("EXPORT_TTL_HOURS", 24), name="EXPORT_TTL_HOURS", minimum=1
            ),
            backup_storage_path=str(values.get("BACKUP_STORAGE_PATH", "/var/backups/opn-oracle")),
            backup_retention_days=_as_int(
                values.get("BACKUP_RETENTION_DAYS", 30),
                name="BACKUP_RETENTION_DAYS",
                minimum=1,
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        try:
            ZoneInfo(self.celery_timezone)
        except ZoneInfoNotFoundError:
            raise ConfigError("CELERY_TIMEZONE no es una zona horaria válida.") from None
        if not 0 <= self.nightly_summaries_hour <= 23:
            raise ConfigError("NIGHTLY_SUMMARIES_HOUR debe estar entre 0 y 23.")
        if not 0 <= self.nightly_summaries_minute <= 59:
            raise ConfigError("NIGHTLY_SUMMARIES_MINUTE debe estar entre 0 y 59.")
        if self.log_format not in {"console", "json"}:
            raise ConfigError("LOG_FORMAT debe ser console o json.")
        if self.metrics_enabled and len(self.metrics_token) < 32:
            raise ConfigError("METRICS_ENABLED=true exige METRICS_TOKEN de al menos 32 caracteres.")
        if self.mail_backend not in {"capture", "smtp", "graph"}:
            raise ConfigError("MAIL_BACKEND debe ser capture, smtp o graph.")
        if self.mail_backend == "graph":
            try:
                uuid.UUID(self.graph_tenant_id)
                uuid.UUID(self.graph_client_id)
            except (ValueError, AttributeError):
                raise ConfigError(
                    "MAIL_BACKEND=graph exige GRAPH_TENANT_ID y GRAPH_CLIENT_ID UUID validos."
                ) from None
            if not self.graph_client_secret or not self.graph_sender_mailbox:
                raise ConfigError(
                    "MAIL_BACKEND=graph exige GRAPH_CLIENT_SECRET y GRAPH_SENDER_MAILBOX."
                )
        if self.signal_avanza_mode not in {"mock", "http"}:
            raise ConfigError("SIGNAL_AVANZA_MODE debe ser mock o http.")
        if self.ai_mode not in {"disabled", "mock", "ollama", "signal"}:
            raise ConfigError("AI_MODE solo admite disabled, mock, ollama o signal.")
        if self.ai_mode == "ollama":
            parsed = urlparse(self.ollama_base_url)
            allowed_hosts = {
                item.strip().lower()
                for item in self.ollama_allowed_hosts.split(",")
                if item.strip()
            }
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.hostname.lower() not in allowed_hosts
            ):
                raise ConfigError(
                    "OLLAMA_BASE_URL debe ser HTTP(S), sin credenciales, y usar un host permitido."
                )
            if not self.ai_enabled:
                raise ConfigError("AI_MODE=ollama exige AI_ENABLED=true.")
        if self.ai_mode == "signal":
            parsed = urlparse(self.signal_ai_base_url)
            allowed_hosts = {
                item.strip().lower()
                for item in self.signal_ai_allowed_hosts.split(",")
                if item.strip()
            }
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.hostname.lower() not in allowed_hosts
            ):
                raise ConfigError(
                    "SIGNAL_AI_BASE_URL debe usar HTTPS, sin credenciales, y host permitido."
                )
            if not self.ai_enabled or not self.signal_ai_api_key:
                raise ConfigError("AI_MODE=signal exige AI_ENABLED=true y SIGNAL_AI_API_KEY.")
        if self.document_storage_backend not in {"local", "s3"}:
            raise ConfigError("DOCUMENT_STORAGE_BACKEND debe ser local o s3.")
        if self.document_scanner_mode not in {"noop", "clamav"}:
            raise ConfigError("DOCUMENT_SCANNER_MODE debe ser noop o clamav.")
        if self.report_pdf_mode != "disabled":
            raise ConfigError(
                "REPORT_PDF_MODE solo admite disabled hasta aprobar un renderer aislado."
            )
        if not Path(self.backup_storage_path).is_absolute():
            raise ConfigError("BACKUP_STORAGE_PATH debe ser una ruta absoluta.")
        if self.document_scanner_mode == "clamav" and not self.document_clamav_host:
            raise ConfigError("DOCUMENT_SCANNER_MODE=clamav exige DOCUMENT_CLAMAV_HOST.")
        if self.document_storage_backend == "s3" and not all(
            (
                self.document_s3_endpoint_url.startswith("https://"),
                self.document_s3_region,
                self.document_s3_bucket,
                self.document_s3_access_key_id,
                self.document_s3_secret_access_key,
                self.document_s3_allowed_hosts,
            )
        ):
            raise ConfigError("Storage S3 exige endpoint HTTPS, región, bucket y credenciales.")
        if self.app_env == "production" and self.ai_mode == "mock":
            raise ConfigError("AI_MODE=mock no está permitido en producción.")
        if self.signal_avanza_mode == "http" and (
            not self.signal_avanza_enabled or not self.signal_avanza_contract_confirmed
        ):
            raise ConfigError("Signal HTTP exige SIGNAL_AVANZA_ENABLED=true y contrato confirmado.")
        if self.signal_avanza_mode == "http" and not self.signal_avanza_base_url.startswith(
            "https://"
        ):
            raise ConfigError("SIGNAL_AVANZA_BASE_URL debe usar HTTPS en modo http.")
        if self.signal_avanza_mode == "http" and not self.integration_encryption_keys:
            raise ConfigError("Signal HTTP exige INTEGRATION_ENCRYPTION_KEYS.")
        if self.app_env != "production":
            return

        missing: list[str] = []
        if len(self.secret_key) < 32 or self.secret_key == "local-development-only-change-me":
            missing.append("SECRET_KEY (mínimo 32 caracteres)")
        if not self.database_url.startswith("postgresql+psycopg://"):
            missing.append("DATABASE_URL PostgreSQL")
        if not self.database_migration_url.startswith("postgresql+psycopg://"):
            missing.append("DATABASE_MIGRATION_URL PostgreSQL")
        if not self.rls_enabled:
            missing.append("RLS_ENABLED=true")
        if not self.redis_url.startswith("redis://") and not self.redis_url.startswith("rediss://"):
            missing.append("REDIS_URL")
        if not self.frontend_origin.startswith("https://"):
            missing.append("FRONTEND_ORIGIN HTTPS")
        if self.flask_debug:
            missing.append("FLASK_DEBUG=false")
        smtp_ready = self.mail_backend == "smtp" and bool(self.smtp_host and self.mail_from)
        graph_ready = self.mail_backend == "graph" and bool(
            self.graph_tenant_id
            and self.graph_client_id
            and self.graph_client_secret
            and self.graph_sender_mailbox
        )
        if not smtp_ready and not graph_ready:
            missing.append("backend de correo smtp o graph completamente configurado")
        if self.celery_task_always_eager:
            missing.append("CELERY_TASK_ALWAYS_EAGER=false")
        if self.documents_enabled and self.document_storage_backend != "s3":
            missing.append("DOCUMENT_STORAGE_BACKEND=s3")
        if (
            self.documents_enabled
            and self.document_scanner_mode == "noop"
            and not self.document_allow_official_unscanned
        ):
            missing.append("DOCUMENT_SCANNER_MODE=clamav")
        if missing:
            raise ConfigError("Configuración de producción incompleta: " + ", ".join(missing))

    def as_flask_config(self) -> dict[str, Any]:
        raw = asdict(self)
        config = {key.upper(): value for key, value in raw.items()}
        engine_options: dict[str, Any] = {"pool_pre_ping": True}
        if not self.database_url.startswith("sqlite"):
            engine_options.update(
                {
                    "pool_size": self.sqlalchemy_pool_size,
                    "max_overflow": self.sqlalchemy_max_overflow,
                    "pool_timeout": self.sqlalchemy_pool_timeout_seconds,
                    "connect_args": {
                        "connect_timeout": max(1, ceil(self.dependency_timeout_seconds)),
                        "options": (
                            "-c statement_timeout="
                            f"{max(1, ceil(self.dependency_timeout_seconds * 1000))}"
                        ),
                    },
                }
            )
        config.update(
            {
                "DEBUG": self.flask_debug,
                "SECRET_KEY": self.secret_key,
                "SQLALCHEMY_DATABASE_URI": self.database_url,
                "SQLALCHEMY_TRACK_MODIFICATIONS": False,
                "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
                "API_TITLE": "OPN Oracle API",
                "API_VERSION": "v1",
                "OPENAPI_VERSION": "3.0.3",
                "OPENAPI_URL_PREFIX": "/api/v1" if self.openapi_enabled else None,
                "OPENAPI_JSON_PATH": "openapi.json",
                "SWAGGER_UI_PATH": "/docs" if self.openapi_enabled else None,
                "TESTING": self.app_env == "test",
                "SESSION_TYPE": "redis",
                "SESSION_KEY_PREFIX": "opn-oracle:session:",
                "SESSION_COOKIE_NAME": self.session_cookie_name,
                "SESSION_COOKIE_HTTPONLY": True,
                "SESSION_COOKIE_SECURE": self.app_env == "production",
                "SESSION_COOKIE_SAMESITE": "Lax",
                "SESSION_COOKIE_PATH": "/",
                "SESSION_PERMANENT": True,
                "SESSION_SERIALIZATION_FORMAT": "msgpack",
                "PERMANENT_SESSION_LIFETIME": timedelta(hours=self.session_absolute_hours),
                "RATELIMIT_STORAGE_URI": self.ratelimit_storage_url,
                "RATELIMIT_HEADERS_ENABLED": True,
                "MAX_CONTENT_LENGTH": self.document_max_bytes + 1024 * 1024,
            }
        )
        return config
