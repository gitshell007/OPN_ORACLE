"""HTTP + PostgreSQL real for G-11 pliego acquisition rework (000173).

Cubre con handler real de ``oracle.document.process``:

1. POST válido → 202 ``procesando`` (antes del job no preferido ni subido)
2. Job real con PDF válido → ready + ``subido`` + evento terminal único
3. Fichero inválido vía mismo handler → ``no_disponible`` sin éxito falso
4. Retry/idempotencia: no duplica terminales ni degrada ready por auto
5. Fallo 403 durable sin blob; GET en «nueva sesión» conserva reason_code
6. Éxito posterior reemplaza fallo; tenant isolation intacto

Requires disposable local PG:

  ORACLE_RUN_INTEGRATION=1
  TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL
  TEST_REDIS_URL
"""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from flask import g
from flask_migrate import upgrade
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from opn_oracle import create_app
from opn_oracle.auth import permissions
from opn_oracle.auth.passwords import PasswordHasher
from opn_oracle.documents.storage import LocalObjectStorage
from opn_oracle.extensions import db
from opn_oracle.jobs import tasks as job_tasks
from opn_oracle.oracle import pliego_acquisition_routes
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.pliego_acquisition import (
    ATTEMPTS_KEY,
    AUDIT_MANUAL_FAILURE,
    AUDIT_MANUAL_SUCCESS,
    AUDIT_UPLOAD_RECEIVED,
    SOURCE_MANUAL,
    get_download_attempt,
    record_download_failure,
    set_acquisition_meta,
)
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE_MARKERS = ("test", "aislados", "ci", "pliego", "g11")


def _assert_disposable(url: str, *, env_name: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0]
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "postgres", "pg"}:
        raise RuntimeError(f"{env_name} host={host!r} not disposable")
    if not db_name or not any(m in db_name.lower() for m in _DISPOSABLE_MARKERS):
        raise RuntimeError(f"{env_name} database={db_name!r} not disposable")
    return url


def _require_pg_urls() -> tuple[str, str, str]:
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL") or migration_url
    redis_url = os.getenv("TEST_REDIS_URL") or "redis://127.0.0.1:6379/15"
    forced = os.getenv("ORACLE_RUN_INTEGRATION") == "1"
    if not migration_url:
        detail = "TEST_DATABASE_URL required for pliego-acquisition PG HTTP gates"
        if forced:
            pytest.fail(detail)
        pytest.skip(detail)
    return (
        _assert_disposable(migration_url, env_name="TEST_DATABASE_URL"),
        _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL"),
        redis_url,
    )


def _valid_text_pcap_pdf() -> bytes:
    """PDF mínimo con texto extraíble (aceptado por PDFParser + pypdf)."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=144)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 40 100 Td (EXTRACTO DEL PCAP G11) Tj ET")
    page[NameObject("/Contents")] = stream
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _invalid_pdf_bytes() -> bytes:
    """Firma PDF pero sin estructura parseable con texto."""
    return b"%PDF-1.4\n% corrupt not a real body\n"


@contextmanager
def _authenticated_http(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    perms: frozenset[str] | None = None,
) -> Iterator[None]:
    granted = perms or frozenset(
        {
            "documents.read",
            "documents.manage",
            "dossier.read",
            "dossier.write",
            "opportunity.read",
            "opportunity.write",
        }
    )
    principal = type("Principal", (), {"id": user_id, "is_authenticated": True})()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(pliego_acquisition_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda _user_id, _active_tenant_id: granted,
    )
    before = app.before_request_funcs.get(None, [])
    index = next(
        (
            i
            for i, function in enumerate(before)
            if getattr(function, "__name__", "") == "protect_csrf_and_install_identity"
        ),
        None,
    )
    original = before[index] if index is not None else None

    def install_identity() -> None:
        g.active_tenant_id = tenant_id
        manager = tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id))
        manager.__enter__()
        g.auth_tenant_context_manager = manager

    if index is not None:
        before[index] = install_identity
    else:
        app.before_request_funcs[None] = [install_identity, *before]
    try:
        yield
    finally:
        if index is not None and original is not None:
            before[index] = original
        else:
            app.before_request_funcs[None] = before


@pytest.fixture
def pliego_pg(tmp_path: Path) -> Iterator[tuple[Any, dict[str, uuid.UUID]]]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1 for real PG pliego gates")
    migration_url, runtime_url, redis_url = _require_pg_urls()
    storage = tmp_path / "docs"
    storage.mkdir()

    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g11-pliego-rework-secret-key-32bx!!",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "OPENAPI_ENABLED": False,
            "DOCUMENTS_ENABLED": True,
            "DOCUMENT_STORAGE_BACKEND": "local",
            "DOCUMENT_LOCAL_ROOT": str(storage),
            "DOCUMENT_SCANNER_MODE": "noop",
            "DOCUMENT_MAX_BYTES": 5 * 1024 * 1024,
            "DOCUMENT_TENANT_QUOTA_BYTES": 50 * 1024 * 1024,
            # Eager off: el test controla el job real vía handler.
            "CELERY_TASK_ALWAYS_EAGER": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    app.extensions["object_storage"] = LocalObjectStorage(storage)
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    membership_a = uuid.uuid4()
    membership_b = uuid.uuid4()
    role_a = uuid.uuid4()
    role_b = uuid.uuid4()
    workspace_a = uuid.uuid4()
    workspace_b = uuid.uuid4()
    dossier_a = uuid.uuid4()
    dossier_b = uuid.uuid4()
    password = "g11-pliego-2026!!"
    ph = PasswordHasher().hash(password)
    now = datetime.now(UTC)

    engine = create_engine(migration_url, poolclass=NullPool)
    with engine.begin() as conn:
        for tid, slug, name in (
            (tenant_a, f"g11r-a-{tenant_a.hex[:8]}", "G11R A"),
            (tenant_b, f"g11r-b-{tenant_b.hex[:8]}", "G11R B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenants(id, slug, name, status, locale, timezone, settings, "
                    "created_at, updated_at) VALUES "
                    "(:id, :slug, :name, 'active', 'es-ES', 'UTC', '{}'::jsonb, now(), now())"
                ),
                {"id": tid, "slug": slug, "name": name},
            )
        for uid, email, display in (
            (user_a, f"g11r-a-{user_a.hex[:8]}@example.test", "G11R Owner A"),
            (user_b, f"g11r-b-{user_b.hex[:8]}@example.test", "G11R Owner B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO users(id, email, display_name, password_hash, status, "
                    "email_verified_at, created_at, updated_at) VALUES "
                    "(:id, :email, :dn, :ph, 'active', now(), now(), now())"
                ),
                {"id": uid, "email": email, "dn": display, "ph": ph},
            )
        for wid, tid, slug in (
            (workspace_a, tenant_a, f"ws-a-{workspace_a.hex[:6]}"),
            (workspace_b, tenant_b, f"ws-b-{workspace_b.hex[:6]}"),
        ):
            conn.execute(
                text(
                    "INSERT INTO workspaces(id, tenant_id, slug, name, status, is_default, "
                    "settings, created_at, updated_at) VALUES "
                    "(:id, :t, :slug, :name, 'active', true, '{}'::jsonb, now(), now())"
                ),
                {"id": wid, "t": tid, "slug": slug, "name": f"WS {slug}"},
            )
        for mid, tid, uid in (
            (membership_a, tenant_a, user_a),
            (membership_b, tenant_b, user_b),
        ):
            conn.execute(
                text(
                    "INSERT INTO tenant_memberships(id, tenant_id, user_id, status, accepted_at, "
                    "settings, created_at, updated_at) VALUES "
                    "(:id, :t, :u, 'active', now(), '{}'::jsonb, now(), now())"
                ),
                {"id": mid, "t": tid, "u": uid},
            )
        for rid, tid in ((role_a, tenant_a), (role_b, tenant_b)):
            conn.execute(
                text(
                    "INSERT INTO roles(id, tenant_id, key, name, description, is_system, "
                    "created_at, updated_at) VALUES "
                    "(:id, :t, 'owner', 'Owner', 'Owner', true, now(), now())"
                ),
                {"id": rid, "t": tid},
            )
            conn.execute(
                text(
                    "INSERT INTO membership_roles(tenant_id, membership_id, role_id) "
                    "VALUES (:t, :m, :r)"
                ),
                {
                    "t": tid,
                    "m": membership_a if tid == tenant_a else membership_b,
                    "r": rid,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO role_permissions(tenant_id, role_id, permission_key) "
                    "SELECT :t, :r, key FROM permissions ON CONFLICT DO NOTHING"
                ),
                {"t": tid, "r": rid},
            )
        for did, tid, wid, uid, title in (
            (dossier_a, tenant_a, workspace_a, user_a, "G11R dossier A"),
            (dossier_b, tenant_b, workspace_b, user_b, "G11R dossier B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO strategic_dossiers("
                    "id, tenant_id, workspace_id, title, description, dossier_type, status, "
                    "strategic_goal, geography, sectors, languages, owner_user_id, "
                    "scoring_config, profile_config, health_score, opportunity_score, "
                    "risk_score, score_explanation, version, synthetic_data, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":id, :t, :w, :title, '', 'procurement', 'active', '', '[]'::jsonb, "
                    "'[]'::jsonb, '[]'::jsonb, :u, '{}'::jsonb, '{}'::jsonb, 50, 0, 0, "
                    "'{}'::jsonb, 1, false, :now, :now)"
                ),
                {
                    "id": did,
                    "t": tid,
                    "w": wid,
                    "title": title,
                    "u": uid,
                    "now": now,
                },
            )
    engine.dispose()

    ids = {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "user_a": user_a,
        "user_b": user_b,
        "dossier_a": dossier_a,
        "dossier_b": dossier_b,
    }
    yield app, ids


def _audit_count(engine, *, tenant_id: uuid.UUID, action: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM audit_events WHERE tenant_id = :t AND action = :a"),
                {"t": tenant_id, "a": action},
            ).scalar_one()
        )


def _doc_meta(engine, *, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> dict[str, Any]:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id, status, metadata FROM documents "
                    "WHERE tenant_id = :t AND dossier_id = :d "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": tenant_id, "d": dossier_id},
            )
            .mappings()
            .first()
        )
    assert row is not None
    return dict(row)


def _run_document_process_job(
    app: Any,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    job_id: str,
) -> dict[str, Any]:
    """Ejecuta el handler real de oracle.document.process (no servicio directo)."""
    with app.app_context(), tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
        job = db.session.get(BackgroundJob, uuid.UUID(job_id))
        assert job is not None
        assert job.job_type == "oracle.document.process"
        payload = dict(job.input_payload or {})
        try:
            result = job_tasks._process_document(payload, job)
            return {"ok": True, "result": result}
        except job_tasks.PermanentJobError as error:
            return {"ok": False, "error": str(error)}


def test_pg_post_procesando_then_job_ready_subido(
    pliego_pg: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1-2: POST -> procesando; job real -> subido + evento terminal unico; GET prefiere."""
    app, ids = pliego_pg
    client = app.test_client()
    dossier_id = ids["dossier_a"]
    tenant_id = ids["tenant_a"]
    user_id = ids["user_a"]
    migration_url, _, _ = _require_pg_urls()
    engine = create_engine(migration_url, poolclass=NullPool)

    # Evitar que publish_job dispare broker: el test invoca el handler a mano.
    monkeypatch.setattr(
        "opn_oracle.oracle.pliego_acquisition.publish_job",
        lambda _job: True,
    )

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        resp = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert resp.status_code == 200
        assert resp.get_json()["overall_status"] == "no_disponible"
        assert resp.get_json()["preferred_document"] is None

        payload = _valid_text_pcap_pdf()
        up = client.post(
            f"/api/v1/dossiers/{dossier_id}/pliego-pcap",
            data={
                "classification": "internal",
                "file": (io.BytesIO(payload), "PCAP_G11_manual.pdf", "application/pdf"),
            },
            content_type="multipart/form-data",
        )
        assert up.status_code == 202, up.get_data(as_text=True)
        up_body = up.get_json()
        assert up_body["acquisition_status"] == "procesando"
        assert up_body["job_id"]
        assert "éxito terminal" in up_body["message"].casefold() or "procesamiento" in (
            up_body["message"].casefold()
        )
        assert up_body["document"]["filename"] == "PCAP_G11_manual.pdf"
        job_id = up_body["job_id"]

        # Antes del job: no preferido ni subido
        mid = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert mid.status_code == 200
        mid_body = mid.get_json()
        assert mid_body["overall_status"] == "procesando"
        assert mid_body["preferred_document"] is None
        assert mid_body["overall_status"] != "subido"
        assert any(a.get("status") == "procesando" for a in mid_body["acquisitions"])

        doc_row = _doc_meta(engine, tenant_id=tenant_id, dossier_id=dossier_id)
        pliego_meta = (doc_row["metadata"] or {}).get("pliego_acquisition") or {}
        assert pliego_meta.get("status") == "procesando"
        assert pliego_meta.get("source") == SOURCE_MANUAL
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_UPLOAD_RECEIVED) == 1
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_SUCCESS) == 0

        # Job real
        outcome = _run_document_process_job(
            app, tenant_id=tenant_id, user_id=user_id, job_id=job_id
        )
        assert outcome["ok"] is True, outcome

        doc_row2 = _doc_meta(engine, tenant_id=tenant_id, dossier_id=dossier_id)
        assert doc_row2["status"] == "ready"
        pliego_meta2 = (doc_row2["metadata"] or {}).get("pliego_acquisition") or {}
        assert pliego_meta2.get("status") == "subido"
        assert pliego_meta2.get("terminal_result") == "success"
        assert pliego_meta2.get("updated_at")
        assert pliego_meta2.get("updated_at") != pliego_meta.get("updated_at")

        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_SUCCESS) == 1
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_UPLOAD_RECEIVED) == 1

        # Idempotencia: re-ejecutar handler no duplica evento terminal
        outcome2 = _run_document_process_job(
            app, tenant_id=tenant_id, user_id=user_id, job_id=job_id
        )
        assert outcome2["ok"] is True
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_SUCCESS) == 1

        final = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert final.status_code == 200
        final_body = final.get_json()
        assert final_body["overall_status"] == "subido"
        assert final_body["preferred_document"] is not None
        assert final_body["preferred_document"]["filename"] == "PCAP_G11_manual.pdf"

        # Auto retry no degrada ready manual
        from opn_oracle.documents.models import Document

        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
            doc = db.session.get(Document, uuid.UUID(str(doc_row2["id"])))
            assert doc is not None
            set_acquisition_meta(
                doc,
                {
                    "status": "no_disponible",
                    "source": "placsp_codice",
                    "reason": "auto retry peor",
                },
            )
            db.session.commit()
            assert acquisition_status_from_doc(doc) == "subido"

    engine.dispose()


def acquisition_status_from_doc(doc: Any) -> str:
    return str(((doc.metadata_json or {}).get("pliego_acquisition") or {}).get("status") or "")


def test_pg_invalid_file_job_no_disponible(
    pliego_pg: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3: parse failure vía handler real → no_disponible, nunca preferido, sin éxito."""
    app, ids = pliego_pg
    client = app.test_client()
    dossier_id = ids["dossier_a"]
    tenant_id = ids["tenant_a"]
    user_id = ids["user_a"]
    migration_url, _, _ = _require_pg_urls()
    engine = create_engine(migration_url, poolclass=NullPool)

    monkeypatch.setattr(
        "opn_oracle.oracle.pliego_acquisition.publish_job",
        lambda _job: True,
    )

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        # Magic de PDF pasa; el parser no extrae texto → fallo de proceso.
        up = client.post(
            f"/api/v1/dossiers/{dossier_id}/pliego-pcap",
            data={
                "classification": "internal",
                "file": (
                    io.BytesIO(_invalid_pdf_bytes()),
                    "PCAP_G11_bad.pdf",
                    "application/pdf",
                ),
            },
            content_type="multipart/form-data",
        )
        assert up.status_code == 202, up.get_data(as_text=True)
        up_body = up.get_json()
        assert up_body["acquisition_status"] == "procesando"
        job_id = up_body["job_id"]
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_UPLOAD_RECEIVED) == 1
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_SUCCESS) == 0

        outcome = _run_document_process_job(
            app, tenant_id=tenant_id, user_id=user_id, job_id=job_id
        )
        assert outcome["ok"] is False

        doc_row = _doc_meta(engine, tenant_id=tenant_id, dossier_id=dossier_id)
        assert doc_row["status"] in {"failed", "quarantined"}
        pliego_meta = (doc_row["metadata"] or {}).get("pliego_acquisition") or {}
        assert pliego_meta.get("status") == "no_disponible"
        assert pliego_meta.get("terminal_result") == "failure"
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_FAILURE) == 1
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_SUCCESS) == 0

        # Idempotencia del fallo terminal
        _run_document_process_job(app, tenant_id=tenant_id, user_id=user_id, job_id=job_id)
        assert _audit_count(engine, tenant_id=tenant_id, action=AUDIT_MANUAL_FAILURE) == 1

        body = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition").get_json()
        assert body["preferred_document"] is None
        assert body["overall_status"] != "subido"
        assert any(
            a.get("status") == "no_disponible" and a.get("kind") == "manual"
            for a in body["acquisitions"]
        )

    engine.dispose()


def test_pg_durable_download_failure_survives_session(
    pliego_pg: tuple[Any, dict[str, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5-6: 403/timeout sin blob queda durable; exito posterior lo supera; isolation."""
    app, ids = pliego_pg
    client = app.test_client()
    dossier_id = ids["dossier_a"]
    tenant_id = ids["tenant_a"]
    user_id = ids["user_a"]
    uri = "https://contrataciondelestado.es/codice/PCAP_g11r.pdf"
    migration_url, _, _ = _require_pg_urls()
    engine = create_engine(migration_url, poolclass=NullPool)

    # Pin con documents[] para que GET resuelva por URI
    pin_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO evidence("
                "id, tenant_id, source_kind, extract, locator, checksum, classification, "
                "provenance, version, created_at, updated_at"
                ") VALUES ("
                ":id, :t, 'procurement', 'pin g11r', '{}'::jsonb, "
                ":checksum, 'internal', "
                "CAST(:prov AS jsonb), 1, now(), now())"
            ),
            {
                "id": evidence_id,
                "t": tenant_id,
                "checksum": bytes.fromhex("ab" * 32),
                "prov": '{"source_kind":"procurement","folder_id":"g11r"}',
            },
        )
        conn.execute(
            text(
                "INSERT INTO dossier_procurement_items("
                "id, tenant_id, dossier_id, kind, folder_id, snapshot, evidence_id, "
                "pinned_by_user_id, created_at, updated_at"
                ") VALUES ("
                ":id, :t, :d, 'tender', :folder, CAST(:snap AS jsonb), :ev, "
                ":u, now(), now())"
            ),
            {
                "id": pin_id,
                "t": tenant_id,
                "d": dossier_id,
                "folder": f"folder-{pin_id.hex[:8]}",
                "ev": evidence_id,
                "u": user_id,
                "snap": (
                    '{"documents":[{"uri":"'
                    + uri
                    + '","file_name":"PCAP.pdf","doc_type":"legal"}]}'
                ),
            },
        )

    with app.app_context(), tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
        entry = record_download_failure(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            reference={"uri": uri, "file_name": "PCAP.pdf"},
            reason_code="http_403_waf",
            reason="Descarga bloqueada (HTTP 403/WAF). Suba el PCAP manualmente.",
            http_status=403,
            procurement_item_id=pin_id,
        )
        db.session.commit()
        assert entry["reason_code"] == "http_403_waf"
        assert entry["attempt"] == 1

        # Contar documentos: no se creó blob falso
        n_docs = db.session.execute(
            text("SELECT count(*) FROM documents WHERE tenant_id = :t AND dossier_id = :d"),
            {"t": tenant_id, "d": dossier_id},
        ).scalar_one()
        assert int(n_docs) == 0

        # profile_config durable
        cfg = db.session.execute(
            text("SELECT profile_config FROM strategic_dossiers WHERE id = :d AND tenant_id = :t"),
            {"d": dossier_id, "t": tenant_id},
        ).scalar_one()
        attempts = (cfg or {}).get(ATTEMPTS_KEY) or {}
        assert attempts[uri]["reason_code"] == "http_403_waf"
        assert attempts[uri]["http_status"] == 403

    # «Nueva sesión»: GET limpio conserva reason_code exacto
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        resp = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["overall_status"] == "no_disponible"
        match = next(a for a in body["acquisitions"] if a.get("source_uri") == uri)
        assert match["reason_code"] == "http_403_waf"
        assert match["http_status"] == 403
        assert "403" in match["reason"] or "WAF" in match["reason"]

        # Timeout actualiza el último intento
        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
            record_download_failure(
                dossier_id=dossier_id,
                tenant_id=tenant_id,
                reference={"uri": uri, "file_name": "PCAP.pdf"},
                reason_code="timeout",
                reason="Tiempo de espera agotado al descargar el pliego. Suba el PCAP manualmente.",
                http_status=None,
                procurement_item_id=pin_id,
            )
            db.session.commit()
            durable = get_download_attempt(
                tenant_id=tenant_id, dossier_id=dossier_id, source_uri=uri
            )
            assert durable is not None
            assert durable["reason_code"] == "timeout"
            assert durable["attempt"] == 2

        resp2 = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        match2 = next(a for a in resp2.get_json()["acquisitions"] if a.get("source_uri") == uri)
        assert match2["reason_code"] == "timeout"

        # Éxito posterior reemplaza el fallo (sin documento real: marcamos attempt)
        from opn_oracle.oracle.pliego_acquisition import clear_download_attempt_on_success

        with tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id)):
            clear_download_attempt_on_success(
                dossier_id=dossier_id,
                tenant_id=tenant_id,
                source_uri=uri,
                status="descargado",
            )
            db.session.commit()
            durable_ok = get_download_attempt(
                tenant_id=tenant_id, dossier_id=dossier_id, source_uri=uri
            )
            assert durable_ok is not None
            assert durable_ok["status"] == "descargado"
            assert durable_ok["reason_code"] == "downloaded"

    # Tenant isolation
    with (
        app.app_context(),
        _authenticated_http(
            app,
            monkeypatch,
            user_id=ids["user_b"],
            tenant_id=ids["tenant_b"],
        ),
    ):
        resp_b = client.get(f"/api/v1/dossiers/{dossier_id}/pliego-acquisition")
        assert resp_b.status_code == 404

    with (
        app.app_context(),
        _authenticated_http(
            app,
            monkeypatch,
            user_id=user_id,
            tenant_id=tenant_id,
            perms=frozenset({"documents.read", "dossier.read"}),
        ),
    ):
        up = client.post(
            f"/api/v1/dossiers/{dossier_id}/pliego-pcap",
            data={
                "file": (io.BytesIO(b"hola"), "x.txt", "text/plain"),
            },
            content_type="multipart/form-data",
        )
        assert up.status_code in {403, 401}

    engine.dispose()
