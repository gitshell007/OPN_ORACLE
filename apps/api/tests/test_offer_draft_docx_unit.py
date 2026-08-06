"""Unit tests for durable offer-draft DOCX export (SV2-G09-B)."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from xml.etree import ElementTree as ET

import pytest

from opn_oracle.ai.offer_draft import materialize_content_from_calculated
from opn_oracle.ai.offer_draft_docx import (
    DOCX_MEDIA_TYPE,
    EXPORT_NOTICE,
    MAX_DOCX_BYTES,
    UNRESOLVED_EVIDENCE_LABEL,
    EvidenceCitation,
    assert_no_internal_ids,
    build_offer_draft_docx,
    collect_evidence_ids,
    content_disposition_attachment,
    resolve_evidence_citations,
    sanitize_export_filename,
)
from opn_oracle.documents.parsers import DOCXParser


def _sample_calculated() -> dict:
    return {
        "banner": "BORRADOR COMERCIAL — no es documento presentable.",
        "human_gate": "draft_requires_human_edit",
        "statement": "Introducción del borrador de oferta para licitación demo ñoño €.",
        "tender_ref": "CONTR-1",
        "lot_hint": "Lote 1",
        "sections": [
            {
                "key": "award_economic",
                "title": "Oferta económica",
                "points_hint": "65 puntos",
                "requirement": "[oficial] Criterio económico",
                "requirement_origin": "official",
                "official_evidence_ids": ["11111111-1111-1111-1111-111111111111"],
                "our_response_draft": "[borrador declarado — no es hecho] Semilla económica.",
                "response_origin": "declared_generated",
                "declared_evidence_ids": ["22222222-2222-2222-2222-222222222222"],
                "gaps": ["Acreditar volumen F.2"],
            },
            {
                "key": "award_technical",
                "title": "Oferta técnica",
                "requirement": "[oficial] Juicio de valor",
                "our_response_draft": "[borrador declarado — no es hecho] Semilla técnica.",
                "gaps": [],
            },
        ],
        "administrative_checklist": [
            {
                "key": "deuc",
                "label": "DEUC",
                "description": "Cumplimentar DEUC",
                "status": "pending",
                "source": "pliego",
            }
        ],
        "gaps_summary": ["Acreditar volumen F.2"],
        "origin": "declared_draft",
        "based_on_verdict": "go_conditioned",
        "official_evidence_ids": ["11111111-1111-1111-1111-111111111111"],
        "declared_evidence_ids": ["22222222-2222-2222-2222-222222222222"],
        "draft_engine": "sv2_borrador_v1",
    }


def _sample_content() -> dict:
    return materialize_content_from_calculated(_sample_calculated())


@pytest.mark.unit
def test_sanitize_export_filename_strips_paths_and_crlf() -> None:
    dirty = "../evil\r\npath/Expediente ñoño: demo"
    name = sanitize_export_filename(dirty, version=3)
    assert name.endswith(".docx")
    assert "\r" not in name and "\n" not in name
    assert ".." not in name
    assert "/" not in name and "\\" not in name
    assert "v3" in name
    assert "Borrador-oferta" in name


@pytest.mark.unit
def test_content_disposition_no_injection() -> None:
    header = content_disposition_attachment("Borrador-oferta-demo-v1.docx")
    assert "attachment;" in header
    assert "filename=" in header
    assert "\r" not in header and "\n" not in header
    assert "filename*=UTF-8''" in header


@pytest.mark.unit
def test_docx_structure_order_styles_and_unicode() -> None:
    content = _sample_content()
    citations = resolve_evidence_citations(
        collect_evidence_ids(content),
        lookup={
            __import__("uuid").UUID("11111111-1111-1111-1111-111111111111"): EvidenceCitation(
                title="PCAP oficial",
                source="Plataforma de Contratación",
                url="https://contrataciondelestado.es/pcap",
            ),
        },
    )
    payload = build_offer_draft_docx(
        content,
        dossier_title="Expediente Demo Ñoño",
        version=2,
        exported_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
        citations=citations,
    )
    assert payload.startswith(b"PK")
    assert len(payload) < MAX_DOCX_BYTES
    assert DOCX_MEDIA_TYPE.startswith("application/vnd.openxmlformats")

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = set(zf.namelist())
        for required in (
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
            "word/_rels/document.xml.rels",
            "word/styles.xml",
        ):
            assert required in names
        rels = zf.read("_rels/.rels").decode("utf-8")
        assert "word/document.xml" in rels
        doc_rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        assert "styles.xml" in doc_rels
        styles = zf.read("word/styles.xml").decode("utf-8")
        # python-docx embeds standard Word styles (Title / Heading*).
        assert "Title" in styles or "title" in styles.casefold()
        assert "Heading1" in styles or "heading 1" in styles.casefold()
        document_xml = zf.read("word/document.xml").decode("utf-8")
        assert "document" in document_xml

    # Repo DOCX parser must extract key paragraphs (not just PK magic).
    parsed = DOCXParser().parse(io.BytesIO(payload))
    texts = [block.text for block in parsed.blocks]
    joined = "\n".join(texts)
    assert texts[0] == "Borrador de oferta"
    assert "Expediente Demo Ñoño" in joined
    assert "CONTR-1" in joined or "Referencia: CONTR-1" in joined
    assert "Lote 1" in joined
    assert "v2" in joined
    assert EXPORT_NOTICE.split(".")[0] in joined or "borrador declarado" in joined.casefold()
    assert "Introducción del borrador" in joined
    assert "ñoño" in joined and "€" in joined
    assert "Oferta económica" in joined
    assert "Criterio económico" in joined or "Criterio / requisito oficial" in joined
    assert "65 puntos" in joined or "Puntos: 65" in joined
    assert "Semilla económica" in joined
    assert "Acreditar volumen F.2" in joined
    assert "DEUC" in joined
    assert "pendiente" in joined.casefold() or "Checklist" in joined
    assert "Anexo de trazabilidad" in joined
    assert "PCAP oficial" in joined
    assert "https://contrataciondelestado.es/pcap" in joined
    # No bare UUIDs / internal identity keys.
    assert "11111111-1111-1111-1111-111111111111" not in joined
    assert "22222222-2222-2222-2222-222222222222" not in joined
    assert "tenant_id" not in joined.casefold()
    assert "user_id" not in joined.casefold()
    assert "source_artifact_id" not in joined.casefold()
    assert '"key"' not in joined  # no raw JSON dump


@pytest.mark.unit
def test_unresolved_evidence_honest_fallback() -> None:
    content = _sample_content()
    ids = collect_evidence_ids(content)
    assert len(ids) >= 1
    citations = resolve_evidence_citations(ids, lookup={})
    assert all(c.title == UNRESOLVED_EVIDENCE_LABEL for c in citations)
    payload = build_offer_draft_docx(
        content,
        dossier_title="Exp",
        version=1,
        citations=citations,
    )
    parsed = DOCXParser().parse(io.BytesIO(payload))
    joined = "\n".join(b.text for b in parsed.blocks)
    assert UNRESOLVED_EVIDENCE_LABEL in joined
    assert "11111111-1111-1111-1111-111111111111" not in joined


@pytest.mark.unit
def test_assert_no_internal_ids_rejects_uuid_leak() -> None:
    with pytest.raises(Exception) as exc:
        assert_no_internal_ids("see 11111111-1111-1111-1111-111111111111")
    assert getattr(exc.value, "code", "") == "export_sanitization_failed"


@pytest.mark.unit
def test_document_xml_styles_present_on_key_paragraphs() -> None:
    content = _sample_content()
    payload = build_offer_draft_docx(content, dossier_title="T", version=1)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    style_vals = [
        el.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
        for el in root.findall(".//w:pStyle", ns)
    ]
    # Title may be styleId "Title"; headings "Heading1"/"Heading2".
    assert any(v and ("Title" in v or v == "Title") for v in style_vals)
    assert any(v and "Heading1" in str(v) for v in style_vals)
    assert any(v and "Heading2" in str(v) for v in style_vals)
    # Table present for checklist
    assert root.find(".//w:tbl", ns) is not None
