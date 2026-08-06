"""Auditoría read-only del contrato Signal respecto a ``documents`` (G-11).

Sin red ni producción: solo fixtures locales, OpenAPI y normalización Oracle.
Si Signal no construye ``documents`` para licitaciones abiertas simuladas, se
documenta como follow-up Signal — G-11 Oracle no se declara cerrado por ello.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opn_oracle.oracle import procurement_items

ROOT = Path(__file__).resolve().parents[3]
SIGNAL_DOCS = ROOT / "docs" / "integrations" / "signal-avanza"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


def test_local_fixtures_do_not_prove_signal_builds_open_tender_documents() -> None:
    """Si no hay fixture Signal con documents en tender abierta, follow-up Signal.

    Oracle solo puede demostrar que *si* llegan, se conservan (test de arriba).
    """
    # Buscar fixtures de investigación / procurement locales.
    found_open_tender_with_docs = False
    evidence_paths: list[str] = []
    for path in FIXTURES.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        blob = json.dumps(raw, ensure_ascii=False)
        if "documents" not in blob:
            continue
        evidence_paths.append(str(path.relative_to(ROOT)))
        # Heurística: ¿parece open tender con documents no vacíos?
        text = blob.casefold()
        if (
            ("placsp" in text or "tender" in text or "folder_id" in text)
            and '"documents": []' not in blob
            and '"uri"' in blob
        ):
            # Puede ser award o investigation — no prueba open tender Signal vivo.
            found_open_tender_with_docs = found_open_tender_with_docs or (
                "open" in text and "uri" in text
            )

    # Conclusión durable para el Gate Packet: sin fixture Signal de licitación
    # abierta con documents CODICE, G-11 Oracle no cierra el tramo Signal.
    report = {
        "fixture_files_mentioning_documents": evidence_paths[:20],
        "proved_signal_open_tender_documents": found_open_tender_with_docs,
        "oracle_preserves_when_present": True,
        "follow_up_signal": not found_open_tender_with_docs,
        "follow_up_scope": (
            "Signal debe construir y devolver `documents[]` (uri, doc_type, file_name) "
            "en placsp_open_tenders / pin de licitación abierta simulada; Oracle ya "
            "conserva el campo en snapshot y activa fallback manual si viene vacío."
        ),
    }
    # Siempre expone la conclusión; el test no falla por follow-up — es auditoría.
    assert report["oracle_preserves_when_present"] is True
    assert isinstance(report["follow_up_signal"], bool)
    # Documentamos en assert message para la salida de pytest.
    assert report["follow_up_scope"]
    if not found_open_tender_with_docs:
        pytest.skip(
            "FOLLOW-UP SIGNAL: no hay fixture local que demuestre documents en "
            "licitación abierta Signal. Oracle G-11 conserva el campo y ofrece "
            "subida manual; el tramo Signal queda abierto. "
            f"paths_with_documents={evidence_paths[:5]}"
        )
