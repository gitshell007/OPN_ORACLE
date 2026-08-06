"""Auditoría read-only del contrato Signal respecto a ``documents`` (G-11).

Sin red ni producción: valida el fixture contractual del checkout Signal y la
normalización Oracle. La ausencia del contrato es un fallo explícito, nunca skip.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from opn_oracle.oracle import procurement_items
from tests.signal_checkout import (
    resolve_explicit_signal_checkout,
    resolve_signal_checkout,
)

ROOT = Path(__file__).resolve().parents[3]
SIGNAL_DOCS = ROOT / "docs" / "integrations" / "signal-avanza"
SIGNAL_G11_CONTRACT = "tests/contract/oracle/fixtures/open_tender_documents.example.json"
SIGNAL_G11_ATOM = "tests/fixtures/placsp_open_tender_documents.atom"


def test_oracle_preserves_documents_when_signal_sends_them() -> None:
    """Si Signal manda documents, el snapshot de pin los conserva (contrato Oracle)."""
    item = {
        "folder_id": "CONTR 2026 11077",
        "title": "red de agentes",
        "buyer": "Agencia",
        "status": "PUB",
        "cpv": ["72230000"],
        "amount": "1000",
        "deadline": "2026-08-06T23:59:00Z",
        "source_url": "https://contrataciondelestado.es/tender",
        "documents": [
            {
                "uri": "https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?id=1",
                "doc_type": "legal",
                "file_name": "PCAP.pdf",
            }
        ],
    }
    snapshot = procurement_items._snapshot("tender", item, "CONTR 2026 11077")
    assert snapshot["documents"]
    assert snapshot["documents"][0]["file_name"] == "PCAP.pdf"


def test_oracle_empty_documents_list_is_preserved_not_invented() -> None:
    item = {
        "folder_id": "CONTR EMPTY",
        "title": "sin docs",
        "status": "PUB",
        "documents": [],
    }
    snapshot = procurement_items._snapshot("tender", item, "CONTR EMPTY")
    assert snapshot.get("documents") == []


def test_oracle_missing_documents_key_is_not_fabricated() -> None:
    item = {
        "folder_id": "CONTR NOKEY",
        "title": "sin clave documents",
        "status": "PUB",
    }
    snapshot = procurement_items._snapshot("tender", item, "CONTR NOKEY")
    assert "documents" not in snapshot or snapshot.get("documents") in (None, [])


def test_signal_contract_docs_mention_documents_for_awards_not_guaranteed_open_tenders() -> None:
    """Evidencia textual del contrato Oracle↔Signal (sin red)."""
    contract = (SIGNAL_DOCS / "CONTRACT_V1.md").read_text(encoding="utf-8")
    # El contrato habla de pliegos/adjudicaciones; no promete documents en open tenders.
    assert "documents" in contract.casefold() or "pliego" in contract.casefold()
    coverage = (SIGNAL_DOCS / "PLACSP_HISTORICAL_COVERAGE_2026-07-23.md").read_text(
        encoding="utf-8"
    )
    # Cobertura histórica award-céntrica hasta demostrar archivo de pliegos.
    assert "pliego" in coverage.casefold()


def _validate_signal_documents_contract(
    signal_root: Path,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    payload = json.loads((signal_root / SIGNAL_G11_CONTRACT).read_text(encoding="utf-8"))
    assert payload["contract"] == "signal.open_tender.documents"
    item = payload["item_example"]
    assert item["canonical_status"] == "open"
    assert item["status"] == "PUB"
    documents = item["documents"]
    assert documents
    required = set(payload["document_required_fields"])
    assert required == {"uri", "doc_type", "file_name"}
    assert all(required <= set(document) for document in documents)
    assert all(
        document["uri"].startswith("https://contrataciondelestado.es/") for document in documents
    )
    assert set(payload["endpoints"]) == {
        "GET /api/v1/registry/tenders/{folder_id}",
        "GET /api/v1/registry/tenders",
        "GET /api/v1/oracle/tender-searches/{search_id}/run",
    }

    # The required Signal contract fields survive Oracle's durable pin snapshot.
    # ``hash`` is explicitly optional metadata and is not part of Oracle's G-11 DTO.
    snapshot = procurement_items._snapshot("tender", item, item["folder_id"])
    expected_documents = [
        {key: document[key] for key in ("uri", "doc_type", "file_name")} for document in documents
    ]
    assert snapshot["documents"] == expected_documents

    # Cross-repo fixture behavior, without inspecting another test's source: the
    # contractual JSON must describe the three document references present in
    # the real CODICE Atom sample in the same order and with the same types.
    atom_root = ElementTree.parse(signal_root / SIGNAL_G11_ATOM).getroot()
    namespace = {
        "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
        "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    }
    expected_types = {
        "LegalDocumentReference": "legal",
        "TechnicalDocumentReference": "technical",
        "AdditionalDocumentReference": "additional",
    }
    atom_documents: list[tuple[str, str]] = []
    for reference_name, document_type in expected_types.items():
        for reference in atom_root.findall(f".//cac:{reference_name}", namespace):
            uri = reference.findtext(".//cbc:URI", default="", namespaces=namespace).strip()
            assert uri
            atom_documents.append((uri, document_type))
    assert [(document["uri"], document["doc_type"]) for document in documents] == atom_documents
    return payload, atom_documents


@pytest.mark.integration
def test_signal_contract_snapshot_proves_open_tender_documents_contract() -> None:
    """Versioned fixture always runs; an explicit Signal checkout is an extra audit."""

    required = (SIGNAL_G11_CONTRACT, SIGNAL_G11_ATOM)
    fixture_root = resolve_signal_checkout(required, environ={})
    fixture_payload, fixture_atom_documents = _validate_signal_documents_contract(fixture_root)

    live_root = resolve_explicit_signal_checkout(required)
    if live_root is not None:
        live_payload, live_atom_documents = _validate_signal_documents_contract(live_root)
        assert live_payload == fixture_payload
        assert live_atom_documents == fixture_atom_documents
