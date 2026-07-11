from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import inspect

from opn_oracle import create_app
from opn_oracle.config import ConfigError, Settings
from opn_oracle.reporting.artifacts import (
    ArtifactAccessError,
    DownloadArtifact,
    artifact_fingerprint,
    create_download_signature,
    verify_download_signature,
)
from opn_oracle.reporting.exports import DATASETS, csv_safe
from opn_oracle.reporting.models import NotificationPreference
from opn_oracle.reporting.notifications import (
    NotificationError,
    next_digest_run,
    safe_internal_link,
)
from opn_oracle.reporting.registry import EXPECTED_TEMPLATES, ReportTemplateRegistry
from opn_oracle.reporting.rendering import (
    DisabledPDFRenderer,
    RenderContext,
    ReportRenderError,
    render_report_html,
)

pytestmark = pytest.mark.unit


def _output(text: str = "Hecho verificable") -> dict[str, object]:
    return {
        "facts": [],
        "inferences": [],
        "recommendations": [
            {
                "action": "Revisar con la persona responsable.",
                "rationale": "La decisión final es humana.",
                "priority": "medium",
            }
        ],
        "confidence": 50,
        "open_questions": [],
        "warnings": [],
        "title": "Informe de prueba",
        "executive_summary": "Resumen trazable.",
        "sections": [
            {
                "heading": "Situación",
                "paragraphs": [
                    {"text": text, "kind": "inference", "confidence": 50, "evidence_ids": []}
                ],
            }
        ],
        "top_opportunities": [],
        "top_risks": [],
        "recommended_actions": [],
        "decisions_required": [],
        "source_index": [],
    }


def test_report_registry_contains_exactly_eight_immutable_templates() -> None:
    registry = ReportTemplateRegistry()
    assert {item.key for item in registry.list()} == EXPECTED_TEMPLATES
    assert all(item.version == "v1" and len(item.sha256) == 32 for item in registry.list())
    assert registry.get("executive_dossier").permissions["publish"] == "report.publish"
    with pytest.raises(KeyError):
        registry.get("executive_dossier", "v2")


def test_safe_html_escapes_content_and_rejects_resource_markup() -> None:
    context = RenderContext(
        "report-1",
        1,
        datetime(2026, 7, 11, tzinfo=UTC).date(),
        "Interno",
        "Ejecutivo",
    )
    rendered = render_report_html(
        _output("Texto con https://example.test como referencia"),
        context,
        max_bytes=100_000,
    )
    assert b"https://example.test" in rendered
    assert (
        b"<script"
        not in render_report_html(
            _output("<script>alert(1)</script>"), context, max_bytes=100_000
        ).lower()
    )
    with pytest.raises(ReportRenderError):
        render_report_html(
            _output('<img src="http://169.254.169.254/">'), context, max_bytes=100_000
        )
    with pytest.raises(ReportRenderError):
        render_report_html(_output("x" * 8000), context, max_bytes=200)
    with pytest.raises(ReportRenderError):
        DisabledPDFRenderer().render(rendered, max_bytes=100_000)


def test_safe_html_accepts_uuid_strings_from_json_artifacts() -> None:
    evidence_id = str(uuid.uuid4())
    payload = _output()
    payload["facts"] = [{"statement": "Hecho persistido como JSON.", "evidence_ids": [evidence_id]}]
    payload["sections"] = [
        {
            "heading": "Hechos",
            "paragraphs": [
                {
                    "text": "Hecho persistido como JSON.",
                    "kind": "fact",
                    "confidence": 80,
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    ]
    payload["source_index"] = [
        {"evidence_id": evidence_id, "label": "Fuente", "locator": "Página 1"}
    ]
    context = RenderContext(
        "report-json",
        1,
        datetime(2026, 7, 11, tzinfo=UTC).date(),
        "Interno",
        "Ejecutivo",
    )
    rendered = render_report_html(payload, context, max_bytes=100_000)
    assert evidence_id.encode() in rendered


def test_csv_formula_injection_is_neutralized() -> None:
    for value in ("=1+1", "+SUM(A1:A2)", "-2+3", "@cmd", "\t=cmd", "  =cmd"):
        assert csv_safe(value).startswith("'")
    assert csv_safe("valor seguro") == "valor seguro"
    assert csv_safe(42) == "42"


def test_export_dataset_columns_are_real_mapped_attributes() -> None:
    for spec in DATASETS.values():
        mapped = set(inspect(spec.model).attrs.keys())
        assert set(spec.default_columns) - {"_watermark"} <= mapped
        assert set(spec.allowed_columns) - {"_watermark"} <= mapped
        assert set(spec.search_columns) <= mapped


def test_internal_links_reject_open_redirects_and_control_characters() -> None:
    assert safe_internal_link("/app/reports?status=ready") == "/app/reports?status=ready"
    for value in (
        "https://evil.test/app/reports",
        "//evil.test/app/reports",
        "/app/../../evil",
        "/app/%2e%2e/evil",
        "/concept-a/ok\\evil",
        "/app/ok\nheader:x",
    ):
        with pytest.raises(NotificationError):
            safe_internal_link(value)


def test_download_signature_is_user_tenant_and_expiry_bound() -> None:
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "report-signature-test-secret-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "REPORT_DOWNLOAD_TTL_SECONDS": 60,
        }
    )
    artifact_id, tenant_id, user_id, session_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    with app.app_context():
        fingerprint = artifact_fingerprint(
            DownloadArtifact(
                kind="report",
                id=artifact_id,
                storage_key="tenant/report/v1.json",
                checksum=b"a" * 32,
                byte_size=123,
                media_type="application/json",
                filename="report.json",
            )
        )
        expires, signature = create_download_signature(
            kind="report",
            artifact_id=artifact_id,
            artifact_fingerprint=fingerprint,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            now=1_000,
        )
        verify_download_signature(
            kind="report",
            artifact_id=artifact_id,
            artifact_fingerprint=fingerprint,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            expires=expires,
            signature=signature,
            now=1_001,
        )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=tenant_id,
                user_id=uuid.uuid4(),
                session_id=session_id,
                expires=expires,
                signature=signature,
                now=1_001,
            )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                expires=expires,
                signature=signature,
                now=1_061,
            )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=uuid.uuid4(),
                user_id=user_id,
                session_id=session_id,
                expires=expires,
                signature=signature,
                now=1_001,
            )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                expires=expires,
                signature=f"{signature[:-1]}{'0' if signature[-1] != '0' else '1'}",
                now=1_001,
            )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint="b" * 64,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
                expires=expires,
                signature=signature,
                now=1_001,
            )
        with pytest.raises(ArtifactAccessError):
            verify_download_signature(
                kind="report",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=uuid.uuid4(),
                expires=expires,
                signature=signature,
                now=1_001,
            )


def test_digest_next_run_is_timezone_and_dst_aware() -> None:
    preference = NotificationPreference(
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        notification_type="*",
        channels={"in_app": True, "email": True},
        digest_cadence="daily",
        timezone="Europe/Madrid",
        local_time=time(8, 0),
        weekday=None,
        minimum_severity="info",
        version=1,
    )
    before_dst = next_digest_run(preference, datetime(2026, 3, 28, 9, tzinfo=UTC))
    after_dst = next_digest_run(preference, datetime(2026, 3, 29, 9, tzinfo=UTC))
    assert before_dst.hour == 6
    assert after_dst.hour == 6


def test_pdf_mode_fails_closed_in_configuration() -> None:
    with pytest.raises(ConfigError):
        Settings.load({"APP_ENV": "test", "REPORT_PDF_MODE": "weasyprint"})
