"""G-11 · fallback real de pliego: fallos HTTP/WAF, estado honesto, prioridad manual."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from opn_oracle.oracle.pliego_acquisition import (
    DOWNLOAD_FAIL_WARNING,
    EMPTY_DOCUMENTS_WARNING,
    PARTIAL_EXTRACT_WARNING,
    SOURCE_MANUAL,
    classify_download_error,
    set_acquisition_meta,
)
from opn_oracle.oracle.procurement_report import (
    ProcurementDocumentReportError,
    _ingest_documents,
    download_placsp_pdf,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_download_classifies_403_waf() -> None:
    with (
        _client(lambda request: httpx.Response(403, text="WAF blocked")) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "http_403_waf"
    assert exc.value.http_status == 403
    assert "manualmente" in str(exc.value).casefold() or "WAF" in str(exc.value) or "403" in str(
        exc.value
    )


def test_download_classifies_429() -> None:
    with (
        _client(lambda request: httpx.Response(429, text="slow down")) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "http_429"
    assert exc.value.http_status == 429


@pytest.mark.parametrize("status", [500, 502, 503])
def test_download_classifies_5xx(status: int) -> None:
    with (
        _client(lambda request: httpx.Response(status, text="upstream")) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "http_5xx"
    assert exc.value.http_status == status


def test_download_rejects_redirect_to_untrusted_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/steal.pdf"},
        )

    with (
        _client(handler) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "redirect_rejected"


def test_download_rejects_redirect_even_to_allowlisted_without_follow() -> None:
    """No follow automático: cada salto debe revalidarse; política SSRF intacta."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://contrataciondelestado.es/other.pdf"},
        )

    with (
        _client(handler) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "redirect_rejected"


def test_download_timeout_is_honest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with (
        _client(handler) as client,
        pytest.raises(ProcurementDocumentReportError) as exc,
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf",
            max_bytes=1024,
            client=client,
        )
    assert exc.value.reason_code == "timeout"


def test_classify_download_error_matrix() -> None:
    assert classify_download_error(Exception("x"), http_status=403)[0] == "http_403_waf"
    assert classify_download_error(Exception("x"), http_status=429)[0] == "http_429"
    assert classify_download_error(Exception("x"), http_status=503)[0] == "http_5xx"
    assert classify_download_error(Exception("timeout waiting"))[0] == "timeout"
    assert classify_download_error(Exception("redirect host"))[0] == "redirect_rejected"


def test_set_acquisition_meta_does_not_downgrade_manual_upload() -> None:
    doc = SimpleNamespace(
        metadata_json={
            "pliego_acquisition": {
                "status": "subido",
                "source": SOURCE_MANUAL,
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        }
    )
    set_acquisition_meta(
        doc,  # type: ignore[arg-type]
        {
            "status": "no_disponible",
            "source": "placsp_codice",
            "reason": "retry peor",
        },
    )
    assert doc.metadata_json["pliego_acquisition"]["status"] == "subido"
    # Auto retry no toca updated_at (salida temprana).
    assert doc.metadata_json["pliego_acquisition"]["updated_at"] == "2020-01-01T00:00:00+00:00"


def test_set_acquisition_meta_allows_manual_pipeline_terminal_and_updates_at() -> None:
    doc = SimpleNamespace(
        metadata_json={
            "pliego_acquisition": {
                "status": "procesando",
                "source": SOURCE_MANUAL,
                "updated_at": "2020-01-01T00:00:00+00:00",
            }
        }
    )
    set_acquisition_meta(
        doc,  # type: ignore[arg-type]
        {
            "status": "no_disponible",
            "source": SOURCE_MANUAL,
            "reason_code": "parse_failed",
            "reason": "parse failed",
        },
        force=True,
    )
    meta = doc.metadata_json["pliego_acquisition"]
    assert meta["status"] == "no_disponible"
    assert meta["updated_at"] != "2020-01-01T00:00:00+00:00"


def test_set_acquisition_meta_allows_procesando_to_subido() -> None:
    doc = SimpleNamespace(
        metadata_json={
            "pliego_acquisition": {"status": "procesando", "source": SOURCE_MANUAL}
        }
    )
    set_acquisition_meta(
        doc,  # type: ignore[arg-type]
        {
            "status": "subido",
            "source": SOURCE_MANUAL,
            "reason_code": "manual_upload",
        },
        force=True,
    )
    assert doc.metadata_json["pliego_acquisition"]["status"] == "subido"
    assert "updated_at" in doc.metadata_json["pliego_acquisition"]


def test_ingest_empty_documents_is_no_disponible_not_silent_zero() -> None:
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        classification="internal",
        source_snapshot={"procurement_items": []},
    )
    with patch(
        "opn_oracle.oracle.procurement_report.prefer_manual_pcap",
        return_value=None,
    ):
        outcome = _ingest_documents(report, SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]
    assert outcome["documents"] == 0
    assert outcome["acquisitions"]
    assert outcome["acquisitions"][0]["status"] == "no_disponible"
    assert outcome["acquisitions"][0]["reason_code"] == "signal_documents_empty"
    assert EMPTY_DOCUMENTS_WARNING in outcome["warnings"][0]
    assert outcome["acquisitions"][0]["manual_upload_offered"] is True


def test_ingest_http_403_uses_partial_extract_when_available() -> None:
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        classification="internal",
        source_snapshot={
            "procurement_items": [
                {
                    "kind": "tender",
                    "snapshot": {
                        "documents": [
                            {
                                "uri": "https://contrataciondelestado.es/pcap.pdf",
                                "file_name": "PCAP.pdf",
                                "doc_type": "legal",
                            }
                        ]
                    },
                }
            ]
        },
    )
    with (
        patch(
            "opn_oracle.oracle.procurement_report.prefer_manual_pcap",
            return_value=None,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.download_placsp_pdf",
            side_effect=ProcurementDocumentReportError(
                "Descarga bloqueada (HTTP 403/WAF). Suba el PCAP manualmente.",
                reason_code="http_403_waf",
                http_status=403,
            ),
        ),
        patch(
            "opn_oracle.oracle.procurement_report._use_partial_extract_fallback",
            return_value=(
                1,
                2,
                [f"{PARTIAL_EXTRACT_WARNING} (ref=PCAP.pdf; waf)"],
                [
                    {
                        "status": "extracto_parcial",
                        "reason_code": "http_403_waf",
                        "document_id": str(uuid.uuid4()),
                        "is_full_pcap": False,
                    }
                ],
            ),
        ) as fb,
        patch(
            "opn_oracle.oracle.procurement_report.record_download_failure",
            return_value={},
        ),
    ):
        outcome = _ingest_documents(report, SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]
    fb.assert_called_once()
    assert outcome["documents"] == 1
    assert outcome["evidence"] == 2
    assert any(a["status"] == "extracto_parcial" for a in outcome["acquisitions"])
    assert any(PARTIAL_EXTRACT_WARNING in w for w in outcome["warnings"])
    assert any(DOWNLOAD_FAIL_WARNING in w for w in outcome["warnings"])


def test_ingest_http_403_without_extract_is_no_disponible_visible() -> None:
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        classification="internal",
        source_snapshot={
            "procurement_items": [
                {
                    "kind": "tender",
                    "snapshot": {
                        "documents": [
                            {
                                "uri": "https://contrataciondelestado.es/pcap.pdf",
                                "file_name": "PCAP.pdf",
                                "doc_type": "legal",
                            }
                        ]
                    },
                }
            ]
        },
    )
    with (
        patch(
            "opn_oracle.oracle.procurement_report.prefer_manual_pcap",
            return_value=None,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.download_placsp_pdf",
            side_effect=ProcurementDocumentReportError(
                "Descarga bloqueada (HTTP 403/WAF).",
                reason_code="http_403_waf",
                http_status=403,
            ),
        ),
        patch(
            "opn_oracle.oracle.procurement_report._use_partial_extract_fallback",
            return_value=(0, 0, [], []),
        ),
        patch(
            "opn_oracle.oracle.procurement_report.record_download_failure",
            return_value={
                "status": "no_disponible",
                "reason_code": "http_403_waf",
                "attempt": 1,
            },
        ) as rec,
    ):
        outcome = _ingest_documents(report, SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]
    rec.assert_called_once()
    assert outcome["documents"] == 0
    assert outcome["acquisitions"][0]["status"] == "no_disponible"
    assert outcome["acquisitions"][0]["reason_code"] == "http_403_waf"
    assert outcome["acquisitions"][0]["manual_upload_offered"] is True
    # No se traga como «éxito con 0 docs» sin razón.
    assert outcome["warnings"]


def test_manual_pcap_preferred_over_auto_download() -> None:
    manual = SimpleNamespace(
        id=uuid.uuid4(),
        status="ready",
        scan_result={},
        original_filename="PCAP_manual.pdf",
    )
    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        requested_by_user_id=uuid.uuid4(),
        classification="internal",
        source_snapshot={
            "procurement_items": [
                {
                    "kind": "tender",
                    "snapshot": {
                        "documents": [
                            {
                                "uri": "https://contrataciondelestado.es/pcap.pdf",
                                "file_name": "PCAP.pdf",
                                "doc_type": "legal",
                            }
                        ]
                    },
                }
            ]
        },
    )
    download = MagicMock()
    with (
        patch(
            "opn_oracle.oracle.procurement_report.prefer_manual_pcap",
            return_value=manual,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.document_available_for_citation",
            return_value=True,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.official_unscanned_document_allowed",
            return_value=False,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.mark_official_unscanned_acceptance",
            return_value=False,
        ),
        patch(
            "opn_oracle.oracle.procurement_report._ensure_chunk_evidence",
            return_value=3,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.download_placsp_pdf",
            download,
        ),
    ):
        outcome = _ingest_documents(report, SimpleNamespace(id=uuid.uuid4()))  # type: ignore[arg-type]
    download.assert_not_called()
    assert outcome["manual_preferred"] is True
    assert outcome["documents"] == 1
    assert outcome["acquisitions"][0]["status"] == "subido"
    assert outcome["acquisitions"][0]["reason_code"] == "manual_preferred"
