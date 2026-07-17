from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from redis import Redis
from sqlalchemy import create_engine, select, text, update

from opn_oracle import create_app
from opn_oracle.ai.models import AITenantPolicy
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.documents.storage import LocalObjectStorage, StoredObject
from opn_oracle.extensions import db
from opn_oracle.jobs.service import stage_job
from opn_oracle.notifications.email import CaptureEmailSender
from opn_oracle.oracle.jobs import BackgroundJob, JobSchedule
from opn_oracle.oracle.models import DossierObjective, Hypothesis, Report, StrategicDossier
from opn_oracle.reporting.exports import (
    ExportError,
    ExportLeaseLost,
    create_export_request,
    process_export,
)
from opn_oracle.reporting.models import (
    DataExport,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    ReportArtifact,
)
from opn_oracle.reporting.notifications import (
    NotificationPermanentError,
    NotificationTemporaryError,
    create_notification,
    next_digest_run,
    send_digest,
    send_notification_email,
)
from opn_oracle.reporting.registry import ReportTemplateRegistry
from opn_oracle.reporting.rendering import DisabledPDFRenderer
from opn_oracle.reporting.service import (
    ReportLeaseLost,
    ReportWorkflowError,
    create_report_request,
    process_report,
)
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def reporting_stack(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    migration_url = os.environ["TEST_DATABASE_URL"]
    runtime_url = os.environ["TEST_RUNTIME_DATABASE_URL"]
    redis_url = os.environ["TEST_REDIS_URL"]
    Redis.from_url(redis_url).flushdb()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "reporting-extra-integration-secret-key",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "CELERY_BROKER_URL": redis_url,
            "CELERY_RESULT_BACKEND": redis_url,
            "AI_ENABLED": True,
            "AI_MODE": "mock",
            "FRONTEND_ORIGIN": "https://oracle.example.test",
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)

    ids = {
        name: uuid.uuid4()
        for name in (
            "tenant",
            "workspace",
            "owner",
            "other_user",
            "owner_membership",
            "other_membership",
            "owner_role",
        )
    }
    password = "frase reporting segura 2026"
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants"
                "(id,slug,name,status,locale,timezone,settings,created_at,updated_at) "
                "VALUES (:tenant,'reporting-extra','Reporting Extra','active','es-ES',"
                "'Europe/Madrid','{}',now(),now())"
            ),
            {"tenant": ids["tenant"]},
        )
        connection.execute(
            text(
                "INSERT INTO users"
                "(id,email,display_name,password_hash,status,email_verified_at,"
                "created_at,updated_at) "
                "VALUES (:owner,'report-owner@example.test','Report Owner',:password,'active',"
                "now(),now(),now()),(:other,'report-other@example.test','Report Other',:password,"
                "'active',now(),now(),now())"
            ),
            {
                "owner": ids["owner"],
                "other": ids["other_user"],
                "password": PasswordHasher().hash(password),
            },
        )
        connection.execute(
            text(
                "INSERT INTO workspaces"
                "(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) "
                "VALUES (:workspace,:tenant,'principal','Principal','active',true,'{}',now(),now())"
            ),
            {"workspace": ids["workspace"], "tenant": ids["tenant"]},
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships"
                "(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (:owner_membership,:tenant,:owner,'active',now(),'{}',now(),now()),"
                "(:other_membership,:tenant,:other,'active',now(),'{}',now(),now())"
            ),
            {
                "owner_membership": ids["owner_membership"],
                "other_membership": ids["other_membership"],
                "tenant": ids["tenant"],
                "owner": ids["owner"],
                "other": ids["other_user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO roles"
                "(id,tenant_id,key,name,description,is_system,created_at,updated_at) "
                "VALUES (:role,:tenant,'owner','Owner','Owner',true,now(),now())"
            ),
            {"role": ids["owner_role"], "tenant": ids["tenant"]},
        )
        connection.execute(
            text(
                "INSERT INTO membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:owner_membership,:role),(:tenant,:other_membership,:role)"
            ),
            {
                "tenant": ids["tenant"],
                "owner_membership": ids["owner_membership"],
                "other_membership": ids["other_membership"],
                "role": ids["owner_role"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :tenant,:role,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"tenant": ids["tenant"], "role": ids["owner_role"]},
        )

    storage = LocalObjectStorage(tmp_path_factory.mktemp("reporting-extra-storage"))
    app.extensions["object_storage"] = storage
    app.extensions["email_sender"] = CaptureEmailSender()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        db.session.add(
            AITenantPolicy(
                tenant_id=ids["tenant"],
                enabled=True,
                provider="mock",
                allowed_models=["mock-oracle-v1"],
                max_classification="internal",
                daily_call_limit=200,
                max_concurrency=4,
                kill_switch=False,
            )
        )
        db.session.commit()
    yield app, ids, password, storage
    Redis.from_url(redis_url).flushdb()
    migrator.dispose()
    with app.app_context():
        downgrade(directory=migrations, revision="base")


@pytest.fixture(autouse=True)
def clean_reporting_sessions(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
) -> None:
    Redis.from_url(os.environ["TEST_REDIS_URL"]).flushdb()


def _csrf(client: Any) -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return str(response.get_json()["csrf_token"])


def _client(
    stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    email: str = "report-owner@example.test",
) -> Any:
    app, ids, password, _ = stack
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password, "tenant_id": str(ids["tenant"])},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 200, response.get_json()
    return client


def _create_dossier(client: Any, ids: dict[str, uuid.UUID], title: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/dossiers",
        json={
            "workspace_id": str(ids["workspace"]),
            "title": title,
            "type": "project",
            "strategic_goal": "Decidir con evidencia",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _create_report(client: Any, dossier_id: str, key: str | None = None) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/dossiers/{dossier_id}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["html", "json"], "classification": "internal"},
        },
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": key or f"report-extra-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 202, response.get_json()
    report = client.get(f"/api/v1/reports/{response.get_json()['report']['id']}")
    assert report.status_code == 200 and report.get_json()["status"] == "ready"
    return report.get_json()


def test_report_routes_validation_human_revision_retry_and_download_security(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
) -> None:
    app, ids, _, storage = reporting_stack
    owner = _client(reporting_stack)
    other = _client(reporting_stack, "report-other@example.test")
    dossier = _create_dossier(owner, ids, "Workflow adicional de informes")

    templates = owner.get("/api/v1/report-templates")
    assert templates.status_code == 200 and len(templates.get_json()["items"]) == 9
    assert templates.get_json()["capabilities"] == {"pdf": False}
    assert owner.get("/api/v1/reports?page[number]=bad").status_code == 422
    invalid_nested_page = owner.get(f"/api/v1/dossiers/{dossier['id']}/reports?page[number]=bad")
    assert invalid_nested_page.status_code == 422

    invalid_requests = (
        ({"template_key": "executive_dossier", "options": {}}, {}, 422),
        (
            {"template_key": "missing", "options": {}},
            {"Idempotency-Key": "missing-template"},
            422,
        ),
        (
            {"template_key": "executive_dossier", "options": {"formats": ["pdf"]}},
            {"Idempotency-Key": "pdf-disabled"},
            422,
        ),
        (
            {"template_key": "opportunity", "options": {}},
            {"Idempotency-Key": "missing-opportunity"},
            422,
        ),
    )
    for payload, extra_headers, expected in invalid_requests:
        response = owner.post(
            f"/api/v1/dossiers/{dossier['id']}/reports",
            json=payload,
            headers={"X-CSRF-Token": _csrf(owner), **extra_headers},
        )
        assert response.status_code == expected, (payload, response.get_json())

    report = _create_report(owner, dossier["id"])
    report_id = report["id"]
    filtered = owner.get(
        "/api/v1/reports?filter[status]=ready"
        "&filter[template]=executive_dossier&filter[search]=Informe"
    )
    assert filtered.status_code == 200
    assert (
        owner.post(
            f"/api/v1/reports/{report_id}/retry",
            headers={"X-CSRF-Token": _csrf(owner), "Idempotency-Key": "retry-not-failed"},
        ).status_code
        == 409
    )
    assert (
        owner.post(
            f"/api/v1/reports/{uuid.uuid4()}/retry",
            headers={"X-CSRF-Token": _csrf(owner), "Idempotency-Key": "retry-not-found"},
        ).status_code
        == 404
    )
    assert (
        owner.post(
            f"/api/v1/reports/{report_id}/publish",
            json={"version": report["version"]},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 409
    )

    assert (
        owner.post(
            f"/api/v1/reports/{report_id}/revisions",
            json={"content": report["revision"]["content"]},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 422
    )
    assert (
        owner.post(
            f"/api/v1/reports/{report_id}/revisions",
            json={"version": report["version"], "content": []},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 422
    )
    assert (
        owner.post(
            f"/api/v1/reports/{report_id}/revisions",
            json={"version": report["version"] + 99, "content": report["revision"]["content"]},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 409
    )

    revised_content = dict(report["revision"]["content"])
    revised_content["title"] = "Informe revisado por una persona"
    revised = owner.post(
        f"/api/v1/reports/{report_id}/revisions",
        json={
            "version": report["version"],
            "content": revised_content,
            "change_summary": "Se precisa el título sin alterar evidencias.",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert revised.status_code == 201, revised.get_json()
    report = revised.get_json()
    assert report["revision"]["revision_no"] == 2
    assert report["revision"]["title"] == "Informe revisado por una persona"

    bad_reviews = (
        ({"version": report["version"], "revision_id": "bad", "decision": "approved"}, 422),
        (
            {
                "version": report["version"],
                "revision_id": report["revision"]["id"],
                "decision": "invalid",
            },
            422,
        ),
        (
            {
                "version": report["version"],
                "revision_id": report["revision"]["id"],
                "decision": "changes_requested",
                "comment": "",
            },
            422,
        ),
    )
    for payload, status in bad_reviews:
        response = owner.post(
            f"/api/v1/reports/{report_id}/reviews",
            json=payload,
            headers={"X-CSRF-Token": _csrf(owner)},
        )
        assert response.status_code == status

    commented = owner.post(
        f"/api/v1/reports/{report_id}/reviews",
        json={
            "version": report["version"],
            "revision_id": report["revision"]["id"],
            "decision": "comment",
            "comment": "Comentario no aprobatorio.",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert commented.status_code == 201
    report = commented.get_json()["report"]
    approved = owner.post(
        f"/api/v1/reports/{report_id}/reviews",
        json={
            "version": report["version"],
            "revision_id": report["revision"]["id"],
            "decision": "approved",
            "comment": "Aprobado.",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert approved.status_code == 201

    report = approved.get_json()["report"]
    artifact = next(item for item in report["artifacts"] if item["format"] == "json")
    missing_link = owner.post(
        f"/api/v1/reports/{report_id}/artifacts/{uuid.uuid4()}/download-link",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert missing_link.status_code == 404
    link = owner.post(
        f"/api/v1/reports/{report_id}/artifacts/{artifact['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()["url"]
    assert owner.get(link).status_code == 200
    assert other.get(link).status_code in {403, 404}
    second_owner_session = _client(reporting_stack)
    assert second_owner_session.get(link).status_code == 403
    assert owner.get(link.replace("signature=", "signature=0")).status_code == 403
    assert owner.get(link.split("?", 1)[0] + "?expires=bad&signature=x").status_code == 403

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        stored = db.session.get(ReportArtifact, uuid.UUID(artifact["id"]))
        assert stored is not None
        replacement = b'{"replacement":true}'
        replacement_key = "/".join((*stored.storage_key.split("/")[:-1], str(uuid.uuid4())))
        storage._path(replacement_key).parent.mkdir(parents=True, exist_ok=True)
        storage._path(replacement_key).write_bytes(replacement)
        stored.storage_key = replacement_key
        stored.checksum = hashlib.sha256(replacement).digest()
        stored.byte_size = len(replacement)
        db.session.commit()
    # The old signature cannot authorize a valid replacement at the same artifact ID.
    assert owner.get(link).status_code == 403
    replacement_link = owner.post(
        f"/api/v1/reports/{report_id}/artifacts/{artifact['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()["url"]
    replacement_response = owner.get(replacement_link)
    assert replacement_response.status_code == 200
    assert replacement_response.data == replacement
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        stored = db.session.get(ReportArtifact, uuid.UUID(artifact["id"]))
        assert stored is not None
        storage._path(stored.storage_key).write_bytes(b"tampered")
    assert owner.get(replacement_link).status_code == 403

    failed_source = _create_report(owner, dossier["id"])
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        failed = db.session.get(Report, uuid.UUID(failed_source["id"]))
        assert failed is not None
        failed.status = "failed"
        failed.error_code = "provider_unavailable"
        db.session.commit()
    retry = owner.post(
        f"/api/v1/reports/{failed_source['id']}/retry",
        headers={"X-CSRF-Token": _csrf(owner), "Idempotency-Key": f"retry-{uuid.uuid4()}"},
    )
    assert retry.status_code == 202, retry.get_json()
    assert retry.get_json()["report"]["parent_report_id"] == failed_source["id"]


def test_pdf_renderer_invalid_output_fails_closed_without_persisting_artifact(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    tmp_path: Path,
) -> None:
    app, ids, _, original_storage = reporting_stack
    storage = LocalObjectStorage(tmp_path / "invalid-pdf")

    class InvalidPDFRenderer:
        enabled = True

        def render(self, html: bytes, *, max_bytes: int) -> bytes:
            assert html and max_bytes > 0
            return b"this is not a PDF"

    app.extensions["object_storage"] = storage
    app.extensions["pdf_renderer"] = InvalidPDFRenderer()
    client = _client(reporting_stack)
    dossier = _create_dossier(client, ids, "PDF fail closed")
    response = client.post(
        f"/api/v1/dossiers/{dossier['id']}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["pdf"], "classification": "internal"},
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": f"pdf-{uuid.uuid4()}"},
    )
    assert response.status_code == 202
    detail = client.get(f"/api/v1/reports/{response.get_json()['report']['id']}").get_json()
    assert detail["status"] == "failed"
    assert detail["artifacts"] == [] and detail["revision"] is None
    assert storage.iter_objects(ids["tenant"]) == ()
    app.extensions["pdf_renderer"] = DisabledPDFRenderer()
    app.extensions["object_storage"] = original_storage


def test_report_worker_requires_lease_and_context_factory_uses_frozen_snapshot(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _, _ = reporting_stack
    client = _client(reporting_stack)
    dossier_data = _create_dossier(client, ids, "Título capturado")
    dossier_id = uuid.UUID(dossier_data["id"])
    captured: dict[str, Any] = {}
    monkeypatch.setattr("opn_oracle.reporting.service.publish_job", lambda job: None)

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        dossier = db.session.get(StrategicDossier, dossier_id)
        assert dossier is not None
        objective = DossierObjective(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            title="Objetivo capturado",
            position=0,
        )
        hypothesis = Hypothesis(
            tenant_id=ids["tenant"],
            dossier_id=dossier_id,
            statement="Hipótesis capturada",
            position=0,
        )
        db.session.add_all((objective, hypothesis))
        db.session.commit()
        report, job, created = create_report_request(
            dossier,
            template_key="executive_dossier",
            options={"formats": ["json"]},
            requested_by_user_id=ids["owner"],
            idempotency_key=f"frozen-context-{uuid.uuid4()}",
        )
        assert created
        with pytest.raises(ReportLeaseLost, match="lease activa"):
            process_report(report.id, job)

        dossier.title = "Título mutado después del snapshot"
        objective.title = "Objetivo mutado después del snapshot"
        hypothesis.statement = "Hipótesis mutada después del snapshot"
        job.status = "running"
        job.execution_lease_id = uuid.uuid4()
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.session.commit()

        def inspect_context(**kwargs: Any) -> dict[str, Any]:
            context = kwargs["context_factory"](2_000)
            captured["payload"] = context.payload
            captured["manifest"] = context.manifest
            raise RuntimeError("stop after frozen context inspection")

        monkeypatch.setattr("opn_oracle.reporting.service.execute_agent", inspect_context)
        with pytest.raises(RuntimeError, match="frozen context"):
            process_report(report.id, job)
        db.session.refresh(report)
        assert report.status == "failed"

    payload = captured["payload"]
    assert payload["snapshot_mode"] is True
    assert payload["dossier"]["title"] == "Título capturado"
    assert payload["objectives"][0]["title"] == "Objetivo capturado"
    assert payload["hypotheses"][0]["statement"] == "Hipótesis capturada"
    assert captured["manifest"]["frozen"] is True


@pytest.mark.parametrize("tamper", ["source", "template", "options"])
def test_report_worker_rejects_snapshot_template_and_option_tampering(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    app, ids, _, storage = reporting_stack
    client = _client(reporting_stack)
    dossier_data = _create_dossier(client, ids, f"Integridad snapshot {tamper}")
    monkeypatch.setattr("opn_oracle.reporting.service.publish_job", lambda job: None)
    before_objects = storage.iter_objects(ids["tenant"])

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        dossier = db.session.get(StrategicDossier, uuid.UUID(dossier_data["id"]))
        assert dossier is not None
        report, job, created = create_report_request(
            dossier,
            template_key="executive_dossier",
            options={"formats": ["json"], "classification": "internal"},
            requested_by_user_id=ids["owner"],
            idempotency_key=f"snapshot-tamper-{tamper}-{uuid.uuid4()}",
        )
        assert created
        assert report.snapshot_hash_algorithm == "canonical-json-sha256-v1"
        template = ReportTemplateRegistry().get(report.template_key, report.template_version)
        assert report.source_snapshot["template"] == {
            "key": report.template_key,
            "version": report.template_version,
            "sha256": template.sha256.hex(),
            "sections": report.source_snapshot["template"]["sections"],
            "evidence_policy": report.source_snapshot["template"]["evidence_policy"],
        }
        assert report.source_snapshot["options"] == report.options

        if tamper == "source":
            mutated = dict(report.source_snapshot)
            mutated["dossier"] = {**mutated["dossier"], "title": "Manipulado"}
            report.source_snapshot = mutated
        elif tamper == "template":
            report.template_version = "v999"
        else:
            report.options = {**report.options, "classification": "public"}
        job.status = "running"
        job.execution_lease_id = uuid.uuid4()
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.session.commit()

        with pytest.raises(ReportWorkflowError):
            process_report(report.id, job)
        db.session.refresh(report)
        assert report.status == "failed"
        assert report.error_code == "ReportWorkflowError"
        assert not list(
            db.session.scalars(select(ReportArtifact).where(ReportArtifact.report_id == report.id))
        )
        assert storage.iter_objects(ids["tenant"]) == before_objects


def test_notification_preferences_alert_policy_inbox_and_ownership_routes(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
) -> None:
    app, ids, _, _ = reporting_stack
    owner = _client(reporting_stack)
    dossier = _create_dossier(owner, ids, "Políticas de aviso")
    assert owner.get("/api/v1/notifications?page[number]=bad").status_code == 422
    assert (
        owner.post(
            f"/api/v1/notifications/{uuid.uuid4()}/read",
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 404
    )
    assert (
        owner.post(
            f"/api/v1/notifications/{uuid.uuid4()}/dismiss",
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 404
    )

    invalid_preferences = (
        {"notification_type": ""},
        {"notification_type": "product", "channels": {"in_app": True}},
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "monthly",
        },
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "weekly",
        },
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "daily",
            "timezone": "Invalid/Zone",
        },
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "daily",
            "local_time": "invalid",
        },
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "instant",
            "quiet_hours_start": "22:00",
        },
        {
            "notification_type": "product",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "instant",
            "minimum_severity": "severe",
        },
    )
    for payload in invalid_preferences:
        response = owner.patch(
            "/api/v1/notification-preferences",
            json=payload,
            headers={"X-CSRF-Token": _csrf(owner)},
        )
        assert response.status_code == 422, (payload, response.get_json())

    created = owner.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "product",
            "channels": {"in_app": True, "email": True},
            "digest_cadence": "weekly",
            "timezone": "Europe/Madrid",
            "local_time": "08:30",
            "weekday": 1,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
            "minimum_severity": "warning",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert created.status_code == 200, created.get_json()
    preference = created.get_json()
    assert owner.get("/api/v1/notification-preferences").get_json()["items"]
    stale = owner.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "product",
            "version": preference["version"] + 1,
            "channels": preference["channels"],
            "digest_cadence": "off",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert stale.status_code == 409
    disabled = owner.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "product",
            "version": preference["version"],
            "channels": preference["channels"],
            "digest_cadence": "off",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert disabled.status_code == 200
    locked = owner.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "security.session_revoked",
            "channels": {"in_app": False, "email": False},
            "digest_cadence": "off",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert locked.status_code == 200
    assert locked.get_json()["security_locked"] is True
    assert locked.get_json()["channels"] == {"in_app": True, "email": True}

    policy = owner.get(f"/api/v1/dossiers/{dossier['id']}/alert-policy")
    assert policy.status_code == 200
    assert owner.get(f"/api/v1/dossiers/{uuid.uuid4()}/alert-policy").status_code == 404
    current = policy.get_json()
    invalid_policies = (
        {"version": current["version"] + 1},
        {"version": current["version"], "signal_score_threshold": 101},
        {"version": current["version"], "opportunity_deadline_days": 366},
        {"version": current["version"], "meeting_upcoming_hours": 0},
        {"version": current["version"], "cooldown_minutes": 10081},
        {"version": current["version"], "enabled_types": []},
        {"version": current["version"], "timezone": "Invalid/Zone"},
        {"version": current["version"], "quiet_hours_start": "22:00"},
    )
    expected = (409, 422, 422, 422, 422, 422, 422, 422)
    for payload, status in zip(invalid_policies, expected, strict=True):
        response = owner.patch(
            f"/api/v1/dossiers/{dossier['id']}/alert-policy",
            json=payload,
            headers={"X-CSRF-Token": _csrf(owner)},
        )
        assert response.status_code == status, (payload, response.get_json())
    updated = owner.patch(
        f"/api/v1/dossiers/{dossier['id']}/alert-policy",
        json={
            "version": current["version"],
            "signal_score_threshold": 88,
            "enabled_types": {"report_ready": True},
            "severity_map": {"report_ready": "success"},
            "timezone": "UTC",
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "06:00",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert updated.status_code == 200 and updated.get_json()["signal_score_threshold"] == 88

    hidden_preference = owner.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "product.hidden",
            "channels": {"in_app": False, "email": False},
            "digest_cadence": "off",
            "minimum_severity": "warning",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert hidden_preference.status_code == 200

    now = datetime.now(UTC)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        own = create_notification(
            user_id=ids["owner"],
            notification_type="product.route",
            severity="warning",
            title="Pendiente",
            body="Notificación visible.",
            dedupe_key=f"route-own-{uuid.uuid4()}",
        ).notification
        other = create_notification(
            user_id=ids["other_user"],
            notification_type="product.route",
            severity="warning",
            title="Ajena",
            body="No debe ser mutable.",
            dedupe_key=f"route-other-{uuid.uuid4()}",
        ).notification
        hidden = create_notification(
            user_id=ids["owner"],
            notification_type="product.hidden",
            severity="info",
            title="Bajo umbral",
            body="No debe aparecer ni generar email.",
            dedupe_key=f"hidden-{uuid.uuid4()}",
        )
        assert hidden.notification.in_app_visible is False
        assert hidden.email_job is None
        expired = Notification(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="product.expired",
            severity="info",
            title="Caducada",
            body="No aparece.",
            dedupe_key=f"expired-{uuid.uuid4()}",
            request_hash=hashlib.sha256(b"expired").digest(),
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
            expires_at=now - timedelta(seconds=1),
        )
        db.session.add(expired)
        db.session.commit()
        own_id, other_id, expired_id, hidden_id = (
            own.id,
            other.id,
            expired.id,
            hidden.notification.id,
        )
    inbox_ids = {item["id"] for item in owner.get("/api/v1/notifications").get_json()["data"]}
    assert str(own_id) in inbox_ids
    assert str(expired_id) not in inbox_ids and str(hidden_id) not in inbox_ids
    assert (
        owner.post(
            f"/api/v1/notifications/{other_id}/read",
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 404
    )
    first_read = owner.post(
        f"/api/v1/notifications/{own_id}/read",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    second_read = owner.post(
        f"/api/v1/notifications/{own_id}/read",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert first_read.status_code == second_read.status_code == 200
    assert first_read.get_json()["read_at"] == second_read.get_json()["read_at"]
    first_dismiss = owner.post(
        f"/api/v1/notifications/{own_id}/dismiss",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    second_dismiss = owner.post(
        f"/api/v1/notifications/{own_id}/dismiss",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert first_dismiss.get_json()["dismissed_at"] == second_dismiss.get_json()["dismissed_at"]

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        schedules = list(db.session.scalars(select(JobSchedule)))
        assert schedules and all(not row.enabled for row in schedules)


def test_notification_email_delivery_handles_retry_inactive_and_ambiguous_smtp(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
) -> None:
    app, ids, _, _ = reporting_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        with pytest.raises(NotificationPermanentError, match="no disponible"):
            send_notification_email(uuid.uuid4())

        created = create_notification(
            user_id=ids["owner"],
            notification_type="security.password_changed",
            severity="critical",
            title="Contraseña modificada",
            body="La contraseña se ha modificado.",
            dedupe_key=f"email-retry-{uuid.uuid4()}",
            link="/app/account/sessions",
        )
        assert created.email_job is not None
        delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == created.notification.id
            )
        )
        assert delivery is not None
        db.session.commit()


def test_digest_respects_threshold_expiry_specific_override_quiet_hours_and_retry_period(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _, _ = reporting_stack
    start = datetime(2026, 7, 13, 8, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        current = start

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            value = cls.current
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr("opn_oracle.reporting.notifications.datetime", FrozenDateTime)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        db.session.execute(
            update(Notification)
            .where(Notification.user_id == ids["owner"], Notification.dismissed_at.is_(None))
            .values(dismissed_at=start)
        )
        exact = NotificationPreference(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="digest.exact",
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=time(8, 0),
            weekday=None,
            minimum_severity="warning",
            security_locked=False,
            version=1,
        )
        wildcard = NotificationPreference(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="*",
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=time(8, 0),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        quiet = NotificationPreference(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="digest.quiet",
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=time(23, 0),
            weekday=None,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(7, 0),
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        retry_preference = NotificationPreference(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="digest.retry-period",
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=time(8, 0),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add_all((exact, wildcard, quiet, retry_preference))
        db.session.flush()

        below = create_notification(
            user_id=ids["owner"],
            notification_type="digest.exact",
            severity="info",
            title="Bajo el umbral",
            body="No debe entrar en el digest.",
            dedupe_key=f"digest-below-{uuid.uuid4()}",
            now=start,
        ).notification
        included = create_notification(
            user_id=ids["owner"],
            notification_type="digest.exact",
            severity="warning",
            title="Exacta incluida",
            body="Solo en el digest específico.",
            dedupe_key=f"digest-exact-{uuid.uuid4()}",
            now=start,
        ).notification
        wildcard_only = create_notification(
            user_id=ids["owner"],
            notification_type="digest.other",
            severity="info",
            title="Wildcard incluida",
            body="Solo en el digest general.",
            dedupe_key=f"digest-wildcard-{uuid.uuid4()}",
            now=start,
        ).notification
        retry_item = create_notification(
            user_id=ids["owner"],
            notification_type="digest.retry-period",
            severity="warning",
            title="Retry estable",
            body="Conserva el periodo original.",
            dedupe_key=f"digest-retry-period-{uuid.uuid4()}",
            now=start,
        ).notification
        for item in (below, included, wildcard_only, retry_item):
            item.created_at = start
            item.updated_at = start
        expired = Notification(
            tenant_id=ids["tenant"],
            user_id=ids["owner"],
            notification_type="digest.exact",
            severity="critical",
            title="Caducada",
            body="No debe entrar en el digest.",
            in_app_visible=True,
            dedupe_key=f"digest-expired-{uuid.uuid4()}",
            request_hash=hashlib.sha256(b"digest-expired").digest(),
            created_at=start - timedelta(hours=12),
            updated_at=start - timedelta(hours=12),
            expires_at=start - timedelta(seconds=1),
        )
        db.session.add(expired)
        exact_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(exact.id)},
            idempotency_key=f"digest-exact-job-{uuid.uuid4()}",
            requested_by_user_id=ids["owner"],
            resource_type="notification_preference",
            resource_id=exact.id,
        )
        wildcard_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(wildcard.id)},
            idempotency_key=f"digest-wildcard-job-{uuid.uuid4()}",
            requested_by_user_id=ids["owner"],
            resource_type="notification_preference",
            resource_id=wildcard.id,
        )
        retry_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(retry_preference.id)},
            idempotency_key=f"digest-period-job-{uuid.uuid4()}",
            requested_by_user_id=ids["owner"],
            resource_type="notification_preference",
            resource_id=retry_preference.id,
        )
        db.session.commit()

        sender = CaptureEmailSender()
        app.extensions["email_sender"] = sender
        exact_result = send_digest(exact.id, exact_job)
        wildcard_result = send_digest(wildcard.id, wildcard_job)
        assert exact_result["count"] == 1
        assert wildcard_result["count"] == 1
        assert below.in_app_visible is False
        assert included.in_app_visible is True and wildcard_only.in_app_visible is True
        assert "Exacta incluida" in sender.messages[0].body
        assert "Bajo el umbral" not in sender.messages[0].body
        assert "Caducada" not in sender.messages[0].body
        assert "Wildcard incluida" in sender.messages[1].body
        assert "Exacta incluida" not in sender.messages[1].body

        quiet_run = next_digest_run(quiet, start)
        assert quiet_run.astimezone(UTC).time() == time(7, 0)

        class FlakyDigest(CaptureEmailSender):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_digest(self, **kwargs: Any) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise OSError("provider down after delivery intent")
                super().send_digest(**kwargs)

        flaky = FlakyDigest()
        app.extensions["email_sender"] = flaky
        with pytest.raises(NotificationTemporaryError):
            send_digest(retry_preference.id, retry_job)
        FrozenDateTime.current = start + timedelta(days=1, minutes=5)
        retried = send_digest(retry_preference.id, retry_job)
        assert retried["delivered"] is True and retried["count"] == 1
        deliveries = list(
            db.session.scalars(
                select(NotificationDelivery).where(NotificationDelivery.job_id == retry_job.id)
            )
        )
        assert len(deliveries) == 1
        assert deliveries[0].attempts == 2
        assert deliveries[0].notification_id == retry_item.id
        assert deliveries[0].dedupe_key.endswith(start.date().isoformat())

        retry_notification = create_notification(
            user_id=ids["owner"],
            notification_type="security.password_changed",
            severity="critical",
            title="Contraseña modificada",
            body="La contraseña se ha modificado.",
            dedupe_key=f"email-retry-digest-test-{uuid.uuid4()}",
            link="/app/account/sessions",
        ).notification
        delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == retry_notification.id
            )
        )
        assert delivery is not None
        db.session.commit()

        class FlakySender(CaptureEmailSender):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_notification(self, **kwargs: Any) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise OSError("SMTP unavailable")
                super().send_notification(**kwargs)

        flaky = FlakySender()
        app.extensions["email_sender"] = flaky
        with pytest.raises(NotificationTemporaryError):
            send_notification_email(delivery.id)
        assert send_notification_email(delivery.id)["delivered"] is True
        assert send_notification_email(delivery.id)["delivered"] is True
        assert flaky.calls == 2 and len(flaky.messages) == 1

        ambiguous_notification = create_notification(
            user_id=ids["owner"],
            notification_type="security.session_revoked",
            severity="critical",
            title="Sesión revocada",
            body="Se ha revocado una sesión.",
            dedupe_key=f"email-ambiguous-{uuid.uuid4()}",
        ).notification
        ambiguous = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == ambiguous_notification.id
            )
        )
        assert ambiguous is not None
        ambiguous.status = "failed"
        ambiguous.delivery_started_at = datetime.now(UTC)
        ambiguous.error_code = "provider_unavailable"
        db.session.commit()
        app.extensions["email_sender"] = SimpleNamespace(supports_idempotency=False)
        with pytest.raises(NotificationPermanentError, match="desconocido"):
            send_notification_email(ambiguous.id)

        inactive_notification = create_notification(
            user_id=ids["other_user"],
            notification_type="security.suspicious_login",
            severity="critical",
            title="Inicio sospechoso",
            body="Revisa la actividad.",
            dedupe_key=f"email-inactive-{uuid.uuid4()}",
        ).notification
        inactive_delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == inactive_notification.id
            )
        )
        assert inactive_delivery is not None
        db.session.execute(
            text("UPDATE users SET status='disabled' WHERE id=:user"),
            {"user": ids["other_user"]},
        )
        db.session.commit()
        app.extensions["email_sender"] = CaptureEmailSender()
        skipped = send_notification_email(inactive_delivery.id)
        assert skipped["delivered"] is False
        db.session.execute(
            text("UPDATE users SET status='active' WHERE id=:user"),
            {"user": ids["other_user"]},
        )
        db.session.commit()


def test_export_routes_search_validation_expiry_and_failure_cleanup(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _, original_storage = reporting_stack
    client = _client(reporting_stack)
    dossier = _create_dossier(client, ids, "Exportación adicional")
    opportunity = client.post(
        f"/api/v1/dossiers/{dossier['id']}/opportunities",
        json={
            "title": "Oportunidad exportable",
            "description": "Descripción",
            "next_action": "Llamar al partner sintético",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert opportunity.status_code == 201
    assert client.get("/api/v1/exports?page[size]=bad").status_code == 422
    assert client.get(f"/api/v1/exports/{uuid.uuid4()}").status_code == 404
    assert (
        client.post(
            f"/api/v1/exports/{uuid.uuid4()}/download-link",
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 404
    )

    invalid = (
        ({"dataset": "unknown"}, {}, 403),
        ({"dataset": "opportunities", "dossier_id": "bad"}, {}, 422),
        ({"dataset": "opportunities", "dossier_id": str(uuid.uuid4())}, {}, 404),
        (
            {"dataset": "opportunities", "columns": ["secret"]},
            {"Idempotency-Key": "bad-columns"},
            422,
        ),
        (
            {"dataset": "opportunities", "filters": {"tenant_id": "x"}},
            {"Idempotency-Key": "bad-filter"},
            422,
        ),
        ({"dataset": "opportunities"}, {"Idempotency-Key": "short"}, 422),
    )
    for payload, headers, expected in invalid:
        response = client.post(
            "/api/v1/exports",
            json=payload,
            headers={"X-CSRF-Token": _csrf(client), **headers},
        )
        assert response.status_code == expected, (payload, response.get_json())

    key = f"search-export-{uuid.uuid4()}"
    payload = {
        "dataset": "opportunities",
        "dossier_id": dossier["id"],
        "columns": ["id", "title", "next_action"],
        "filters": {"search": "partner sintético"},
    }
    exported = client.post(
        "/api/v1/exports",
        json=payload,
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert exported.status_code == 202, exported.get_json()
    row = exported.get_json()["export"]
    assert row["status"] == "ready"
    replay = client.post(
        "/api/v1/exports",
        json=payload,
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert replay.status_code == 200 and replay.get_json()["replayed"] is True
    conflict_payload = dict(payload)
    conflict_payload["filters"] = {"search": "otra intención"}
    conflict = client.post(
        "/api/v1/exports",
        json=conflict_payload,
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert conflict.status_code == 409
    download_link = client.post(
        f"/api/v1/exports/{row['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert download_link.status_code == 200
    csv = client.get(download_link.get_json()["url"])
    assert csv.status_code == 200 and b"partner" in csv.data
    tampered_link = download_link.get_json()["url"].replace("signature=", "signature=x")
    assert client.get(tampered_link).status_code == 403

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        ready = db.session.get(DataExport, uuid.UUID(row["id"]))
        assert ready is not None
        replacement = b"id,title\nreplacement,Reemplazo\n"
        assert ready.storage_key is not None
        replacement_key = "/".join((*ready.storage_key.split("/")[:-1], str(uuid.uuid4())))
        original_storage._path(replacement_key).parent.mkdir(parents=True, exist_ok=True)
        original_storage._path(replacement_key).write_bytes(replacement)
        ready.storage_key = replacement_key
        ready.checksum = hashlib.sha256(replacement).digest()
        ready.byte_size = len(replacement)
        ready.version += 1
        db.session.commit()
    assert client.get(download_link.get_json()["url"]).status_code == 403
    replacement_link = client.post(
        f"/api/v1/exports/{row['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(client)},
    ).get_json()["url"]
    assert client.get(replacement_link).data == replacement

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        ready = db.session.get(DataExport, uuid.UUID(row["id"]))
        assert ready is not None
        ready.created_at = datetime.now(UTC) - timedelta(days=1)
        ready.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.session.commit()
    expired = client.post(
        f"/api/v1/exports/{row['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert expired.status_code == 410
    assert client.get(download_link.get_json()["url"]).status_code == 403

    class BadMetadataStorage:
        def __init__(self) -> None:
            self.deleted: list[str] = []

        def put(self, key: str, source: Any, *, max_bytes: int, media_type: str) -> StoredObject:
            del max_bytes, media_type
            data = source.read()
            return StoredObject(key, len(data), b"\x00" * 32)

        def delete(self, key: str) -> None:
            self.deleted.append(key)

    bad_storage = BadMetadataStorage()
    app.extensions["object_storage"] = bad_storage
    monkeypatch.setattr("opn_oracle.reporting.exports.publish_job", lambda job: None)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        export, job, created = create_export_request(
            dataset="opportunities",
            columns=["id", "title", "next_action"],
            filters={"search": "partner"},
            dossier_id=uuid.UUID(dossier["id"]),
            requested_by_user_id=ids["owner"],
            idempotency_key=f"bad-storage-{uuid.uuid4()}",
        )
        assert created
        with pytest.raises(ExportLeaseLost, match="lease activa"):
            process_export(export.id, job)
        job.status = "running"
        job.execution_lease_id = uuid.uuid4()
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.session.commit()
        with pytest.raises(ExportError, match="metadata inconsistente"):
            process_export(export.id, job)
        db.session.refresh(export)
        assert export.status == "failed"
        assert export.storage_key is None and export.checksum is None
        assert bad_storage.deleted
        with pytest.raises(ExportError, match="no disponible"):
            process_export(uuid.uuid4(), job)
        export.status = "purged"
        export.expires_at = datetime.now(UTC)
        db.session.commit()
        with pytest.raises(ExportError, match="no procesable"):
            process_export(export.id, job)
    app.extensions["object_storage"] = original_storage


def test_export_revalidates_dataset_permission_in_worker_and_download_routes(
    reporting_stack: tuple[Any, dict[str, uuid.UUID], str, LocalObjectStorage],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _, _ = reporting_stack
    client = _client(reporting_stack)
    dossier = _create_dossier(client, ids, "Revocación de exportación")
    monkeypatch.setattr("opn_oracle.reporting.exports.publish_job", lambda job: None)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        export, job, created = create_export_request(
            dataset="opportunities",
            columns=["id", "title"],
            filters={},
            dossier_id=uuid.UUID(dossier["id"]),
            requested_by_user_id=ids["owner"],
            idempotency_key=f"revoked-dataset-{uuid.uuid4()}",
        )
        assert created
        db.session.execute(
            text(
                "DELETE FROM role_permissions WHERE tenant_id=:tenant AND role_id=:role "
                "AND permission_key='opportunity.read'"
            ),
            {"tenant": ids["tenant"], "role": ids["owner_role"]},
        )
        db.session.commit()
        export_id, job_id = export.id, job.id

    assert client.get(f"/api/v1/exports/{export_id}").status_code == 404
    assert (
        client.post(
            f"/api/v1/exports/{export_id}/download-link",
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 404
    )

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant"], actor_id=ids["owner"])),
    ):
        export = db.session.get(DataExport, export_id)
        assert export is not None
        job = db.session.get(BackgroundJob, job_id)
        assert job is not None
        job.status = "running"
        job.execution_lease_id = uuid.uuid4()
        job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.session.commit()
        with pytest.raises(ExportError, match="permiso del dataset fue revocado"):
            process_export(export.id, job)
        db.session.refresh(export)
        assert export.status == "failed" and export.error_code == "permission_revoked"
        db.session.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "VALUES (:tenant,:role,'opportunity.read') ON CONFLICT DO NOTHING"
            ),
            {"tenant": ids["tenant"], "role": ids["owner_role"]},
        )
        db.session.commit()
