from __future__ import annotations

import httpx
import pytest

from opn_oracle.oracle.procurement_report import (
    MAX_DOCUMENTS_PER_REPORT,
    ProcurementDocumentReportError,
    _referenced_documents,
    download_placsp_pdf,
)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


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
