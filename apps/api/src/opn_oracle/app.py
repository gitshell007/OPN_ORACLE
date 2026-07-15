"""Flask application factory."""

from __future__ import annotations

import json
import weakref
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import click
from apiflask import APIFlask
from dotenv import load_dotenv
from flask import Response
from werkzeug.middleware.proxy_fix import ProxyFix

from opn_oracle.ai.routes import bp as ai_bp
from opn_oracle.ai.routes import public_bp as ai_contract_bp
from opn_oracle.api.health import bp as health_bp
from opn_oracle.api.meta import bp as meta_bp
from opn_oracle.auth.routes import bp as auth_bp
from opn_oracle.auth.runtime import init_auth_runtime
from opn_oracle.auth.validation import init_json_validation
from opn_oracle.celery_app import celery_init_app
from opn_oracle.cli.backup_agent import register_backup_agent_cli
from opn_oracle.cli.oracle import register_oracle_cli
from opn_oracle.cli.platform import register_platform_cli
from opn_oracle.common.errors import register_error_handlers
from opn_oracle.common.logging import configure_logging
from opn_oracle.common.metrics import bp as metrics_bp
from opn_oracle.common.metrics import init_metrics
from opn_oracle.common.openapi import declare_problem_responses
from opn_oracle.common.request_context import init_request_context
from opn_oracle.common.responses import ProblemSchema
from opn_oracle.common.security_headers import init_security_headers
from opn_oracle.config import Settings
from opn_oracle.documents.routes import bp as documents_bp
from opn_oracle.documents.scanner import ClamAVScanner, NoopScanner
from opn_oracle.documents.storage import LocalObjectStorage, S3ObjectStorage
from opn_oracle.extensions import db, init_extensions
from opn_oracle.integrations.crypto import IntegrationKeyring
from opn_oracle.integrations.entity_intel_routes import bp as entity_intel_bp
from opn_oracle.integrations.procurement_routes import bp as procurement_bp
from opn_oracle.integrations.routes import bp as signal_integrations_bp
from opn_oracle.integrations.signal_avanza import MockSignalAvanzaAdapter
from opn_oracle.integrations.webhooks import bp as signal_webhooks_bp
from opn_oracle.jobs.routes import bp as jobs_bp
from opn_oracle.notifications.email import CaptureEmailSender, GraphEmailSender, SMTPEmailSender
from opn_oracle.oracle.routes import bp as oracle_bp
from opn_oracle.platform.backup_routes import bp as platform_backups_bp
from opn_oracle.platform.routes import bp as platform_bp
from opn_oracle.reporting.rendering import DisabledPDFRenderer
from opn_oracle.reporting.routes import bp as reporting_bp
from opn_oracle.tenants.admin_routes import bp as tenant_admin_bp


def _load_local_dotenv() -> None:
    if __import__("os").environ.get("APP_ENV", "development") != "production":
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _configure_proxy(app: APIFlask) -> None:
    count = app.config["TRUSTED_PROXY_COUNT"]
    if count:
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app,
            x_for=count,
            x_proto=count,
            x_host=count,
            x_port=count,
            x_prefix=count,
        )


def _register_cli(app: APIFlask) -> None:
    @app.cli.command("export-openapi")
    @click.argument("output", type=click.Path(dir_okay=False, path_type=Path))
    def export_openapi(output: Path) -> None:
        """Export the deterministic OpenAPI document to OUTPUT."""

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(app.spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        click.echo(f"OpenAPI exported to {output}")


def create_app(config_override: Mapping[str, Any] | None = None) -> APIFlask:
    """Create and configure an API instance without import-time side effects."""

    _load_local_dotenv()
    settings = Settings.load(config_override)
    app = APIFlask(
        __name__,
        title="OPN Oracle API",
        version=settings.app_version,
        enable_openapi=settings.openapi_enabled,
        openapi_blueprint_url_prefix="/api/v1",
        spec_path="/openapi.json" if settings.openapi_enabled else None,
        docs_path="/docs" if settings.openapi_enabled else None,
    )
    app.config.from_mapping(settings.as_flask_config())
    app.config["VALIDATION_ERROR_SCHEMA"] = ProblemSchema

    _configure_proxy(app)
    configure_logging(app)
    init_request_context(app)
    init_metrics(app)
    init_security_headers(app)
    init_extensions(app)
    celery_init_app(app)
    if app.config["DOCUMENT_STORAGE_BACKEND"] == "s3":
        app.extensions["object_storage"] = S3ObjectStorage(
            endpoint_url=app.config["DOCUMENT_S3_ENDPOINT_URL"],
            region=app.config["DOCUMENT_S3_REGION"],
            bucket=app.config["DOCUMENT_S3_BUCKET"],
            access_key=app.config["DOCUMENT_S3_ACCESS_KEY_ID"],
            secret_key=app.config["DOCUMENT_S3_SECRET_ACCESS_KEY"],
            allowed_hosts=frozenset(
                host.strip().lower()
                for host in app.config["DOCUMENT_S3_ALLOWED_HOSTS"].split(",")
                if host.strip()
            ),
        )
    else:
        app.extensions["object_storage"] = LocalObjectStorage(app.config["DOCUMENT_LOCAL_ROOT"])
    app.extensions["malware_scanner"] = (
        ClamAVScanner(
            host=app.config["DOCUMENT_CLAMAV_HOST"],
            port=app.config["DOCUMENT_CLAMAV_PORT"],
            timeout_seconds=app.config["DOCUMENT_CLAMAV_TIMEOUT_SECONDS"],
            max_bytes=app.config["DOCUMENT_MAX_BYTES"],
        )
        if app.config["DOCUMENT_SCANNER_MODE"] == "clamav"
        else NoopScanner()
    )
    app.extensions["signal_avanza_adapter"] = MockSignalAvanzaAdapter()
    if app.config["INTEGRATION_ENCRYPTION_KEYS"]:
        app.extensions["integration_keyring"] = IntegrationKeyring(
            app.config["INTEGRATION_ENCRYPTION_KEYS"],
            app.config["INTEGRATION_PRIMARY_KEY_VERSION"],
        )
    init_auth_runtime(app)
    init_json_validation(app)
    if app.config["MAIL_BACKEND"] == "smtp":
        app.extensions["email_sender"] = SMTPEmailSender(
            host=app.config["SMTP_HOST"],
            port=app.config["SMTP_PORT"],
            username=app.config["SMTP_USERNAME"],
            password=app.config["SMTP_PASSWORD"],
            use_tls=app.config["SMTP_USE_TLS"],
            sender=app.config["MAIL_FROM"],
        )
    elif app.config["MAIL_BACKEND"] == "graph":
        graph_sender = GraphEmailSender(
            tenant_id=app.config["GRAPH_TENANT_ID"],
            client_id=app.config["GRAPH_CLIENT_ID"],
            client_secret=app.config["GRAPH_CLIENT_SECRET"],
            sender_mailbox=app.config["GRAPH_SENDER_MAILBOX"],
            timeout_seconds=app.config["GRAPH_TIMEOUT_SECONDS"],
        )
        app.extensions["email_sender"] = graph_sender
        app.extensions["email_sender_finalizer"] = weakref.finalize(app, graph_sender.close)
    else:
        app.extensions["email_sender"] = CaptureEmailSender()
    app.extensions["pdf_renderer"] = DisabledPDFRenderer()
    register_error_handlers(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(meta_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(platform_bp)
    app.register_blueprint(platform_backups_bp)
    app.register_blueprint(tenant_admin_bp)
    app.register_blueprint(oracle_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(ai_contract_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(reporting_bp)
    app.register_blueprint(signal_integrations_bp)
    app.register_blueprint(entity_intel_bp)
    app.register_blueprint(procurement_bp)
    app.register_blueprint(signal_webhooks_bp)
    app.register_blueprint(metrics_bp)
    app.spec_processor(declare_problem_responses)
    _register_cli(app)
    register_platform_cli(app)
    register_backup_agent_cli(app)
    register_oracle_cli(app)

    @app.teardown_request
    def rollback_failed_transaction(error: BaseException | None) -> None:
        if error is not None:
            db.session.rollback()

    @app.get("/")
    def api_root() -> Response:
        return Response(status=204)

    return app
