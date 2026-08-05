"""Bounded acquisition of official PLACSP documents for tender reports."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import PurePath
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from opn_oracle.documents.models import Document, DocumentChunk
from opn_oracle.documents.parsers import ParseError
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
    _sha256 as _snapshot_sha256,
)
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


def _collect_document_refs(documents: Any, *, seen: set[str], values: list[dict[str, str]]) -> None:
    if not isinstance(documents, list):
        return
    for document in documents:
        if not isinstance(document, dict):
            continue
        uri = str(document.get("uri") or "").strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        values.append(
            {
                "uri": uri,
                "file_name": str(document.get("file_name") or "pliego-placsp.pdf"),
                "doc_type": str(document.get("doc_type") or "additional"),
            }
        )


def _referenced_documents(report: Report) -> list[dict[str, str]]:
    """Collect CODICE attachment URIs from pinned awards *and* open tenders.

    Awards nest documents under ``snapshot.entries[].documents``. Open tenders
    (Signal ``placsp_open_tenders``) expose them at ``snapshot.documents``.
    Both feed the same bounded PLACSP download path so a prospective bid can
    pull pliegos without waiting for award.
    """
    values: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in report.source_snapshot.get("procurement_items", []):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        snapshot = item.get("snapshot")
        if not isinstance(snapshot, dict):
            continue
        if kind == "award":
            entries = snapshot.get("entries", [])
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    _collect_document_refs(entry.get("documents"), seen=seen, values=values)
        elif kind == "tender":
            # Top-level documents (open tender pin).
            _collect_document_refs(snapshot.get("documents"), seen=seen, values=values)
            # Defensive: some providers may nest under entries.
            entries = snapshot.get("entries", [])
            for entry in entries if isinstance(entries, list) else []:
                if isinstance(entry, dict):
                    _collect_document_refs(entry.get("documents"), seen=seen, values=values)
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


# Aviso honesto cuando el PDF oficial viene cifrado y se usa material ya extraído.
ENCRYPTED_PDF_EXTRACT_WARNING = "análisis sobre extracto; PDF original cifrado"

_EXTRACT_FILENAME_HINTS = (
    "extracto",
    "pcap",
    "ppt",
    "pliego",
    "oferta",
    "solvencia",
    "criterio",
)


def _is_encrypted_pdf_error(exc: BaseException) -> bool:
    msg = str(exc or "").casefold()
    return "cifrado" in msg or "encrypted" in msg


def _dossier_ready_text_extracts(
    dossier_id: uuid.UUID,
    *,
    reference: dict[str, str] | None = None,
) -> list[Document]:
    """Documentos ready del expediente con texto ya parseado (extractos / pliegos).

    Preferidos frente a re-parsear un PDF PLACSP cifrado. No descifra nada.
    """
    rows = list(
        db.session.scalars(
            select(Document)
            .where(
                Document.dossier_id == dossier_id,
                Document.status == "ready",
            )
            .order_by(Document.created_at.asc())
        )
    )
    usable: list[Document] = []
    ref_name = (reference or {}).get("file_name") or ""
    ref_type = ((reference or {}).get("doc_type") or "").casefold()
    ref_stem = PurePath(ref_name).stem.casefold() if ref_name else ""
    for doc in rows:
        # Debe tener al menos un chunk de texto.
        has_text = db.session.scalar(
            select(DocumentChunk.id)
            .where(
                DocumentChunk.document_id == doc.id,
                DocumentChunk.text_content != "",
            )
            .limit(1)
        )
        if has_text is None:
            continue
        name = (doc.original_filename or "").casefold()
        media = (doc.media_type or "").casefold()
        is_textish = media.startswith("text/") or media in {
            "application/json",
            "application/vnd.opn.transcript+json",
        }
        name_hint = any(h in name for h in _EXTRACT_FILENAME_HINTS)
        # Emparejar por tipo CODICE (legal→pcap, technical→ppt) o por stem.
        type_hint = False
        if ref_type in {"legal", "pcap"} and (
            "pcap" in name or "pliego" in name or "extracto" in name
        ):
            type_hint = True
        if ref_type in {"technical", "ppt"} and (
            "ppt" in name or "tecn" in name or "extracto" in name
        ):
            type_hint = True
        stem_hint = bool(ref_stem and ref_stem[:8] and ref_stem[:8] in name)
        if is_textish or name_hint or type_hint or stem_hint:
            usable.append(doc)
    return usable


def _use_encrypted_pdf_extract_fallback(
    report: Report,
    reference: dict[str, str],
    *,
    reason: str,
) -> tuple[int, int, list[str]]:
    """Si el PDF CODICE está cifrado, reutiliza extractos ready del expediente.

    Returns (documents_used, evidence_made, warnings).
    """
    extracts = _dossier_ready_text_extracts(report.dossier_id, reference=reference)
    if not extracts:
        return 0, 0, []
    warnings = [
        f"{ENCRYPTED_PDF_EXTRACT_WARNING} "
        f"(ref={reference.get('file_name') or reference.get('uri')}; {reason})"
    ]
    evidence = 0
    used_ids: set[uuid.UUID] = set()
    for doc in extracts:
        if doc.id in used_ids:
            continue
        if not (document_available_for_citation(doc) or official_unscanned_document_allowed(doc)):
            continue
        mark_official_unscanned_acceptance(
            doc,
            report_id=report.id,
            job_id=None,
        )
        # Anota en metadata que el informe usó extracto ante PDF cifrado.
        meta = dict(doc.metadata_json or {})
        meta["encrypted_pdf_fallback"] = {
            "warning": ENCRYPTED_PDF_EXTRACT_WARNING,
            "source_uri": reference.get("uri"),
            "source_file_name": reference.get("file_name"),
            "reason": reason,
        }
        doc.metadata_json = meta
        evidence += _ensure_chunk_evidence(doc)
        used_ids.add(doc.id)
        if len(used_ids) >= 3:
            break
    if not used_ids:
        return 0, 0, []
    db.session.commit()
    return len(used_ids), evidence, warnings


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
        process_error: BaseException | None = None
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
            try:
                process_document(document.id, version.id, job)
            except (DocumentError, ParseError) as error:
                process_error = error
            document = db.session.get(Document, document.id)
        # PDF cifrado u otro fallo de parse: caer a extractos ya en el expediente.
        if process_error is not None and _is_encrypted_pdf_error(process_error):
            used, ev, fb_warnings = _use_encrypted_pdf_extract_fallback(
                report,
                reference,
                reason=str(process_error),
            )
            if used:
                warnings.extend(fb_warnings)
                processed += used
                evidence += ev
                continue
            # Sin texto en memoria/expediente: error legible como hasta ahora.
            raise DocumentError(str(process_error))
        if process_error is not None:
            raise process_error
        if document is None:
            raise DocumentError(document_unavailable_reason(None))
        # Documento existente failed por cifrado previo → mismo fallback.
        if (document.status != "ready" or not document_available_for_citation(document)) and (
            "cifrado" in str(document.safe_error_code or "").casefold()
            or "cifrado" in str(getattr(document, "status", "") or "").casefold()
        ):
            used, ev, fb_warnings = _use_encrypted_pdf_extract_fallback(
                report,
                reference,
                reason="documento previo no usable (posible PDF cifrado)",
            )
            if used:
                warnings.extend(fb_warnings)
                processed += used
                evidence += ev
                continue
        if not (
            document_available_for_citation(document)
            or official_unscanned_document_allowed(document)
        ):
            # Último intento: extractos del expediente (p.ej. PDF cifrado sin error tipado).
            used, ev, fb_warnings = _use_encrypted_pdf_extract_fallback(
                report,
                reference,
                reason=document_unavailable_reason(document),
            )
            if used:
                warnings.extend(fb_warnings)
                processed += used
                evidence += ev
                continue
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
    # Refresco primero: reincorpora la evidencia recién ingerida. El aviso de
    # PDF cifrado se escribe DESPUÉS para no morir en el replace del snapshot
    # (refresh también preserva overlays, por si se dispara desde otros caminos).
    refresh_report_snapshot(report)
    warnings = list(outcome.get("warnings") or [])
    extract_warnings = [w for w in warnings if ENCRYPTED_PDF_EXTRACT_WARNING in w]
    if extract_warnings:
        snap = dict(report.source_snapshot or {})
        notes = list(snap.get("document_notes") or [])
        for w in extract_warnings:
            if w not in notes:
                notes.append(w)
        snap["document_notes"] = notes
        snap["encrypted_pdf_fallback"] = True
        report.source_snapshot = snap
        report.source_snapshot_hash = _snapshot_sha256(snap)
        db.session.commit()
    return {**process_report(report.id, job), "procurement_documents": outcome}
