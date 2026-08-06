"""G-11 · estado honesto de adquisición de pliego/PCAP y subida manual.

La descarga automática PLACSP es best-effort. Comercialmente el camino fiable es:
subir el PCAP → Oracle trocea, puntúa y prepara el esqueleto.

Estados de adquisición:
  - procesando: subida recibida; pipeline asíncrono aún no cierra (no terminal)
  - descargado: PDF oficial descargado y procesado
  - subido: PCAP manual válido y ready (prioridad máxima; terminal)
  - extracto_parcial: se usó extracto/metadatos con procedencia y aviso
  - no_disponible: sin documento usable (HTTP/WAF, Signal vacío, parse fallido)

La prioridad manual sobre auto solo aplica cuando el documento está ready/usable.
Los fallos de descarga se persisten por tenant+dossier+URI sin crear un documento falso.
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

AcquisitionStatus = Literal[
    "procesando", "descargado", "subido", "extracto_parcial", "no_disponible"
]

ACQUISITION_STATUSES: frozenset[str] = frozenset(
    {"procesando", "descargado", "subido", "extracto_parcial", "no_disponible"}
)

# Prioridad: subida humana ready > descarga OK > extracto > procesando > no disponible.
_STATUS_RANK: dict[str, int] = {
    "subido": 40,
    "descargado": 30,
    "extracto_parcial": 20,
    "procesando": 15,
    "no_disponible": 10,
}

META_KEY = "pliego_acquisition"
SOURCE_MANUAL = "manual_pcap"
SOURCE_PLACSP = "placsp_codice"
SOURCE_EXTRACT = "extracto_parcial"
# Durable last download attempt on dossier.profile_config (no fake document).
ATTEMPTS_KEY = "pliego_download_attempts"

DOWNLOAD_FAIL_WARNING = "descarga automática fallida; suba el PCAP manualmente"
EMPTY_DOCUMENTS_WARNING = "Signal no entregó documentos CODICE; suba el PCAP manualmente"
PARTIAL_EXTRACT_WARNING = "análisis sobre extracto parcial; no es el PCAP completo"

AUDIT_UPLOAD_RECEIVED = "document.pcap_upload_received"
AUDIT_MANUAL_SUCCESS = "document.pcap_manual_upload_success"
AUDIT_MANUAL_FAILURE = "document.pcap_manual_upload_failed"
# Legacy action retained only for historical rows; new terminal success uses AUDIT_MANUAL_SUCCESS.
AUDIT_LEGACY_UPLOAD = "document.pcap_manual_upload"


class PliegoAcquisitionError(Exception):
    def __init__(self, message: str, *, code: str = "pliego_acquisition_error") -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def acquisition_meta(document: Document) -> dict[str, Any]:
    raw = (document.metadata_json or {}).get(META_KEY)
    return dict(raw) if isinstance(raw, dict) else {}


def set_acquisition_meta(
    document: Document,
    payload: dict[str, Any],
    *,
    force: bool = False,
) -> None:
    """Actualiza metadata de adquisición.

    Protege un ``subido`` manual terminal de degradación por retry automático, pero
    permite transiciones del propio pipeline manual (p.ej. ``procesando`` →
    ``subido`` / ``no_disponible``) y correcciones con ``force=True``.
    ``updated_at`` siempre se renueva.
    """
    meta = dict(document.metadata_json or {})
    existing = dict(meta.get(META_KEY) or {}) if isinstance(meta.get(META_KEY), dict) else {}
    existing_status = str(existing.get("status") or "")
    new_status = str(payload.get("status") or "")
    payload_source = str(payload.get("source") or existing.get("source") or "")
    existing_source = str(existing.get("source") or "")

    if (
        not force
        and existing_status == "subido"
        and existing_source == SOURCE_MANUAL
        and new_status
        and new_status != "subido"
        and _STATUS_RANK.get(new_status, 0) < _STATUS_RANK.get("subido", 0)
        and payload_source != SOURCE_MANUAL
    ):
        # Retry automático / descarga: no degradar un PCAP manual ready.
        return

    existing.update(payload)
    existing["updated_at"] = _now().isoformat()
    meta[META_KEY] = existing
    document.metadata_json = meta


def _is_manual_pcap(document: Document) -> bool:
    meta = acquisition_meta(document)
    if str(meta.get("source") or "") == SOURCE_MANUAL:
        return True
    if str((document.metadata_json or {}).get("source") or "") == SOURCE_MANUAL:
        return True
    name = (document.original_filename or "").casefold()
    return "pcap" in name and str(meta.get("status") or "") in {
        "subido",
        "procesando",
        "no_disponible",
    }


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
                Document.status.in_(
                    ("ready", "queued", "processing", "uploaded", "failed", "quarantined")
                ),
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
    """PCAP manual ready/usable tiene prioridad absoluta sobre auto/extractos.

    Upload en cola, fallido o en cuarentena no bloquea una descarga automática válida.
    """
    for doc in list_manual_pcap_documents(tenant_id=tenant_id, dossier_id=dossier_id):
        meta = acquisition_meta(doc)
        # Solo ready cuenta como preferido, independientemente de meta intermedia.
        if doc.status != "ready":
            continue
        if str(meta.get("status") or "") == "no_disponible":
            continue
        if document_available_for_citation(doc):
            return doc
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


def _manual_acquisition_status(document: Document) -> tuple[str, str, str]:
    """Return (status, reason_code, reason) for a manual PCAP document."""
    meta = acquisition_meta(document)
    if document.status == "ready":
        return (
            "subido",
            str(meta.get("reason_code") or "manual_upload"),
            str(meta.get("reason") or "PCAP subido manualmente y listo para uso."),
        )
    if document.status in {"failed", "quarantined"}:
        code = str(
            meta.get("reason_code")
            or document.safe_error_code
            or ("quarantined" if document.status == "quarantined" else "parse_failed")
        )
        return (
            "no_disponible",
            code,
            str(
                meta.get("reason")
                or f"La subida manual no es usable ({document.status}: {code})."
            ),
        )
    # queued / processing / uploaded → no terminal
    return (
        "procesando",
        str(meta.get("reason_code") or "upload_received"),
        str(
            meta.get("reason")
            or "PCAP recibido; Oracle lo procesa en segundo plano."
        ),
    )


def _load_download_attempts(
    *, tenant_id: uuid.UUID, dossier_id: uuid.UUID
) -> dict[str, dict[str, Any]]:
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        return {}
    raw = (dossier.profile_config or {}).get(ATTEMPTS_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and key:
            out[str(key)] = dict(value)
    return out


def get_download_attempt(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    source_uri: str,
) -> dict[str, Any] | None:
    attempts = _load_download_attempts(tenant_id=tenant_id, dossier_id=dossier_id)
    row = attempts.get(source_uri)
    return dict(row) if isinstance(row, dict) else None


def record_download_failure(
    *,
    dossier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    reference: dict[str, str],
    reason_code: str,
    reason: str,
    http_status: int | None = None,
    procurement_item_id: uuid.UUID | str | None = None,
    attempt: int | None = None,
) -> dict[str, Any]:
    """Persiste el último intento de descarga por tenant+dossier+URI (sin blob falso)."""
    uri = str(reference.get("uri") or "").strip()
    if not uri:
        return {}

    dossier = db.session.scalar(
        select(StrategicDossier)
        .where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if dossier is None:
        return {}

    config = dict(dossier.profile_config or {})
    raw_attempts = config.get(ATTEMPTS_KEY)
    attempts = dict(raw_attempts) if isinstance(raw_attempts, dict) else {}
    previous = dict(attempts.get(uri) or {}) if isinstance(attempts.get(uri), dict) else {}
    attempt_n = attempt if attempt is not None else int(previous.get("attempt") or 0) + 1
    entry: dict[str, Any] = {
        "status": "no_disponible",
        "reason_code": reason_code,
        "reason": reason,
        "http_status": http_status,
        "source_uri": uri,
        "file_name": reference.get("file_name"),
        "procurement_item_id": (
            str(procurement_item_id)
            if procurement_item_id
            else previous.get("procurement_item_id")
        ),
        "attempt": attempt_n,
        "updated_at": _now().isoformat(),
    }
    attempts[uri] = entry
    config[ATTEMPTS_KEY] = attempts
    dossier.profile_config = config

    # Si ya hay documento ligado, anotar sin inventar filas.
    linked = db.session.scalar(
        select(Document)
        .where(
            Document.tenant_id == tenant_id,
            Document.dossier_id == dossier_id,
            Document.metadata_json["source_uri"].as_string() == uri,
        )
        .order_by(Document.created_at.desc())
        .limit(1)
    )
    if linked is not None:
        set_acquisition_meta(
            linked,
            {
                "status": "no_disponible",
                "source": SOURCE_PLACSP,
                "reason_code": reason_code,
                "reason": reason,
                "http_status": http_status,
                "source_uri": uri,
                "source_file_name": reference.get("file_name"),
                "attempt": attempt_n,
            },
        )
    return entry


def clear_download_attempt_on_success(
    *,
    dossier_id: uuid.UUID,
    tenant_id: uuid.UUID,
    source_uri: str,
    status: str = "descargado",
) -> None:
    """Un éxito posterior supera el fallo durable de descarga."""
    uri = (source_uri or "").strip()
    if not uri:
        return
    dossier = db.session.scalar(
        select(StrategicDossier)
        .where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    if dossier is None:
        return
    config = dict(dossier.profile_config or {})
    raw_attempts = config.get(ATTEMPTS_KEY)
    attempts = dict(raw_attempts) if isinstance(raw_attempts, dict) else {}
    previous = dict(attempts.get(uri) or {}) if isinstance(attempts.get(uri), dict) else {}
    attempts[uri] = {
        **previous,
        "status": status,
        "reason_code": "downloaded" if status == "descargado" else status,
        "reason": "Documento oficial PLACSP descargado y procesado.",
        "source_uri": uri,
        "attempt": int(previous.get("attempt") or 0) + 1,
        "updated_at": _now().isoformat(),
        "http_status": 200,
    }
    config[ATTEMPTS_KEY] = attempts
    dossier.profile_config = config


def resolve_dossier_pliego_acquisition(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Estado honesto agregado + por referencia CODICE / subida manual.

    Nunca convierte un error tragado en «0 documentos» normal: si no hay PCAP
    usable, el estado es ``no_disponible`` con razón explícita (durable).
    """
    manual = prefer_manual_pcap(tenant_id=tenant_id, dossier_id=dossier_id)
    manual_all = list_manual_pcap_documents(
        tenant_id=tenant_id, dossier_id=dossier_id, opportunity_id=opportunity_id
    )
    download_attempts = _load_download_attempts(tenant_id=tenant_id, dossier_id=dossier_id)

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
                        "reason": str(meta.get("reason") or PARTIAL_EXTRACT_WARNING),
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
            # Fallo HTTP/WAF durable (profile_config) o metadata de doc ligado.
            fail_reason = DOWNLOAD_FAIL_WARNING
            fail_code = "download_unavailable"
            fail_http: int | None = None
            fail_attempt: int | None = None
            durable = download_attempts.get(ref["uri"])
            if isinstance(durable, dict) and str(durable.get("status")) == "no_disponible":
                fail_reason = str(durable.get("reason") or fail_reason)
                fail_code = str(durable.get("reason_code") or fail_code)
                raw_http = durable.get("http_status")
                fail_http = int(raw_http) if raw_http is not None else None
                raw_attempt = durable.get("attempt")
                fail_attempt = int(raw_attempt) if raw_attempt is not None else None
            else:
                for doc in extract_docs:
                    meta = acquisition_meta(doc)
                    if (
                        meta.get("source_uri") == ref["uri"]
                        and str(meta.get("status")) == "no_disponible"
                    ):
                        fail_reason = str(meta.get("reason") or fail_reason)
                        fail_code = str(meta.get("reason_code") or fail_code)
                        raw_http = meta.get("http_status")
                        fail_http = int(raw_http) if raw_http is not None else None
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
                    "http_status": fail_http,
                    "attempt": fail_attempt,
                }
            )

    for doc in manual_all:
        meta = acquisition_meta(doc)
        status, reason_code, reason = _manual_acquisition_status(doc)
        acquisitions.append(
            {
                "key": f"manual:{doc.id}",
                "status": status,
                "reason_code": reason_code,
                "reason": reason,
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
    elif any(a["status"] == "procesando" for a in acquisitions):
        overall = "procesando"
        overall_reason = "Hay una subida manual en procesamiento; aún no es un éxito terminal."
        overall_code = "upload_processing"
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
        # Prefer durable reason when all refs failed the same way.
        durable_codes = [
            a.get("reason_code")
            for a in acquisitions
            if a.get("status") == "no_disponible" and a.get("source_uri")
        ]
        if durable_codes and all(c == durable_codes[0] for c in durable_codes):
            overall_code = str(durable_codes[0] or "download_unavailable")
            reasons = [
                a.get("reason")
                for a in acquisitions
                if a.get("reason_code") == overall_code
            ]
            overall_reason = str(reasons[0] if reasons else DOWNLOAD_FAIL_WARNING)
        else:
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

    El POST deja el estado en ``procesando`` (no terminal). El job
    ``oracle.document.process`` cierra a ``subido`` / ``no_disponible``.

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
            "status": "procesando",
            "source": SOURCE_MANUAL,
            "reason_code": "upload_received",
            "reason": (
                "PCAP recibido; procesamiento en curso. "
                "Aún no es un éxito terminal ni preferido."
            ),
            "opportunity_id": str(opportunity_id) if opportunity_id else None,
            "procurement_item_id": str(procurement_item_id) if procurement_item_id else None,
            "folder_id": folder_id,
            "uploaded_by_user_id": str(uploader_id),
            "uploaded_at": _now().isoformat(),
            "terminal_result": None,
        },
    )
    meta = dict(document.metadata_json or {})
    meta["source"] = SOURCE_MANUAL
    meta["document_type"] = "legal"
    meta["manual_pcap"] = True
    document.metadata_json = meta
    db.session.flush()

    # Recepción (no terminal). result=success solo indica que la recepción se
    # registró; el éxito de adquisición terminal usa AUDIT_MANUAL_SUCCESS.
    append_audit_event(
        db.session,
        action=AUDIT_UPLOAD_RECEIVED,
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
            "acquisition_status": "procesando",
            "priority": "manual_over_auto_when_ready",
            "uploader_id": str(uploader_id),
            "phase": "upload_received",
            "terminal": False,
        },
    )

    job_id: str | None = None
    if process_inline and job is not None:
        try:
            process_document(document.id, version.id, job)
            document = db.session.get(Document, document.id) or document
            finalize_manual_pcap_after_process(
                document_id=document.id,
                job=job,
                process_result={"inline": True},
            )
            document = db.session.get(Document, document.id) or document
            if document.status in {"failed", "quarantined"}:
                raise PliegoAcquisitionError(
                    "El archivo se recibió pero no se pudo procesar. "
                    "Revise formato (PDF/texto) y tamaño.",
                    code="parse_failed",
                )
        except DocumentError as error:
            db.session.rollback()
            failed_document = db.session.get(Document, document.id)
            if failed_document is not None:
                finalize_manual_pcap_after_process(
                    document_id=failed_document.id,
                    job=job,
                    error=error,
                )
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


def finalize_manual_pcap_after_process(
    *,
    document_id: uuid.UUID,
    job: Any,
    process_result: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> dict[str, Any] | None:
    """Cierra la adquisición manual al terminar ``oracle.document.process``.

    - ready usable → ``subido`` + evento terminal único de éxito
    - failed/quarantined/parse permanente → ``no_disponible`` + evento de fallo
    - ignored/retry temporal → permanece ``procesando`` sin afirmar éxito
    """
    del process_result  # reserved for future diagnostics
    document = db.session.scalar(
        select(Document)
        .where(Document.id == document_id)
        .execution_options(populate_existing=True)
    )
    if document is None:
        return None
    if not _is_manual_pcap(document):
        return None

    meta = acquisition_meta(document)
    if meta.get("terminal_result") in {"success", "failure"}:
        # Idempotente: no duplicar eventos terminales ni reescribir meta.
        return {
            "ignored": True,
            "reason": "already_terminal",
            "terminal_result": meta.get("terminal_result"),
            "status": meta.get("status"),
        }

    correlation_id = getattr(job, "correlation_id", None) or getattr(job, "id", None)
    correlation = str(correlation_id) if correlation_id is not None else None
    job_id = str(getattr(job, "id", "") or "") or None

    if document.status == "ready":
        set_acquisition_meta(
            document,
            {
                "status": "subido",
                "source": SOURCE_MANUAL,
                "reason_code": "manual_upload",
                "reason": (
                    "PCAP subido manualmente y procesado; tiene prioridad sobre "
                    "descarga automática y extractos."
                ),
                "terminal_result": "success",
                "closed_by_job_id": job_id,
            },
            force=True,
        )
        append_audit_event(
            db.session,
            action=AUDIT_MANUAL_SUCCESS,
            resource_type="document",
            resource_id=document.id,
            dossier_id=document.dossier_id,
            result="success",
            correlation_id=correlation,
            metadata={
                "filename": document.original_filename,
                "acquisition_status": "subido",
                "priority": "manual_over_auto",
                "job_id": job_id,
                "phase": "process_complete",
                "document_status": document.status,
            },
        )
        db.session.commit()
        return {"status": "subido", "terminal_result": "success"}

    if document.status in {"failed", "quarantined"} or error is not None:
        code = str(
            document.safe_error_code
            or (type(error).__name__.lower() if error is not None else "parse_failed")
        )
        if document.status == "quarantined":
            code = "quarantined"
        reason = (
            f"La subida manual falló al procesar ({code}). "
            "El PCAP no es usable ni preferido."
        )
        set_acquisition_meta(
            document,
            {
                "status": "no_disponible",
                "source": SOURCE_MANUAL,
                "reason_code": code,
                "reason": reason,
                "terminal_result": "failure",
                "closed_by_job_id": job_id,
            },
            force=True,
        )
        append_audit_event(
            db.session,
            action=AUDIT_MANUAL_FAILURE,
            resource_type="document",
            resource_id=document.id,
            dossier_id=document.dossier_id,
            result="failure",
            correlation_id=correlation,
            metadata={
                "filename": document.original_filename,
                "acquisition_status": "no_disponible",
                "reason_code": code,
                "job_id": job_id,
                "phase": "process_failed",
                "document_status": document.status,
            },
        )
        db.session.commit()
        return {"status": "no_disponible", "terminal_result": "failure", "reason_code": code}

    # Temporal / ignored: no afirmar éxito; mantener no terminal.
    if str(meta.get("status") or "") != "procesando":
        set_acquisition_meta(
            document,
            {
                "status": "procesando",
                "source": SOURCE_MANUAL,
                "reason_code": "upload_received",
                "reason": "PCAP en procesamiento; resultado aún no terminal.",
            },
            force=True,
        )
        db.session.commit()
    return {"status": "procesando", "terminal_result": None}


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
    # No pisa subido manual (proteccion en set_acquisition_meta).
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
    if document.dossier_id is not None:
        clear_download_attempt_on_success(
            dossier_id=document.dossier_id,
            tenant_id=document.tenant_id,
            source_uri=str(reference.get("uri") or ""),
            status="descargado",
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
