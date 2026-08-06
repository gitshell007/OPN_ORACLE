"""G-11 · estado honesto de adquisición de pliego/PCAP y subida manual.

La descarga automática PLACSP es best-effort. Comercialmente el camino fiable es:
subir el PCAP → Oracle trocea, puntúa y prepara el esqueleto.

Estados durables por documento/adquisición:
  - descargado: PDF oficial descargado y procesado
  - subido: PCAP manual válido (prioridad máxima)
  - extracto_parcial: se usó extracto/metadatos con procedencia y aviso
  - no_disponible: sin documento usable (HTTP/WAF, Signal vacío, parse fallido)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, BinaryIO, Literal

from sqlalchemy import select

from opn_oracle.documents.models import Document, DocumentChunk
from opn_oracle.documents.security import document_available_for_citation
from opn_oracle.documents.service import DocumentError, create_upload, process_document
from opn_oracle.extensions import db
from opn_oracle.jobs.service import publish_job, stage_job
from opn_oracle.oracle.models import DossierProcurementItem, Opportunity, StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.platform.audit import append_audit_event

AcquisitionStatus = Literal["descargado", "subido", "extracto_parcial", "no_disponible"]

ACQUISITION_STATUSES: frozenset[str] = frozenset(
    {"descargado", "subido", "extracto_parcial", "no_disponible"}
)

# Prioridad: subida humana > descarga OK > extracto parcial > no disponible.
_STATUS_RANK: dict[str, int] = {
    "subido": 40,
    "descargado": 30,
    "extracto_parcial": 20,
    "no_disponible": 10,
}

META_KEY = "pliego_acquisition"
SOURCE_MANUAL = "manual_pcap"
SOURCE_PLACSP = "placsp_codice"
SOURCE_EXTRACT = "extracto_parcial"

DOWNLOAD_FAIL_WARNING = "descarga automática fallida; suba el PCAP manualmente"
EMPTY_DOCUMENTS_WARNING = "Signal no entregó documentos CODICE; suba el PCAP manualmente"
PARTIAL_EXTRACT_WARNING = "análisis sobre extracto parcial; no es el PCAP completo"


class PliegoAcquisitionError(Exception):
    def __init__(self, message: str, *, code: str = "pliego_acquisition_error") -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def acquisition_meta(document: Document) -> dict[str, Any]:
    raw = (document.metadata_json or {}).get(META_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def set_acquisition_meta(document: Document, payload: dict[str, Any]) -> None:
    meta = dict(document.metadata_json or {})
    existing = dict(meta.get(META_KEY) or {}) if isinstance(meta.get(META_KEY), dict) else {}
    # No degradar una subida humana con un estado peor (retry automático).
    existing_status = str(existing.get("status") or "")
    new_status = str(payload.get("status") or "")
    if (
        existing_status == "subido"
        and new_status
        and new_status != "subido"
        and _STATUS_RANK.get(new_status, 0) < _STATUS_RANK.get("subido", 0)
    ):
        return
    existing.update(payload)
    existing.setdefault("updated_at", _now().isoformat())
    meta[META_KEY] = existing
    document.metadata_json = meta


def _is_manual_pcap(document: Document) -> bool:
    meta = acquisition_meta(document)
    if str(meta.get("source") or "") == SOURCE_MANUAL:
        return True
    if str((document.metadata_json or {}).get("source") or "") == SOURCE_MANUAL:
        return True
    name = (document.original_filename or "").casefold()
    return "pcap" in name and str(meta.get("status") or "") == "subido"


def list_manual_pcap_documents(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = None,
) -> list[Document]:
    rows = list(
        db.session.scalars(
            select(Document)
            .where(
                Document.tenant_id == tenant_id,
                Document.dossier_id == dossier_id,
                Document.status.in_(("ready", "queued", "processing", "uploaded")),
            )
            .order_by(Document.created_at.desc())
        )
    )
    out: list[Document] = []
    for doc in rows:
        meta = acquisition_meta(doc)
        if str(meta.get("source") or "") != SOURCE_MANUAL and not _is_manual_pcap(doc):
            continue
        if opportunity_id is not None:
            linked = meta.get("opportunity_id")
            if linked and str(linked) != str(opportunity_id):
                continue
        out.append(doc)
    return out


def prefer_manual_pcap(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> Document | None:
    """PCAP manual ready tiene prioridad absoluta sobre auto/extractos."""
    for doc in list_manual_pcap_documents(tenant_id=tenant_id, dossier_id=dossier_id):
        if doc.status == "ready" and document_available_for_citation(doc):
            return doc
        # ready sin antivirus oficial aceptado: aún preferible si tiene texto
        if doc.status == "ready":
            has_text = db.session.scalar(
                select(DocumentChunk.id)
                .where(
                    DocumentChunk.document_id == doc.id,
                    DocumentChunk.text_content != "",
                )
                .limit(1)
            )
            if has_text is not None:
                return doc
    return None


def _pin_document_refs(item: DossierProcurementItem) -> list[dict[str, str]]:
    snap = item.snapshot if isinstance(item.snapshot, dict) else {}
    values: list[dict[str, str]] = []
    seen: set[str] = set()

    def collect(documents: Any) -> None:
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
                    "file_name": str(document.get("file_name") or "pliego.pdf"),
                    "doc_type": str(document.get("doc_type") or "additional"),
                }
            )

    collect(snap.get("documents"))
    entries = snap.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                collect(entry.get("documents"))
    return values


def _serialize_document_brief(document: Document | None) -> dict[str, Any] | None:
    if document is None:
        return None
    meta = acquisition_meta(document)
    return {
        "id": str(document.id),
        "filename": document.original_filename,
        "status": document.status,
        "media_type": document.media_type,
        "byte_size": document.byte_size,
        "acquisition": meta or None,
        "created_at": document.created_at.isoformat() if document.created_at else None,
    }


def resolve_dossier_pliego_acquisition(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Estado honesto agregado + por referencia CODICE / subida manual.

    Nunca convierte un error tragado en «0 documentos» normal: si no hay PCAP
    usable, el estado es ``no_disponible`` con razón explícita.
    """
    manual = prefer_manual_pcap(tenant_id=tenant_id, dossier_id=dossier_id)
    manual_all = list_manual_pcap_documents(
        tenant_id=tenant_id, dossier_id=dossier_id, opportunity_id=opportunity_id
    )

    pins = list(
        db.session.scalars(
            select(DossierProcurementItem).where(
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.dossier_id == dossier_id,
            )
        )
    )

    acquisitions: list[dict[str, Any]] = []
    signal_docs_total = 0
    signal_docs_empty_pins = 0

    for pin in pins:
        refs = _pin_document_refs(pin)
        if not refs:
            signal_docs_empty_pins += 1
            acquisitions.append(
                {
                    "key": f"pin:{pin.id}:empty",
                    "status": "no_disponible",
                    "reason_code": "signal_documents_empty",
                    "reason": EMPTY_DOCUMENTS_WARNING,
                    "folder_id": pin.folder_id,
                    "kind": pin.kind,
                    "procurement_item_id": str(pin.id),
                    "source_uri": None,
                    "file_name": None,
                    "document": None,
                    "manual_upload_offered": True,
                }
            )
            continue
        for ref in refs:
            signal_docs_total += 1
            # ¿Hay documento ready ligado a esta URI?
            linked = db.session.scalar(
                select(Document)
                .where(
                    Document.tenant_id == tenant_id,
                    Document.dossier_id == dossier_id,
                    Document.status == "ready",
                    Document.metadata_json["source_uri"].as_string() == ref["uri"],
                )
                .order_by(Document.created_at.desc())
                .limit(1)
            )
            if linked is not None and document_available_for_citation(linked):
                meta = acquisition_meta(linked)
                status = str(meta.get("status") or "descargado")
                if status not in ACQUISITION_STATUSES:
                    status = "descargado"
                acquisitions.append(
                    {
                        "key": f"uri:{ref['uri']}",
                        "status": status,
                        "reason_code": "downloaded" if status == "descargado" else status,
                        "reason": str(
                            meta.get("reason") or "Documento oficial descargado y listo."
                        ),
                        "folder_id": pin.folder_id,
                        "kind": pin.kind,
                        "procurement_item_id": str(pin.id),
                        "source_uri": ref["uri"],
                        "file_name": ref["file_name"],
                        "document": _serialize_document_brief(linked),
                        "manual_upload_offered": True,
                    }
                )
                continue
            # Extracto parcial anotado
            extract_docs = list(
                db.session.scalars(
                    select(Document)
                    .where(
                        Document.tenant_id == tenant_id,
                        Document.dossier_id == dossier_id,
                        Document.status == "ready",
                    )
                    .order_by(Document.created_at.desc())
                    .limit(20)
                )
            )
            partial: Document | None = None
            for doc in extract_docs:
                meta = acquisition_meta(doc)
                if str(meta.get("status")) == "extracto_parcial" and (
                    meta.get("source_uri") in {None, ref["uri"]} or not meta.get("source_uri")
                ):
                    partial = doc
                    break
                fb = (doc.metadata_json or {}).get("encrypted_pdf_fallback") or {}
                if isinstance(fb, dict) and fb.get("source_uri") == ref["uri"]:
                    partial = doc
                    break
            if partial is not None:
                meta = acquisition_meta(partial)
                acquisitions.append(
                    {
                        "key": f"uri:{ref['uri']}",
                        "status": "extracto_parcial",
                        "reason_code": str(meta.get("reason_code") or "partial_extract"),
                        "reason": str(
                            meta.get("reason")
                            or PARTIAL_EXTRACT_WARNING
                        ),
                        "folder_id": pin.folder_id,
                        "kind": pin.kind,
                        "procurement_item_id": str(pin.id),
                        "source_uri": ref["uri"],
                        "file_name": ref["file_name"],
                        "document": _serialize_document_brief(partial),
                        "manual_upload_offered": True,
                    }
                )
                continue
            # Fallo HTTP/WAF registrado en metadata de intentos o sin blob
            fail_reason = DOWNLOAD_FAIL_WARNING
            fail_code = "download_unavailable"
            for doc in extract_docs:
                meta = acquisition_meta(doc)
                if (
                    meta.get("source_uri") == ref["uri"]
                    and str(meta.get("status")) == "no_disponible"
                ):
                    fail_reason = str(meta.get("reason") or fail_reason)
                    fail_code = str(meta.get("reason_code") or fail_code)
                    break
            acquisitions.append(
                {
                    "key": f"uri:{ref['uri']}",
                    "status": "no_disponible",
                    "reason_code": fail_code,
                    "reason": fail_reason,
                    "folder_id": pin.folder_id,
                    "kind": pin.kind,
                    "procurement_item_id": str(pin.id),
                    "source_uri": ref["uri"],
                    "file_name": ref["file_name"],
                    "document": None,
                    "manual_upload_offered": True,
                }
            )

    for doc in manual_all:
        meta = acquisition_meta(doc)
        acquisitions.append(
            {
                "key": f"manual:{doc.id}",
                "status": (
                    "subido" if doc.status == "ready" else str(meta.get("status") or "subido")
                ),
                "reason_code": "manual_upload",
                "reason": str(
                    meta.get("reason") or "PCAP subido manualmente por el usuario."
                ),
                "folder_id": meta.get("folder_id"),
                "kind": "manual",
                "procurement_item_id": meta.get("procurement_item_id"),
                "opportunity_id": meta.get("opportunity_id"),
                "source_uri": None,
                "file_name": doc.original_filename,
                "document": _serialize_document_brief(doc),
                "manual_upload_offered": True,
            }
        )

    if manual is not None:
        overall: AcquisitionStatus = "subido"
        overall_reason = (
            "Hay un PCAP subido manualmente y listo; tiene prioridad sobre "
            "extractos e intentos automáticos."
        )
        overall_code = "manual_preferred"
    elif any(a["status"] == "descargado" for a in acquisitions):
        overall = "descargado"
        overall_reason = "Al menos un pliego oficial se descargó y procesó correctamente."
        overall_code = "downloaded"
    elif any(a["status"] == "extracto_parcial" for a in acquisitions):
        overall = "extracto_parcial"
        overall_reason = PARTIAL_EXTRACT_WARNING
        overall_code = "partial_extract"
    elif not pins:
        overall = "no_disponible"
        overall_reason = "No hay licitaciones/adjudicaciones fijadas ni PCAP subido."
        overall_code = "no_pins"
    elif signal_docs_total == 0:
        overall = "no_disponible"
        overall_reason = EMPTY_DOCUMENTS_WARNING
        overall_code = "signal_documents_empty"
    else:
        overall = "no_disponible"
        overall_reason = DOWNLOAD_FAIL_WARNING
        overall_code = "download_unavailable"

    return {
        "dossier_id": str(dossier_id),
        "opportunity_id": str(opportunity_id) if opportunity_id else None,
        "overall_status": overall,
        "overall_reason_code": overall_code,
        "overall_reason": overall_reason,
        "manual_upload_offered": True,
        "manual_upload_priority": True,
        "cta": {
            "label": "Subir PCAP",
            "action": "upload_manual_pcap",
            "hint": (
                "La descarga automática es best-effort (WAF/HTTP pueden bloquearla). "
                "Suba el PCAP: Oracle lo trocea, puntúa y prepara el esqueleto."
            ),
        },
        "signal_document_refs": signal_docs_total,
        "pins_without_documents": signal_docs_empty_pins,
        "preferred_document": _serialize_document_brief(manual),
        "acquisitions": acquisitions,
    }


def upload_manual_pcap(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    uploader_id: uuid.UUID,
    filename: str,
    media_type: str,
    source: BinaryIO,
    classification: str = "internal",
    opportunity_id: uuid.UUID | None = None,
    procurement_item_id: uuid.UUID | None = None,
    folder_id: str | None = None,
    process_inline: bool = False,
    job: Any | None = None,
) -> tuple[Document, Any, str | None]:
    """Subida manual del PCAP por el pipeline real de parsing/chunking/evidencia.

    Returns (document, version, job_id_or_none).
    """
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        raise PliegoAcquisitionError("Expediente no disponible.", code="not_found")
    if not dossier_accessible(db.session(), dossier, uploader_id, write=True):
        raise PliegoAcquisitionError("Expediente no disponible.", code="not_found")

    if opportunity_id is not None:
        opp = db.session.scalar(
            select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.tenant_id == tenant_id,
                Opportunity.dossier_id == dossier_id,
            )
        )
        if opp is None:
            raise PliegoAcquisitionError(
                "La oportunidad no pertenece a este expediente.",
                code="opportunity_not_found",
            )

    if procurement_item_id is not None:
        pin = db.session.scalar(
            select(DossierProcurementItem).where(
                DossierProcurementItem.id == procurement_item_id,
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.dossier_id == dossier_id,
            )
        )
        if pin is None:
            raise PliegoAcquisitionError(
                "La referencia de contratación no pertenece a este expediente.",
                code="procurement_item_not_found",
            )
        if not folder_id:
            folder_id = pin.folder_id

    try:
        document, version = create_upload(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            uploader_id=uploader_id,
            filename=filename,
            media_type=media_type,
            source=source,
            classification=classification,
        )
    except DocumentError as error:
        raise PliegoAcquisitionError(str(error), code="document_rejected") from error

    set_acquisition_meta(
        document,
        {
            "status": "subido",
            "source": SOURCE_MANUAL,
            "reason_code": "manual_upload",
            "reason": (
                "PCAP subido manualmente; tiene prioridad sobre "
                "descarga automática y extractos."
            ),
            "opportunity_id": str(opportunity_id) if opportunity_id else None,
            "procurement_item_id": str(procurement_item_id) if procurement_item_id else None,
            "folder_id": folder_id,
            "uploaded_by_user_id": str(uploader_id),
            "uploaded_at": _now().isoformat(),
        },
    )
    # Marcadores legibles para bag/pliego y filtros existentes.
    meta = dict(document.metadata_json or {})
    meta["source"] = SOURCE_MANUAL
    meta["document_type"] = "legal"
    meta["manual_pcap"] = True
    document.metadata_json = meta
    db.session.flush()

    append_audit_event(
        db.session,
        action="document.pcap_manual_upload",
        resource_type="document",
        resource_id=document.id,
        dossier_id=dossier_id,
        result="success",
        metadata={
            "filename": document.original_filename,
            "opportunity_id": str(opportunity_id) if opportunity_id else None,
            "procurement_item_id": str(procurement_item_id) if procurement_item_id else None,
            "folder_id": folder_id,
            "media_type": media_type,
            "byte_size": document.byte_size,
            "acquisition_status": "subido",
            "priority": "manual_over_auto",
            "uploader_id": str(uploader_id),
        },
    )

    job_id: str | None = None
    if process_inline and job is not None:
        try:
            process_document(document.id, version.id, job)
            document = db.session.get(Document, document.id) or document
            if document.status == "failed":
                # Rollback de estado de adquisición honesto ante parse fallido.
                set_acquisition_meta(
                    document,
                    {
                        "status": "no_disponible",
                        "source": SOURCE_MANUAL,
                        "reason_code": "parse_failed",
                        "reason": (
                            f"La subida manual falló al procesar: "
                            f"{document.safe_error_code or 'error de formato'}."
                        ),
                    },
                )
                db.session.commit()
                raise PliegoAcquisitionError(
                    "El archivo se recibió pero no se pudo procesar. "
                    "Revise formato (PDF/texto) y tamaño.",
                    code="parse_failed",
                )
        except DocumentError as error:
            db.session.rollback()
            # Re-cargar y marcar no_disponible sin dejar estado «subido» falso.
            document = db.session.get(Document, document.id)
            if document is not None:
                set_acquisition_meta(
                    document,
                    {
                        "status": "no_disponible",
                        "source": SOURCE_MANUAL,
                        "reason_code": "parse_failed",
                        "reason": str(error),
                    },
                )
                db.session.commit()
            raise PliegoAcquisitionError(str(error), code="parse_failed") from error
    else:
        bg_job = stage_job(
            "oracle.document.process",
            payload={"document_id": str(document.id), "version_id": str(version.id)},
            idempotency_key=f"document-process-{version.id}",
            requested_by_user_id=uploader_id,
            dossier_id=dossier_id,
            resource_type="document",
            resource_id=document.id,
        )
        db.session.commit()
        publish_job(bg_job)
        job_id = str(bg_job.id)

    return document, version, job_id


def record_download_failure(
    *,
    dossier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    reference: dict[str, str],
    reason_code: str,
    reason: str,
    http_status: int | None = None,
) -> None:
    """Persiste un marcador durable de fallo HTTP/WAF (sin fingir 0 documentos)."""
    # Documento sentinel de metadata-only no se crea: el estado vive en el
    # informe (document_acquisitions) y se relee vía pins. Aquí anotamos en
    # cualquier doc ligado a la URI, si existe.
    linked = db.session.scalar(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.dossier_id == dossier_id,
            Document.metadata_json["source_uri"].as_string() == reference.get("uri"),
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    if linked is None:
        return
    set_acquisition_meta(
        linked,
        {
            "status": "no_disponible",
            "source": SOURCE_PLACSP,
            "reason_code": reason_code,
            "reason": reason,
            "http_status": http_status,
            "source_uri": reference.get("uri"),
            "source_file_name": reference.get("file_name"),
        },
    )


def mark_partial_extract(
    document: Document,
    *,
    reference: dict[str, str],
    reason_code: str,
    reason: str,
) -> None:
    set_acquisition_meta(
        document,
        {
            "status": "extracto_parcial",
            "source": SOURCE_EXTRACT,
            "reason_code": reason_code,
            "reason": reason,
            "source_uri": reference.get("uri"),
            "source_file_name": reference.get("file_name"),
            "provenance": "dossier_ready_extract",
            "is_full_pcap": False,
        },
    )


def mark_downloaded(document: Document, *, reference: dict[str, str]) -> None:
    # No pisa subido.
    set_acquisition_meta(
        document,
        {
            "status": "descargado",
            "source": SOURCE_PLACSP,
            "reason_code": "downloaded",
            "reason": "Documento oficial PLACSP descargado y procesado.",
            "source_uri": reference.get("uri"),
            "source_file_name": reference.get("file_name"),
        },
    )


def classify_download_error(
    error: BaseException,
    *,
    http_status: int | None = None,
) -> tuple[str, str]:
    """Return (reason_code, human_reason) for honest UI/API."""
    msg = str(error or "")
    low = msg.casefold()
    if http_status == 403 or "403" in low or "forbidden" in low or "waf" in low:
        return (
            "http_403_waf",
            "Descarga bloqueada (HTTP 403/WAF). Suba el PCAP manualmente.",
        )
    if http_status == 429 or "429" in low or "rate" in low:
        return (
            "http_429",
            "Descarga limitada por el origen (HTTP 429). Suba el PCAP manualmente.",
        )
    if http_status is not None and http_status >= 500:
        return (
            "http_5xx",
            f"El origen devolvió error HTTP {http_status}. Suba el PCAP manualmente.",
        )
    if "timeout" in low or "timed out" in low:
        return (
            "timeout",
            "Tiempo de espera agotado al descargar el pliego. Suba el PCAP manualmente.",
        )
    if "redirect" in low or "no está permitida" in low or "no confiable" in low:
        return (
            "redirect_rejected",
            "Redirección a host no validado rechazada (SSRF). Suba el PCAP manualmente.",
        )
    if "no es pdf" in low:
        return ("not_pdf", "El adjunto no es un PDF válido.")
    if "límite" in low:
        return ("size_limit", "El documento supera el límite del informe.")
    return ("download_failed", msg or DOWNLOAD_FAIL_WARNING)
