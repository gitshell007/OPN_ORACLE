"""Bounded acquisition of official PLACSP documents for tender reports."""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from opn_oracle.documents.models import Document, DocumentChunk
from opn_oracle.documents.security import (
    document_available_for_citation,
    document_unavailable_reason,
    mark_official_unscanned_acceptance,
    official_unscanned_document_allowed,
)
from opn_oracle.documents.service import (
    DocumentError,
    create_evidence,
    create_upload,
    process_document,
)
from opn_oracle.extensions import db
from opn_oracle.oracle.models import Evidence, Report
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.service import (
    process_report,
    refresh_report_snapshot,
)

PLACSP_DOCUMENT_HOSTS = frozenset({"contrataciondelestado.es"})
MAX_DOCUMENTS_PER_REPORT = 10
MAX_DOCUMENT_BYTES_PER_REPORT = 15 * 1024 * 1024
MAX_EVIDENCE_CHUNKS_PER_DOCUMENT = 3
DOWNLOAD_TIMEOUT_SECONDS = 20.0


class ProcurementDocumentReportError(RuntimeError):
    pass


def _safe_placsp_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in PLACSP_DOCUMENT_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ProcurementDocumentReportError("La referencia documental PLACSP no está permitida.")
    return uri


def download_placsp_pdf(
    uri: str,
    *,
    max_bytes: int,
    client: httpx.Client | None = None,
) -> bytes:
    """Download one direct CODICE attachment, rejecting redirects and oversized data."""
    _safe_placsp_uri(uri)
    owns_client = client is None
    request_client = client or httpx.Client(
        timeout=httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS), follow_redirects=False
    )
    try:
        with request_client.stream("GET", uri, headers={"Accept": "application/pdf"}) as response:
            if response.is_redirect or response.status_code != 200:
                raise ProcurementDocumentReportError(
                    "No se pudo descargar el documento oficial PLACSP."
                )
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise ProcurementDocumentReportError(
                            "El documento oficial supera el límite del informe."
                        )
                except ValueError as error:
                    raise ProcurementDocumentReportError(
                        "El documento oficial devolvió un tamaño inválido."
                    ) from error
            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > max_bytes:
                    raise ProcurementDocumentReportError(
                        "El documento oficial supera el límite del informe."
                    )
    except httpx.HTTPError as error:
        raise ProcurementDocumentReportError(
            "No se pudo descargar el documento oficial PLACSP."
        ) from error
    finally:
        if owns_client:
            request_client.close()
    if not payload.startswith(b"%PDF-"):
        raise ProcurementDocumentReportError("Se omitió un adjunto PLACSP que no es PDF.")
    return bytes(payload)


def _referenced_documents(report: Report) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in report.source_snapshot.get("procurement_items", []):
        if not isinstance(item, dict) or item.get("kind") != "award":
            continue
        snapshot = item.get("snapshot")
        entries = snapshot.get("entries", []) if isinstance(snapshot, dict) else []
        for entry in entries if isinstance(entries, list) else []:
            for document in entry.get("documents", []) if isinstance(entry, dict) else []:
                if not isinstance(document, dict):
                    continue
                uri = str(document.get("uri") or "").strip()
                if uri and uri not in seen:
                    seen.add(uri)
                    values.append(
                        {
                            "uri": uri,
                            "file_name": str(document.get("file_name") or "pliego-placsp.pdf"),
                            "doc_type": str(document.get("doc_type") or "additional"),
                        }
                    )
    return values[:MAX_DOCUMENTS_PER_REPORT]


def _existing_document(dossier_id: uuid.UUID, checksum: bytes) -> Document | None:
    return db.session.scalar(
        select(Document).where(
            Document.dossier_id == dossier_id,
            Document.checksum == checksum,
            Document.status == "ready",
        )
    )


def _ensure_chunk_evidence(document: Document) -> int:
    chunks = list(
        db.session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.sequence)
            .limit(MAX_EVIDENCE_CHUNKS_PER_DOCUMENT)
        )
    )
    made = 0
    for chunk in chunks:
        existing = db.session.scalar(
            select(Evidence.id).where(
                Evidence.document_chunk_id == chunk.id,
                Evidence.tenant_id == document.tenant_id,
            )
        )
        if existing is None and chunk.text_content:
            create_evidence(document, chunk, start=0, end=len(chunk.text_content))
            made += 1
    return made


def _ingest_documents(report: Report, job: Any) -> dict[str, Any]:
    documents = _referenced_documents(report)
    if not documents:
        return {
            "documents": 0,
            "evidence": 0,
            "warnings": ["Las adjudicaciones fijadas no incluyen documentos CODICE."],
        }
    total_bytes = 0
    processed = evidence = 0
    warnings: list[str] = []
    for reference in documents:
        try:
            remaining = MAX_DOCUMENT_BYTES_PER_REPORT - total_bytes
            if remaining <= 0:
                warnings.append("Se alcanzó el límite total de descarga del informe.")
                break
            payload = download_placsp_pdf(reference["uri"], max_bytes=remaining)
            total_bytes += len(payload)
        except ProcurementDocumentReportError as error:
            warnings.append(str(error))
            continue
        checksum = hashlib.sha256(payload).digest()
        document = _existing_document(report.dossier_id, checksum)
        if document is None:
            document, version = create_upload(
                tenant_id=report.tenant_id,
                dossier_id=report.dossier_id,
                uploader_id=report.requested_by_user_id,
                filename=reference["file_name"],
                media_type="application/pdf",
                source=io.BytesIO(payload),
                classification=report.classification,
            )
            document.metadata_json = {
                "source": "placsp_codice",
                "source_uri": reference["uri"],
                "document_type": reference["doc_type"],
            }
            db.session.commit()
            process_document(document.id, version.id, job)
            document = db.session.get(Document, document.id)
        if document is None:
            raise DocumentError(document_unavailable_reason(None))
        if not (
            document_available_for_citation(document)
            or official_unscanned_document_allowed(document)
        ):
            raise DocumentError(document_unavailable_reason(document))
        accepted_by_exception = mark_official_unscanned_acceptance(
            document,
            report_id=report.id,
            job_id=getattr(job, "id", None),
        )
        if accepted_by_exception:
            acceptance = document.scan_result.get("official_unscanned_acceptance", {})
            append_audit_event(
                db.session,
                action="document.official_unscanned_accepted",
                resource_type="document",
                resource_id=document.id,
                dossier_id=document.dossier_id,
                result="success",
                correlation_id=getattr(job, "correlation_id", None),
                metadata={
                    "report_id": str(report.id),
                    "scan_status": document.scan_status,
                    "source_host": acceptance.get("source_host"),
                    "policy": acceptance.get("policy"),
                },
            )
            db.session.commit()
        if not document_available_for_citation(document):
            raise DocumentError(document_unavailable_reason(document))
        processed += 1
        evidence += _ensure_chunk_evidence(document)
    return {
        "documents": processed,
        "evidence": evidence,
        "warnings": warnings,
        "bytes": total_bytes,
    }


def process_procurement_document_report(report_id: uuid.UUID, job: Any) -> dict[str, Any]:
    report = db.session.scalar(
        select(Report).where(Report.id == report_id, Report.tenant_id == job.tenant_id)
    )
    if report is None or report.background_job_id != job.id:
        raise ProcurementDocumentReportError("Informe documental no disponible.")
    if report.template_key != "tender":
        raise ProcurementDocumentReportError(
            "El informe documental requiere la plantilla tender/v1."
        )
    outcome = _ingest_documents(report, job)
    refresh_report_snapshot(report)
    return {**process_report(report.id, job), "procurement_documents": outcome}
