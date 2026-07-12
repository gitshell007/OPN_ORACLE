from __future__ import annotations

import hashlib
import io
import os
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from flask_migrate import downgrade, upgrade
from redis import Redis
from sqlalchemy import create_engine, func, select, text

from opn_oracle import create_app
from opn_oracle.ai.models import AITenantPolicy
from opn_oracle.ai.provider import LLMRequest, LLMResult, MockLLMProvider
from opn_oracle.ai.schemas import ReportOutput
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.cli.oracle import stable_id
from opn_oracle.documents.models import (
    Document,
    DocumentChunk,
    DocumentProcessingAttempt,
    DocumentVersion,
)
from opn_oracle.documents.service import (
    DocumentError,
    create_upload,
    process_document,
    purge_due_documents,
    reconcile_storage_orphans,
    recover_expired_document_attempts,
)
from opn_oracle.documents.storage import (
    LocalObjectStorage,
    StorageError,
    StoredObject,
    object_key,
)
from opn_oracle.extensions import db
from opn_oracle.jobs.service import enqueue_job, stage_job
from opn_oracle.jobs.tasks import dispatch_queued_jobs
from opn_oracle.notifications.email import CaptureEmailSender
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.links import DossierCollaborator
from opn_oracle.oracle.models import Report, StrategicDossier
from opn_oracle.reporting.models import (
    DataExport,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    ReportArtifact,
)
from opn_oracle.reporting.notifications import (
    NotificationError,
    NotificationPermanentError,
    NotificationTemporaryError,
    create_notification,
    publish_notification_job,
    send_digest,
    send_notification_email,
    sync_digest_schedule,
)
from opn_oracle.reporting.service import (
    ReportConflictError,
    create_report_request,
)
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def oracle_stack() -> Iterator[tuple[Any, dict[str, uuid.UUID], str]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    migration_url, runtime_url, redis_url = (
        os.environ["TEST_DATABASE_URL"],
        os.environ["TEST_RUNTIME_DATABASE_URL"],
        os.environ["TEST_REDIS_URL"],
    )
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "oracle-domain-integration-secret-key-32",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations)
    ids = {
        name: uuid.uuid4()
        for name in (
            "tenant_a",
            "tenant_b",
            "workspace_a",
            "workspace_b",
            "user",
            "membership",
            "role",
            "limited_user",
            "limited_membership",
            "limited_role",
            "reader_user",
            "reader_membership",
            "reader_role",
        )
    }
    password = "frase dominio segura 2026"
    engine = create_engine(migration_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants(id,slug,name,status,locale,timezone,settings,created_at,updated_at) VALUES (:a,'oracle-a','Oracle A','active','es-ES','UTC','{}',now(),now()),(:b,'oracle-b','Oracle B','active','es-ES','UTC','{}',now(),now())"
            ),
            {"a": ids["tenant_a"], "b": ids["tenant_b"]},
        )
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,password_hash,status,email_verified_at,created_at,updated_at) VALUES (:u,'domain-owner@example.test','Domain Owner',:p,'active',now(),now(),now()),(:lu,'domain-limited@example.test','Domain Limited',:p,'active',now(),now(),now()),(:ru,'domain-reader@example.test','Domain Reader',:p,'active',now(),now(),now())"
            ),
            {
                "u": ids["user"],
                "lu": ids["limited_user"],
                "ru": ids["reader_user"],
                "p": PasswordHasher().hash(password),
            },
        )
        connection.execute(
            text(
                "INSERT INTO workspaces(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) VALUES (:wa,:a,'principal','Principal','active',true,'{}',now(),now()),(:wb,:b,'principal','Principal','active',true,'{}',now(),now())"
            ),
            {
                "wa": ids["workspace_a"],
                "wb": ids["workspace_b"],
                "a": ids["tenant_a"],
                "b": ids["tenant_b"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) VALUES (:m,:t,:u,'active',now(),'{}',now(),now()),(:lm,:t,:lu,'active',now(),'{}',now(),now()),(:rm,:t,:ru,'active',now(),'{}',now(),now())"
            ),
            {
                "m": ids["membership"],
                "lm": ids["limited_membership"],
                "rm": ids["reader_membership"],
                "t": ids["tenant_a"],
                "u": ids["user"],
                "lu": ids["limited_user"],
                "ru": ids["reader_user"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO roles(id,tenant_id,key,name,description,is_system,created_at,updated_at) VALUES (:r,:t,'owner','Owner','Owner',true,now(),now()),(:lr,:t,'analyst','Analyst','Analyst',false,now(),now()),(:rr,:t,'reader','Reader','Reader',false,now(),now())"
            ),
            {
                "r": ids["role"],
                "lr": ids["limited_role"],
                "rr": ids["reader_role"],
                "t": ids["tenant_a"],
            },
        )
        connection.execute(
            text("INSERT INTO membership_roles(tenant_id,membership_id,role_id) VALUES (:t,:m,:r)"),
            {"t": ids["tenant_a"], "m": ids["membership"], "r": ids["role"]},
        )
        connection.execute(
            text("INSERT INTO membership_roles(tenant_id,membership_id,role_id) VALUES (:t,:m,:r)"),
            {
                "t": ids["tenant_a"],
                "m": ids["reader_membership"],
                "r": ids["reader_role"],
            },
        )
        connection.execute(
            text("INSERT INTO membership_roles(tenant_id,membership_id,role_id) VALUES (:t,:m,:r)"),
            {
                "t": ids["tenant_a"],
                "m": ids["limited_membership"],
                "r": ids["limited_role"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) VALUES (:t,:r,'dossier.read'),(:t,:r,'task.read')"
            ),
            {"t": ids["tenant_a"], "r": ids["reader_role"]},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) SELECT :t,:r,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"t": ids["tenant_a"], "r": ids["role"]},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) SELECT :t,:r,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"t": ids["tenant_a"], "r": ids["limited_role"]},
        )
    engine.dispose()
    yield app, ids, password
    Redis.from_url(redis_url).flushdb()
    with app.app_context():
        downgrade(directory=migrations, revision="base")


def test_global_product_read_models_enforce_dossier_scope(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, password = oracle_stack
    owner = _client(oracle_stack)
    allowed = _create_dossier(owner, ids, "Portfolio permitido")
    forbidden = _create_dossier(owner, ids, "Portfolio restringido")

    reader_user, reader_membership, reader_role = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    email = f"portfolio-reader-{reader_user}@example.test"
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users(id,email,display_name,password_hash,status,email_verified_at,created_at,updated_at) "
                "VALUES (:id,:email,'Portfolio Reader',:password,'active',now(),now(),now())"
            ),
            {
                "id": reader_user,
                "email": email,
                "password": PasswordHasher().hash(password),
            },
        )
        connection.execute(
            text(
                "INSERT INTO tenant_memberships(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (:id,:tenant,:user,'active',now(),'{}',now(),now())"
            ),
            {"id": reader_membership, "tenant": ids["tenant_a"], "user": reader_user},
        )
        connection.execute(
            text(
                "INSERT INTO roles(id,tenant_id,key,name,description,is_system,created_at,updated_at) "
                "VALUES (:id,:tenant,:key,'Portfolio reader','Read models',false,now(),now())"
            ),
            {
                "id": reader_role,
                "tenant": ids["tenant_a"],
                "key": f"portfolio_reader_{reader_role.hex[:20]}",
            },
        )
        connection.execute(
            text(
                "INSERT INTO membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role)"
            ),
            {
                "tenant": ids["tenant_a"],
                "membership": reader_membership,
                "role": reader_role,
            },
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :tenant,:role,key FROM permissions WHERE key = ANY(:keys)"
            ),
            {
                "tenant": ids["tenant_a"],
                "role": reader_role,
                "keys": [
                    "dossier.read",
                    "signal.read",
                    "opportunity.read",
                    "risk.read",
                    "actor.read",
                    "meeting.read",
                    "task.read",
                ],
            },
        )
    engine.dispose()
    assert (
        owner.put(
            f"/api/v1/dossiers/{allowed['id']}/collaborators/{reader_user}",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 200
    )

    def create_nested(dossier_id: str, resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = owner.post(
            f"/api/v1/dossiers/{dossier_id}/{resource}",
            json=payload,
            headers={"X-CSRF-Token": _csrf(owner)},
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()

    opportunity = create_nested(
        allowed["id"],
        "opportunities",
        {"title": "Oportunidad visible", "strategic_fit": 90, "confidence": 80},
    )
    create_nested(
        forbidden["id"],
        "opportunities",
        {"title": "Oportunidad privada", "strategic_fit": 95, "confidence": 90},
    )
    for dossier, title in ((allowed, "Riesgo visible"), (forbidden, "Riesgo privado")):
        create_nested(
            dossier["id"],
            "risks",
            {"title": title, "impact": 85, "likelihood": 70, "confidence": 80},
        )
    for dossier, title in ((allowed, "Reunión visible"), (forbidden, "Reunión privada")):
        create_nested(
            dossier["id"],
            "meetings",
            {"title": title, "scheduled_at": "2026-07-20T09:00:00+00:00"},
        )
    task = create_nested(
        allowed["id"], "tasks", {"title": "Tarea visible", "due_date": "2026-07-18"}
    )
    private_task = create_nested(
        forbidden["id"], "tasks", {"title": "Tarea privada", "due_date": "2026-07-17"}
    )
    for row in (task, private_task):
        assert (
            owner.patch(
                f"/api/v1/tasks/{row['id']}",
                json={"status": "in_progress"},
                headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
            ).status_code
            == 200
        )

    actors: list[dict[str, Any]] = []
    for name, dossier in (
        ("Actor visible portfolio", allowed),
        ("Actor privado portfolio", forbidden),
    ):
        actor_response = owner.post(
            "/api/v1/actors",
            json={"canonical_name": name, "actor_type": "organization"},
            headers={"X-CSRF-Token": _csrf(owner)},
        )
        assert actor_response.status_code == 201
        actor = actor_response.get_json()
        actors.append(actor)
        assert (
            owner.post(
                f"/api/v1/dossiers/{dossier['id']}/actors",
                json={"actor_id": actor["id"]},
                headers={"X-CSRF-Token": _csrf(owner)},
            ).status_code
            == 201
        )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        for number, (dossier, title) in enumerate(
            ((allowed, "Señal visible portfolio"), (forbidden, "Señal privada portfolio")),
            start=1,
        ):
            signal_id, link_id = uuid.uuid4(), uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO signals(id,tenant_id,provider,external_id,title,summary,source_type,source_name,published_at,ingested_at,tags,entities,categories,raw_hash,credibility,raw_payload,created_at,updated_at) "
                    "VALUES (:id,:tenant,'synthetic',:external,:title,'Resumen','news','Fuente',now(),now(),'[]','[]','[]',:hash,80,'{}',now(),now())"
                ),
                {
                    "id": signal_id,
                    "tenant": ids["tenant_a"],
                    "external": f"portfolio-{number}-{signal_id}",
                    "title": title,
                    "hash": hashlib.sha256(str(signal_id).encode()).digest(),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,overall_score,score_details,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) "
                    "VALUES (:id,:tenant,:dossier,:signal,'new',80,70,75,85,79,'{}','Importa','Revisar','{}',1,now(),now())"
                ),
                {
                    "id": link_id,
                    "tenant": ids["tenant_a"],
                    "dossier": uuid.UUID(dossier["id"]),
                    "signal": signal_id,
                },
            )
    engine.dispose()

    reader = _client_as(oracle_stack, email)
    expected = {
        "/api/v1/signals": "Señal visible portfolio",
        "/api/v1/opportunities": opportunity["title"],
        "/api/v1/risks": "Riesgo visible",
        "/api/v1/meetings": "Reunión visible",
        "/api/v1/tasks": "Tarea visible",
    }
    for path, title in expected.items():
        response = reader.get(path)
        assert response.status_code == 200, response.get_json()
        body = response.get_json()
        assert body["meta"]["total"] == 1
        assert body["included"]["dossiers"] == [
            {"id": allowed["id"], "title": allowed["title"], "status": "draft"}
        ]
        item = body["data"][0]
        assert (item["signal"]["title"] if path.endswith("signals") else item["title"]) == title

    actor_list = reader.get("/api/v1/actors").get_json()
    assert actor_list["meta"]["total"] == 1
    assert actor_list["data"][0]["id"] == actors[0]["id"]
    assert reader.get(f"/api/v1/actors/{actors[1]['id']}").status_code == 404

    search = reader.get("/api/v1/search?q=visible&types=actors,signals,opportunities&limit=3")
    assert search.status_code == 200
    search_groups = search.get_json()["groups"]
    assert {item["id"] for item in search_groups["actors"]} == {actors[0]["id"]}
    assert len(search_groups["signals"]) == len(search_groups["opportunities"]) == 1
    private_search = reader.get(
        "/api/v1/search?q=privada&types=actors,signals,opportunities&limit=3"
    ).get_json()["groups"]
    assert all(not items for items in private_search.values())
    assert reader.get("/api/v1/search?q=x").status_code == 422

    home = reader.get("/api/v1/home")
    assert home.status_code == 200
    home_body = home.get_json()
    assert home_body["dossier_total"] == 1
    assert {metric["key"]: metric["count"] for metric in home_body["metrics"]} == {
        "dossiers": 0,
        "signals": 1,
        "opportunities": 1,
        "risks": 1,
        "meetings": 1,
        "tasks": 1,
    }
    assert {item["dossier_id"] for item in home_body["attention"]} == {allowed["id"]}

    changes = reader.get("/api/v1/changes")
    assert changes.status_code == 200
    change_body = changes.get_json()
    assert change_body["meta"] == {
        "page": 1,
        "size": 10,
        "total": 1,
        "review_supported": False,
    }
    assert change_body["data"][0]["resource_id"] == task["id"]
    assert change_body["data"][0]["to_status"] == "in_progress"
    assert (
        reader.get(f"/api/v1/changes?filter[dossier_id]={forbidden['id']}").get_json()["meta"][
            "total"
        ]
        == 0
    )
    assert reader.get("/api/v1/tasks?filter[dossier_id]=invalid").status_code == 422


def test_document_upload_process_search_evidence_reprocess_and_delete(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "documents")

    class CleanScanner:
        def scan(self, source: Any) -> Any:
            from opn_oracle.documents.scanner import ScanResult

            source.read(1)
            return ScanResult("clean", "test-clean")

    app.extensions["malware_scanner"] = CleanScanner()
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Expediente documental")
    rejected = client.post(
        f"/api/v1/dossiers/{dossier['id']}/documents",
        data={"file": (io.BytesIO(b"MZ\x00binary"), "spoof.txt", "text/plain")},
        headers={"X-CSRF-Token": _csrf(client)},
        content_type="multipart/form-data",
    )
    assert rejected.status_code == 422
    uploaded = client.post(
        f"/api/v1/dossiers/{dossier['id']}/documents",
        data={
            "classification": "internal",
            "file": (
                io.BytesIO(
                    "Alianza estratégica confirmada. Próximo hito verificable en septiembre.".encode()
                ),
                "../nota estratégica.txt",
                "text/plain",
            ),
        },
        headers={"X-CSRF-Token": _csrf(client)},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 202, uploaded.get_json()
    document = uploaded.get_json()["document"]
    detail = client.get(f"/api/v1/documents/{document['id']}")
    assert detail.status_code == 200 and detail.get_json()["status"] == "ready"
    assert detail.get_json()["filename"] == "nota estratégica.txt"
    downloaded = client.get(f"/api/v1/documents/{document['id']}/download")
    assert downloaded.status_code == 200
    assert "Alianza estratégica" in downloaded.data.decode()
    search = client.get(f"/api/v1/dossiers/{dossier['id']}/search?q=alianza")
    assert search.status_code == 200 and len(search.get_json()["items"]) == 1
    result = search.get_json()["items"][0]
    evidence = client.post(
        f"/api/v1/documents/{document['id']}/create-evidence",
        json={"chunk_id": result["chunk_id"], "start": 0, "end": 20},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert evidence.status_code == 201
    source = client.get(f"/api/v1/evidence/{evidence.get_json()['id']}")
    assert source.status_code == 200 and source.get_json()["document_id"] == document["id"]
    old_evidence_id = evidence.get_json()["id"]
    reprocess = client.post(
        f"/api/v1/documents/{document['id']}/reprocess",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert reprocess.status_code == 202
    assert reprocess.get_json()["document"]["version"] == 2
    assert client.get(f"/api/v1/evidence/{old_evidence_id}").status_code == 200
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        jobs = list(
            db.session.scalars(
                select(BackgroundJob)
                .where(
                    BackgroundJob.resource_id == uuid.UUID(document["id"]),
                    BackgroundJob.job_type == "oracle.document.process",
                )
                .order_by(BackgroundJob.created_at)
            )
        )
        assert len(jobs) == 2
        stale = process_document(
            uuid.UUID(document["id"]), uuid.UUID(document["current_version_id"]), jobs[0]
        )
        assert stale == {
            "ignored": True,
            "reason": "superseded_version",
            "version_id": document["current_version_id"],
        }
        current = db.session.get(Document, uuid.UUID(document["id"]))
        assert current is not None
        current.status = "queued"
        current.scan_status = "pending"
        db.session.commit()
    assert client.get(f"/api/v1/documents/{document['id']}/download").status_code == 404
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        current = db.session.get(Document, uuid.UUID(document["id"]))
        assert current is not None
        current.status = "ready"
        current.scan_status = "clean"
        db.session.commit()
    removed = client.delete(
        f"/api/v1/documents/{document['id']}",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert removed.status_code == 204
    assert client.get(f"/api/v1/documents/{document['id']}").status_code == 404


def test_document_quota_is_serialized_across_sessions(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    storage = LocalObjectStorage(tmp_path / "quota")
    app.extensions["object_storage"] = storage
    old_quota = app.config["DOCUMENT_TENANT_QUOTA_BYTES"]
    app.config["DOCUMENT_TENANT_QUOTA_BYTES"] = 10
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Cuota concurrente")

    barrier = threading.Barrier(2)

    def upload(number: int) -> str:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            barrier.wait(timeout=5)
            try:
                create_upload(
                    tenant_id=ids["tenant_a"],
                    dossier_id=uuid.UUID(dossier["id"]),
                    uploader_id=ids["user"],
                    filename=f"quota-{number}.txt",
                    media_type="text/plain",
                    source=io.BytesIO(b"123456"),
                    classification="internal",
                )
                db.session.commit()
                return "stored"
            except DocumentError:
                db.session.rollback()
                return "rejected"
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(upload, (1, 2)))
    app.config["DOCUMENT_TENANT_QUOTA_BYTES"] = old_quota
    assert outcomes == ["rejected", "stored"]


def test_document_purge_legal_hold_and_orphan_reconciliation(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    storage = LocalObjectStorage(tmp_path / "retention")
    app.extensions["object_storage"] = storage
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Retención")
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        document, _ = create_upload(
            tenant_id=ids["tenant_a"],
            dossier_id=uuid.UUID(dossier["id"]),
            uploader_id=ids["user"],
            filename="retention.txt",
            media_type="text/plain",
            source=io.BytesIO(b"retention"),
            classification="internal",
        )
        document.status = "deleted"
        document.deleted_at = datetime.now(UTC)
        document.purge_after = datetime.now(UTC) - timedelta(seconds=1)
        document.legal_hold = True
        db.session.commit()
        assert purge_due_documents(ids["tenant_a"]) == 0
        assert storage.get(document.storage_key).read() == b"retention"
        document.legal_hold = False
        db.session.commit()
        assert purge_due_documents(ids["tenant_a"]) == 1
        with pytest.raises(StorageError):
            storage.get(document.storage_key)
        orphan_id = uuid.uuid4()
        orphan_key = object_key(ids["tenant_a"], uuid.UUID(dossier["id"]), orphan_id)
        storage.put(orphan_key, io.BytesIO(b"orphan"), max_bytes=10, media_type="text/plain")
        orphan_path = tmp_path / "retention" / orphan_key
        old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
        os.utime(orphan_path, (old, old))
        assert reconcile_storage_orphans(ids["tenant_a"]) == 1
        with pytest.raises(StorageError):
            storage.get(orphan_key)


def test_document_job_survives_broker_publish_failure(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "broker")
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Fallo de broker")
    task = app.extensions["celery"].tasks["oracle.document.process"]
    original = task.apply_async

    def fail_publish(*args: Any, **kwargs: Any) -> None:
        raise OSError("broker down")

    monkeypatch.setattr(task, "apply_async", fail_publish)
    response = client.post(
        f"/api/v1/dossiers/{dossier['id']}/documents",
        data={"file": (io.BytesIO(b"durable document"), "durable.txt", "text/plain")},
        headers={"X-CSRF-Token": _csrf(client)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    job_id = uuid.UUID(response.get_json()["job_id"])
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        job = db.session.get(BackgroundJob, job_id)
        assert job is not None and job.stage == "publish_pending"
    monkeypatch.setattr(task, "apply_async", original)
    with app.app_context():
        assert dispatch_queued_jobs.run() >= 1
    assert (
        client.get(f"/api/v1/documents/{response.get_json()['document']['id']}").status_code == 200
    )


def test_two_document_workers_fence_same_version(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    storage = LocalObjectStorage(tmp_path / "fencing")
    app.extensions["object_storage"] = storage
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Fencing documental")
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        document, version = create_upload(
            tenant_id=ids["tenant_a"],
            dossier_id=uuid.UUID(dossier["id"]),
            uploader_id=ids["user"],
            filename="fence.txt",
            media_type="text/plain",
            source=io.BytesIO(b"contenido concurrente trazable"),
            classification="internal",
        )
        jobs = [
            stage_job(
                "oracle.document.process",
                payload={"document_id": str(document.id), "version_id": str(version.id)},
                idempotency_key=f"fence-document-{number}-{document.id}",
                requested_by_user_id=ids["user"],
                dossier_id=uuid.UUID(dossier["id"]),
                resource_type="document",
                resource_id=document.id,
            )
            for number in (1, 2)
        ]
        document_id, version_id = document.id, version.id
        job_ids = [job.id for job in jobs]
        db.session.commit()
    barrier = threading.Barrier(2)

    class BlockingScanner:
        def scan(self, source: Any) -> Any:
            from opn_oracle.documents.scanner import ScanResult

            source.read(1)
            barrier.wait(timeout=5)
            return ScanResult("clean", "blocking-test")

    app.extensions["malware_scanner"] = BlockingScanner()

    def run(job_id: uuid.UUID) -> dict[str, Any]:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            job = db.session.get(BackgroundJob, job_id)
            assert job is not None
            result = process_document(document_id, version_id, job)
            db.session.remove()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, job_ids))
    assert sum(result.get("chunks", 0) > 0 for result in results) == 1
    assert sum(result.get("reason") == "lost_fence" for result in results) == 1


def test_document_endpoints_are_cross_tenant_invisible(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, password = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "cross-tenant")

    class CleanScanner:
        def scan(self, source: Any) -> Any:
            from opn_oracle.documents.scanner import ScanResult

            return ScanResult("clean", "cross-tenant-test")

    app.extensions["malware_scanner"] = CleanScanner()
    client_a = _client(oracle_stack)
    dossier = _create_dossier(client_a, ids, "Documento privado tenant A")
    uploaded = client_a.post(
        f"/api/v1/dossiers/{dossier['id']}/documents",
        data={"file": (io.BytesIO(b"secreto tenant alfa"), "private.txt", "text/plain")},
        headers={"X-CSRF-Token": _csrf(client_a)},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 202
    document_id = uploaded.get_json()["document"]["id"]
    found = client_a.get(f"/api/v1/dossiers/{dossier['id']}/search?q=secreto").get_json()["items"][
        0
    ]
    evidence = client_a.post(
        f"/api/v1/documents/{document_id}/create-evidence",
        json={"chunk_id": found["chunk_id"], "start": 0, "end": 7},
        headers={"X-CSRF-Token": _csrf(client_a)},
    ).get_json()

    membership_b, role_b = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenant_memberships(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                "VALUES (:m,:t,:u,'active',now(),'{}',now(),now())"
            ),
            {"m": membership_b, "t": ids["tenant_b"], "u": ids["user"]},
        )
        connection.execute(
            text(
                "INSERT INTO roles(id,tenant_id,key,name,description,is_system,created_at,updated_at) "
                "VALUES (:r,:t,'owner','Owner B','Owner B',true,now(),now())"
            ),
            {"r": role_b, "t": ids["tenant_b"]},
        )
        connection.execute(
            text("INSERT INTO membership_roles(tenant_id,membership_id,role_id) VALUES (:t,:m,:r)"),
            {"t": ids["tenant_b"], "m": membership_b, "r": role_b},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :t,:r,key FROM permissions"
            ),
            {"t": ids["tenant_b"], "r": role_b},
        )
    engine.dispose()
    client_b = app.test_client()
    login = client_b.post(
        "/api/v1/auth/login",
        json={
            "email": "domain-owner@example.test",
            "password": password,
            "tenant_id": str(ids["tenant_b"]),
        },
        headers={"X-CSRF-Token": _csrf(client_b)},
    )
    assert login.status_code == 200
    assert client_b.get(f"/api/v1/documents/{document_id}").status_code == 404
    assert client_b.get(f"/api/v1/documents/{document_id}/download").status_code == 404
    assert client_b.get(f"/api/v1/dossiers/{dossier['id']}/search?q=secreto").status_code == 404
    assert client_b.get("/api/v1/documents/search?q=secreto").get_json()["items"] == []
    assert client_b.get(f"/api/v1/documents/evidence/{evidence['id']}").status_code == 404
    assert client_b.get(f"/api/v1/evidence/{evidence['id']}").status_code == 404
    assert (
        client_b.post(
            f"/api/v1/documents/{document_id}/create-evidence",
            json={"chunk_id": found["chunk_id"], "start": 0, "end": 2},
            headers={"X-CSRF-Token": _csrf(client_b)},
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            f"/api/v1/documents/{document_id}/reprocess",
            headers={"X-CSRF-Token": _csrf(client_b)},
        ).status_code
        == 404
    )
    assert (
        client_b.delete(
            f"/api/v1/documents/{document_id}",
            headers={"X-CSRF-Token": _csrf(client_b)},
        ).status_code
        == 404
    )


def test_expired_document_lease_fences_blocked_worker_and_recovers_retry(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "lease-expiry")
    dossier = _create_dossier(_client(oracle_stack), ids, "Lease documental")
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        document, version = create_upload(
            tenant_id=ids["tenant_a"],
            dossier_id=uuid.UUID(dossier["id"]),
            uploader_id=ids["user"],
            filename="blocked.txt",
            media_type="text/plain",
            source=io.BytesIO(b"worker bloqueado no debe publicar chunks"),
            classification="internal",
        )
        job = stage_job(
            "oracle.document.process",
            payload={"document_id": str(document.id), "version_id": str(version.id)},
            idempotency_key=f"blocked-lease-{document.id}",
            requested_by_user_id=ids["user"],
            dossier_id=uuid.UUID(dossier["id"]),
            resource_type="document",
            resource_id=document.id,
        )
        document_id, version_id, job_id = document.id, version.id, job.id
        db.session.commit()
    entered, release = threading.Event(), threading.Event()

    class BlockedScanner:
        def scan(self, source: Any) -> Any:
            from opn_oracle.documents.scanner import ScanResult

            entered.set()
            assert release.wait(timeout=10)
            return ScanResult("clean", "blocked-test")

    app.extensions["malware_scanner"] = BlockedScanner()

    def run_worker() -> dict[str, Any]:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            current_job = db.session.get(BackgroundJob, job_id)
            assert current_job is not None
            return process_document(document_id, version_id, current_job)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_worker)
        assert entered.wait(timeout=10)
        advanced = datetime.now(UTC) + timedelta(minutes=10)
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            attempt = db.session.scalar(
                select(DocumentProcessingAttempt).where(
                    DocumentProcessingAttempt.background_job_id == job_id
                )
            )
            assert attempt is not None
            attempt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.session.commit()
            assert recover_expired_document_attempts(ids["tenant_a"], now=advanced) == 1
            retry_job = db.session.scalar(
                select(BackgroundJob).where(
                    BackgroundJob.idempotency_key == f"document-recovery-{attempt.id}"
                )
            )
            assert retry_job is not None and retry_job.status == "queued"
            retry_job_id = retry_job.id
        release.set()
        result = future.result(timeout=10)
    assert result == {"ignored": True, "reason": "lost_or_expired_lease"}
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        count = db.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == version_id)
        )
        version = db.session.get(DocumentVersion, version_id)
        attempt = db.session.scalar(
            select(DocumentProcessingAttempt).where(
                DocumentProcessingAttempt.background_job_id == job_id
            )
        )
        assert count == 0
        assert version is not None and version.status == "queued"
        assert version.processing_token is None
        assert attempt is not None and attempt.status == "abandoned"
        retry_job = db.session.get(BackgroundJob, retry_job_id)
        assert retry_job is not None
        retry_result = process_document(document_id, version_id, retry_job)
        assert retry_result["chunks"] > 0
        assert db.session.get(DocumentVersion, version_id).status == "ready"
        attempts = list(
            db.session.scalars(
                select(DocumentProcessingAttempt)
                .where(DocumentProcessingAttempt.document_version_id == version_id)
                .order_by(DocumentProcessingAttempt.attempt_number)
            )
        )
        assert [item.status for item in attempts] == ["abandoned", "succeeded"]
        assert attempts[0].execution_token != attempts[1].execution_token


@pytest.fixture(autouse=True)
def clean_sessions(oracle_stack: tuple[Any, dict[str, uuid.UUID], str]) -> None:
    Redis.from_url(os.environ["TEST_REDIS_URL"]).flushdb()


def _csrf(client: Any) -> str:
    return str(client.get("/api/v1/auth/csrf").get_json()["csrf_token"])


def _client(stack: tuple[Any, dict[str, uuid.UUID], str]) -> Any:
    return _client_as(stack, "domain-owner@example.test")


def _client_as(stack: tuple[Any, dict[str, uuid.UUID], str], email: str) -> Any:
    app, ids, password = stack
    client = app.test_client()
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "tenant_id": str(ids["tenant_a"]),
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 200
    return client


def _create_dossier(client: Any, ids: dict[str, uuid.UUID], title: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/dossiers",
        json={
            "workspace_id": str(ids["workspace_a"]),
            "title": title,
            "type": "project",
            "strategic_goal": "Validar siguiente acción",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    return response.get_json()


def _enable_mock_ai(app: Any, ids: dict[str, uuid.UUID]) -> None:
    app.config.update(AI_ENABLED=True, AI_MODE="mock")
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        policy = db.session.scalar(
            select(AITenantPolicy).where(AITenantPolicy.tenant_id == ids["tenant_a"])
        )
        if policy is None:
            policy = AITenantPolicy(
                tenant_id=ids["tenant_a"],
                enabled=True,
                provider="mock",
                allowed_models=[],
                max_classification="internal",
                monthly_soft_budget_micros=0,
                monthly_hard_budget_micros=0,
                daily_call_limit=0,
                max_concurrency=4,
                max_context_tokens=8000,
                max_output_tokens=4000,
                kill_switch=False,
                redaction_profile={},
            )
            db.session.add(policy)
        else:
            policy.enabled = True
            policy.provider = "mock"
            policy.max_classification = "internal"
            policy.kill_switch = False
        db.session.commit()


def test_dossier_create_uses_active_default_workspace(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    response = client.post(
        "/api/v1/dossiers",
        json={
            "title": "Expediente sin selector de workspace",
            "type": "project",
            "strategic_goal": "Comprobar el workspace predeterminado",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    assert response.get_json()["workspace_id"] == str(ids["workspace_a"])


def test_dossier_creation_can_apply_an_editable_type_specific_starter_profile(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    response = client.post(
        "/api/v1/dossiers",
        json={
            "workspace_id": str(ids["workspace_a"]),
            "title": "Convocatoria de transición",
            "type": "tender_or_grant",
            "strategic_goal": "Presentar una propuesta sólida antes del plazo.",
            "create_starter_profile": True,
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert response.status_code == 201
    dossier_id = response.get_json()["id"]

    objectives = client.get(f"/api/v1/dossiers/{dossier_id}/objectives").get_json()["data"]
    hypotheses = client.get(f"/api/v1/dossiers/{dossier_id}/hypotheses").get_json()["data"]
    watchlists = client.get(f"/api/v1/dossiers/{dossier_id}/watchlists").get_json()["data"]

    assert [row["title"] for row in objectives] == ["Preparar una respuesta competitiva y conforme"]
    assert len(hypotheses) == 2
    assert watchlists[0]["name"] == "Vigilancia inicial"
    assert watchlists[0]["query_config"] == {
        "profile_version": "v1",
        "dossier_type": "tender_or_grant",
        "keywords": ["Convocatoria de transición"],
        "source_types": [
            "tender_or_grant",
            "official_publication",
            "company_signal",
            "relationship_signal",
            "risk_signal",
        ],
        "requires_review": True,
    }
    assert (
        client.get(
            f"/api/v1/dossiers/{dossier_id}/watchlists/{watchlists[0]['id']}/monitors"
        ).status_code
        == 200
    )

    invalid = client.post(
        "/api/v1/dossiers",
        json={
            "title": "Tipo no booleano",
            "type": "project",
            "create_starter_profile": "yes",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert invalid.status_code == 422


def test_dossier_crud_filters_concurrency_archive_and_idor(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Expediente API")
    listed = client.get(
        "/api/v1/dossiers?page[number]=1&page[size]=10&sort=title&filter[search]=Expediente"
    )
    assert listed.status_code == 200 and listed.get_json()["meta"]["total"] >= 1
    assert client.get("/api/v1/dossiers?page[size]=101").status_code == 422
    selected = client.get(
        f"/api/v1/dossiers?filter[selected_ids]={dossier['id']}&filter[type]=project"
    )
    assert selected.status_code == 200 and selected.get_json()["meta"]["total"] == 1
    assert client.get("/api/v1/dossiers?filter[owner]=not-a-uuid").status_code == 422
    assert client.get("/api/v1/dossiers?filter[date_from]=not-a-date").status_code == 422
    patched = client.patch(
        f"/api/v1/dossiers/{dossier['id']}",
        json={"version": 1, "status": "active"},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert patched.status_code == 200 and patched.get_json()["version"] == 2
    conflict = client.patch(
        f"/api/v1/dossiers/{dossier['id']}",
        json={"title": "Stale"},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert conflict.status_code == 409
    archived = client.post(
        f"/api/v1/dossiers/{dossier['id']}/archive",
        json={"version": 2},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"2"'},
    )
    assert archived.status_code == 200 and archived.get_json()["status"] == "archived"
    other = uuid.uuid4()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO strategic_dossiers(id,tenant_id,workspace_id,title,description,dossier_type,status,strategic_goal,geography,sectors,languages,scoring_config,health_score,opportunity_score,risk_score,score_explanation,version,synthetic_data,created_at,updated_at) VALUES (:id,:t,:w,'Otro tenant','','project','active','','[]','[]','[]','{}',0,0,0,'{}',1,false,now(),now())"
            ),
            {"id": other, "t": ids["tenant_b"], "w": ids["workspace_b"]},
        )
    engine.dispose()
    assert client.get(f"/api/v1/dossiers/{other}").status_code == 404


def test_bulk_dossier_delete_is_atomic_scoped_and_keeps_audit_trail(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    owner = _client(oracle_stack)
    first = _create_dossier(owner, ids, "Eliminar uno")
    second = _create_dossier(owner, ids, "Eliminar dos")
    ids_to_delete = [first["id"], second["id"]]

    deleted = owner.post(
        "/api/v1/dossiers/bulk-delete",
        json={"dossier_ids": ids_to_delete},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert deleted.status_code == 200, deleted.get_json()
    assert set(deleted.get_json()["deleted_ids"]) == set(ids_to_delete)
    assert deleted.get_json()["deleted_count"] == 2
    assert all(
        owner.get(f"/api/v1/dossiers/{dossier_id}").status_code == 404
        for dossier_id in ids_to_delete
    )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as connection:
        audit_rows = (
            connection.execute(
                text(
                    "SELECT tenant_id, dossier_id, resource_id, metadata->>'deleted_dossier_id' AS deleted_id "
                    "FROM audit_events WHERE action='dossier.deleted' AND resource_id = ANY(:ids)"
                ).bindparams(ids=ids_to_delete)
            )
            .mappings()
            .all()
        )
    engine.dispose()
    assert {str(row["resource_id"]) for row in audit_rows} == set(ids_to_delete)
    assert all(
        row["tenant_id"] == ids["tenant_a"] and row["dossier_id"] is None for row in audit_rows
    )
    assert {row["deleted_id"] for row in audit_rows} == set(ids_to_delete)

    unavailable = _create_dossier(owner, ids, "No borrar parcialmente")
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    denied = limited.post(
        "/api/v1/dossiers/bulk-delete",
        json={"dossier_ids": [unavailable["id"]]},
        headers={"X-CSRF-Token": _csrf(limited)},
    )
    assert denied.status_code == 404
    assert owner.get(f"/api/v1/dossiers/{unavailable['id']}").status_code == 200

    invalid = owner.post(
        "/api/v1/dossiers/bulk-delete",
        json={"dossier_ids": [unavailable["id"], unavailable["id"]]},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert invalid.status_code == 422


def test_signal_many_to_many_review_promote_idempotency_and_audit(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    one, two = (
        _create_dossier(client, ids, "Dossier señal uno"),
        _create_dossier(client, ids, "Dossier señal dos"),
    )
    signal_id, link_one, link_two = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO signals(id,tenant_id,provider,external_id,title,summary,source_type,source_name,ingested_at,tags,entities,categories,raw_hash,credibility,raw_payload,created_at,updated_at) VALUES (:id,:t,'synthetic','shared','Señal compartida','','report','Fuente',now(),'[]','[]','[]',:hash,80,'{}',now(),now())"
            ),
            {"id": signal_id, "t": ids["tenant_a"], "hash": hashlib.sha256(b"shared").digest()},
        )
        for link, dossier in ((link_one, one["id"]), (link_two, two["id"])):
            connection.execute(
                text(
                    "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) VALUES (:id,:t,:d,:s,'new',0,0,0,0,'','','{}',1,now(),now())"
                ),
                {"id": link, "t": ids["tenant_a"], "d": uuid.UUID(dossier), "s": signal_id},
            )
    engine.dispose()
    missing_version = client.post(
        f"/api/v1/signals/{link_one}/review",
        json={"relevance": 50},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert missing_version.status_code == 422
    invalid_review = client.post(
        f"/api/v1/signals/{link_one}/review",
        json={"version": 1, "relevance": "alta"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert invalid_review.status_code == 422
    review = client.post(
        f"/api/v1/signals/{link_one}/review",
        json={
            "version": 1,
            "relevance": 80,
            "novelty": 70,
            "confidence": 75,
            "strategic_impact": 85,
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert review.status_code == 200 and review.get_json()["status"] == "reviewed"
    invalid_promotion = client.post(
        f"/api/v1/signals/{link_one}/promote",
        json={"kind": "opportunity", "title": "Inválida", "strategic_fit": 101},
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": "promote-invalid"},
    )
    assert invalid_promotion.status_code == 422
    payload = {
        "kind": "opportunity",
        "title": "Oportunidad promovida",
        "strategic_fit": 80,
        "urgency": 70,
        "expected_value": 75,
        "actionability": 65,
        "relationship_leverage": 60,
        "timing": 70,
        "confidence": 75,
        "effort": 30,
        "blocking_risk": 20,
    }
    first = client.post(
        f"/api/v1/signals/{link_one}/promote",
        json=payload,
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": "promote-one"},
    )
    retry = client.post(
        f"/api/v1/signals/{link_one}/promote",
        json=payload,
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": "promote-one"},
    )
    assert first.status_code == retry.status_code == 200
    assert first.get_json()["resource"]["id"] == retry.get_json()["resource"]["id"]
    unauthorized_client = _client_as(oracle_stack, "domain-limited@example.test")
    unauthorized = unauthorized_client.post(
        f"/api/v1/signals/{link_one}/promote",
        json=payload,
        headers={
            "X-CSRF-Token": _csrf(unauthorized_client),
            "Idempotency-Key": "promote-one",
        },
    )
    assert unauthorized.status_code == 404
    changed = client.post(
        f"/api/v1/signals/{link_one}/promote",
        json=payload | {"title": "Otro"},
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": "promote-one"},
    )
    assert changed.status_code == 409
    assert client.get(f"/api/v1/dossiers/{one['id']}/audit").status_code == 200
    untouched = client.get(f"/api/v1/dossiers/{two['id']}/signals").get_json()["data"][0]["link"]
    assert untouched["status"] == "new"


def test_nested_api_seed_idempotency_and_listing_performance(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = oracle_stack
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Dossier recursos")
    created = client.post(
        f"/api/v1/dossiers/{dossier['id']}/tasks",
        json={"title": "Preparar validación", "priority": "high"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert created.status_code == 201
    assert client.get(f"/api/v1/dossiers/{dossier['id']}/tasks").status_code == 200
    runner = app.test_cli_runner()
    first = runner.invoke(args=["seed-oracle-demo", "--tenant-id", str(ids["tenant_a"])])
    second = runner.invoke(args=["seed-oracle-demo", "--tenant-id", str(ids["tenant_a"])])
    assert first.exit_code == second.exit_code == 0
    repaired_hypothesis = stable_id(f"{ids['tenant_a']}:hypothesis:expansion-regional")
    repair_engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with repair_engine.begin() as connection:
        connection.execute(text("DELETE FROM hypotheses WHERE id=:id"), {"id": repaired_hypothesis})
    repair_engine.dispose()
    repaired = runner.invoke(args=["seed-oracle-demo", "--tenant-id", str(ids["tenant_a"])])
    assert repaired.exit_code == 0
    started = time.perf_counter()
    response = client.get("/api/v1/dossiers?page[number]=1&page[size]=100&sort=-updated_at")
    assert response.status_code == 200 and time.perf_counter() - started < 2.0
    assert sum(1 for row in response.get_json()["data"] if row["synthetic_data"]) == 8
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as connection:
        counts = {
            table: connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": ids["tenant_a"]},
            ).scalar_one()
            for table in (
                "dossier_objectives",
                "hypotheses",
                "watchlists",
                "dossier_signals",
                "dossier_actors",
                "meetings",
                "decisions",
                "tasks",
                "insights",
                "score_history",
            )
        }
        assert (
            connection.execute(
                text("SELECT count(*) FROM hypotheses WHERE id=:id"),
                {"id": repaired_hypothesis},
            ).scalar_one()
            == 1
        )
    engine.dispose()
    runtime = create_engine(os.environ["TEST_RUNTIME_DATABASE_URL"])
    with runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(ids["tenant_b"])},
        )
        for table in ("dossier_signals", "opportunities", "actors", "evidence", "score_history"):
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant_a"),
                    {"tenant_a": ids["tenant_a"]},
                ).scalar_one()
                == 0
            )
    runtime.dispose()
    assert all(count >= 8 for count in counts.values())


def test_resource_policy_membership_and_archived_child_guard(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    owner = _client(oracle_stack)
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    dossier = _create_dossier(owner, ids, "Expediente privado")
    dossier_id = dossier["id"]
    assert limited.get(f"/api/v1/dossiers/{dossier_id}").status_code == 404
    assert all(
        row["id"] != dossier_id for row in limited.get("/api/v1/dossiers").get_json()["data"]
    )
    assert (
        limited.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "No autorizada"},
            headers={"X-CSRF-Token": _csrf(limited)},
        ).status_code
        == 404
    )
    viewer = owner.put(
        f"/api/v1/dossiers/{dossier_id}/collaborators/{ids['limited_user']}",
        json={"role": "viewer"},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert viewer.status_code == 200
    assert limited.get(f"/api/v1/dossiers/{dossier_id}").status_code == 200
    assert (
        limited.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "Sigue sin escritura"},
            headers={"X-CSRF-Token": _csrf(limited)},
        ).status_code
        == 404
    )
    editor = owner.put(
        f"/api/v1/dossiers/{dossier_id}/collaborators/{ids['limited_user']}",
        json={"role": "editor"},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert editor.status_code == 200
    assert (
        limited.put(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{ids['reader_user']}",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": _csrf(limited)},
        ).status_code
        == 404
    )
    reader_link = owner.put(
        f"/api/v1/dossiers/{dossier_id}/collaborators/{ids['reader_user']}",
        json={"role": "viewer"},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert reader_link.status_code == 200
    reader = _client_as(oracle_stack, "domain-reader@example.test")
    assert reader.get(f"/api/v1/dossiers/{dossier_id}").status_code == 200
    assert (
        reader.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "Sin permiso RBAC"},
            headers={"X-CSRF-Token": _csrf(reader)},
        ).status_code
        == 403
    )
    assert (
        limited.patch(
            f"/api/v1/dossiers/{dossier_id}",
            json={"owner_user_id": str(ids["limited_user"])},
            headers={"X-CSRF-Token": _csrf(limited), "If-Match": 'W/"1"'},
        ).status_code
        == 404
    )
    assert (
        limited.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "Autorizada", "status": "done"},
            headers={"X-CSRF-Token": _csrf(limited)},
        ).get_json()["status"]
        == "open"
    )
    invalid_owner = owner.patch(
        f"/api/v1/dossiers/{dossier_id}",
        json={"owner_user_id": str(uuid.uuid4())},
        headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
    )
    assert invalid_owner.status_code == 422
    assert (
        owner.delete(
            f"/api/v1/dossiers/{dossier_id}/collaborators/{ids['reader_user']}",
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 204
    )
    archived = owner.post(
        f"/api/v1/dossiers/{dossier_id}/archive",
        json={"version": 1},
        headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
    )
    assert archived.status_code == 200
    assert (
        limited.post(
            f"/api/v1/dossiers/{dossier_id}/tasks",
            json={"title": "No tras archivo"},
            headers={"X-CSRF-Token": _csrf(limited)},
        ).status_code
        == 422
    )
    assert (
        owner.post(
            "/api/v1/feedback",
            json={"target_type": "dossier", "target_id": dossier_id, "comment": "No permitido"},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 422
    )


def test_configured_scoring_override_actor_and_evidence_policy(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    owner = _client(oracle_stack)
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    response = owner.post(
        "/api/v1/dossiers",
        json={
            "workspace_id": str(ids["workspace_a"]),
            "title": "Scoring configurable",
            "type": "custom",
            "scoring_config": {
                "opportunity_weights": {
                    "strategic_fit": 1,
                    "urgency": 0,
                    "expected_value": 0,
                    "actionability": 0,
                    "relationship_leverage": 0,
                    "timing": 0,
                    "confidence": 0,
                    "effort": 0,
                    "blocking_risk": 0,
                }
            },
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert response.status_code == 201
    dossier_id = response.get_json()["id"]
    opportunity = owner.post(
        f"/api/v1/dossiers/{dossier_id}/opportunities",
        json={"title": "Configurable", "strategic_fit": 81, "execution_effort": 44},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert opportunity.status_code == 201
    opportunity_data = opportunity.get_json()
    assert opportunity_data["overall_score"] == 81
    assert opportunity_data["score_details"]["normalized_execution_effort"] == 44
    score_filtered = owner.get(
        f"/api/v1/dossiers/{dossier_id}/opportunities?filter[score_min]=80&filter[selected_ids]={opportunity_data['id']}"
    )
    assert score_filtered.status_code == 200
    assert score_filtered.get_json()["meta"]["total"] == 1
    assert (
        owner.patch(
            f"/api/v1/opportunities/{opportunity_data['id']}",
            json={"score_override": 42},
            headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
        ).status_code
        == 422
    )
    overridden = owner.patch(
        f"/api/v1/opportunities/{opportunity_data['id']}",
        json={
            "status": "qualified",
            "score_override": 42,
            "score_override_reason": "Criterio humano documentado",
        },
        headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
    )
    assert overridden.status_code == 200
    assert overridden.get_json()["overall_score"] == 42
    assert overridden.get_json()["version"] == 2
    actor = owner.post(
        "/api/v1/actors",
        json={"canonical_name": "Entidad de prueba", "actor_type": "organization"},
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()
    dossier_actor = owner.post(
        f"/api/v1/dossiers/{dossier_id}/actors",
        json={"actor_id": actor["id"], "influence": 80, "relevance_to_dossier": 60},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert dossier_actor.status_code == 201
    assert dossier_actor.get_json()["priority"] > 0

    shared_context = _create_dossier(owner, ids, "Contexto compartido sin evidencia")
    assert (
        owner.put(
            f"/api/v1/dossiers/{shared_context['id']}/collaborators/{ids['limited_user']}",
            json={"role": "viewer"},
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 200
    )
    signal_id, link_id, link_two = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO signals(id,tenant_id,provider,external_id,title,summary,source_type,source_name,ingested_at,tags,entities,categories,raw_hash,credibility,raw_payload,created_at,updated_at) VALUES (:id,:t,'synthetic','evidence','Señal evidencia','','report','Fuente',now(),'[]','[]','[]',:hash,80,'{}',now(),now())"
            ),
            {
                "id": signal_id,
                "t": ids["tenant_a"],
                "hash": hashlib.sha256(b"evidence-policy").digest(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,overall_score,score_details,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) VALUES (:id,:t,:d,:s,'new',0,0,0,0,0,'{}','','','{}',1,now(),now())"
            ),
            {"id": link_id, "t": ids["tenant_a"], "d": uuid.UUID(dossier_id), "s": signal_id},
        )
        connection.execute(
            text(
                "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,overall_score,score_details,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) VALUES (:id,:t,:d,:s,'new',0,0,0,0,0,'{}','','','{}',1,now(),now())"
            ),
            {
                "id": link_two,
                "t": ids["tenant_a"],
                "d": uuid.UUID(shared_context["id"]),
                "s": signal_id,
            },
        )
    evidence = owner.post(
        "/api/v1/evidence",
        json={
            "dossier_id": dossier_id,
            "signal_id": str(signal_id),
            "extract": "Fragmento verificable",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert evidence.status_code == 201
    evidence_id = evidence.get_json()["id"]
    assert (
        owner.patch(
            f"/api/v1/evidence/{evidence_id}",
            json={"classification": "public"},
            headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    assert (
        owner.patch(
            f"/api/v1/evidence/{evidence_id}",
            json={"classification": "internal"},
            headers={"X-CSRF-Token": _csrf(owner), "If-Match": 'W/"1"'},
        ).status_code
        == 409
    )
    linked = owner.put(
        f"/api/v1/opportunities/{opportunity_data['id']}/evidence/{evidence_id}",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert linked.status_code == 200
    links = owner.get(f"/api/v1/opportunities/{opportunity_data['id']}/evidence?page[size]=10")
    assert links.status_code == 200 and links.get_json()["meta"]["total"] == 1
    assert (
        owner.delete(
            f"/api/v1/opportunities/{opportunity_data['id']}/evidence/{evidence_id}",
            headers={"X-CSRF-Token": _csrf(owner)},
        ).status_code
        == 204
    )
    assert limited.get(f"/api/v1/signals/{signal_id}").status_code == 200
    assert limited.get(f"/api/v1/evidence/{evidence_id}").status_code == 404
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM score_history WHERE tenant_id=:t AND resource_id=:r"),
                {"t": ids["tenant_a"], "r": uuid.UUID(opportunity_data["id"])},
            ).scalar_one()
            == 2
        )
    engine.dispose()


def test_promote_race_same_key_different_payload_is_conflict(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    owner = _client(oracle_stack)
    dossier = _create_dossier(owner, ids, "Idempotencia concurrente")
    signal_id, link_id = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO signals(id,tenant_id,provider,external_id,title,summary,source_type,source_name,ingested_at,tags,entities,categories,raw_hash,credibility,raw_payload,created_at,updated_at) VALUES (:id,:t,'synthetic',:external,'Señal carrera','','report','Fuente',now(),'[]','[]','[]',:hash,80,'{}',now(),now())"
            ),
            {
                "id": signal_id,
                "t": ids["tenant_a"],
                "external": f"race-{signal_id}",
                "hash": hashlib.sha256(str(signal_id).encode()).digest(),
            },
        )
        connection.execute(
            text(
                "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,overall_score,score_details,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) VALUES (:id,:t,:d,:s,'reviewed',70,70,70,70,70,'{}','','','{}',1,now(),now())"
            ),
            {
                "id": link_id,
                "t": ids["tenant_a"],
                "d": uuid.UUID(dossier["id"]),
                "s": signal_id,
            },
        )
    engine.dispose()
    barrier = threading.Barrier(2)

    def promote(title: str) -> int:
        client = _client(oracle_stack)
        csrf = _csrf(client)
        barrier.wait(timeout=5)
        return client.post(
            f"/api/v1/signals/{link_id}/promote",
            json={"kind": "opportunity", "title": title, "strategic_fit": 70},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "shared-race-key"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(promote, ("Payload A", "Payload B")))
    assert statuses == [200, 409]


def test_durable_job_eager_idempotency_poll_and_cancel(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = oracle_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        first = enqueue_job(
            "oracle.signal.triage",
            payload={"resource_id": str(uuid.uuid4())},
            idempotency_key="phase07-eager-idempotent",
            requested_by_user_id=ids["user"],
        )
        repeated = enqueue_job(
            "oracle.signal.triage",
            payload=first.input_payload,
            idempotency_key="phase07-eager-idempotent",
            requested_by_user_id=ids["user"],
        )
        assert first.id == repeated.id
        db.session.refresh(first)
        assert first.status == "succeeded" and first.progress == 100
        queued = BackgroundJob(
            tenant_id=ids["tenant_a"],
            job_type="oracle.signal.triage",
            status="queued",
            queue="signals",
            idempotency_key="phase07-cancel",
            payload_hash=hashlib.sha256(b"{}").digest(),
            input_payload={},
        )
        db.session.add(queued)
        failed = BackgroundJob(
            tenant_id=ids["tenant_a"],
            job_type="oracle.signal.triage",
            status="failed",
            stage="retry_exhausted",
            queue="signals",
            idempotency_key="phase07-manual-retry",
            payload_hash=hashlib.sha256(b"{}").digest(),
            input_payload={},
            attempts=3,
            max_attempts=3,
            retryable=True,
            requested_by_user_id=ids["user"],
        )
        db.session.add(failed)
        report_job = BackgroundJob(
            tenant_id=ids["tenant_a"],
            job_type="oracle.report.generate",
            status="failed",
            stage="retry_exhausted",
            queue="documents",
            idempotency_key="phase07-report-permission",
            payload_hash=hashlib.sha256(b"{}").digest(),
            input_payload={},
            attempts=3,
            max_attempts=3,
            retryable=True,
            requested_by_user_id=ids["limited_user"],
        )
        db.session.add(report_job)
        db.session.commit()
        first_id = first.id
        queued_id = queued.id
        failed_id = failed.id
        report_job_id = report_job.id
        db.session.remove()

    client = _client(oracle_stack)
    detail = client.get(f"/api/v1/jobs/{first_id}")
    assert detail.status_code == 200 and detail.headers["ETag"]
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    assert limited.get(f"/api/v1/jobs/{first_id}").status_code == 404
    assert all(row["id"] != str(first_id) for row in limited.get("/api/v1/jobs").get_json()["data"])
    assert (
        client.post(
            f"/api/v1/jobs/{queued_id}/cancel", headers={"X-CSRF-Token": _csrf(client)}
        ).status_code
        == 428
    )
    assert (
        client.post(
            f"/api/v1/jobs/{queued_id}/cancel",
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"9"'},
        ).status_code
        == 409
    )
    cancelled = client.post(
        f"/api/v1/jobs/{queued_id}/cancel",
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert cancelled.status_code == 202
    assert cancelled.get_json()["cancel_requested"] is True
    assert cancelled.get_json()["status"] == "cancelled"
    retried = client.post(
        f"/api/v1/jobs/{failed_id}/retry",
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert retried.status_code == 202
    assert retried.get_json()["status"] == "succeeded"
    assert retried.get_json()["attempts"] == 1
    analyst = _client_as(oracle_stack, "domain-limited@example.test")
    report_retry = analyst.post(
        f"/api/v1/jobs/{report_job_id}/retry",
        headers={"X-CSRF-Token": _csrf(analyst), "If-Match": 'W/"1"'},
    )
    assert report_retry.status_code == 202
    assert report_retry.get_json()["status"] == "failed"
    assert report_retry.get_json()["error_code"] == "permanent_failure"
    reader = _client_as(oracle_stack, "domain-reader@example.test")
    assert reader.get(f"/api/v1/jobs/{report_job_id}").status_code == 404
    assert (
        reader.post(
            f"/api/v1/jobs/{report_job_id}/retry",
            headers={"X-CSRF-Token": _csrf(reader), "If-Match": 'W/"1"'},
        ).status_code
        == 404
    )


def test_archive_is_single_transaction(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Archivo atómico")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE FUNCTION reject_archive_metadata() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.archived_by_user_id IS NOT NULL THEN RAISE EXCEPTION 'forced archive failure'; END IF; RETURN NEW; END $$"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER reject_archive_metadata BEFORE UPDATE ON strategic_dossiers FOR EACH ROW EXECUTE FUNCTION reject_archive_metadata()"
            )
        )
    failed = client.post(
        f"/api/v1/dossiers/{dossier['id']}/archive",
        json={"version": 1},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert failed.status_code == 500
    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER reject_archive_metadata ON strategic_dossiers"))
        connection.execute(text("DROP FUNCTION reject_archive_metadata()"))
    engine.dispose()
    unchanged = client.get(f"/api/v1/dossiers/{dossier['id']}").get_json()
    assert unchanged["status"] == "draft" and unchanged["version"] == 1


def test_core_resource_crud_actions_and_actor_merge(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    _, ids, _ = oracle_stack
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Matriz CRUD")
    dossier_id = dossier["id"]

    def create_nested(resource: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/{resource}",
            json=payload,
            headers={"X-CSRF-Token": _csrf(client)},
        )
        assert response.status_code == 201, response.get_json()
        return response.get_json()

    objective = create_nested("objectives", {"title": "Objetivo", "status": "achieved"})
    assert objective["status"] == "open"
    assert (
        client.patch(
            f"/api/v1/objectives/{objective['id']}",
            json={"status": "in_progress"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/objectives/{objective['id']}",
            json={"description": "stale"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 409
    )
    hypothesis = create_nested("hypotheses", {"statement": "Hipótesis", "confidence": 70})
    assert client.get(f"/api/v1/hypotheses/{hypothesis['id']}").status_code == 200
    assert (
        client.patch(
            f"/api/v1/hypotheses/{hypothesis['id']}",
            json={"rationale": "Sin versión"},
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/hypotheses/{hypothesis['id']}",
            json={"rationale": "Validada"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    watchlist = create_nested("watchlists", {"name": "Radar", "cadence": "daily"})
    watchlist_patch = client.patch(
        f"/api/v1/watchlists/{watchlist['id']}",
        json={"name": "Radar actualizado"},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert watchlist_patch.status_code == 200
    assert watchlist_patch.get_json()["name"] == "Radar actualizado"
    monitor = client.post(
        f"/api/v1/watchlists/{watchlist['id']}/monitors",
        json={"provider": "mock", "external_id": "monitor-1"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert monitor.status_code == 201
    assert (
        client.get(f"/api/v1/watchlists/{watchlist['id']}/monitors").get_json()["meta"]["total"]
        == 1
    )
    meeting = create_nested("meetings", {"title": "Reunión", "status": "completed"})
    assert meeting["status"] == "planned"
    briefing = client.post(
        f"/api/v1/meetings/{meeting['id']}/briefings",
        json={"content": {"questions": ["¿Siguiente acción?"]}},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert briefing.status_code == 201
    assert client.get(f"/api/v1/briefings/{briefing.get_json()['id']}").status_code == 200
    assert (
        client.get(f"/api/v1/meetings/{meeting['id']}/briefings").get_json()["meta"]["total"] == 1
    )
    meeting_patch = client.patch(
        f"/api/v1/meetings/{meeting['id']}",
        json={"status": "completed"},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert meeting_patch.status_code == 200 and meeting_patch.get_json()["version"] == 2
    history = client.get(f"/api/v1/dossiers/{dossier_id}/status-history")
    assert history.status_code == 200 and history.get_json()["meta"]["total"] >= 1
    assert (
        client.patch(
            f"/api/v1/meetings/{meeting['id']}",
            json={"status": "planned"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"2"'},
        ).status_code
        == 422
    )
    decision = create_nested("decisions", {"title": "Decisión"})
    task = create_nested("tasks", {"title": "Tarea", "owner_user_id": str(ids["user"])})
    insight = create_nested(
        "insights",
        {"title": "Insight", "insight_type": "risk", "facts": ["Hecho"]},
    )
    report_response = client.post(
        f"/api/v1/dossiers/{dossier_id}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["json"], "classification": "internal"},
        },
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"crud-report-{uuid.uuid4()}",
        },
    )
    assert report_response.status_code == 202
    report = report_response.get_json()["report"]
    assert decision["status"] == "proposed"
    assert task["status"] == "open"
    assert insight["status"] == "draft"
    assert client.get(f"/api/v1/reports/{report['id']}").get_json()["status"] == "failed"
    for resource, row in (("decisions", decision), ("tasks", task), ("reports", report)):
        assert client.get(f"/api/v1/{resource}/{row['id']}").status_code == 200
    assert (
        client.patch(
            f"/api/v1/insights/{insight['id']}",
            json={"recommendation": "Actuar"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )

    target = client.post(
        "/api/v1/actors",
        json={"canonical_name": "Actor destino", "actor_type": "organization"},
        headers={"X-CSRF-Token": _csrf(client)},
    ).get_json()
    source = client.post(
        "/api/v1/actors",
        json={"canonical_name": "Actor origen", "actor_type": "organization"},
        headers={"X-CSRF-Token": _csrf(client)},
    ).get_json()
    actor_patch = client.patch(
        f"/api/v1/actors/{target['id']}",
        json={"canonical_name": "Actor destino actualizado", "metadata": {"source": "human"}},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert actor_patch.status_code == 200
    assert actor_patch.get_json()["canonical_name"] == "Actor destino actualizado"
    contextual_actor = create_nested(
        "actors", {"actor_id": source["id"], "roles": ["aliado"], "influence": 20}
    )
    contextual_patch = client.patch(
        f"/api/v1/dossier-actors/{contextual_actor['id']}",
        json={"influence": 90, "priority": 1},
        headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
    )
    assert contextual_patch.status_code == 200
    assert contextual_patch.get_json()["version"] == 2
    assert contextual_patch.get_json()["priority"] != 1
    relationship = client.post(
        "/api/v1/relationships",
        json={
            "from_actor_id": source["id"],
            "to_actor_id": target["id"],
            "dossier_id": dossier_id,
            "relationship_type": "alliance",
            "strength": 60,
            "confidence": 70,
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert relationship.status_code == 201
    assert (
        client.patch(
            f"/api/v1/relationships/{relationship.get_json()['id']}",
            json={"strength": 75},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    merged = client.post(
        f"/api/v1/actors/{target['id']}/merge",
        json={"source_actor_id": source["id"], "reason": "Duplicado verificado"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert merged.status_code == 200
    assert "Actor origen" in merged.get_json()["aliases"]
    feedback = client.post(
        "/api/v1/feedback",
        json={"target_type": "task", "target_id": task["id"], "rating": 1},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert feedback.status_code == 201
    assert (
        client.patch(
            f"/api/v1/feedback/{feedback.get_json()['id']}",
            json={"comment": "Confirmado"},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/dossiers/{dossier_id}/feedback").get_json()["meta"]["total"] >= 1
    summary = client.put(
        f"/api/v1/dossiers/{dossier_id}/living-summary",
        json={"summary": {"headline": "Resumen vivo"}},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert summary.status_code == 201
    assert client.get(f"/api/v1/dossiers/{dossier_id}/living-summary").status_code == 200
    assert (
        client.get(f"/api/v1/dossiers/{dossier_id}/tasks?page[size]=1").get_json()["meta"]["size"]
        == 1
    )
    assert (
        client.delete(
            f"/api/v1/feedback/{feedback.get_json()['id']}",
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/briefings/{briefing.get_json()['id']}",
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 204
    )
    assert (
        client.delete(
            f"/api/v1/dossiers/{dossier_id}/living-summary",
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 204
    )
    archived_dossier = _create_dossier(client, ids, "Merge archivado")
    archived_target = client.post(
        "/api/v1/actors",
        json={"canonical_name": "Destino archivado", "actor_type": "organization"},
        headers={"X-CSRF-Token": _csrf(client)},
    ).get_json()
    archived_source = client.post(
        "/api/v1/actors",
        json={"canonical_name": "Origen archivado", "actor_type": "organization"},
        headers={"X-CSRF-Token": _csrf(client)},
    ).get_json()
    assert (
        client.post(
            f"/api/v1/dossiers/{archived_dossier['id']}/actors",
            json={"actor_id": archived_source["id"]},
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v1/dossiers/{archived_dossier['id']}/archive",
            json={"version": 1},
            headers={"X-CSRF-Token": _csrf(client), "If-Match": 'W/"1"'},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/actors/{archived_target['id']}/merge",
            json={"source_actor_id": archived_source["id"], "reason": "No permitido"},
            headers={"X-CSRF-Token": _csrf(client)},
        ).status_code
        == 422
    )
    runtime = create_engine(os.environ["TEST_RUNTIME_DATABASE_URL"])
    with runtime.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"),
            {"tenant": str(ids["tenant_b"])},
        )
        for table in (
            "strategic_dossiers",
            "dossier_objectives",
            "hypotheses",
            "watchlists",
            "signal_monitors",
            "signals",
            "dossier_signals",
            "evidence",
            "evidence_dossiers",
            "opportunities",
            "risk_items",
            "actors",
            "dossier_actors",
            "relationships",
            "meetings",
            "briefings",
            "decisions",
            "tasks",
            "insights",
            "feedback",
            "reports",
            "living_summaries",
            "score_history",
            "status_history",
        ):
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant_a"),
                    {"tenant_a": ids["tenant_a"]},
                ).scalar_one()
                == 0
            )
    runtime.dispose()


def test_report_request_concurrency_and_generation_versions(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _ = oracle_stack
    dossier = _create_dossier(_client(oracle_stack), ids, "Concurrencia de informes")
    dossier_id = uuid.UUID(dossier["id"])
    monkeypatch.setattr("opn_oracle.reporting.service.publish_job", lambda job: None)

    def request_report(
        key: str, formats: list[str], barrier: threading.Barrier
    ) -> tuple[str, int, bool, str]:
        with (
            app.app_context(),
            tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
        ):
            row = db.session.get(StrategicDossier, dossier_id)
            assert row is not None
            barrier.wait(timeout=10)
            try:
                report, _, created = create_report_request(
                    row,
                    template_key="executive_dossier",
                    options={"formats": formats, "classification": "internal"},
                    requested_by_user_id=ids["user"],
                    idempotency_key=key,
                )
                result = str(report.id), report.generation_version, created, "ok"
            except ReportConflictError:
                db.session.rollback()
                result = "", 0, False, "conflict"
            finally:
                db.session.remove()
            return result

    same_key = f"same-report-{uuid.uuid4()}"
    same_barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        same = list(
            pool.map(
                lambda _: request_report(same_key, ["json"], same_barrier),
                range(2),
            )
        )
    assert {item[0] for item in same} == {same[0][0]}
    assert sorted(item[2] for item in same) == [False, True]
    assert {item[3] for item in same} == {"ok"}

    conflict_key = f"different-report-{uuid.uuid4()}"
    conflict_barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        different = list(
            pool.map(
                lambda formats: request_report(conflict_key, formats, conflict_barrier),
                (["html"], ["json"]),
            )
        )
    assert sorted(item[3] for item in different) == ["conflict", "ok"]

    version_barrier = threading.Barrier(2)
    keys = [f"version-report-{uuid.uuid4()}" for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(
            pool.map(
                lambda key: request_report(key, ["json"], version_barrier),
                keys,
            )
        )
    assert len({item[1] for item in versions}) == 2
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        stored_versions = list(
            db.session.scalars(
                select(Report.generation_version)
                .where(Report.dossier_id == dossier_id)
                .order_by(Report.generation_version)
            )
        )
        assert stored_versions == list(range(1, len(stored_versions) + 1))


@pytest.mark.parametrize("scenario", ["provider", "schema", "reviewer"])
def test_report_generation_failures_never_publish_artifacts(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    app, ids, _ = oracle_stack
    storage = LocalObjectStorage(tmp_path / f"report-failure-{scenario}")
    app.extensions["object_storage"] = storage
    _enable_mock_ai(app, ids)
    fallback = MockLLMProvider("report-failure-test")

    class ScenarioProvider:
        def generate_structured(self, request: LLMRequest, schema: type[Any]) -> LLMResult:
            if scenario == "provider" and request.agent == "report_writer":
                raise RuntimeError("provider unavailable")
            if scenario == "reviewer" and request.agent == "evidence_reviewer":
                raise RuntimeError("reviewer unavailable")
            if scenario == "schema" and request.agent == "report_writer":
                invalid = ReportOutput.model_construct(
                    facts=[],
                    inferences=[],
                    recommendations=[],
                    confidence=50,
                    open_questions=[],
                    warnings=[],
                )
                return LLMResult(invalid, 1, 1, 0, 1)
            return fallback.generate_structured(request, schema)

        def embed(self, texts: list[str]) -> Any:
            return fallback.embed(texts)

        def health(self) -> Any:
            return fallback.health()

    provider = ScenarioProvider()
    monkeypatch.setattr("opn_oracle.ai.service.provider_from_config", lambda config: provider)
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, f"Fallo de informe {scenario}")
    response = client.post(
        f"/api/v1/dossiers/{dossier['id']}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["html", "json"], "classification": "internal"},
        },
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"failure-{scenario}-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 202
    report_id = response.get_json()["report"]["id"]
    report = client.get(f"/api/v1/reports/{report_id}").get_json()
    assert report["status"] == "failed"
    assert report["artifacts"] == []
    assert report["revision"] is None
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        assert not list(
            db.session.scalars(
                select(ReportArtifact).where(ReportArtifact.report_id == uuid.UUID(report_id))
            )
        )
        assert not db.session.scalar(
            select(Notification).where(
                Notification.report_id == uuid.UUID(report_id),
                Notification.notification_type == "report.ready",
            )
        )
    assert storage.iter_objects(ids["tenant_a"]) == ()


def test_report_publish_permission_immutability_and_supersession(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "report-workflow")
    _enable_mock_ai(app, ids)
    owner = _client(oracle_stack)
    dossier = _create_dossier(owner, ids, "Workflow de publicación")
    dossier_id = uuid.UUID(dossier["id"])
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        db.session.add(
            DossierCollaborator(
                tenant_id=ids["tenant_a"],
                dossier_id=dossier_id,
                user_id=ids["limited_user"],
                role="editor",
            )
        )
        db.session.commit()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM role_permissions WHERE tenant_id=:tenant "
                "AND role_id=:role AND permission_key='report.publish'"
            ),
            {"tenant": ids["tenant_a"], "role": ids["limited_role"]},
        )
    engine.dispose()

    def generated(key: str) -> dict[str, Any]:
        response = owner.post(
            f"/api/v1/dossiers/{dossier['id']}/reports",
            json={
                "template_key": "executive_dossier",
                "options": {"formats": ["json"], "classification": "internal"},
            },
            headers={"X-CSRF-Token": _csrf(owner), "Idempotency-Key": key},
        )
        assert response.status_code == 202
        report_id = response.get_json()["report"]["id"]
        report = owner.get(f"/api/v1/reports/{report_id}").get_json()
        assert report["status"] == "ready"
        return report

    first = generated(f"publish-first-{uuid.uuid4()}")
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    approved = limited.post(
        f"/api/v1/reports/{first['id']}/reviews",
        json={
            "version": first["version"],
            "revision_id": first["revision"]["id"],
            "decision": "approved",
            "comment": "Revisión del analista.",
        },
        headers={"X-CSRF-Token": _csrf(limited)},
    )
    assert approved.status_code == 201
    reviewed = approved.get_json()["report"]
    forbidden = limited.post(
        f"/api/v1/reports/{first['id']}/publish",
        json={"version": reviewed["version"]},
        headers={"X-CSRF-Token": _csrf(limited)},
    )
    assert forbidden.status_code == 403
    published = owner.post(
        f"/api/v1/reports/{first['id']}/publish",
        json={"version": reviewed["version"]},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert published.status_code == 200
    immutable = owner.post(
        f"/api/v1/reports/{first['id']}/revisions",
        json={
            "version": published.get_json()["version"],
            "content": first["revision"]["content"],
            "change_summary": "Intento de edición in-place.",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert immutable.status_code == 422

    second = generated(f"publish-second-{uuid.uuid4()}")
    assert second["generation_version"] == first["generation_version"] + 1
    assert owner.get(f"/api/v1/reports/{first['id']}").get_json()["status"] == "published"
    second_review = owner.post(
        f"/api/v1/reports/{second['id']}/reviews",
        json={
            "version": second["version"],
            "revision_id": second["revision"]["id"],
            "decision": "approved",
            "comment": "Nueva versión validada.",
        },
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()["report"]
    second_publish = owner.post(
        f"/api/v1/reports/{second['id']}/publish",
        json={"version": second_review["version"]},
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert second_publish.status_code == 200
    assert owner.get(f"/api/v1/reports/{first['id']}").get_json()["status"] == "superseded"


def test_notification_quiet_hours_and_digest_delivery_ledger(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = oracle_stack
    now = datetime.now(UTC)
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        quiet_type = f"quiet.{uuid.uuid4().hex}"
        quiet_preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=quiet_type,
            channels={"in_app": True, "email": True},
            digest_cadence="instant",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            quiet_hours_start=(now - timedelta(hours=1)).time().replace(tzinfo=None),
            quiet_hours_end=(now + timedelta(hours=1)).time().replace(tzinfo=None),
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(quiet_preference)
        db.session.flush()
        quiet_notification = create_notification(
            user_id=ids["user"],
            notification_type=quiet_type,
            severity="info",
            title="Entrega diferida",
            body="No debe publicarse durante horas silenciosas.",
            dedupe_key=f"quiet-notification-{uuid.uuid4()}",
            now=now,
        )
        assert quiet_notification.email_job is not None
        assert quiet_notification.email_job.not_before is not None
        assert quiet_notification.email_job.not_before > now
        db.session.commit()
        publish_notification_job(quiet_notification)
        db.session.refresh(quiet_notification.email_job)
        assert quiet_notification.email_job.published_at is None

        digest_type = f"digest.{uuid.uuid4().hex}"
        preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=digest_type,
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(preference)
        db.session.flush()
        create_notification(
            user_id=ids["user"],
            notification_type=digest_type,
            severity="success",
            title="Elemento del digest",
            body="Resumen trazable.",
            dedupe_key=f"digest-notification-{uuid.uuid4()}",
        )
        job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(preference.id)},
            idempotency_key=f"digest-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=preference.id,
        )
        db.session.commit()
        sender = CaptureEmailSender()
        app.extensions["email_sender"] = sender
        first = send_digest(preference.id, job)
        second = send_digest(preference.id, job)
        assert first["delivered"] is True and second["delivered"] is True
        assert len(sender.messages) == 1

        disabled_preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=f"digest-disabled.{uuid.uuid4().hex}",
            channels={"in_app": True, "email": False},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(disabled_preference)
        db.session.flush()
        assert sync_digest_schedule(disabled_preference) is None
        disabled_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(disabled_preference.id)},
            idempotency_key=f"digest-disabled-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=disabled_preference.id,
        )
        db.session.commit()
        with pytest.raises(NotificationPermanentError):
            send_digest(disabled_preference.id, disabled_job)
        disabled_preference.channels = {"in_app": True, "email": True}
        schedule = sync_digest_schedule(disabled_preference)
        assert schedule is not None and schedule.enabled is True
        disabled_preference.channels = {"in_app": True, "email": False}
        assert sync_digest_schedule(disabled_preference) is schedule
        assert schedule.enabled is False
        db.session.commit()

        wildcard = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type="*",
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        exact_type = f"digest-exact.{uuid.uuid4().hex}"
        exact = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=exact_type,
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add_all((wildcard, exact))
        db.session.flush()
        create_notification(
            user_id=ids["user"],
            notification_type=exact_type,
            severity="info",
            title="Solo digest específico",
            body="No debe duplicarse en wildcard.",
            dedupe_key=f"digest-exact-notification-{uuid.uuid4()}",
        )
        create_notification(
            user_id=ids["user"],
            notification_type=f"digest-wild-only.{uuid.uuid4().hex}",
            severity="info",
            title="Solo digest wildcard",
            body="No tiene preferencia específica.",
            dedupe_key=f"digest-wild-notification-{uuid.uuid4()}",
        )
        exact_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(exact.id)},
            idempotency_key=f"digest-exact-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=exact.id,
        )
        wildcard_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(wildcard.id)},
            idempotency_key=f"digest-wildcard-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=wildcard.id,
        )
        db.session.commit()
        precedence_sender = CaptureEmailSender()
        app.extensions["email_sender"] = precedence_sender
        assert send_digest(exact.id, exact_job)["delivered"] is True
        assert send_digest(wildcard.id, wildcard_job)["delivered"] is True
        assert len(precedence_sender.messages) == 2
        exact_body, wildcard_body = (
            precedence_sender.messages[0].body,
            precedence_sender.messages[1].body,
        )
        assert "Solo digest específico" in exact_body
        assert "Solo digest específico" not in wildcard_body
        assert "Solo digest wildcard" in wildcard_body

        retry_type = f"digest-retry.{uuid.uuid4().hex}"
        retry_preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=retry_type,
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(retry_preference)
        db.session.flush()
        create_notification(
            user_id=ids["user"],
            notification_type=retry_type,
            severity="info",
            title="Digest reintentable",
            body="El primer proveedor falla.",
            dedupe_key=f"digest-retry-notification-{uuid.uuid4()}",
        )
        retry_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(retry_preference.id)},
            idempotency_key=f"digest-retry-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=retry_preference.id,
        )
        db.session.commit()

        class FlakySender(CaptureEmailSender):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_digest(self, **kwargs: Any) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise OSError("provider down")
                super().send_digest(**kwargs)

        flaky = FlakySender()
        app.extensions["email_sender"] = flaky
        with pytest.raises(NotificationTemporaryError):
            send_digest(retry_preference.id, retry_job)
        retried = send_digest(retry_preference.id, retry_job)
        assert retried["delivered"] is True
        assert flaky.calls == 2 and len(flaky.messages) == 1

        ambiguous_type = f"digest-ambiguous.{uuid.uuid4().hex}"
        ambiguous_preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=ambiguous_type,
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=now.time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(ambiguous_preference)
        db.session.flush()
        ambiguous_notification = create_notification(
            user_id=ids["user"],
            notification_type=ambiguous_type,
            severity="info",
            title="Entrega ambigua",
            body="No debe repetirse por SMTP no idempotente.",
            dedupe_key=f"digest-ambiguous-notification-{uuid.uuid4()}",
        ).notification
        ambiguous_job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(ambiguous_preference.id)},
            idempotency_key=f"digest-ambiguous-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=ambiguous_preference.id,
        )
        period = now.date().isoformat()
        db.session.add(
            NotificationDelivery(
                tenant_id=ids["tenant_a"],
                notification_id=ambiguous_notification.id,
                job_id=ambiguous_job.id,
                channel="email",
                status="failed",
                dedupe_key=f"digest:{ambiguous_preference.id}:{period}",
                attempts=1,
                delivery_started_at=now,
                error_code="provider_unavailable",
            )
        )
        db.session.commit()

        class AmbiguousSender:
            supports_idempotency = False

        app.extensions["email_sender"] = AmbiguousSender()
        with pytest.raises(NotificationPermanentError):
            send_digest(ambiguous_preference.id, ambiguous_job)


def test_instant_notification_email_retry_and_ambiguous_delivery(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = oracle_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        notification_type = f"instant.{uuid.uuid4().hex}"
        db.session.add(
            NotificationPreference(
                tenant_id=ids["tenant_a"],
                user_id=ids["user"],
                notification_type=notification_type,
                channels={"in_app": True, "email": True},
                digest_cadence="instant",
                timezone="UTC",
                local_time=datetime.now(UTC).time().replace(tzinfo=None),
                weekday=None,
                minimum_severity="info",
                security_locked=False,
                version=1,
            )
        )
        db.session.flush()
        created = create_notification(
            user_id=ids["user"],
            notification_type=notification_type,
            severity="success",
            title="Correo instantáneo",
            body="Entrega idempotente.",
            dedupe_key=f"instant-email-{uuid.uuid4()}",
            link="/app/reports",
        )
        assert created.email_job is not None
        delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == created.notification.id
            )
        )
        assert delivery is not None
        db.session.commit()
        sender = CaptureEmailSender()
        app.extensions["email_sender"] = sender
        first = send_notification_email(delivery.id)
        replay = send_notification_email(delivery.id)
        assert first["delivered"] is True and replay["delivered"] is True
        assert len(sender.messages) == 1

        retry_type = f"instant-retry.{uuid.uuid4().hex}"
        db.session.add(
            NotificationPreference(
                tenant_id=ids["tenant_a"],
                user_id=ids["user"],
                notification_type=retry_type,
                channels={"in_app": True, "email": True},
                digest_cadence="instant",
                timezone="UTC",
                local_time=datetime.now(UTC).time().replace(tzinfo=None),
                weekday=None,
                minimum_severity="info",
                security_locked=False,
                version=1,
            )
        )
        db.session.flush()
        retry_notification = create_notification(
            user_id=ids["user"],
            notification_type=retry_type,
            severity="info",
            title="Correo reintentable",
            body="El primer envío falla.",
            dedupe_key=f"instant-retry-{uuid.uuid4()}",
        ).notification
        retry_delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == retry_notification.id
            )
        )
        assert retry_delivery is not None
        db.session.commit()

        class FlakyNotificationSender(CaptureEmailSender):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def send_notification(self, **kwargs: Any) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise OSError("provider down")
                super().send_notification(**kwargs)

        flaky = FlakyNotificationSender()
        app.extensions["email_sender"] = flaky
        with pytest.raises(NotificationTemporaryError):
            send_notification_email(retry_delivery.id)
        assert send_notification_email(retry_delivery.id)["delivered"] is True
        assert flaky.calls == 2 and len(flaky.messages) == 1

        ambiguous_type = f"instant-ambiguous.{uuid.uuid4().hex}"
        db.session.add(
            NotificationPreference(
                tenant_id=ids["tenant_a"],
                user_id=ids["user"],
                notification_type=ambiguous_type,
                channels={"in_app": True, "email": True},
                digest_cadence="instant",
                timezone="UTC",
                local_time=datetime.now(UTC).time().replace(tzinfo=None),
                weekday=None,
                minimum_severity="info",
                security_locked=False,
                version=1,
            )
        )
        db.session.flush()
        ambiguous_notification = create_notification(
            user_id=ids["user"],
            notification_type=ambiguous_type,
            severity="info",
            title="Correo ambiguo",
            body="No debe duplicarse.",
            dedupe_key=f"instant-ambiguous-{uuid.uuid4()}",
        ).notification
        ambiguous_delivery = db.session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == ambiguous_notification.id
            )
        )
        assert ambiguous_delivery is not None
        ambiguous_delivery.status = "failed"
        ambiguous_delivery.delivery_started_at = datetime.now(UTC)
        ambiguous_delivery.error_code = "provider_unavailable"
        db.session.commit()

        class NonIdempotentSender:
            supports_idempotency = False

        app.extensions["email_sender"] = NonIdempotentSender()
        with pytest.raises(NotificationPermanentError):
            send_notification_email(ambiguous_delivery.id)
        with pytest.raises(NotificationPermanentError):
            send_notification_email(uuid.uuid4())


def test_digest_retry_freezes_the_exact_multi_item_batch(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider retry must not lose old items or absorb newly-created ones."""

    app, ids, _ = oracle_stack
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        notification_type = f"digest-frozen.{uuid.uuid4().hex}"
        preference = NotificationPreference(
            tenant_id=ids["tenant_a"],
            user_id=ids["user"],
            notification_type=notification_type,
            channels={"in_app": True, "email": True},
            digest_cadence="daily",
            timezone="UTC",
            local_time=datetime.now(UTC).time().replace(tzinfo=None),
            weekday=None,
            minimum_severity="info",
            security_locked=False,
            version=1,
        )
        db.session.add(preference)
        db.session.flush()
        initial_now = datetime.now(UTC)
        for ordinal in (1, 2):
            create_notification(
                user_id=ids["user"],
                notification_type=notification_type,
                severity="info",
                title=f"Elemento congelado {ordinal}",
                body=f"Contenido estable {ordinal}",
                dedupe_key=f"digest-frozen-{ordinal}-{uuid.uuid4()}",
                link=f"/app/notifications?item={ordinal}",
                expires_at=initial_now + timedelta(minutes=1),
            )
        job = stage_job(
            "notifications.send_digest",
            payload={"preference_id": str(preference.id)},
            idempotency_key=f"digest-frozen-job-{uuid.uuid4()}",
            requested_by_user_id=ids["user"],
            resource_type="notification_preference",
            resource_id=preference.id,
        )
        db.session.commit()

        class CaptureFailedBatch(CaptureEmailSender):
            def __init__(self) -> None:
                super().__init__()
                self.attempted_items: list[tuple[tuple[str, str, str | None], ...]] = []

            def send_digest(self, **kwargs: Any) -> None:
                self.attempted_items.append(tuple(kwargs["items"]))
                if len(self.attempted_items) == 1:
                    raise OSError("temporary provider failure")
                super().send_digest(**kwargs)

        sender = CaptureFailedBatch()
        app.extensions["email_sender"] = sender
        with pytest.raises(NotificationTemporaryError):
            send_digest(preference.id, job)
        assert len(sender.attempted_items[0]) == 2
        delivery = db.session.scalar(
            select(NotificationDelivery).where(NotificationDelivery.job_id == job.id)
        )
        assert delivery is not None
        assert delivery.batch_snapshot is not None
        assert delivery.batch_sha256 is not None and len(delivery.batch_sha256) == 32
        assert delivery.batch_snapshot["cadence"] == "daily"
        assert delivery.batch_snapshot["preference_id"] == str(preference.id)
        assert len(delivery.batch_snapshot["items"]) == 2

        # Quiet hours defer the retry without changing or re-sending the frozen batch.
        preference.quiet_hours_start = datetime.min.time()
        preference.quiet_hours_end = datetime.min.time()
        db.session.commit()
        with pytest.raises(NotificationTemporaryError, match="horas silenciosas"):
            send_digest(preference.id, job)
        assert len(sender.attempted_items) == 1
        preference.quiet_hours_start = None
        preference.quiet_hours_end = None

        # Arrives after the delivery attempt: it belongs to the next digest, not this retry.
        create_notification(
            user_id=ids["user"],
            notification_type=notification_type,
            severity="critical",
            title="Elemento posterior",
            body="No debe colarse en el lote ya intentado.",
            dedupe_key=f"digest-frozen-new-{uuid.uuid4()}",
        )
        db.session.commit()

        # Expiry is evaluated before freezing. Advancing beyond the items' expiry must not
        # rewrite the retry payload.
        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz: Any = None) -> datetime:
                value = initial_now + timedelta(minutes=2)
                return value if tz is not None else value.replace(tzinfo=None)

        monkeypatch.setattr("opn_oracle.reporting.notifications.datetime", FrozenDateTime)

        result = send_digest(preference.id, job)
        assert result["delivered"] is True
        assert result["count"] == 2
        assert sender.attempted_items[1] == sender.attempted_items[0]
        assert len(sender.messages) == 1

        # Any persisted snapshot mutation is detected before another provider call.
        tampered = dict(delivery.batch_snapshot)
        tampered_items = [dict(item) for item in tampered["items"]]
        tampered_items[0]["body"] = "Contenido alterado"
        tampered["items"] = tampered_items
        delivery.batch_snapshot = tampered
        db.session.commit()
        with pytest.raises(NotificationPermanentError, match="integridad"):
            send_digest(preference.id, job)
        assert len(sender.attempted_items) == 2


def test_export_respects_collaborator_scope_and_selected_ids(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "export-scope")
    owner = _client(oracle_stack)
    dossier_a = _create_dossier(owner, ids, "Export visible")
    dossier_b = _create_dossier(owner, ids, "Export oculto")
    opportunity_a = owner.post(
        f"/api/v1/dossiers/{dossier_a['id']}/opportunities",
        json={"title": "Oportunidad visible seleccionada", "description": "visible"},
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()
    opportunity_b = owner.post(
        f"/api/v1/dossiers/{dossier_b['id']}/opportunities",
        json={"title": "Oportunidad oculta seleccionada", "description": "oculta"},
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        existing = db.session.get(
            DossierCollaborator,
            (ids["tenant_a"], uuid.UUID(dossier_a["id"]), ids["limited_user"]),
        )
        if existing is None:
            db.session.add(
                DossierCollaborator(
                    tenant_id=ids["tenant_a"],
                    dossier_id=uuid.UUID(dossier_a["id"]),
                    user_id=ids["limited_user"],
                    role="viewer",
                )
            )
        db.session.commit()
    limited = _client_as(oracle_stack, "domain-limited@example.test")
    response = limited.post(
        "/api/v1/exports",
        json={
            "dataset": "opportunities",
            "filters": {
                "selected_ids": [opportunity_a["id"], opportunity_b["id"]],
                "search": "seleccionada",
            },
            "columns": ["id", "dossier_id", "title"],
        },
        headers={
            "X-CSRF-Token": _csrf(limited),
            "Idempotency-Key": f"collaborator-export-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 202, response.get_json()
    exported = response.get_json()["export"]
    assert exported["status"] == "ready"
    link = limited.post(
        f"/api/v1/exports/{exported['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(limited)},
    )
    payload = limited.get(link.get_json()["url"]).data.decode("utf-8-sig")
    assert "Oportunidad visible seleccionada" in payload
    assert "Oportunidad oculta seleccionada" not in payload
    assert opportunity_a["id"] in payload
    assert opportunity_b["id"] not in payload


def test_export_datasets_failure_cleanup_replay_and_expiry(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    owner = _client(oracle_stack)
    dossier = _create_dossier(owner, ids, "Estados de exportación")
    opportunity = owner.post(
        f"/api/v1/dossiers/{dossier['id']}/opportunities",
        json={"title": "Exportación controlada", "description": "scope"},
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()

    class BrokenMetadataStorage(LocalObjectStorage):
        def put(self, *args: Any, **kwargs: Any) -> StoredObject:
            stored = super().put(*args, **kwargs)
            return StoredObject(stored.key, stored.byte_size, b"\x00" * 32)

    broken = BrokenMetadataStorage(tmp_path / "export-broken")
    app.extensions["object_storage"] = broken
    failed_response = owner.post(
        "/api/v1/exports",
        json={
            "dataset": "opportunities",
            "dossier_id": dossier["id"],
            "filters": {"selected_ids": [opportunity["id"]]},
        },
        headers={
            "X-CSRF-Token": _csrf(owner),
            "Idempotency-Key": f"export-broken-{uuid.uuid4()}",
        },
    )
    assert failed_response.status_code == 202
    failed_id = failed_response.get_json()["export"]["id"]
    assert owner.get(f"/api/v1/exports/{failed_id}").get_json()["status"] == "failed"
    assert broken.iter_objects(ids["tenant_a"]) == ()

    storage = LocalObjectStorage(tmp_path / "export-datasets")
    app.extensions["object_storage"] = storage
    created: dict[str, dict[str, Any]] = {}
    for dataset in ("signals", "opportunities", "risks", "actors", "tasks", "reports", "audit"):
        key = f"export-dataset-{dataset}-{uuid.uuid4()}"
        body: dict[str, Any] = {"dataset": dataset}
        response = owner.post(
            "/api/v1/exports",
            json=body,
            headers={"X-CSRF-Token": _csrf(owner), "Idempotency-Key": key},
        )
        assert response.status_code == 202, (dataset, response.get_json())
        exported = owner.get(f"/api/v1/exports/{response.get_json()['export']['id']}").get_json()
        assert exported["status"] == "ready", (dataset, exported)
        created[dataset] = {"row": exported, "key": key, "body": body}
    audit_export = created["audit"]["row"]
    assert audit_export["watermark"].startswith("OPN Oracle · auditoría")

    replayed = owner.post(
        "/api/v1/exports",
        json=created["reports"]["body"],
        headers={
            "X-CSRF-Token": _csrf(owner),
            "Idempotency-Key": created["reports"]["key"],
        },
    )
    assert replayed.status_code == 200 and replayed.get_json()["replayed"] is True
    conflict = owner.post(
        "/api/v1/exports",
        json={"dataset": "reports", "filters": {"search": "otro"}},
        headers={
            "X-CSRF-Token": _csrf(owner),
            "Idempotency-Key": created["reports"]["key"],
        },
    )
    assert conflict.status_code == 409

    report_export = created["reports"]["row"]
    valid_link = owner.post(
        f"/api/v1/exports/{report_export['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(owner)},
    ).get_json()["url"]
    separator = "&signature="
    prefix, signature = valid_link.split(separator)
    tampered = f"{prefix}{separator}{signature[:-1]}{'0' if signature[-1] != '0' else '1'}"
    assert owner.get(tampered).status_code == 403
    assert (
        owner.get(
            f"/api/v1/export-artifacts/{report_export['id']}/download?expires=nope"
        ).status_code
        == 403
    )
    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        row = db.session.get(DataExport, uuid.UUID(report_export["id"]))
        assert row is not None
        row.expires_at = row.created_at + timedelta(microseconds=1)
        db.session.commit()
    expired = owner.post(
        f"/api/v1/exports/{report_export['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(owner)},
    )
    assert expired.status_code == 410
    assert owner.get(valid_link).status_code == 403


def test_notification_security_preference_read_all_and_dismiss(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, ids, _ = oracle_stack
    client = _client(oracle_stack)
    preference = client.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "security.password_changed",
            "channels": {"in_app": False, "email": False},
            "digest_cadence": "off",
            "timezone": "Europe/Madrid",
            "local_time": "08:00",
            "minimum_severity": "critical",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert preference.status_code == 200, preference.get_json()
    locked = preference.get_json()
    assert locked["security_locked"] is True
    assert locked["channels"] == {"in_app": True, "email": True}
    assert locked["digest_cadence"] == "instant"
    invalid_channels = client.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": "product.test",
            "channels": {"in_app": "false", "email": False},
            "digest_cadence": "instant",
            "timezone": "UTC",
            "local_time": "08:00",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert invalid_channels.status_code == 422

    hidden_type = f"email-only.{uuid.uuid4().hex}"
    email_only = client.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": hidden_type,
            "channels": {"in_app": False, "email": True},
            "digest_cadence": "instant",
            "timezone": "UTC",
            "local_time": "08:00",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert email_only.status_code == 200

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        hidden = create_notification(
            user_id=ids["user"],
            notification_type=hidden_type,
            severity="info",
            title="Solo correo",
            body="No debe aparecer en el inbox.",
            dedupe_key=f"email-only-notification-{uuid.uuid4()}",
        ).notification
        assert hidden.in_app_visible is False
        rows = [
            create_notification(
                user_id=ids["user"],
                notification_type="product.test",
                severity="info",
                title=f"Notificación {index}",
                body="Pendiente de lectura.",
                dedupe_key=f"read-all-{index}-{uuid.uuid4()}",
            ).notification
            for index in range(2)
        ]
        ids_to_read = [str(row.id) for row in rows]
        hidden_id = str(hidden.id)
        db.session.commit()
    read_all = client.post(
        "/api/v1/notifications/read-all",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert read_all.status_code == 200
    assert read_all.get_json()["updated"] >= 2
    assert read_all.get_json()["unread_count"] == 0
    dismissed = client.post(
        f"/api/v1/notifications/{ids_to_read[0]}/dismiss",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert dismissed.status_code == 200 and dismissed.get_json()["dismissed_at"] is not None
    inbox_ids = {item["id"] for item in client.get("/api/v1/notifications").get_json()["data"]}
    assert hidden_id not in inbox_ids
    assert ids_to_read[0] not in inbox_ids
    assert ids_to_read[1] in inbox_ids


def test_reporting_api_validation_retry_revision_and_policy_states(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, _ = oracle_stack
    app.extensions["object_storage"] = LocalObjectStorage(tmp_path / "reporting-api-states")
    _enable_mock_ai(app, ids)
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Estados API de reporting")
    dossier_id = dossier["id"]
    csrf = _csrf(client)

    templates = client.get("/api/v1/report-templates")
    assert templates.status_code == 200 and len(templates.get_json()["items"]) == 8
    assert client.get("/api/v1/reports?page[number]=x").status_code == 422
    assert client.get("/api/v1/notifications?page[size]=x").status_code == 422
    assert client.get("/api/v1/exports?page[number]=x").status_code == 422

    def invalid_report(template_key: str, options: dict[str, Any]) -> None:
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports",
            json={"template_key": template_key, "options": options},
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": f"invalid-report-{uuid.uuid4()}",
            },
        )
        assert response.status_code == 422, (template_key, options, response.get_json())

    invalid_report("executive_dossier", {"unknown": True})
    invalid_report("opportunity", {})
    invalid_report("opportunity", {"opportunity_id": "not-uuid"})
    invalid_report("opportunity", {"opportunity_id": str(uuid.uuid4())})
    invalid_report("actors", {"actor_ids": "not-a-list"})
    invalid_report("actors", {"actor_ids": ["not-uuid"]})
    invalid_report("actors", {"actor_ids": [str(uuid.uuid4())]})
    invalid_report("weekly_change", {"period_start": "not-a-date", "period_end": "2026-07-11"})
    invalid_report("weekly_change", {"period_start": "2026-07-12", "period_end": "2026-07-11"})
    invalid_report("executive_dossier", {"formats": "json"})
    invalid_report("executive_dossier", {"formats": []})
    invalid_report("executive_dossier", {"formats": ["xlsx"]})
    invalid_report("executive_dossier", {"formats": ["pdf"]})
    invalid_report("executive_dossier", {"classification": "secret"})
    invalid_report("executive_dossier", {"confidentiality_label": "x" * 121})

    def generate(key: str) -> dict[str, Any]:
        response = client.post(
            f"/api/v1/dossiers/{dossier_id}/reports",
            json={
                "template_key": "executive_dossier",
                "options": {"formats": ["json"], "classification": "internal"},
            },
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": key},
        )
        assert response.status_code == 202
        return client.get(f"/api/v1/reports/{response.get_json()['report']['id']}").get_json()

    report = generate(f"api-state-ready-{uuid.uuid4()}")
    assert report["status"] == "ready"
    filtered = client.get(
        "/api/v1/reports?filter[status]=ready&filter[template]=executive_dossier"
        "&filter[search]=Informe&page[number]=1&page[size]=5"
    )
    assert filtered.status_code == 200 and filtered.get_json()["meta"]["total"] >= 1
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/retry",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"retry-ready-{uuid.uuid4()}"},
        ).status_code
        == 409
    )

    content = dict(report["revision"]["content"])
    content["title"] = "Revisión humana trazable"
    revised = client.post(
        f"/api/v1/reports/{report['id']}/revisions",
        json={
            "version": report["version"],
            "content": content,
            "change_summary": "Corrección humana validada.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert revised.status_code == 201, revised.get_json()
    revised_report = revised.get_json()
    assert revised_report["revision"]["revision_no"] == 2
    assert revised_report["revision"]["title"] == "Revisión humana trazable"
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/revisions",
            json={"version": report["version"], "content": content, "change_summary": "stale"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/revisions",
            json={"version": revised_report["version"], "content": "invalid"},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/reviews",
            json={
                "version": revised_report["version"],
                "revision_id": str(uuid.uuid4()),
                "decision": "approved",
                "comment": "wrong revision",
            },
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/reviews",
            json={
                "version": revised_report["version"],
                "revision_id": revised_report["revision"]["id"],
                "decision": "changes_requested",
                "comment": "",
            },
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 422
    )
    comment = client.post(
        f"/api/v1/reports/{report['id']}/reviews",
        json={
            "version": revised_report["version"],
            "revision_id": revised_report["revision"]["id"],
            "decision": "comment",
            "comment": "Comentario sin aprobar.",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert comment.status_code == 201
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/publish",
            json={"version": comment.get_json()["report"]["version"]},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 409
    )

    app.config["AI_ENABLED"] = False
    failed = generate(f"api-state-failed-{uuid.uuid4()}")
    app.config["AI_ENABLED"] = True
    assert failed["status"] == "failed"
    assert (
        client.post(
            f"/api/v1/reports/{failed['id']}/retry",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 422
    )
    retry_key = f"retry-failed-{uuid.uuid4()}"
    retry = client.post(
        f"/api/v1/reports/{failed['id']}/retry",
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": retry_key},
    )
    assert retry.status_code == 202
    assert (
        client.get(f"/api/v1/reports/{retry.get_json()['report']['id']}").get_json()["status"]
        == "ready"
    )
    assert (
        client.post(
            f"/api/v1/reports/{failed['id']}/retry",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": retry_key},
        ).status_code
        == 200
    )

    random_id = uuid.uuid4()
    for path in (
        f"/api/v1/reports/{random_id}/retry",
        f"/api/v1/reports/{random_id}/revisions",
        f"/api/v1/reports/{random_id}/reviews",
        f"/api/v1/reports/{random_id}/publish",
        f"/api/v1/reports/{random_id}/artifacts/{uuid.uuid4()}/download-link",
    ):
        assert client.post(path, json={}, headers={"X-CSRF-Token": csrf}).status_code == 404
    assert client.get(f"/api/v1/report-artifacts/{random_id}/download").status_code == 404
    artifact_id = report["artifacts"][0]["id"]
    assert (
        client.get(f"/api/v1/report-artifacts/{artifact_id}/download?expires=nope").status_code
        == 403
    )

    assert client.get(f"/api/v1/dossiers/{dossier_id}/alert-policy").status_code == 200
    policy = client.get(f"/api/v1/dossiers/{dossier_id}/alert-policy").get_json()
    updated_policy = client.patch(
        f"/api/v1/dossiers/{dossier_id}/alert-policy",
        json={
            "version": policy["version"],
            "signal_score_threshold": 80,
            "opportunity_deadline_days": 30,
            "meeting_upcoming_hours": 48,
            "cooldown_minutes": 120,
            "enabled_types": {"report_ready": True},
            "severity_map": {"report_ready": "success"},
            "timezone": "UTC",
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert updated_policy.status_code == 200
    assert (
        client.patch(
            f"/api/v1/dossiers/{dossier_id}/alert-policy",
            json={"version": policy["version"], "signal_score_threshold": 70},
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 409
    )
    for invalid in (
        {"signal_score_threshold": 101},
        {"risk_score_threshold": 101},
        {"opportunity_deadline_days": 366},
        {"meeting_upcoming_hours": 0},
        {"cooldown_minutes": 10081},
        {"enabled_types": []},
        {"timezone": "Invalid/Timezone"},
        {"quiet_hours_start": "22:00"},
    ):
        response = client.patch(
            f"/api/v1/dossiers/{dossier_id}/alert-policy",
            json={"version": updated_policy.get_json()["version"], **invalid},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 422

    preference_type = f"api.coverage.{uuid.uuid4().hex}"
    weekly = client.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": preference_type,
            "channels": {"in_app": True, "email": True},
            "digest_cadence": "weekly",
            "timezone": "UTC",
            "local_time": "09:30",
            "weekday": 2,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
            "minimum_severity": "warning",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert weekly.status_code == 200
    assert client.get("/api/v1/notification-preferences").status_code == 200
    stale_preference = client.patch(
        "/api/v1/notification-preferences",
        json={
            "notification_type": preference_type,
            "version": weekly.get_json()["version"] + 1,
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "off",
            "timezone": "UTC",
            "local_time": "08:00",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert stale_preference.status_code == 409
    for payload in (
        {"notification_type": " "},
        {"notification_type": "bad.channels", "channels": []},
        {
            "notification_type": "bad.cadence",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "monthly",
        },
        {
            "notification_type": "bad.weekday",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "weekly",
            "weekday": 9,
        },
        {
            "notification_type": "bad.time",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "instant",
            "local_time": "99:00",
        },
        {
            "notification_type": "bad.quiet",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "instant",
            "quiet_hours_start": "22:00",
        },
        {
            "notification_type": "bad.severity",
            "channels": {"in_app": True, "email": False},
            "digest_cadence": "instant",
            "minimum_severity": "urgent",
        },
    ):
        assert (
            client.patch(
                "/api/v1/notification-preferences",
                json=payload,
                headers={"X-CSRF-Token": csrf},
            ).status_code
            == 422
        )

    assert client.get("/api/v1/exports").status_code == 200
    assert (
        client.post(
            "/api/v1/exports",
            json={"dataset": "unknown"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"unknown-{uuid.uuid4()}"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/exports",
            json={"dataset": "reports", "dossier_id": "not-uuid"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"bad-dossier-{uuid.uuid4()}"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/exports",
            json={"dataset": "reports", "columns": ["secret"]},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"bad-column-{uuid.uuid4()}"},
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/exports/{random_id}").status_code == 404
    assert (
        client.post(
            f"/api/v1/exports/{random_id}/download-link",
            headers={"X-CSRF-Token": csrf},
        ).status_code
        == 404
    )
    assert client.get(f"/api/v1/export-artifacts/{random_id}/download").status_code == 404


def test_report_notification_export_end_to_end(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str], tmp_path: Path
) -> None:
    app, ids, password = oracle_stack
    storage = LocalObjectStorage(tmp_path / "reporting")
    app.extensions["object_storage"] = storage
    _enable_mock_ai(app, ids)

    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Reporting trazable")
    uploaded = client.post(
        f"/api/v1/dossiers/{dossier['id']}/documents",
        data={
            "file": (
                io.BytesIO(b"Hito verificable para el informe ejecutivo."),
                "evidencia-informe.txt",
                "text/plain",
            )
        },
        headers={"X-CSRF-Token": _csrf(client)},
        content_type="multipart/form-data",
    )
    assert uploaded.status_code == 202, uploaded.get_json()
    document_id = uploaded.get_json()["document"]["id"]
    search = client.get(f"/api/v1/dossiers/{dossier['id']}/search?q=verificable")
    assert search.status_code == 200 and search.get_json()["items"]
    chunk_id = search.get_json()["items"][0]["chunk_id"]
    evidence = client.post(
        f"/api/v1/documents/{document_id}/create-evidence",
        json={"chunk_id": chunk_id, "start": 0, "end": 20},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert evidence.status_code == 201

    key = f"report-test-{uuid.uuid4()}"
    created = client.post(
        f"/api/v1/dossiers/{dossier['id']}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["html", "json"], "classification": "internal"},
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert created.status_code == 202, created.get_json()
    report_id = created.get_json()["report"]["id"]
    detail = client.get(f"/api/v1/reports/{report_id}")
    assert detail.status_code == 200
    report = detail.get_json()
    assert report["status"] == "ready", report["error_code"]
    assert {item["format"] for item in report["artifacts"]} == {"html", "json"}
    assert [item["id"] for item in report["evidence"]] == [evidence.get_json()["id"]]
    assert report["revision"]["content"]["facts"][0]["evidence_ids"] == [evidence.get_json()["id"]]

    replay = client.post(
        f"/api/v1/dossiers/{dossier['id']}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["html", "json"], "classification": "internal"},
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert replay.status_code == 200
    assert replay.get_json()["report"]["id"] == report_id
    assert replay.get_json()["replayed"] is True
    conflict = client.post(
        f"/api/v1/dossiers/{dossier['id']}/reports",
        json={
            "template_key": "executive_dossier",
            "options": {"formats": ["json"], "classification": "internal"},
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert conflict.status_code == 409

    revision_id = report["revision"]["id"]
    reviewed = client.post(
        f"/api/v1/reports/{report_id}/reviews",
        json={
            "version": report["version"],
            "revision_id": revision_id,
            "decision": "approved",
            "comment": "Evidencia verificada.",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert reviewed.status_code == 201, reviewed.get_json()
    reviewed_report = reviewed.get_json()["report"]
    assert reviewed_report["status"] == "reviewed"
    stale = client.post(
        f"/api/v1/reports/{report_id}/reviews",
        json={
            "version": report["version"],
            "revision_id": revision_id,
            "decision": "comment",
            "comment": "Comentario obsoleto.",
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert stale.status_code == 409
    published = client.post(
        f"/api/v1/reports/{report_id}/publish",
        json={"version": reviewed_report["version"]},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert published.status_code == 200 and published.get_json()["status"] == "published"

    html_artifact = next(item for item in report["artifacts"] if item["format"] == "html")
    link = client.post(
        f"/api/v1/reports/{report_id}/artifacts/{html_artifact['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert link.status_code == 200
    downloaded = client.get(link.get_json()["url"])
    assert downloaded.status_code == 200
    assert b"Informe mock" in downloaded.data and b"<script" not in downloaded.data.lower()

    opportunity = client.post(
        f"/api/v1/dossiers/{dossier['id']}/opportunities",
        json={"title": "=SUM(A1:A2)", "description": "CSV seguro"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert opportunity.status_code == 201
    export_key = f"export-test-{uuid.uuid4()}"
    exported = client.post(
        "/api/v1/exports",
        json={"dataset": "opportunities", "dossier_id": dossier["id"]},
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": export_key},
    )
    assert exported.status_code == 202, exported.get_json()
    export = exported.get_json()["export"]
    assert export["status"] == "ready"
    export_link = client.post(
        f"/api/v1/exports/{export['id']}/download-link",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert export_link.status_code == 200
    csv_payload = client.get(export_link.get_json()["url"])
    assert csv_payload.status_code == 200
    assert b"'=SUM(A1:A2)" in csv_payload.data

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        membership_b = connection.execute(
            text("SELECT id FROM tenant_memberships WHERE tenant_id=:tenant AND user_id=:user"),
            {"tenant": ids["tenant_b"], "user": ids["user"]},
        ).scalar_one_or_none()
        if membership_b is None:
            membership_b = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO tenant_memberships"
                    "(id,tenant_id,user_id,status,accepted_at,settings,created_at,updated_at) "
                    "VALUES (:id,:tenant,:user,'active',now(),'{}',now(),now())"
                ),
                {"id": membership_b, "tenant": ids["tenant_b"], "user": ids["user"]},
            )
        role_b = connection.execute(
            text("SELECT id FROM roles WHERE tenant_id=:tenant AND key='owner'"),
            {"tenant": ids["tenant_b"]},
        ).scalar_one_or_none()
        if role_b is None:
            role_b = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO roles"
                    "(id,tenant_id,key,name,description,is_system,created_at,updated_at) "
                    "VALUES (:id,:tenant,'owner','Owner B','Owner B',true,now(),now())"
                ),
                {"id": role_b, "tenant": ids["tenant_b"]},
            )
        connection.execute(
            text(
                "INSERT INTO membership_roles(tenant_id,membership_id,role_id) "
                "VALUES (:tenant,:membership,:role) ON CONFLICT DO NOTHING"
            ),
            {"tenant": ids["tenant_b"], "membership": membership_b, "role": role_b},
        )
        connection.execute(
            text(
                "INSERT INTO role_permissions(tenant_id,role_id,permission_key) "
                "SELECT :tenant,:role,key FROM permissions ON CONFLICT DO NOTHING"
            ),
            {"tenant": ids["tenant_b"], "role": role_b},
        )
    engine.dispose()
    tenant_b_client = app.test_client()
    tenant_b_login = tenant_b_client.post(
        "/api/v1/auth/login",
        json={
            "email": "domain-owner@example.test",
            "password": password,
            "tenant_id": str(ids["tenant_b"]),
        },
        headers={"X-CSRF-Token": _csrf(tenant_b_client)},
    )
    assert tenant_b_login.status_code == 200
    assert tenant_b_client.get(f"/api/v1/reports/{report_id}").status_code == 404
    assert tenant_b_client.get(link.get_json()["url"]).status_code == 404
    assert tenant_b_client.get(f"/api/v1/exports/{export['id']}").status_code == 404

    inbox = client.get("/api/v1/notifications")
    assert inbox.status_code == 200 and inbox.get_json()["meta"]["unread_count"] >= 2
    first_notification = inbox.get_json()["data"][0]
    read = client.post(
        f"/api/v1/notifications/{first_notification['id']}/read",
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert read.status_code == 200 and read.get_json()["read_at"] is not None

    with (
        app.app_context(),
        tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])),
    ):
        first = create_notification(
            user_id=ids["user"],
            notification_type="test.dedupe",
            severity="info",
            title="Deduplicación",
            body="Misma intención.",
            dedupe_key="reporting-dedupe-key",
        )
        replayed = create_notification(
            user_id=ids["user"],
            notification_type="test.dedupe",
            severity="info",
            title="Deduplicación",
            body="Misma intención.",
            dedupe_key="reporting-dedupe-key",
        )
        assert first.notification.id == replayed.notification.id
        with pytest.raises(NotificationError):
            create_notification(
                user_id=ids["user"],
                notification_type="test.dedupe",
                severity="critical",
                title="Otra intención",
                body="No debe reutilizar la clave.",
                dedupe_key="reporting-dedupe-key",
            )
        db.session.rollback()
        report_artifacts = list(
            db.session.scalars(select(ReportArtifact).where(ReportArtifact.report_id == report_id))
        )
        data_export = db.session.get(DataExport, uuid.UUID(export["id"]))
        assert report_artifacts and data_export is not None and data_export.storage_key
        for key_name in [
            *(item.storage_key for item in report_artifacts),
            data_export.storage_key,
        ]:
            stored_path = tmp_path / "reporting" / key_name
            old = (datetime.now(UTC) - timedelta(days=2)).timestamp()
            os.utime(stored_path, (old, old))
        assert reconcile_storage_orphans(ids["tenant_a"]) == 0
        assert all(storage.get(item.storage_key).read() for item in report_artifacts)
        assert storage.get(data_export.storage_key).read()
        assert db.session.scalar(
            select(func.count(Notification.id)).where(Notification.user_id == ids["user"])
        )


def test_upgrade_from_0004_backfills_multidossier_evidence_mapping(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    app, _, _ = oracle_stack
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        downgrade(directory=migrations, revision="base")
        upgrade(directory=migrations, revision="20260710_0004")
    tenant_id, workspace_id, signal_id, evidence_id = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    dossier_ids = (uuid.uuid4(), uuid.uuid4())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO tenants(id,slug,name,status,locale,timezone,settings,created_at,updated_at) VALUES (:id,'snapshot-0004','Snapshot','active','es-ES','UTC','{}',now(),now())"
            ),
            {"id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces(id,tenant_id,slug,name,status,is_default,settings,created_at,updated_at) VALUES (:id,:tenant,'main','Main','active',true,'{}',now(),now())"
            ),
            {"id": workspace_id, "tenant": tenant_id},
        )
        for index, dossier_id in enumerate(dossier_ids):
            connection.execute(
                text(
                    "INSERT INTO strategic_dossiers(id,tenant_id,workspace_id,title,description,dossier_type,status,strategic_goal,geography,sectors,languages,scoring_config,health_score,opportunity_score,risk_score,score_explanation,version,synthetic_data,created_at,updated_at) VALUES (:id,:tenant,:workspace,:title,'','custom','draft','','[]','[]','[]','{}',0,0,0,'{}',1,false,now(),now())"
                ),
                {
                    "id": dossier_id,
                    "tenant": tenant_id,
                    "workspace": workspace_id,
                    "title": f"Dossier {index}",
                },
            )
        connection.execute(
            text(
                "INSERT INTO signals(id,tenant_id,provider,external_id,title,summary,source_type,source_name,ingested_at,tags,entities,categories,raw_hash,credibility,raw_payload,created_at,updated_at) VALUES (:id,:tenant,'snapshot','multi','Multi','','report','Snapshot',now(),'[]','[]','[]',:hash,70,'{}',now(),now())"
            ),
            {
                "id": signal_id,
                "tenant": tenant_id,
                "hash": hashlib.sha256(b"snapshot-multi").digest(),
            },
        )
        for dossier_id in dossier_ids:
            connection.execute(
                text(
                    "INSERT INTO dossier_signals(id,tenant_id,dossier_id,signal_id,status,relevance,novelty,confidence,strategic_impact,why_it_matters,recommended_action,feedback,triage_version,created_at,updated_at) VALUES (:id,:tenant,:dossier,:signal,'new',0,0,0,0,'','','{}',1,now(),now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tenant": tenant_id,
                    "dossier": dossier_id,
                    "signal": signal_id,
                },
            )
        connection.execute(
            text(
                "INSERT INTO evidence(id,tenant_id,signal_id,extract,locator,checksum,classification,provenance,created_at,updated_at) VALUES (:id,:tenant,:signal,'Snapshot','{}',:checksum,'internal','{}',now(),now())"
            ),
            {
                "id": evidence_id,
                "tenant": tenant_id,
                "signal": signal_id,
                "checksum": hashlib.sha256(b"snapshot-evidence").digest(),
            },
        )
    with app.app_context():
        upgrade(directory=migrations)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM evidence_dossiers WHERE evidence_id=:id"),
                {"id": evidence_id},
            ).scalar_one()
            == 2
        )
    engine.dispose()
