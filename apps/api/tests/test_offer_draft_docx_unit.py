"""Unit tests for durable offer-draft DOCX export (SV2-G09-B / G09-B rework)."""

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
    HUMAN_GATE_PUBLIC_LABEL,
    MAX_DOCX_BYTES,
    UNRESOLVED_EVIDENCE_LABEL,
    EvidenceCitation,
    assert_no_internal_ids,
    build_offer_draft_docx,
    collect_evidence_ids,
    content_disposition_attachment,
    humanize_human_gate,
    resolve_evidence_citations,
    sanitize_export_filename,
)
from opn_oracle.documents.parsers import DOCXParser

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _W_NS}


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


def _adversarial_page_break_calculated() -> dict:
    """Fixture that forces a multi-page section (long response + trailing gap)."""

    filler = (
        "Párrafo de relleno comercial para forzar el límite de página. "
        "Describe la metodología, el equipo, el plan de trabajo y las garantías. "
    ) * 40
    return {
        "banner": "BORRADOR COMERCIAL — no es documento presentable.",
        "human_gate": "draft_requires_human_edit",
        "statement": "Introducción adversaria de paginación.",
        "tender_ref": "CONTR-PAGE",
        "lot_hint": "Lote único",
        "sections": [
            {
                "key": "award_economic",
                "title": "Oferta económica",
                "points_hint": "65 puntos",
                "requirement": "[oficial] Criterio económico del PCAP",
                "requirement_origin": "official",
                "official_evidence_ids": ["11111111-1111-1111-1111-111111111111"],
                "our_response_draft": (
                    "[borrador declarado — no es hecho] Semilla económica extensa. " + filler
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": ["22222222-2222-2222-2222-222222222222"],
                "gaps": [
                    "Acreditar volumen F.2",
                    "Adjuntar modelo económico firmado",
                ],
            },
            {
                "key": "award_technical",
                "title": "Oferta técnica",
                "requirement": "[oficial] Juicio de valor",
                "our_response_draft": "[borrador declarado — no es hecho] Semilla técnica.",
                "gaps": ["Completar memoria técnica"],
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
        "gaps_summary": ["Acreditar volumen F.2", "Completar memoria técnica"],
        "origin": "declared_draft",
        "based_on_verdict": "go_conditioned",
        "official_evidence_ids": ["11111111-1111-1111-1111-111111111111"],
        "declared_evidence_ids": ["22222222-2222-2222-2222-222222222222"],
        "draft_engine": "sv2_borrador_v1",
    }


def _paragraph_has_bool(p_el: ET.Element, tag: str) -> bool:
    """True when paragraph properties set w:tag (val missing or not '0'/'false')."""

    ppr = p_el.find("w:pPr", _NS)
    if ppr is None:
        return False
    node = ppr.find(f"w:{tag}", _NS)
    if node is None:
        return False
    val = node.get(f"{{{_W_NS}}}val")
    if val is None:
        return True
    return val not in {"0", "false", "off"}


def _doc_xml_root(payload: bytes) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return ET.fromstring(zf.read("word/document.xml"))


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
    # Public human-gate phrasing; never the machine code.
    assert "draft_requires_human_edit" not in joined
    assert "Requiere revisión y edición humana" in joined or HUMAN_GATE_PUBLIC_LABEL in joined
    # Semantic public labels preserved.
    assert "requisito oficial" in joined.casefold() or "[oficial]" in joined.casefold()
    assert "borrador declarado" in joined.casefold()
    assert UNRESOLVED_EVIDENCE_LABEL in joined or "PCAP oficial" in joined
    # No bare UUIDs / internal identity keys / machine tokens.
    assert "11111111-1111-1111-1111-111111111111" not in joined
    assert "22222222-2222-2222-2222-222222222222" not in joined
    assert "tenant_id" not in joined.casefold()
    assert "user_id" not in joined.casefold()
    assert "source_artifact_id" not in joined.casefold()
    assert "declared_draft" not in joined
    assert "declared_generated" not in joined
    assert "award_economic" not in joined
    assert "go_conditioned" not in joined
    assert "sv2_borrador_v1" not in joined
    assert '"key"' not in joined  # no raw JSON dump
    # Full sanitizer gate over emitted text.
    assert_no_internal_ids(joined)


@pytest.mark.unit
def test_public_language_rejects_machine_gate_token() -> None:
    """Denylist must reject the pre-fix leaked gate code (fails on old wording)."""

    leaked = "Puerta humana: draft_requires_human_edit — el borrador no es documento presentable."
    with pytest.raises(Exception) as exc:
        assert_no_internal_ids(leaked)
    assert getattr(exc.value, "code", "") == "export_sanitization_failed"

    # Correct public wording is accepted.
    public = f"Puerta humana: {HUMAN_GATE_PUBLIC_LABEL}"
    assert_no_internal_ids(public)
    assert humanize_human_gate("draft_requires_human_edit") == HUMAN_GATE_PUBLIC_LABEL
    assert "draft_requires_human_edit" not in humanize_human_gate("draft_requires_human_edit")


@pytest.mark.unit
def test_assert_no_internal_ids_rejects_snake_case_and_codes() -> None:
    for bad in (
        "campo declared_draft en texto",
        "origen declared_generated",
        "veredicto go_conditioned",
        "our_response_draft filtrado",
        "see 11111111-1111-1111-1111-111111111111",
        "tenant_id=abc",
    ):
        with pytest.raises(Exception) as exc:
            assert_no_internal_ids(bad)
        assert getattr(exc.value, "code", "") == "export_sanitization_failed"


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
    assert_no_internal_ids(joined)


@pytest.mark.unit
def test_assert_no_internal_ids_rejects_uuid_leak() -> None:
    with pytest.raises(Exception) as exc:
        assert_no_internal_ids("see 11111111-1111-1111-1111-111111111111")
    assert getattr(exc.value, "code", "") == "export_sanitization_failed"


@pytest.mark.unit
def test_document_xml_styles_present_on_key_paragraphs() -> None:
    content = _sample_content()
    payload = build_offer_draft_docx(content, dossier_title="T", version=1)
    root = _doc_xml_root(payload)
    style_vals = [el.get(f"{{{_W_NS}}}val") for el in root.findall(".//w:pStyle", _NS)]
    # Title may be styleId "Title"; headings "Heading1"/"Heading2".
    assert any(v and ("Title" in v or v == "Title") for v in style_vals)
    assert any(v and "Heading1" in str(v) for v in style_vals)
    assert any(v and "Heading2" in str(v) for v in style_vals)
    # Table present for checklist
    assert root.find(".//w:tbl", _NS) is not None


@pytest.mark.unit
def test_section_blocks_have_keep_with_next_and_widow_control() -> None:
    """Structural OOXML: section title→gap chain keeps together (no orphan bullets)."""

    content = _sample_content()
    payload = build_offer_draft_docx(content, dossier_title="T", version=1)
    root = _doc_xml_root(payload)
    paragraphs = root.findall(".//w:body/w:p", _NS)
    assert paragraphs, "document must contain body paragraphs"

    def _para_text(p_el: ET.Element) -> str:
        return "".join(t.text or "" for t in p_el.findall(".//w:t", _NS))

    # Locate economic section heading and following body paras until next heading.
    econ_idx = None
    for idx, p_el in enumerate(paragraphs):
        if _para_text(p_el).strip() == "Oferta económica":
            econ_idx = idx
            break
    assert econ_idx is not None, "economic section heading missing"

    block: list[ET.Element] = [paragraphs[econ_idx]]
    for p_el in paragraphs[econ_idx + 1 :]:
        style = p_el.find("w:pPr/w:pStyle", _NS)
        style_val = style.get(f"{{{_W_NS}}}val") if style is not None else None
        if style_val and "Heading" in str(style_val):
            break
        text = _para_text(p_el).strip()
        if not text:
            continue
        block.append(p_el)

    assert len(block) >= 3, "section block should include title + body + gap"
    # All but last keep with next; all keep lines / widow control.
    for p_el in block[:-1]:
        assert _paragraph_has_bool(p_el, "keepNext"), _para_text(p_el)
        assert _paragraph_has_bool(p_el, "keepLines"), _para_text(p_el)
        assert _paragraph_has_bool(p_el, "widowControl"), _para_text(p_el)
    last = block[-1]
    assert _paragraph_has_bool(last, "keepLines")
    assert _paragraph_has_bool(last, "widowControl")
    # Last of block must NOT force keep-with-next (allows natural page break after section).
    assert not _paragraph_has_bool(last, "keepNext")

    # Gap bullet text is present in the block (not detached structurally).
    block_text = "\n".join(_para_text(p) for p in block)
    assert "Gap: Acreditar volumen F.2" in block_text

    # Headings generally carry widow control.
    heading_paras = [
        p
        for p in paragraphs
        if (p.find("w:pPr/w:pStyle", _NS) is not None)
        and "Heading" in str(p.find("w:pPr/w:pStyle", _NS).get(f"{{{_W_NS}}}val") or "")
    ]
    assert heading_paras
    for hp in heading_paras:
        assert _paragraph_has_bool(hp, "widowControl")
        assert _paragraph_has_bool(hp, "keepLines")


@pytest.mark.unit
def test_adversarial_page_break_fixture_coheres_and_stays_public() -> None:
    """Long multi-page fixture: sanitizer + keepNext chain on economic section."""

    content = materialize_content_from_calculated(_adversarial_page_break_calculated())
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
        dossier_title="Expediente Paginación Adversaria",
        version=1,
        exported_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
        citations=citations,
    )
    assert payload.startswith(b"PK")
    assert len(payload) < MAX_DOCX_BYTES

    parsed = DOCXParser().parse(io.BytesIO(payload))
    joined = "\n".join(b.text for b in parsed.blocks)
    assert "draft_requires_human_edit" not in joined
    assert "declared_draft" not in joined
    assert "declared_generated" not in joined
    assert "award_economic" not in joined
    assert HUMAN_GATE_PUBLIC_LABEL.split(".")[0] in joined
    assert "Gap: Acreditar volumen F.2" in joined
    assert "Oferta económica" in joined
    assert_no_internal_ids(joined)

    root = _doc_xml_root(payload)
    paragraphs = root.findall(".//w:body/w:p", _NS)

    def _para_text(p_el: ET.Element) -> str:
        return "".join(t.text or "" for t in p_el.findall(".//w:t", _NS))

    econ_idx = next(
        i for i, p in enumerate(paragraphs) if _para_text(p).strip() == "Oferta económica"
    )
    block: list[ET.Element] = [paragraphs[econ_idx]]
    for p_el in paragraphs[econ_idx + 1 :]:
        style = p_el.find("w:pPr/w:pStyle", _NS)
        style_val = style.get(f"{{{_W_NS}}}val") if style is not None else None
        if style_val and "Heading" in str(style_val):
            break
        if _para_text(p_el).strip():
            block.append(p_el)
    # Long section still has keepNext on all but last (gap stays glued to heading when possible).
    assert len(block) >= 4
    for p_el in block[:-1]:
        assert _paragraph_has_bool(p_el, "keepNext")
    assert "Gap:" in _para_text(block[-1]) or any("Gap:" in _para_text(p) for p in block)
