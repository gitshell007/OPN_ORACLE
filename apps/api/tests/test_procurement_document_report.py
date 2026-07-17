from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from flask import Flask

from opn_oracle.documents.security import (
    document_available_for_citation,
    mark_official_unscanned_acceptance,
    official_unscanned_document_allowed,
)
from opn_oracle.oracle.procurement_report import (
    MAX_DOCUMENTS_PER_REPORT,
    ProcurementDocumentReportError,
    _referenced_documents,
    download_placsp_pdf,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _document(
    *,
    scan_status: str = "not_configured",
    source_uri: str = "https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?id=1",
):
    return SimpleNamespace(
        id="document-1",
        status="ready",
        scan_status=scan_status,
        scan_result={"engine": "noop", "signature": None},
        metadata_json={"source_uri": source_uri},
    )


def test_download_placsp_pdf_accepts_direct_pdf_and_rejects_untrusted_host() -> None:
    with _client(lambda request: httpx.Response(200, content=b"%PDF-1.7\nsource")) as client:
        payload = download_placsp_pdf(
            "https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?cifrado=x",
            max_bytes=1024,
            client=client,
        )
    assert payload.startswith(b"%PDF-")
    with pytest.raises(ProcurementDocumentReportError):
        download_placsp_pdf("https://example.test/file.pdf", max_bytes=1024)


def test_download_placsp_pdf_enforces_size_and_pdf_signature() -> None:
    with (
        _client(
            lambda request: httpx.Response(200, headers={"content-length": "999"}, content=b"%PDF-")
        ) as client,
        pytest.raises(ProcurementDocumentReportError, match="límite"),
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.pdf", max_bytes=32, client=client
        )
    with (
        _client(lambda request: httpx.Response(200, content=b"<xml/>")) as client,
        pytest.raises(ProcurementDocumentReportError, match="no es PDF"),
    ):
        download_placsp_pdf(
            "https://contrataciondelestado.es/file.xml", max_bytes=1024, client=client
        )


def test_referenced_documents_deduplicates_and_limits_award_documents() -> None:
    docs = [
        {"uri": f"https://contrataciondelestado.es/file-{index}.pdf", "file_name": f"{index}.pdf"}
        for index in range(MAX_DOCUMENTS_PER_REPORT + 2)
    ]
    report = type(
        "Report",
        (),
        {
            "source_snapshot": {
                "procurement_items": [
                    {"kind": "award", "snapshot": {"entries": [{"documents": [*docs, docs[0]]}]}},
                    {"kind": "tender", "snapshot": {"entries": [{"documents": docs}]}},
                ]
            }
        },
    )()
    result = _referenced_documents(report)
    assert len(result) == MAX_DOCUMENTS_PER_REPORT
    assert result[0]["uri"].endswith("file-0.pdf")


def test_official_unscanned_policy_is_flagged_narrow_and_auditable() -> None:
    app = Flask(__name__)
    app.config.update(
        DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=False,
        DOCUMENT_SCANNER_MODE="noop",
    )

    with app.app_context():
        document = _document()
        assert official_unscanned_document_allowed(document) is False
        assert document_available_for_citation(document) is False

        app.config["DOCUMENT_ALLOW_OFFICIAL_UNSCANNED"] = True
        assert official_unscanned_document_allowed(document) is True
        assert document_available_for_citation(document) is False
        assert mark_official_unscanned_acceptance(document, report_id="report-1", job_id="job-1")
        assert document_available_for_citation(document) is True
        acceptance = document.scan_result["official_unscanned_acceptance"]
        assert acceptance["policy"] == "official_source_without_clamav_v1"
        assert acceptance["source_host"] == "contrataciondelestado.es"

        assert (
            official_unscanned_document_allowed(
                _document(source_uri="https://example.test/pliego.pdf")
            )
            is False
        )

        app.config["DOCUMENT_SCANNER_MODE"] = "clamav"
        assert official_unscanned_document_allowed(_document()) is False


@pytest.mark.parametrize("scan_status", ["infected", "error"])
def test_official_unscanned_policy_never_accepts_infected_or_error(scan_status: str) -> None:
    app = Flask(__name__)
    app.config.update(
        DOCUMENT_ALLOW_OFFICIAL_UNSCANNED=True,
        DOCUMENT_SCANNER_MODE="noop",
    )
    with app.app_context():
        document = _document(scan_status=scan_status)
        assert official_unscanned_document_allowed(document) is False
        assert mark_official_unscanned_acceptance(document) is False
        assert document_available_for_citation(document) is False
