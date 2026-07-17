"""Document security acceptance policy shared by reports, download and search."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from flask import current_app

from opn_oracle.documents.models import Document

OFFICIAL_UNSCANNED_HOSTS = frozenset({"contrataciondelestado.es"})
OFFICIAL_UNSCANNED_POLICY = "official_source_without_clamav_v1"


def official_document_source_uri(document: Document) -> str:
    value = (document.metadata_json or {}).get("source_uri")
    return str(value or "").strip()


def official_document_source_host(document: Document) -> str | None:
    uri = official_document_source_uri(document)
    if not uri:
        return None
    parsed = urlparse(uri)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port
        not in {
            None,
            443,
        }
    ):
        return None
    hostname = parsed.hostname
    return hostname if hostname in OFFICIAL_UNSCANNED_HOSTS else None


def official_unscanned_exception_enabled() -> bool:
    return (
        bool(current_app.config.get("DOCUMENT_ALLOW_OFFICIAL_UNSCANNED", False))
        and current_app.config.get("DOCUMENT_SCANNER_MODE") == "noop"
    )


def official_unscanned_document_allowed(document: Document) -> bool:
    return (
        document.status == "ready"
        and document.scan_status == "not_configured"
        and official_unscanned_exception_enabled()
        and official_document_source_host(document) is not None
    )


def official_unscanned_acceptance(document: Document) -> dict[str, Any] | None:
    acceptance = (document.scan_result or {}).get("official_unscanned_acceptance")
    if isinstance(acceptance, dict) and acceptance.get("accepted") is True:
        return acceptance
    return None


def document_available_for_citation(document: Document) -> bool:
    if document.status != "ready":
        return False
    if document.scan_status == "clean":
        return True
    return (
        official_unscanned_document_allowed(document)
        and official_unscanned_acceptance(document) is not None
    )


def document_unavailable_reason(document: Document | None) -> str:
    if document is None:
        return "El documento oficial no quedó disponible."
    if document.status != "ready":
        return "El documento oficial no quedó procesado."
    if document.scan_status in {"infected", "error"}:
        return "El documento oficial no supera la revisión de seguridad."
    if document.scan_status == "not_configured":
        if not current_app.config.get("DOCUMENT_ALLOW_OFFICIAL_UNSCANNED", False):
            return (
                "El antivirus documental no está configurado y la excepción oficial está "
                "desactivada."
            )
        if current_app.config.get("DOCUMENT_SCANNER_MODE") != "noop":
            return "La excepción oficial no aplica cuando el antivirus está configurado."
        if official_document_source_host(document) is None:
            return "El documento sin escanear no procede de una fuente oficial permitida."
    return "El documento oficial no supera la política documental."


def mark_official_unscanned_acceptance(
    document: Document,
    *,
    report_id: Any | None = None,
    job_id: Any | None = None,
) -> bool:
    if not official_unscanned_document_allowed(document):
        return False
    host = official_document_source_host(document)
    result = dict(document.scan_result or {})
    current = result.get("official_unscanned_acceptance")
    if isinstance(current, dict) and current.get("accepted") is True:
        return False
    result["official_unscanned_acceptance"] = {
        "accepted": True,
        "policy": OFFICIAL_UNSCANNED_POLICY,
        "reason": "clamav_postponed_official_source",
        "source_uri": official_document_source_uri(document),
        "source_host": host,
        "scan_status": document.scan_status,
        "scanner_mode": current_app.config.get("DOCUMENT_SCANNER_MODE"),
        "report_id": str(report_id) if report_id is not None else None,
        "job_id": str(job_id) if job_id is not None else None,
        "accepted_at": datetime.now(UTC).isoformat(),
    }
    document.scan_result = result
    return True


def document_scan_provenance(document: Document) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "document_scan_status": document.scan_status,
        "document_scan_engine": (document.scan_result or {}).get("engine"),
    }
    exception = official_unscanned_acceptance(document)
    if exception is not None:
        provenance["document_scan_exception"] = {
            "policy": exception.get("policy"),
            "reason": exception.get("reason"),
            "source_host": exception.get("source_host"),
        }
    return provenance
