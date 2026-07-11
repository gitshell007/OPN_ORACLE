"""Secure document lifecycle, parsing, evidence and tenant-scoped FTS."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any, BinaryIO

from flask import current_app
from sqlalchemy import delete, func, select, update

from opn_oracle.documents.models import (
    Document,
    DocumentChunk,
    DocumentProcessingAttempt,
    DocumentVersion,
)
from opn_oracle.documents.parsers import CHUNKER_VERSION, ParseError, chunk_document, parser_for
from opn_oracle.documents.scanner import ScannerUnavailable
from opn_oracle.documents.storage import ObjectStorage, StorageError, object_key
from opn_oracle.extensions import db
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Evidence

ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/csv",
        "text/vtt",
        "application/x-subrip",
        "application/vnd.opn.transcript+json",
    }
)


class DocumentError(ValueError):
    pass


ACTIVE_ATTEMPT_STATES = ("scanning", "parsing", "chunking")


def _renew_attempt(
    attempt_id: uuid.UUID,
    execution_token: uuid.UUID,
    *,
    expected_status: str,
    next_status: str,
    now: datetime | None = None,
) -> bool:
    """Fresh-transaction CAS; an expired/stale worker can never renew itself."""
    checkpoint = now or datetime.now(UTC)
    db.session.rollback()
    attempt = db.session.scalar(
        select(DocumentProcessingAttempt).where(
            DocumentProcessingAttempt.id == attempt_id,
            DocumentProcessingAttempt.execution_token == execution_token,
            DocumentProcessingAttempt.status == expected_status,
            DocumentProcessingAttempt.lease_expires_at >= checkpoint,
        )
    )
    if attempt is None:
        db.session.rollback()
        return False
    absolute_deadline = attempt.started_at + timedelta(
        seconds=int(current_app.config["CELERY_TASK_TIME_LIMIT"])
    )
    renewed_until = min(checkpoint + timedelta(seconds=60), absolute_deadline)
    if renewed_until <= checkpoint:
        db.session.rollback()
        return False
    changed = db.session.execute(
        update(DocumentProcessingAttempt)
        .where(
            DocumentProcessingAttempt.id == attempt_id,
            DocumentProcessingAttempt.execution_token == execution_token,
            DocumentProcessingAttempt.status == expected_status,
            DocumentProcessingAttempt.lease_expires_at >= checkpoint,
        )
        .values(status=next_status, lease_expires_at=renewed_until)
        .returning(DocumentProcessingAttempt.id)
    ).scalar_one_or_none()
    db.session.commit()
    return changed is not None


def recover_expired_document_attempts(tenant_id: uuid.UUID, *, now: datetime | None = None) -> int:
    """Abandon expired tokens and make their exact current version safely retryable."""
    checkpoint = now or datetime.now(UTC)
    attempts = list(
        db.session.scalars(
            select(DocumentProcessingAttempt)
            .where(
                DocumentProcessingAttempt.tenant_id == tenant_id,
                DocumentProcessingAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
                DocumentProcessingAttempt.lease_expires_at < checkpoint,
            )
            .with_for_update(skip_locked=True)
        )
    )
    recovered = 0
    for attempt in attempts:
        version = db.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == attempt.document_version_id,
                DocumentVersion.tenant_id == tenant_id,
                DocumentVersion.processing_token == attempt.execution_token,
            )
        )
        attempt.status = "abandoned"
        attempt.completed_at = checkpoint
        attempt.safe_error_code = "lease_expired"
        if version is not None:
            version.processing_token = None
            version.status = "queued"
            version.safe_error_code = "lease_expired"
            document = db.session.scalar(
                select(Document).where(
                    Document.id == version.document_id,
                    Document.tenant_id == tenant_id,
                    Document.current_version_id == version.id,
                    Document.status != "deleted",
                )
            )
            if document is not None:
                document.status = "queued"
                document.safe_error_code = "lease_expired"
                from opn_oracle.jobs.service import stage_job

                original_job = db.session.get(BackgroundJob, attempt.background_job_id)
                stage_job(
                    "oracle.document.process",
                    payload={
                        "document_id": str(document.id),
                        "version_id": str(version.id),
                    },
                    idempotency_key=f"document-recovery-{attempt.id}",
                    requested_by_user_id=(
                        original_job.requested_by_user_id if original_job is not None else None
                    ),
                    dossier_id=document.dossier_id,
                    resource_type="document",
                    resource_id=document.id,
                    max_attempts=3,
                )
        recovered += 1
    db.session.commit()
    return recovered


def safe_filename(value: str) -> str:
    clean = PurePath(value.replace("\\", "/")).name.replace("\r", "").replace("\n", "")
    clean = "".join(char for char in clean if char.isprintable()).strip(" .")
    return clean[:255] or "documento"


def verify_magic(source: BinaryIO, media_type: str) -> None:
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise DocumentError("Formato no admitido.")
    head = source.read(8192)
    source.seek(0)
    if media_type == "application/pdf" and not head.startswith(b"%PDF-"):
        raise DocumentError("El contenido no corresponde a un PDF.")
    if media_type.endswith("wordprocessingml.document") and not head.startswith(b"PK\x03\x04"):
        raise DocumentError("El contenido no corresponde a un DOCX.")
    if (
        media_type.startswith("text/")
        or media_type == "application/x-subrip"
        or media_type == "application/vnd.opn.transcript+json"
    ):
        if b"\x00" in head:
            raise DocumentError("El contenido no corresponde a texto seguro.")
        try:
            head.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("El texto debe usar UTF-8.") from exc


def create_upload(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    uploader_id: uuid.UUID,
    filename: str,
    media_type: str,
    source: BinaryIO,
    classification: str,
) -> tuple[Document, DocumentVersion]:
    if classification not in {"public", "internal"}:
        raise DocumentError("Clasificación no válida.")
    verify_magic(source, media_type)
    bind = db.session.get_bind()
    if bind.dialect.name == "postgresql":
        db.session.execute(
            select(
                func.pg_advisory_xact_lock(func.hashtextextended(f"document-quota:{tenant_id}", 0))
            )
        )
    used = db.session.scalar(
        select(func.coalesce(func.sum(Document.byte_size), 0)).where(
            Document.tenant_id == tenant_id, Document.status != "deleted"
        )
    )
    max_bytes = int(current_app.config["DOCUMENT_MAX_BYTES"])
    if int(used or 0) >= int(current_app.config["DOCUMENT_TENANT_QUOTA_BYTES"]):
        raise DocumentError("Se ha alcanzado la cuota documental del tenant.")
    document_id = uuid.uuid4()
    key = object_key(tenant_id, dossier_id, document_id)
    storage: ObjectStorage = current_app.extensions["object_storage"]
    try:
        stored = storage.put(key, source, max_bytes=max_bytes, media_type=media_type)
        if int(used or 0) + stored.byte_size > int(
            current_app.config["DOCUMENT_TENANT_QUOTA_BYTES"]
        ):
            storage.delete(key)
            raise DocumentError("El archivo supera la cuota documental del tenant.")
        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            uploaded_by_user_id=uploader_id,
            original_filename=safe_filename(filename),
            storage_key=key,
            media_type=media_type,
            byte_size=stored.byte_size,
            checksum=stored.checksum,
            classification=classification,
            status="queued",
            scan_status="pending",
            scan_result={},
            metadata_json={},
        )
        version = DocumentVersion(
            tenant_id=tenant_id,
            document_id=document_id,
            dossier_id=dossier_id,
            version_number=1,
            status="queued",
            source_checksum=stored.checksum,
            provenance={"storage_checksum": stored.checksum.hex()},
        )
        db.session.add_all((document, version))
        db.session.flush()
        document.current_version_id = version.id
    except (StorageError, OSError) as exc:
        db.session.rollback()
        raise DocumentError("No se pudo almacenar el documento.") from exc
    except Exception:
        db.session.rollback()
        with suppress(Exception):
            storage.delete(key)
        raise
    return document, version


def process_document(
    document_id: uuid.UUID, version_id: uuid.UUID, job: BackgroundJob
) -> dict[str, Any]:
    execution_token = uuid.uuid4()
    now = datetime.now(UTC)
    document = db.session.scalar(
        select(Document)
        .where(Document.id == document_id, Document.tenant_id == job.tenant_id)
        .with_for_update()
    )
    if document is None or document.status == "deleted":
        raise DocumentError("Documento no disponible.")
    if document.current_version_id != version_id:
        return {"ignored": True, "reason": "superseded_version", "version_id": str(version_id)}
    version = db.session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document.id,
            DocumentVersion.tenant_id == job.tenant_id,
        )
    )
    if version is None:
        raise DocumentError("Versión documental no disponible.")
    if version.status == "ready":
        count = db.session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
        )
        return {
            "document_id": str(document.id),
            "version_id": str(version.id),
            "chunks": int(count or 0),
        }
    attempt = db.session.scalar(
        select(DocumentProcessingAttempt)
        .where(
            DocumentProcessingAttempt.background_job_id == job.id,
            DocumentProcessingAttempt.tenant_id == job.tenant_id,
        )
        .order_by(DocumentProcessingAttempt.attempt_number.desc())
        .limit(1)
    )
    if attempt is not None:
        if attempt.status == "succeeded":
            return {
                "document_id": str(document.id),
                "version_id": str(version.id),
                "replayed": True,
            }
        if attempt.lease_expires_at > now and attempt.status not in {"failed", "abandoned"}:
            return {"ignored": True, "reason": "attempt_in_progress"}
        attempt.status = "abandoned"
        attempt.completed_at = now
    attempt_number = (
        int(
            db.session.scalar(
                select(func.coalesce(func.max(DocumentProcessingAttempt.attempt_number), 0)).where(
                    DocumentProcessingAttempt.document_version_id == version.id,
                    DocumentProcessingAttempt.tenant_id == job.tenant_id,
                )
            )
            or 0
        )
        + 1
    )
    attempt = DocumentProcessingAttempt(
        tenant_id=job.tenant_id,
        document_version_id=version.id,
        background_job_id=job.id,
        attempt_number=attempt_number,
        status="scanning",
        execution_token=execution_token,
        lease_expires_at=now + timedelta(minutes=5),
        started_at=now,
    )
    db.session.add(attempt)
    db.session.flush()
    attempt_id = attempt.id
    storage: ObjectStorage = current_app.extensions["object_storage"]
    try:
        document.status = "processing"
        version.status = "scanning"
        version.processing_token = execution_token
        version.processing_started_at = datetime.now(UTC)
        db.session.commit()
        with storage.get(document.storage_key) as source:
            scan = current_app.extensions["malware_scanner"].scan(source)
        if not _renew_attempt(
            attempt_id,
            execution_token,
            expected_status="scanning",
            next_status="parsing",
        ):
            return {"ignored": True, "reason": "lost_or_expired_lease"}
        if scan.status == "infected":
            checkpoint = datetime.now(UTC)
            current_attempt = db.session.scalar(
                select(DocumentProcessingAttempt)
                .where(
                    DocumentProcessingAttempt.id == attempt_id,
                    DocumentProcessingAttempt.execution_token == execution_token,
                    DocumentProcessingAttempt.status == "parsing",
                    DocumentProcessingAttempt.lease_expires_at >= checkpoint,
                )
                .with_for_update()
            )
            current_document = db.session.get(Document, document.id)
            if (
                current_attempt is None
                or current_document is None
                or current_document.current_version_id != version.id
                or version.processing_token != execution_token
            ):
                return {"ignored": True, "reason": "lost_fence"}
            current_document.scan_status = scan.status
            current_document.scan_result = {"engine": scan.engine, "signature": scan.signature}
            document.status = "quarantined"
            version.status = "quarantined"
            settlement_time = datetime.now(UTC)
            settled = db.session.execute(
                update(DocumentProcessingAttempt)
                .where(
                    DocumentProcessingAttempt.id == attempt_id,
                    DocumentProcessingAttempt.execution_token == execution_token,
                    DocumentProcessingAttempt.status == "parsing",
                    DocumentProcessingAttempt.lease_expires_at >= settlement_time,
                )
                .values(status="failed", completed_at=settlement_time)
                .returning(DocumentProcessingAttempt.id)
            ).scalar_one_or_none()
            if settled is None:
                db.session.rollback()
                return {"ignored": True, "reason": "lost_or_expired_lease"}
            db.session.commit()
            raise DocumentError("Documento en cuarentena.")
        with storage.get(document.storage_key) as source:
            parser = parser_for(document.media_type)
            parsed = parser.parse(source)
        chunks = chunk_document(parsed)
        if not chunks:
            raise ParseError("El documento no contiene texto extraíble; OCR no está habilitado.")
        if not _renew_attempt(
            attempt_id,
            execution_token,
            expected_status="parsing",
            next_status="chunking",
        ):
            return {"ignored": True, "reason": "lost_or_expired_lease"}
        checkpoint = datetime.now(UTC)
        current_attempt = db.session.scalar(
            select(DocumentProcessingAttempt)
            .where(
                DocumentProcessingAttempt.id == attempt_id,
                DocumentProcessingAttempt.execution_token == execution_token,
                DocumentProcessingAttempt.status == "chunking",
                DocumentProcessingAttempt.lease_expires_at >= checkpoint,
            )
            .with_for_update()
        )
        document = db.session.scalar(
            select(Document)
            .where(Document.id == document_id, Document.tenant_id == job.tenant_id)
            .with_for_update()
        )
        version = db.session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.tenant_id == job.tenant_id,
                DocumentVersion.processing_token == execution_token,
            )
        )
        if (
            current_attempt is None
            or document is None
            or version is None
            or document.current_version_id != version_id
        ):
            if current_attempt is not None:
                current_attempt.status = "abandoned"
                current_attempt.completed_at = datetime.now(UTC)
                db.session.commit()
            return {"ignored": True, "reason": "lost_fence"}
        document.scan_status = scan.status
        document.scan_result = {"engine": scan.engine, "signature": scan.signature}
        db.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id)
        )
        for item in chunks:
            locator = item.locator
            db.session.add(
                DocumentChunk(
                    tenant_id=document.tenant_id,
                    document_version_id=version.id,
                    document_id=document.id,
                    dossier_id=document.dossier_id,
                    sequence=item.sequence,
                    text_content=item.text,
                    page_number=int(locator["page"]) if "page" in locator else None,
                    paragraph_number=int(locator["paragraph"]) if "paragraph" in locator else None,
                    char_start=item.char_start,
                    char_end=item.char_end,
                    checksum=item.checksum,
                    locator=locator,
                    provenance={
                        "parser": parsed.parser_name,
                        "parser_version": parsed.parser_version,
                    },
                )
            )
        version.status = "ready"
        version.parser_name = parsed.parser_name
        version.parser_version = parsed.parser_version
        version.chunker_version = CHUNKER_VERSION
        version.processing_completed_at = datetime.now(UTC)
        version.processing_token = None
        document.status = "ready"
        document.safe_error_code = None
        settlement_time = datetime.now(UTC)
        settled = db.session.execute(
            update(DocumentProcessingAttempt)
            .where(
                DocumentProcessingAttempt.id == attempt_id,
                DocumentProcessingAttempt.execution_token == execution_token,
                DocumentProcessingAttempt.status == "chunking",
                DocumentProcessingAttempt.lease_expires_at >= settlement_time,
            )
            .values(status="succeeded", completed_at=settlement_time)
            .returning(DocumentProcessingAttempt.id)
        ).scalar_one_or_none()
        if settled is None:
            db.session.rollback()
            return {"ignored": True, "reason": "lost_or_expired_lease"}
        db.session.commit()
        return {
            "document_id": str(document.id),
            "version_id": str(version.id),
            "chunks": len(chunks),
        }
    except (DocumentError, ParseError, ScannerUnavailable, StorageError, OSError) as exc:
        db.session.rollback()
        current = db.session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        current_version = db.session.get(DocumentVersion, version_id)
        current_attempt = db.session.scalar(
            select(DocumentProcessingAttempt).where(
                DocumentProcessingAttempt.id == attempt_id,
                DocumentProcessingAttempt.execution_token == execution_token,
                DocumentProcessingAttempt.status.in_(ACTIVE_ATTEMPT_STATES),
                DocumentProcessingAttempt.lease_expires_at >= datetime.now(UTC),
            )
        )
        owns_fence = (
            current is not None
            and current.current_version_id == version_id
            and current_version is not None
            and current_version.processing_token == execution_token
        )
        if owns_fence and current is not None and current.status != "quarantined":
            current.status = "failed"
            current.safe_error_code = type(exc).__name__.lower()
        if owns_fence and current_version is not None and current_version.status != "quarantined":
            current_version.status = "failed"
            current_version.safe_error_code = type(exc).__name__.lower()
            current_version.processing_completed_at = datetime.now(UTC)
            current_version.processing_token = None
        if current_attempt is not None:
            current_attempt.status = "failed"
            current_attempt.safe_error_code = type(exc).__name__.lower()
            current_attempt.completed_at = datetime.now(UTC)
        db.session.commit()
        raise DocumentError("No se pudo procesar el documento.") from exc


def new_reprocess_version(document: Document) -> DocumentVersion:
    previous = db.session.scalar(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.tenant_id == document.tenant_id,
        )
    )
    version = DocumentVersion(
        tenant_id=document.tenant_id,
        document_id=document.id,
        dossier_id=document.dossier_id,
        version_number=int(previous or 0) + 1,
        status="queued",
        source_checksum=document.checksum,
        provenance={"reprocessed_from_version_id": str(document.current_version_id)},
    )
    db.session.add(version)
    db.session.flush()
    document.current_version_id = version.id
    document.status = "queued"
    document.safe_error_code = None
    document.version += 1
    return version


def soft_delete(document: Document, actor_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    document.status = "deleted"
    document.deleted_at = now
    document.deleted_by_user_id = actor_id
    document.purge_after = now + timedelta(days=30)
    document.version += 1
    db.session.commit()


def purge_due_documents(tenant_id: uuid.UUID, *, now: datetime | None = None) -> int:
    """Idempotently remove object/text while preserving citation hashes and metadata."""
    effective_now = now or datetime.now(UTC)
    documents = list(
        db.session.scalars(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.status == "deleted",
                Document.legal_hold.is_(False),
                Document.purge_after.is_not(None),
                Document.purge_after <= effective_now,
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
    )
    storage: ObjectStorage = current_app.extensions["object_storage"]
    purged = 0
    for document in documents:
        try:
            storage.delete(document.storage_key)
        except (StorageError, OSError):
            continue
        version_ids = select(DocumentVersion.id).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.tenant_id == tenant_id,
        )
        chunk_ids = select(DocumentChunk.id).where(
            DocumentChunk.document_id == document.id,
            DocumentChunk.tenant_id == tenant_id,
        )
        db.session.execute(
            update(Evidence)
            .where(Evidence.tenant_id == tenant_id, Evidence.document_chunk_id.in_(chunk_ids))
            .values(
                extract="[contenido eliminado por política de retención]",
                provenance=Evidence.provenance.op("||")(
                    {"content_purged": True, "purged_at": effective_now.isoformat()}
                ),
            )
        )
        db.session.execute(
            update(DocumentChunk)
            .where(DocumentChunk.document_id == document.id, DocumentChunk.tenant_id == tenant_id)
            .values(
                text_content="[contenido eliminado por política de retención]",
                provenance=DocumentChunk.provenance.op("||")({"content_purged": True}),
            )
        )
        db.session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id.in_(version_ids), DocumentVersion.tenant_id == tenant_id)
            .values(status="purged")
        )
        document.metadata_json = {
            **document.metadata_json,
            "content_purged": True,
            "purged_at": effective_now.isoformat(),
        }
        purged += 1
    db.session.commit()
    return purged


def reconcile_storage_orphans(
    tenant_id: uuid.UUID, *, now: datetime | None = None, grace_hours: int = 24
) -> int:
    """Delete only old objects not referenced by the tenant-scoped source of truth."""
    effective_now = now or datetime.now(UTC)
    storage: ObjectStorage = current_app.extensions["object_storage"]
    # ObjectStorage is shared by documents, reports and data exports. Every durable
    # owner must participate in the same source-of-truth registry before deletion.
    from opn_oracle.reporting.models import DataExport, ReportArtifact

    referenced = set(
        db.session.scalars(select(Document.storage_key).where(Document.tenant_id == tenant_id))
    )
    referenced.update(
        db.session.scalars(
            select(ReportArtifact.storage_key).where(ReportArtifact.tenant_id == tenant_id)
        )
    )
    referenced.update(
        key
        for key in db.session.scalars(
            select(DataExport.storage_key).where(
                DataExport.tenant_id == tenant_id,
                DataExport.storage_key.is_not(None),
            )
        )
        if key is not None
    )
    deleted = 0
    for item in storage.iter_objects(tenant_id):
        if item.key in referenced or item.modified_at > effective_now - timedelta(
            hours=grace_hours
        ):
            continue
        try:
            storage.delete(item.key)
        except (StorageError, OSError):
            continue
        deleted += 1
    return deleted


def create_evidence(document: Document, chunk: DocumentChunk, *, start: int, end: int) -> Evidence:
    if chunk.document_id != document.id or not 0 <= start < end <= len(chunk.text_content):
        raise DocumentError("Rango de evidencia no válido.")
    extract = chunk.text_content[start:end]
    evidence = Evidence(
        tenant_id=document.tenant_id,
        signal_id=None,
        source_kind="document",
        document_id=document.id,
        document_version_id=chunk.document_version_id,
        document_chunk_id=chunk.id,
        extract=extract,
        locator={**chunk.locator, "chunk_start": start, "chunk_end": end},
        checksum=hashlib.sha256(extract.encode()).digest(),
        classification=document.classification,
        provenance={"chunk_checksum": chunk.checksum.hex(), "immutable_version": True},
    )
    db.session.add(evidence)
    db.session.flush()
    db.session.add(
        EvidenceDossier(
            tenant_id=document.tenant_id, evidence_id=evidence.id, dossier_id=document.dossier_id
        )
    )
    db.session.commit()
    return evidence
