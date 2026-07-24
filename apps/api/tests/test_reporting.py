from __future__ import annotations

import uuid
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import inspect

from opn_oracle import create_app
from opn_oracle.ai.context import build_frozen_context
from opn_oracle.ai.schemas import ReportOutput
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
    WeasyPrintPDFRenderer,
    render_report_html,
)
from opn_oracle.reporting.service import (
    ReportOutputContractError,
    ReportWorkflowError,
    _report_failure_message,
    _validate_report_output,
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


def test_report_registry_contains_exact_supported_templates() -> None:
    registry = ReportTemplateRegistry()
    assert {item.key for item in registry.list()} == EXPECTED_TEMPLATES
    assert all(len(item.sha256) == 32 for item in registry.list())
    assert registry.get("entity_intelligence").version == "v2"
    assert registry.get("competitive_procurement").version == "v2"
    assert registry.get("entity_intelligence", "v1").sections[0] == "Cobertura y límites"
    assert registry.get("entity_intelligence", "v2").sections[0] == "Resumen ejecutivo"
    assert registry.get("executive_dossier").permissions["publish"] == "report.publish"
    with pytest.raises(KeyError):
        registry.get("executive_dossier", "v2")


def test_report_registry_resolves_template_versions_without_freezing_legacy_outputs() -> None:
    registry = ReportTemplateRegistry()
    v1 = registry.get("entity_intelligence", "v1")
    v2 = registry.get("entity_intelligence", "v2")
    output = ReportOutput.model_validate(
        {
            **_output(),
            "sections": [
                {
                    "heading": heading,
                    "paragraphs": [
                        {
                            "text": f"Contenido heredado de {heading}.",
                            "kind": "inference",
                            "confidence": 50,
                            "evidence_ids": [],
                        }
                    ],
                }
                for heading in v1.sections
            ],
        }
    )

    _validate_report_output(output, template=v1, snapshot_ids=set())
    with pytest.raises(ReportWorkflowError, match="secciones requeridas"):
        _validate_report_output(output, template=v2, snapshot_ids=set())


def test_paraphrased_headings_are_accepted_and_rewritten_to_the_template_canon() -> None:
    """Regresión g1-r3 (Informe de actores · Coches de Bomberos, 2026-07-24).

    El modelo devolvió los headings con mayúsculas/acentos distintos y la
    igualdad exacta tiró el informe entero. La equivalencia normalizada debe
    aceptarlos y reescribirlos al literal de la plantilla; una sección ausente
    de verdad debe seguir fallando.
    """

    template = ReportTemplateRegistry().get("actors")
    paraphrased = [
        heading.upper().replace("INFERIDAS", "INFERÍDAS") for heading in template.sections
    ]
    output = ReportOutput.model_validate(
        {
            **_output(),
            "sections": [
                {
                    "heading": heading,
                    "paragraphs": [
                        {
                            "text": f"Lectura de {heading}.",
                            "kind": "inference",
                            "confidence": 50,
                            "evidence_ids": [],
                        }
                    ],
                }
                for heading in paraphrased
            ],
        }
    )

    _validate_report_output(output, template=template, snapshot_ids=set())
    assert [section.heading for section in output.sections] == list(template.sections)

    truncated = ReportOutput.model_validate(
        {
            **_output(),
            "sections": [
                {
                    "heading": template.sections[0],
                    "paragraphs": [
                        {
                            "text": "Solo la primera sección.",
                            "kind": "inference",
                            "confidence": 50,
                            "evidence_ids": [],
                        }
                    ],
                }
            ],
        }
    )
    with pytest.raises(ReportWorkflowError, match="secciones requeridas"):
        _validate_report_output(truncated, template=template, snapshot_ids=set())


def test_frozen_context_carries_the_dossier_portfolio_and_declares_its_trim() -> None:
    """La cartera congelada tiene que llegar al modelo, no solo al snapshot.

    `executive_dossier` pide «Oportunidades principales» y «Riesgos principales» y
    `action_plan` pide acciones y decisiones: si el contexto no las transporta, esas
    secciones se redactan sobre el vacío.
    """

    built = build_frozen_context(
        dossier_id=uuid.uuid4(),
        dossier={"id": "d", "title": "Expediente"},
        objectives=[],
        hypotheses=[],
        living_summary={},
        evidence=(),
        max_tokens=4000,
        opportunities=[{"id": "o1", "title": "Oportunidad congelada", "overall_score": 80}],
        risks=[{"id": "r1", "title": "Riesgo congelado", "overall_score": 70}],
        tasks=[{"id": "t1", "title": "Acción pendiente", "status": "open"}],
        decisions=[{"id": "dec1", "title": "Decisión propuesta", "status": "proposed"}],
        portfolio_context_meta={"portfolio_limit": 25, "opportunities_truncated": False},
    )

    assert [item["title"] for item in built.payload["opportunities"]] == ["Oportunidad congelada"]
    assert [item["title"] for item in built.payload["risks"]] == ["Riesgo congelado"]
    assert [item["title"] for item in built.payload["tasks"]] == ["Acción pendiente"]
    assert [item["title"] for item in built.payload["decisions"]] == ["Decisión propuesta"]
    assert built.payload["portfolio_context_meta"]["portfolio_limit"] == 25

    # Sin cartera, las claves existen vacías: el modelo distingue «no hay» de «no se envió».
    empty = build_frozen_context(
        dossier_id=uuid.uuid4(),
        dossier={"id": "d", "title": "Expediente"},
        objectives=[],
        hypotheses=[],
        living_summary={},
        evidence=(),
        max_tokens=4000,
    )
    assert empty.payload["opportunities"] == []
    assert empty.payload["decisions"] == []


def test_empty_sections_name_the_template_and_reach_the_user_as_a_contract_failure() -> None:
    """Auditoría de producción 2026-07-24 (`executive_dossier` y `action_plan`).

    El modelo devolvió `sections: []` y el usuario solo vio «Código seguro:
    ReportWorkflowError». El fallo debe declararse como incumplimiento de contrato
    —recuperable reintentando— y decir qué secciones faltaban.
    """

    template = ReportTemplateRegistry().get("executive_dossier")
    empty = ReportOutput.model_validate({**_output(), "sections": []})

    with pytest.raises(ReportOutputContractError) as failure:
        _validate_report_output(empty, template=template, snapshot_ids=set())

    message = str(failure.value)
    assert "sin ninguna sección" in message
    assert str(len(template.sections)) in message
    for heading in template.sections:
        assert heading in message
    # El contrato sigue siendo un ReportWorkflowError para las rutas que ya lo capturan.
    assert isinstance(failure.value, ReportWorkflowError)
    # Y llega al informe en vez del mensaje genérico.
    assert _report_failure_message(failure.value) == message


def test_report_output_closure_fields_are_required_only_when_enabled() -> None:
    template = ReportTemplateRegistry().get("executive_dossier")
    output = ReportOutput.model_validate(
        {
            **_output(),
            "sections": [
                {
                    "heading": heading,
                    "paragraphs": [
                        {
                            "text": f"Lectura ejecutiva de {heading}.",
                            "kind": "inference",
                            "confidence": 60,
                            "evidence_ids": [],
                        }
                    ],
                }
                for heading in template.sections
            ],
        }
    )

    _validate_report_output(output, template=template, snapshot_ids=set())
    with pytest.raises(ReportWorkflowError, match="campos ejecutivos de cierre"):
        _validate_report_output(
            output,
            template=template,
            snapshot_ids=set(),
            require_closure_fields=True,
        )

    completed = output.model_copy(
        update={
            "top_opportunities": ["Oportunidad verificable"],
            "top_risks": ["Riesgo verificable"],
            "recommended_actions": ["Acción recomendada"],
        }
    )
    _validate_report_output(
        completed,
        template=template,
        snapshot_ids=set(),
        require_closure_fields=True,
    )


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


def test_pdf_mode_accepts_weasyprint_and_fails_closed_for_unknown_renderers() -> None:
    settings = Settings.load({"APP_ENV": "test", "REPORT_PDF_MODE": "weasyprint"})
    assert settings.report_pdf_mode == "weasyprint"
    with pytest.raises(ConfigError):
        Settings.load({"APP_ENV": "test", "REPORT_PDF_MODE": "chromium"})


def test_weasyprint_renderer_emits_real_pdf_and_respects_size_limit() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:  # librerías nativas ausentes
        pytest.skip(f"weasyprint no disponible en este entorno: {exc}")

    context = RenderContext(
        report_id=str(uuid.uuid4()),
        version=1,
        generated_on=datetime.now(UTC).date(),
        confidentiality_label="Uso interno",
        template_label="Informe de prueba",
    )
    rendered = render_report_html(_output(), context, max_bytes=500_000)
    renderer = WeasyPrintPDFRenderer()
    pdf = renderer.render(rendered, max_bytes=5_000_000)
    assert pdf.startswith(b"%PDF-")
    with pytest.raises(ReportRenderError, match="supera el límite"):
        renderer.render(rendered, max_bytes=1_000)
