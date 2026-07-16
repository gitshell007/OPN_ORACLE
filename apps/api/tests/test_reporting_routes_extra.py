from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from opn_oracle.ai.schemas import ReportOutput
from opn_oracle.notifications.email import CaptureEmailSender, SMTPEmailSender
from opn_oracle.reporting.artifacts import (
    ArtifactAccessError,
    DownloadArtifact,
    artifact_fingerprint,
    create_download_signature,
    export_artifact,
    read_artifact,
    report_artifact,
    verify_download_signature,
)
from opn_oracle.reporting.exports import (
    DATASETS,
    ExportError,
    _normalize_request,
    _query,
    csv_safe,
    serialize_export,
)
from opn_oracle.reporting.models import Notification, NotificationPreference
from opn_oracle.reporting.notifications import (
    NotificationError,
    _default_channels,
    _quiet_end,
    _quiet_now,
    next_digest_run,
    safe_internal_link,
    serialize_notification,
    serialize_preference,
)
from opn_oracle.reporting.registry import ReportTemplateRegistry
from opn_oracle.reporting.service import (
    ReportWorkflowError,
    _all_evidence_ids,
    _authoritative_source_index,
    _validate_options,
    serialize_report,
)

pytestmark = pytest.mark.unit


def test_artifact_helpers_fail_closed_for_kind_state_expiry_and_integrity(app: Any) -> None:
    artifact_id, tenant_id, user_id, session_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    payload = b"contenido trazable"

    class Reader(io.BytesIO):
        closed_by_service = False

        def close(self) -> None:
            self.closed_by_service = True
            super().close()

    class Storage:
        value = payload
        error: Exception | None = None
        last_reader: Reader | None = None

        def get(self, key: str) -> Reader:
            assert key == "tenant/report/artifact"
            if self.error is not None:
                raise self.error
            self.last_reader = Reader(self.value)
            return self.last_reader

    storage = Storage()
    app.extensions["object_storage"] = storage
    row = DownloadArtifact(
        kind="report",
        id=artifact_id,
        storage_key="tenant/report/artifact",
        checksum=hashlib.sha256(payload).digest(),
        byte_size=len(payload),
        media_type="application/json",
        filename="report.json",
    )
    with app.app_context():
        fingerprint = artifact_fingerprint(row)
        with pytest.raises(ArtifactAccessError, match="Tipo"):
            create_download_signature(
                kind="document",
                artifact_id=artifact_id,
                artifact_fingerprint=fingerprint,
                tenant_id=tenant_id,
                user_id=user_id,
                session_id=session_id,
            )
        expires, signature = create_download_signature(
            kind="report",
            artifact_id=artifact_id,
            artifact_fingerprint=fingerprint,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            now=10_000,
        )
        for invalid_expires, invalid_signature in (
            (9_999, signature),
            (expires + 6, signature),
            (expires, "short"),
        ):
            with pytest.raises(ArtifactAccessError, match="caducado"):
                verify_download_signature(
                    kind="report",
                    artifact_id=artifact_id,
                    artifact_fingerprint=fingerprint,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    session_id=session_id,
                    expires=invalid_expires,
                    signature=invalid_signature,
                    now=10_000,
                )

        assert read_artifact(row) == payload
        assert storage.last_reader is not None and storage.last_reader.closed_by_service
        storage.value = payload + b"alterado"
        with pytest.raises(ArtifactAccessError, match="integridad"):
            read_artifact(row)
        storage.error = OSError("storage unavailable")
        with pytest.raises(ArtifactAccessError, match="no disponible"):
            read_artifact(row)


@pytest.mark.parametrize("format_name", ["html", "json", "pdf"])
def test_report_and_export_artifact_require_available_complete_metadata(
    format_name: str,
) -> None:
    payload = b"x"
    report_id, artifact_id = uuid.uuid4(), uuid.uuid4()
    report_row = SimpleNamespace(
        id=artifact_id,
        report_id=report_id,
        status="available",
        format=format_name,
        storage_key="key",
        checksum=hashlib.sha256(payload).digest(),
        byte_size=1,
        media_type="application/octet-stream",
    )
    item = report_artifact(report_row)
    assert item.filename == f"oracle-report-{report_id}.{format_name}"
    report_row.status = "deleted"
    with pytest.raises(ArtifactAccessError, match="no disponible"):
        report_artifact(report_row)

    export_row = SimpleNamespace(
        id=artifact_id,
        status="ready",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
        storage_key="key",
        checksum=hashlib.sha256(payload).digest(),
        byte_size=1,
        media_type="text/csv",
    )
    assert export_artifact(export_row).filename.endswith(".csv")
    for field, value in (
        ("status", "failed"),
        ("expires_at", None),
        ("storage_key", None),
        ("checksum", None),
        ("byte_size", None),
        ("media_type", None),
    ):
        broken = SimpleNamespace(**vars(export_row))
        setattr(broken, field, value)
        with pytest.raises(ArtifactAccessError, match="no disponible"):
            export_artifact(broken)


def test_export_normalization_rejects_unsafe_shape_and_normalizes_dates_and_ids() -> None:
    selected = uuid.uuid4()
    spec, columns, filters = _normalize_request(
        "audit",
        [],
        {
            "selected_ids": [selected],
            "date_from": "2026-07-01T00:00:00Z",
            "date_to": "2026-07-11T12:30:00+00:00",
        },
    )
    assert spec is DATASETS["audit"]
    assert columns[-1] == "_watermark"
    assert filters["selected_ids"] == [str(selected)]
    assert filters["date_from"].endswith("+00:00")

    invalid_cases = (
        ("unknown", [], {}),
        ("tasks", ["id", "id"], {}),
        ("tasks", ["secret"], {}),
        ("tasks", ["id"], {"tenant_id": str(uuid.uuid4())}),
        ("tasks", ["id"], {"selected_ids": "not-a-list"}),
        ("tasks", ["id"], {"selected_ids": ["not-a-uuid"]}),
        ("tasks", ["id"], {"date_from": "tomorrow"}),
        ("tasks", ["id"], {"date_to": "31/12/2026"}),
    )
    for dataset, raw_columns, raw_filters in invalid_cases:
        with pytest.raises(ExportError):
            _normalize_request(dataset, raw_columns, raw_filters)


def test_export_query_applies_scope_filters_and_rejects_invalid_dataset_filters() -> None:
    dossier_id = uuid.uuid4()
    common = {
        "tenant_id": uuid.uuid4(),
        "requested_by_user_id": uuid.uuid4(),
        "dossier_id": dossier_id,
    }
    for dataset in ("signals", "actors", "opportunities", "audit"):
        row = SimpleNamespace(
            **common,
            filters={
                "search": "trazable",
                "selected_ids": [str(uuid.uuid4())],
                "date_from": "2026-07-01T00:00:00+00:00",
                "date_to": "2026-07-11T23:59:00+00:00",
            },
        )
        statement = _query(row, DATASETS[dataset])
        sql = str(statement)
        assert "ORDER BY" in sql and "DISTINCT" in sql
        assert "created_at" in sql

    audit_with_status = SimpleNamespace(**common, filters={"status": "ready"})
    with pytest.raises(ExportError, match="estado"):
        _query(audit_with_status, DATASETS["audit"])
    long_search = SimpleNamespace(**common, filters={"search": "x" * 201})
    with pytest.raises(ExportError, match="demasiado largo"):
        _query(long_search, DATASETS["tasks"])


def test_csv_and_export_serialization_cover_typed_values_and_hide_non_audit_watermark() -> None:
    identifier = uuid.uuid4()
    assert csv_safe(None) == ""
    assert csv_safe(date(2026, 7, 11)) == "2026-07-11"
    assert csv_safe(identifier) == str(identifier)
    assert csv_safe({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert csv_safe("\n=cmd").startswith("'")

    now = datetime.now(UTC)
    base = dict(
        id=identifier,
        dataset="tasks",
        format="csv",
        status="ready",
        dossier_id=None,
        job_id=None,
        filters={},
        columns=["id"],
        watermark="sensitive tenant watermark",
        byte_size=None,
        checksum=None,
        expires_at=None,
        error_code=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    serialized = serialize_export(SimpleNamespace(**base))
    assert serialized["watermark"] == ""
    assert serialized["checksum"] is None and serialized["expires_at"] is None
    base.update(
        dataset="audit",
        dossier_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        checksum=b"\x01" * 32,
        expires_at=now,
    )
    serialized = serialize_export(SimpleNamespace(**base))
    assert serialized["watermark"] == "sensitive tenant watermark"
    assert serialized["checksum"] == "01" * 32


def test_report_option_validation_fails_before_provider_or_persistence(app: Any) -> None:
    registry = ReportTemplateRegistry()
    dossier_id = uuid.uuid4()
    invalid: tuple[tuple[str, dict[str, Any], str], ...] = (
        ("executive_dossier", {"unexpected": True}, "no admitidas"),
        ("weekly_change", {}, "period_start es obligatorio"),
        ("opportunity", {"opportunity_id": "bad"}, "debe ser UUID"),
        ("actors", {"actor_ids": "bad"}, "lista"),
        ("actors", {"actor_ids": ["bad"]}, "UUID no válido"),
        ("executive_dossier", {"period_start": "not-a-date"}, "fecha ISO"),
        (
            "executive_dossier",
            {"period_start": "2026-07-12", "period_end": "2026-07-11"},
            "posterior",
        ),
        ("executive_dossier", {"formats": []}, "lista no vacía"),
        ("executive_dossier", {"formats": ["docx"]}, "Formato"),
        ("executive_dossier", {"formats": ["pdf"]}, "PDF no está habilitado"),
        ("executive_dossier", {"classification": "secret"}, "public o internal"),
        ("executive_dossier", {"confidentiality_label": ""}, "no es válido"),
    )
    with app.app_context():
        for template_key, options, message in invalid:
            with pytest.raises(ReportWorkflowError, match=message):
                _validate_options(registry.get(template_key), dossier_id, options)
        normalized = _validate_options(
            registry.get("executive_dossier"),
            dossier_id,
            {
                "formats": ["json", "json", "html"],
                "period_start": "2026-07-01",
                "period_end": "2026-07-11",
            },
        )
    assert normalized["formats"] == ["json", "html"]
    assert normalized["classification"] == "internal"
    assert normalized["confidentiality_label"] == "Uso interno"


def test_report_output_collects_citations_from_every_supported_location() -> None:
    evidence_ids = [uuid.uuid4() for _ in range(4)]
    output = ReportOutput.model_validate(
        {
            "facts": [{"statement": "Hecho", "evidence_ids": [evidence_ids[0]]}],
            "inferences": [
                {
                    "statement": "Inferencia",
                    "reasoning_summary": "Razonamiento",
                    "confidence": 70,
                    "evidence_ids": [evidence_ids[1]],
                }
            ],
            "recommendations": [],
            "confidence": 70,
            "open_questions": [],
            "warnings": [],
            "title": "Informe",
            "executive_summary": "Resumen",
            "sections": [
                {
                    "heading": "Sección",
                    "paragraphs": [
                        {
                            "text": "Texto",
                            "kind": "fact",
                            "confidence": 80,
                            "evidence_ids": [evidence_ids[2]],
                        }
                    ],
                }
            ],
            "top_opportunities": [],
            "top_risks": [],
            "recommended_actions": [],
            "decisions_required": [],
            "source_index": [
                {"evidence_id": evidence_ids[3], "label": "Fuente", "locator": "p. 1"}
            ],
        }
    )
    assert _all_evidence_ids(output) == set(evidence_ids)


def test_report_output_downgrades_uncited_factual_paragraphs_before_validation() -> None:
    evidence_id = uuid.uuid4()
    output = ReportOutput.model_validate(
        {
            "facts": [{"statement": "Hecho citado.", "evidence_ids": [evidence_id]}],
            "inferences": [],
            "recommendations": [],
            "confidence": 70,
            "open_questions": [],
            "warnings": [],
            "title": "Informe",
            "executive_summary": "Resumen",
            "sections": [
                {
                    "heading": "Objetivo",
                    "paragraphs": [
                        {
                            "text": "Afirmación sin cita directa.",
                            "kind": "fact",
                            "confidence": 95,
                            "evidence_ids": [],
                        },
                        {
                            "text": "Hecho con cita.",
                            "kind": "fact",
                            "confidence": 90,
                            "evidence_ids": [evidence_id],
                        },
                    ],
                }
            ],
            "top_opportunities": [],
            "top_risks": [],
            "recommended_actions": [],
            "decisions_required": [],
            "source_index": [],
        }
    )
    snapshot = [
        SimpleNamespace(
            evidence_id=evidence_id,
            source_label="Fuente",
            locator={"kind": "test"},
        )
    ]

    normalized = _authoritative_source_index(output, snapshot)

    first, second = normalized.sections[0].paragraphs
    assert first.kind == "inference"
    assert first.confidence == 70
    assert first.evidence_ids == []
    assert second.kind == "fact"
    assert normalized.source_index[0].evidence_id == evidence_id


def test_report_output_replaces_evidence_uuids_in_business_prose_with_citations() -> None:
    evidence_id, unknown_id = uuid.uuid4(), uuid.uuid4()
    output = ReportOutput.model_validate(
        {
            "facts": [{"statement": "Hecho", "evidence_ids": [evidence_id]}],
            "inferences": [],
            "recommendations": [
                {
                    "action": f"Revisar la evidencia {evidence_id}",
                    "rationale": f"La fuente {unknown_id} requiere contraste.",
                    "priority": "medium",
                }
            ],
            "confidence": 70,
            "open_questions": [f"¿Qué confirma {evidence_id}?"],
            "warnings": [f"La evidencia citada ({evidence_id}) no está verificada."],
            "title": "Informe",
            "executive_summary": f"La señal {evidence_id} requiere seguimiento.",
            "sections": [
                {
                    "heading": "Situación",
                    "paragraphs": [
                        {
                            "text": f"La evidencia {evidence_id} está disponible.",
                            "kind": "fact",
                            "confidence": 80,
                            "evidence_ids": [evidence_id],
                        }
                    ],
                }
            ],
            "top_opportunities": [],
            "top_risks": [],
            "recommended_actions": [],
            "decisions_required": [],
            "source_index": [],
        }
    )
    snapshot = [
        SimpleNamespace(
            evidence_id=evidence_id,
            source_label="Fuente de prueba",
            locator={"kind": "test"},
        )
    ]

    normalized = _authoritative_source_index(output, snapshot)

    assert normalized.warnings == ["La evidencia citada ([1]) no está verificada."]
    assert normalized.executive_summary == "La señal [1] requiere seguimiento."
    assert normalized.recommendations[0].action == "Revisar la evidencia [1]"
    assert (
        normalized.recommendations[0].rationale
        == "La fuente [fuente no disponible] requiere contraste."
    )
    prose = " ".join(
        [
            normalized.executive_summary,
            *normalized.warnings,
            normalized.recommendations[0].action,
            normalized.recommendations[0].rationale,
            normalized.sections[0].paragraphs[0].text,
        ]
    )
    assert str(evidence_id) not in prose
    assert str(unknown_id) not in prose


def test_report_api_serialization_sanitizes_legacy_warning_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_id = uuid.uuid4()
    content = {
        "facts": [{"statement": "Hecho", "evidence_ids": [str(evidence_id)]}],
        "inferences": [],
        "recommendations": [],
        "confidence": 70,
        "open_questions": [],
        "warnings": [f"La evidencia citada ({evidence_id}) es una señal no verificada."],
        "title": "Informe histórico",
        "executive_summary": "Resumen",
        "sections": [],
        "top_opportunities": [],
        "top_risks": [],
        "recommended_actions": [],
        "decisions_required": [],
        "source_index": [
            {
                "evidence_id": str(evidence_id),
                "label": "Fuente histórica",
                "locator": "{}",
            }
        ],
    }
    now = datetime.now(UTC)
    report = SimpleNamespace(
        id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        title="Informe histórico",
        status="ready",
        report_type="action_plan",
        template_key="action_plan",
        template_version="v1",
        generation_version=4,
        classification="internal",
        confidentiality_label="Uso interno",
        background_job_id=None,
        parent_report_id=None,
        ready_at=now,
        reviewed_at=None,
        published_at=None,
        error_code=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    revision = SimpleNamespace(
        id=uuid.uuid4(),
        revision_no=1,
        status="ready",
        title="Generación 4",
        content=content,
        change_summary="",
        created_at=now,
    )

    monkeypatch.setattr("opn_oracle.reporting.service.latest_revision", lambda report_id: revision)
    monkeypatch.setattr(
        "opn_oracle.reporting.service.db",
        SimpleNamespace(session=SimpleNamespace(scalars=lambda statement: [])),
    )

    serialized = serialize_report(report, detail=True)

    warning = serialized["revision"]["content"]["warnings"][0]
    assert warning == "La evidencia citada ([1]) es una señal no verificada."
    assert str(evidence_id) not in warning
    assert serialized["revision"]["content"]["facts"][0]["evidence_ids"] == [str(evidence_id)]


def test_notification_serialization_quiet_windows_and_timezone_validation() -> None:
    now = datetime(2026, 7, 11, 23, 30, tzinfo=UTC)
    preference = NotificationPreference(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        notification_type="report.ready",
        channels={"in_app": True, "email": True},
        digest_cadence="weekly",
        timezone="UTC",
        local_time=time(8, 0),
        weekday=0,
        quiet_hours_start=time(22, 0),
        quiet_hours_end=time(7, 0),
        minimum_severity="warning",
        security_locked=False,
        version=3,
    )
    assert _quiet_now(preference, now)
    assert _quiet_end(preference, now) == datetime(2026, 7, 12, 7, 0, tzinfo=UTC)
    preference.quiet_hours_start = preference.quiet_hours_end = time(8, 0)
    assert _quiet_now(preference, now)
    preference.quiet_hours_start = preference.quiet_hours_end = None
    assert not _quiet_now(preference, now)
    assert _quiet_end(preference, now) == now
    serialized = serialize_preference(preference)
    assert serialized["quiet_hours_start"] is None and serialized["version"] == 3
    assert _default_channels("report.ready") == {"in_app": True, "email": False}
    assert _default_channels("security.password_changed") == {
        "in_app": True,
        "email": True,
    }

    preference.timezone = "Invalid/Timezone"
    with pytest.raises(NotificationError, match="Timezone"):
        next_digest_run(preference, now)

    notification = Notification(
        id=uuid.uuid4(),
        tenant_id=preference.tenant_id,
        user_id=preference.user_id,
        notification_type="report.ready",
        severity="success",
        title="Listo",
        body="Disponible",
        link=None,
        dedupe_key="notification-serialization",
        request_hash=b"x" * 32,
        read_at=now,
        dismissed_at=now,
        expires_at=now + timedelta(days=1),
        resource_type="report",
        resource_id=uuid.uuid4(),
        created_at=now,
    )
    payload = serialize_notification(notification)
    assert payload["read_at"] and payload["dismissed_at"] and payload["expires_at"]
    assert payload["resource_id"] == str(notification.resource_id)


def test_safe_internal_link_supports_none_and_truncates_only_valid_internal_paths() -> None:
    assert safe_internal_link(None) is None
    long_path = "/app/reports?query=" + "x" * 2000
    assert len(safe_internal_link(long_path) or "") == 1000
    assert safe_internal_link(" /app/reports ") == "/app/reports"


def test_capture_and_smtp_email_templates_are_idempotent_and_do_not_hide_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = CaptureEmailSender()
    capture.send_notification(
        recipient="user@example.test",
        title="Informe listo",
        body="Ya está disponible.",
        url="https://oracle.example.test/app/reports/1",
        idempotency_key="notification-1",
    )
    capture.send_notification(
        recipient="user@example.test",
        title="Informe listo",
        body="Ya está disponible.",
        url="https://oracle.example.test/app/reports/1",
        idempotency_key="notification-1",
    )
    capture.send_digest(
        recipient="user@example.test",
        cadence="weekly",
        items=(("Cambio", "Descripción", "https://oracle.example.test/app/change"),),
        preferences_url="https://oracle.example.test/app/account/notifications",
        idempotency_key="digest-1",
    )
    assert len(capture.messages) == 2
    assert "Abrir en OPN Oracle" in capture.messages[0].body
    assert "Resumen semanal" in capture.messages[1].body

    calls: list[tuple[str, Any]] = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(("connect", (host, port, timeout)))

        def __enter__(self) -> FakeSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            calls.append(("starttls", None))

        def login(self, username: str, password: str) -> None:
            calls.append(("login", (username, password)))

        def send_message(self, message: Any) -> None:
            calls.append(("send", message))

    monkeypatch.setattr("opn_oracle.notifications.email.smtplib.SMTP", FakeSMTP)
    smtp = SMTPEmailSender(
        host="smtp.example.test",
        port=587,
        username="oracle",
        password="secret",
        use_tls=True,
        sender="oracle@example.test",
    )
    smtp.send_notification(
        recipient="user@example.test",
        title="Aviso",
        body="Contenido",
        url=None,
        idempotency_key="smtp-notification-1",
    )
    smtp.send_notification(
        recipient="user@example.test",
        title="Aviso",
        body="Contenido",
        url=None,
        idempotency_key="smtp-notification-1",
    )
    assert [name for name, _ in calls].count("send") == 1
    sent_message = next(value for name, value in calls if name == "send")
    assert sent_message["Message-ID"] == "<smtp-notification-1@oracle.opnconsultoria.com>"
    assert ("starttls", None) in calls
    assert ("login", ("oracle", "secret")) in calls
