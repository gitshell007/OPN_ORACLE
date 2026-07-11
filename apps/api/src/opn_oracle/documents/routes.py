"""Tenant-safe upload, download, search and evidence APIs."""

from __future__ import annotations

import uuid
from contextlib import suppress
from datetime import datetime
from typing import Any, BinaryIO, cast

from apiflask import APIBlueprint
from flask import current_app, g, request, send_file
from flask_login import current_user
from sqlalchemy import func, select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.documents.models import Document, DocumentChunk
from opn_oracle.documents.service import (
    DocumentError,
    create_evidence,
    create_upload,
    new_reprocess_version,
    soft_delete,
)
from opn_oracle.documents.storage import StorageError
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.oracle.models import Evidence, StrategicDossier
from opn_oracle.oracle.policy import dossier_access_clause, dossier_accessible

bp = APIBlueprint("documents", __name__, url_prefix="/api/v1", tag="Documentos")


@bp.before_request
def require_documents_enabled() -> Any:
    if not current_app.config["DOCUMENTS_ENABLED"]:
        return problem_response(
            503, detail="El módulo documental está deshabilitado.", code="documents_disabled"
        )
    return None


def _dossier(dossier_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    row = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id, StrategicDossier.tenant_id == g.active_tenant_id
        )
    )
    if row is None or not dossier_accessible(db.session(), row, current_user.id, write=write):
        return None
    return row


def _document(
    document_id: uuid.UUID, *, write: bool, include_deleted: bool = False
) -> Document | None:
    row = db.session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == g.active_tenant_id)
    )
    if row is None or (row.status == "deleted" and not include_deleted):
        return None
    if _dossier(row.dossier_id, write=write) is None:
        return None
    return row


def _serialize(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "dossier_id": str(document.dossier_id),
        "filename": document.original_filename,
        "media_type": document.media_type,
        "byte_size": document.byte_size,
        "checksum": document.checksum.hex(),
        "classification": document.classification,
        "status": document.status,
        "scan_status": document.scan_status,
        "safe_error_code": document.safe_error_code,
        "current_version_id": str(document.current_version_id)
        if document.current_version_id
        else None,
        "version": document.version,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


@bp.post("/dossiers/<uuid:dossier_id>/documents")
@require_permission("documents.manage")
def upload_document(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return problem_response(422, detail="Selecciona un archivo.", code="validation_error")
    try:
        document, version = create_upload(
            tenant_id=g.active_tenant_id,
            dossier_id=dossier_id,
            uploader_id=current_user.id,
            filename=upload.filename,
            media_type=str(upload.mimetype or "application/octet-stream").lower(),
            source=cast(BinaryIO, upload.stream),
            classification=str(request.form.get("classification", "internal")),
        )
        job = stage_job(
            "oracle.document.process",
            payload={"document_id": str(document.id), "version_id": str(version.id)},
            idempotency_key=f"document-process-{version.id}",
            requested_by_user_id=current_user.id,
            dossier_id=dossier_id,
            resource_type="document",
            resource_id=document.id,
        )
        db.session.commit()
        publish_job(job)
    except DocumentError as error:
        return problem_response(422, detail=str(error), code="document_rejected")
    except Exception:
        db.session.rollback()
        if "document" in locals():
            with suppress(Exception):
                current_app.extensions["object_storage"].delete(document.storage_key)
        raise
    return {"document": _serialize(document), "job_id": str(job.id)}, 202


@bp.get("/dossiers/<uuid:dossier_id>/documents")
@require_permission("documents.read")
def list_documents(dossier_id: uuid.UUID) -> Any:
    if _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    rows = db.session.scalars(
        select(Document)
        .where(
            Document.tenant_id == g.active_tenant_id,
            Document.dossier_id == dossier_id,
            Document.status != "deleted",
        )
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    return {"items": [_serialize(item) for item in rows]}


@bp.get("/documents/<uuid:document_id>")
@require_permission("documents.read")
def get_document(document_id: uuid.UUID) -> Any:
    document = _document(document_id, write=False)
    if document is None:
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    return _serialize(document)


@bp.get("/documents/<uuid:document_id>/download")
@require_permission("documents.read")
def download_document(document_id: uuid.UUID) -> Any:
    document = _document(document_id, write=False)
    if document is None or document.status != "ready" or document.scan_status != "clean":
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    try:
        source = current_app.extensions["object_storage"].get(document.storage_key)
    except StorageError:
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    return send_file(
        source,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=document.original_filename,
        max_age=0,
    )


@bp.delete("/documents/<uuid:document_id>")
@require_permission("documents.manage")
def delete_document(document_id: uuid.UUID) -> Any:
    document = _document(document_id, write=True)
    if document is None:
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    if document.legal_hold:
        return problem_response(
            409, detail="El documento está sujeto a conservación legal.", code="legal_hold"
        )
    soft_delete(document, current_user.id)
    return "", 204


@bp.post("/documents/<uuid:document_id>/reprocess")
@require_permission("documents.manage")
def reprocess_document(document_id: uuid.UUID) -> Any:
    document = _document(document_id, write=True)
    if document is None or document.status == "quarantined":
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    version = new_reprocess_version(document)
    job = stage_job(
        "oracle.document.process",
        payload={"document_id": str(document.id), "version_id": str(version.id)},
        idempotency_key=f"document-process-{version.id}",
        requested_by_user_id=current_user.id,
        dossier_id=document.dossier_id,
        resource_type="document",
        resource_id=document.id,
    )
    db.session.commit()
    publish_job(job)
    return {"document": _serialize(document), "job_id": str(job.id)}, 202


def _search(dossier_id: uuid.UUID | None) -> Any:
    query_text = request.args.get("q", "").strip()
    if not 2 <= len(query_text) <= 200:
        return problem_response(
            422, detail="La consulta debe tener entre 2 y 200 caracteres.", code="validation_error"
        )
    try:
        page, size = (
            max(1, int(request.args.get("page", "1"))),
            min(50, max(1, int(request.args.get("size", "20")))),
        )
    except ValueError:
        return problem_response(422, detail="Paginación no válida.", code="validation_error")
    if dossier_id is not None and _dossier(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no disponible.", code="not_found")
    tsquery = func.plainto_tsquery("simple", query_text)
    criteria = [
        DocumentChunk.tenant_id == g.active_tenant_id,
        Document.status == "ready",
        Document.current_version_id == DocumentChunk.document_version_id,
        DocumentChunk.search_vector.op("@@")(tsquery),
        dossier_access_clause(tenant_id=g.active_tenant_id, user_id=current_user.id),
    ]
    if dossier_id is not None:
        criteria.append(DocumentChunk.dossier_id == dossier_id)
    raw_document_id = request.args.get("document_id")
    if raw_document_id:
        try:
            criteria.append(DocumentChunk.document_id == uuid.UUID(raw_document_id))
        except ValueError:
            return problem_response(422, detail="document_id no válido.", code="validation_error")
    media_type = request.args.get("media_type")
    if media_type:
        criteria.append(Document.media_type == media_type[:120])
    created_from = request.args.get("created_from")
    if created_from:
        try:
            criteria.append(Document.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            return problem_response(422, detail="created_from no válido.", code="validation_error")
    statement = (
        select(
            DocumentChunk,
            Document,
            func.ts_rank_cd(DocumentChunk.search_vector, tsquery).label("rank"),
            func.ts_headline(
                "simple",
                DocumentChunk.text_content,
                tsquery,
                "MaxFragments=2,MaxWords=30,MinWords=8",
            ).label("snippet"),
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(StrategicDossier, StrategicDossier.id == DocumentChunk.dossier_id)
        .where(*criteria)
        .order_by(func.ts_rank_cd(DocumentChunk.search_vector, tsquery).desc(), DocumentChunk.id)
        .offset((page - 1) * size)
        .limit(size)
    )
    items = []
    for chunk, document, rank, snippet in db.session.execute(statement):
        items.append(
            {
                "chunk_id": str(chunk.id),
                "document_id": str(document.id),
                "dossier_id": str(chunk.dossier_id),
                "filename": document.original_filename,
                "media_type": document.media_type,
                "classification": document.classification,
                "rank": float(rank),
                "snippet": str(snippet),
                "text": chunk.text_content[:4000],
                "locator": chunk.locator,
            }
        )
    return {"items": items, "page": page, "size": size}


@bp.get("/documents/search")
@require_permission("documents.read")
def global_search() -> Any:
    return _search(None)


@bp.get("/dossiers/<uuid:dossier_id>/search")
@require_permission("documents.read")
def dossier_search(dossier_id: uuid.UUID) -> Any:
    return _search(dossier_id)


@bp.post("/documents/<uuid:document_id>/create-evidence")
@require_permission("documents.manage")
def create_document_evidence(document_id: uuid.UUID) -> Any:
    document = _document(document_id, write=True)
    payload = request.get_json(silent=True)
    if document is None or document.status != "ready" or not isinstance(payload, dict):
        return problem_response(404, detail="Documento no disponible.", code="not_found")
    try:
        chunk_id = uuid.UUID(str(payload.get("chunk_id", "")))
        start, end = int(payload.get("start", 0)), int(payload.get("end", 0))
    except (TypeError, ValueError):
        return problem_response(422, detail="Rango no válido.", code="validation_error")
    chunk = db.session.scalar(
        select(DocumentChunk).where(
            DocumentChunk.id == chunk_id,
            DocumentChunk.document_id == document.id,
            DocumentChunk.tenant_id == g.active_tenant_id,
        )
    )
    if chunk is None:
        return problem_response(404, detail="Fragmento no disponible.", code="not_found")
    try:
        evidence = create_evidence(document, chunk, start=start, end=end)
    except DocumentError as error:
        return problem_response(422, detail=str(error), code="validation_error")
    return {"id": str(evidence.id), "extract": evidence.extract, "locator": evidence.locator}, 201


@bp.get("/documents/evidence/<uuid:evidence_id>")
@require_permission("documents.read")
def get_evidence(evidence_id: uuid.UUID) -> Any:
    evidence = db.session.scalar(
        select(Evidence).where(Evidence.id == evidence_id, Evidence.tenant_id == g.active_tenant_id)
    )
    if evidence is None or evidence.source_kind != "document" or evidence.document_id is None:
        return problem_response(404, detail="Evidencia no disponible.", code="not_found")
    document = _document(evidence.document_id, write=False, include_deleted=True)
    if document is None:
        return problem_response(404, detail="Evidencia no disponible.", code="not_found")
    return {
        "id": str(evidence.id),
        "document_id": str(evidence.document_id),
        "document_version_id": str(evidence.document_version_id),
        "document_chunk_id": str(evidence.document_chunk_id),
        "filename": document.original_filename,
        "extract": evidence.extract,
        "locator": evidence.locator,
        "classification": evidence.classification,
        "checksum": evidence.checksum.hex(),
        "created_at": evidence.created_at.isoformat(),
    }
