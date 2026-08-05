"""G04-PDFCIF-NOTA: document_notes survives refresh and is exposed in the API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from opn_oracle.oracle.procurement_report import (
    ENCRYPTED_PDF_EXTRACT_WARNING,
    process_procurement_document_report,
)
from opn_oracle.reporting.service import (
    _document_notes_from_snapshot,
    _preserve_snapshot_overlays,
    serialize_report,
)

ENCRYPTED_NOTE = (
    f"{ENCRYPTED_PDF_EXTRACT_WARNING} (ref=PCAP_CONTR.pdf; No se admiten PDF cifrados.)"
)


def test_preserve_snapshot_overlays_keeps_document_notes_and_flags() -> None:
    previous = {
        "document_notes": [ENCRYPTED_NOTE],
        "encrypted_pdf_fallback": True,
        "schema": "oracle-report-snapshot-v1",
        "dossier": {"id": "old"},
    }
    rebuilt = {
        "schema": "oracle-report-snapshot-v1",
        "dossier": {"id": "new"},
        "evidence": [],
    }
    merged = _preserve_snapshot_overlays(previous, rebuilt)
    assert merged["dossier"] == {"id": "new"}  # rebuilt wins
    assert merged["document_notes"] == [ENCRYPTED_NOTE]
    assert merged["encrypted_pdf_fallback"] is True


def test_preserve_snapshot_overlays_keeps_arbitrary_freeze_keys() -> None:
    """Sibling pattern: freeze_report_enrichment writes keys that _snapshot never rebuilds."""
    previous = {
        "competitive_analysis": {"schema": "v1", "rows": 3},
        "pending_evidence_schema": "entity-v1",
    }
    rebuilt = {"schema": "oracle-report-snapshot-v1", "evidence": []}
    merged = _preserve_snapshot_overlays(previous, rebuilt)
    assert merged["competitive_analysis"] == {"schema": "v1", "rows": 3}
    assert merged["pending_evidence_schema"] == "entity-v1"


def test_refresh_report_snapshot_preserves_document_notes() -> None:
    """The bug path: notes written on the draft snapshot must survive refresh."""
    from opn_oracle.reporting.service import refresh_report_snapshot

    report = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        status="draft",
        template_key="tender",
        template_version="v1",
        options={},
        version=1,
        source_snapshot={
            "schema": "oracle-report-snapshot-v1",
            "document_notes": [ENCRYPTED_NOTE],
            "encrypted_pdf_fallback": True,
            "evidence": [],
        },
        source_snapshot_hash=b"\x00" * 32,
    )
    dossier = SimpleNamespace(id=report.dossier_id, tenant_id=report.tenant_id)
    rebuilt = {
        "schema": "oracle-report-snapshot-v1",
        "dossier": {"id": str(report.dossier_id)},
        "template": {"key": "tender", "version": "v1"},
        "evidence": [],
        "options": {},
    }
    session = MagicMock()
    session.scalar.return_value = dossier
    session.scalars.return_value = []
    session.execute.return_value = None

    with (
        patch("opn_oracle.reporting.service.db", SimpleNamespace(session=session)),
        patch("opn_oracle.reporting.service.ReportTemplateRegistry") as registry_cls,
        patch(
            "opn_oracle.reporting.service._snapshot",
            return_value=(rebuilt, []),
        ),
        patch("opn_oracle.reporting.service._sha256", return_value=b"\x11" * 32),
    ):
        registry_cls.return_value.get.return_value = SimpleNamespace(key="tender", version="v1")
        refresh_report_snapshot(report)

    assert report.source_snapshot["document_notes"] == [ENCRYPTED_NOTE]
    assert report.source_snapshot["encrypted_pdf_fallback"] is True
    assert report.source_snapshot["dossier"]["id"] == str(report.dossier_id)
    session.commit.assert_called()


def test_serialize_report_exposes_document_notes_and_merges_into_warnings() -> None:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    report = SimpleNamespace(
        id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        title="Informe pliegos",
        status="ready",
        report_type="tender",
        template_key="tender",
        template_version="v1",
        generation_version=1,
        classification="internal",
        confidentiality_label="Uso interno",
        background_job_id=None,
        parent_report_id=None,
        ready_at=now,
        reviewed_at=None,
        published_at=None,
        error_code=None,
        error_message=None,
        ai_artifact_id=None,
        version=2,
        source_snapshot={
            "document_notes": [ENCRYPTED_NOTE],
            "encrypted_pdf_fallback": True,
        },
        created_at=now,
        updated_at=now,
    )
    revision = SimpleNamespace(
        id=uuid.uuid4(),
        revision_no=1,
        status="ready",
        title="Generación 1",
        content={
            "title": "Informe pliegos",
            "executive_summary": "Resumen.",
            "confidence": 70,
            "sections": [],
            "open_questions": [],
            "warnings": ["Otra advertencia metodológica."],
            "facts": [],
            "source_index": [],
        },
        change_summary="",
        created_at=now,
    )

    with (
        patch("opn_oracle.reporting.service.latest_revision", return_value=revision),
        patch(
            "opn_oracle.reporting.service.db",
            SimpleNamespace(
                session=SimpleNamespace(
                    scalars=lambda statement: [],
                    execute=lambda statement: SimpleNamespace(scalar_one_or_none=lambda: None),
                )
            ),
        ),
        patch(
            "opn_oracle.reporting.service._sanitize_report_content_for_ui",
            side_effect=lambda content: dict(content),
        ),
    ):
        serialized = serialize_report(report, detail=True)

    assert serialized["document_notes"] == [ENCRYPTED_NOTE]
    assert serialized["encrypted_pdf_fallback"] is True
    assert ENCRYPTED_NOTE in serialized["revision"]["content"]["warnings"]
    assert "Otra advertencia metodológica." in serialized["revision"]["content"]["warnings"]
    # Client-facing product copy, not an internal error code.
    assert "PDF original cifrado" in serialized["document_notes"][0]
    assert "error_code" not in serialized["document_notes"][0]


def test_process_procurement_writes_notes_after_refresh() -> None:
    """Regression: notes must be applied after refresh (or preserved by it)."""
    report_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    job = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, correlation_id="c1")
    report = SimpleNamespace(
        id=report_id,
        tenant_id=tenant_id,
        background_job_id=job.id,
        template_key="tender",
        source_snapshot={"schema": "oracle-report-snapshot-v1", "evidence": []},
        source_snapshot_hash=b"\x00" * 32,
    )
    call_order: list[str] = []

    def fake_refresh(rep: Any) -> None:
        call_order.append("refresh")
        # Simulate the historical bug: full replace of source_snapshot.
        rep.source_snapshot = {
            "schema": "oracle-report-snapshot-v1",
            "dossier": {},
            "evidence": [],
        }

    def fake_process(rid: uuid.UUID, j: Any) -> dict[str, Any]:
        call_order.append("process")
        assert rid == report_id
        return {"status": "generating"}

    session = MagicMock()
    session.scalar.return_value = report

    with (
        patch("opn_oracle.oracle.procurement_report.db", SimpleNamespace(session=session)),
        patch(
            "opn_oracle.oracle.procurement_report._ingest_documents",
            return_value={
                "documents": 1,
                "evidence": 2,
                "warnings": [ENCRYPTED_NOTE],
                "bytes": 100,
            },
        ),
        patch(
            "opn_oracle.oracle.procurement_report.refresh_report_snapshot",
            side_effect=fake_refresh,
        ),
        patch(
            "opn_oracle.oracle.procurement_report.process_report",
            side_effect=fake_process,
        ),
        patch(
            "opn_oracle.oracle.procurement_report._snapshot_sha256",
            return_value=b"\x22" * 32,
        ),
    ):
        result = process_procurement_document_report(report_id, job)

    assert call_order == ["refresh", "process"]
    assert ENCRYPTED_NOTE in report.source_snapshot.get("document_notes", [])
    assert report.source_snapshot.get("encrypted_pdf_fallback") is True
    assert result["status"] == "generating"
    assert result["procurement_documents"]["warnings"] == [ENCRYPTED_NOTE]
    session.commit.assert_called()


def test_document_notes_helper_dedupes_and_strips() -> None:
    notes = _document_notes_from_snapshot(
        {
            "document_notes": [
                f"  {ENCRYPTED_NOTE}  ",
                ENCRYPTED_NOTE,
                "",
                42,
                "otra nota legible",
            ]
        }
    )
    assert notes == [ENCRYPTED_NOTE, "otra nota legible"]


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        (None, []),
        ({}, []),
        ({"document_notes": "no-list"}, []),
    ],
)
def test_document_notes_helper_handles_empty(snapshot: Any, expected: list[str]) -> None:
    assert _document_notes_from_snapshot(snapshot) == expected
