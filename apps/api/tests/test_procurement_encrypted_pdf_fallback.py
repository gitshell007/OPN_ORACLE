"""SV2-PLIEGOS-2: PDF cifrado → fallback a extractos del expediente con aviso."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import uuid

import pytest

from opn_oracle.oracle.procurement_report import (
    ENCRYPTED_PDF_EXTRACT_WARNING,
    _is_encrypted_pdf_error,
    _use_encrypted_pdf_extract_fallback,
)


def test_is_encrypted_pdf_error_detects_spanish_and_english() -> None:
    assert _is_encrypted_pdf_error(ValueError("No se admiten PDF cifrados."))
    assert _is_encrypted_pdf_error(RuntimeError("PDF encrypted / password protected"))
    assert not _is_encrypted_pdf_error(ValueError("PDF inválido o no procesable."))
    assert not _is_encrypted_pdf_error(ValueError("timeout"))


def test_encrypted_fallback_returns_empty_when_no_extracts() -> None:
    report = SimpleNamespace(id=uuid.uuid4(), dossier_id=uuid.uuid4())
    with patch(
        "opn_oracle.oracle.procurement_report._dossier_ready_text_extracts",
        return_value=[],
    ):
        used, evidence, warnings = _use_encrypted_pdf_extract_fallback(
            report,
            {"uri": "https://contrataciondelestado.es/x.pdf", "file_name": "PCAP.pdf"},
            reason="No se admiten PDF cifrados.",
        )
    assert used == 0
    assert evidence == 0
    assert warnings == []


def test_encrypted_fallback_uses_extracts_and_emits_visible_warning() -> None:
    report = SimpleNamespace(id=uuid.uuid4(), dossier_id=uuid.uuid4())
    extract_doc = SimpleNamespace(
        id=uuid.uuid4(),
        original_filename="EXTRACTO_PCAP_CONTR_2026_11077.txt",
        media_type="text/plain",
        metadata_json={},
        status="ready",
    )
    with (
        patch(
            "opn_oracle.oracle.procurement_report._dossier_ready_text_extracts",
            return_value=[extract_doc],
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
            return_value=2,
        ),
        patch("opn_oracle.oracle.procurement_report.db") as mock_db,
    ):
        mock_db.session = MagicMock()
        used, evidence, warnings = _use_encrypted_pdf_extract_fallback(
            report,
            {
                "uri": "https://contrataciondelestado.es/pcap.pdf",
                "file_name": "PCAP_CONTR.pdf",
                "doc_type": "legal",
            },
            reason="No se admiten PDF cifrados.",
        )
    assert used == 1
    assert evidence == 2
    assert len(warnings) == 1
    assert ENCRYPTED_PDF_EXTRACT_WARNING in warnings[0]
    assert extract_doc.metadata_json.get("encrypted_pdf_fallback", {}).get("warning") == (
        ENCRYPTED_PDF_EXTRACT_WARNING
    )
    mock_db.session.commit.assert_called()


def test_warning_constant_is_the_product_copy() -> None:
    assert ENCRYPTED_PDF_EXTRACT_WARNING == "análisis sobre extracto; PDF original cifrado"
