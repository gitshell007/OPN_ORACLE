"""Unit tests for durable opportunity offer draft (SV2-G09-A)."""

from __future__ import annotations

import pytest

from opn_oracle.ai.offer_draft import (
    OfferDraftError,
    OfferDraftVersionConflict,
    apply_editable_patch,
    assert_version_match,
    build_plain_text_document,
    make_etag,
    materialize_content_from_calculated,
    parse_expected_version,
)


def _sample_calculated() -> dict:
    return {
        "banner": "BORRADOR COMERCIAL — no es documento presentable.",
        "human_gate": "draft_requires_human_edit",
        "statement": "Introducción del borrador de oferta para licitación demo.",
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
        "draft_engine": "sv2_borrador_v1",
    }


@pytest.mark.unit
def test_materialize_preserves_structure_and_honesty() -> None:
    content = materialize_content_from_calculated(_sample_calculated())
    assert content["origin"] == "declared_draft"
    assert content["human_gate"] == "draft_requires_human_edit"
    assert content["statement"].startswith("Introducción")
    assert len(content["sections"]) == 2
    assert content["sections"][0]["key"] == "award_economic"
    assert content["sections"][0]["requirement_origin"] == "official"
    assert content["sections"][0]["response_origin"] == "declared_generated"
    assert "no es hecho" in content["sections"][0]["our_response_draft"]
    assert content["sections"][0]["order"] == 0
    assert content["administrative_checklist"][0]["key"] == "deuc"


@pytest.mark.unit
def test_materialize_rejects_missing_or_empty() -> None:
    with pytest.raises(OfferDraftError) as missing:
        materialize_content_from_calculated({})
    assert missing.value.code == "draft_offer_missing"

    with pytest.raises(OfferDraftError) as no_sections:
        materialize_content_from_calculated(
            {"statement": "solo intro", "sections": [], "banner": "x"}
        )
    assert no_sections.value.code == "draft_offer_invalid"


@pytest.mark.unit
def test_apply_patch_edits_only_editable_fields() -> None:
    content = materialize_content_from_calculated(_sample_calculated())
    patched = apply_editable_patch(
        content,
        {
            "statement": "Introducción revisada por comercial.",
            "sections": [
                {
                    "key": "award_economic",
                    "our_response_draft": (
                        "[borrador declarado — no es hecho] Texto económico editado."
                    ),
                }
            ],
        },
    )
    assert patched["statement"] == "Introducción revisada por comercial."
    assert "editado" in patched["sections"][0]["our_response_draft"]
    # Structure preserved
    assert patched["sections"][0]["title"] == "Oferta económica"
    assert patched["sections"][0]["requirement"].startswith("[oficial]")
    assert patched["sections"][0]["response_origin"] == "declared_generated"
    assert patched["origin"] == "declared_draft"
    assert patched["banner"] == content["banner"]


@pytest.mark.unit
def test_apply_patch_reprefixes_honesty_marker() -> None:
    content = materialize_content_from_calculated(_sample_calculated())
    patched = apply_editable_patch(
        content,
        {
            "sections": [
                {"key": "award_technical", "our_response_draft": "Texto sin marca de honestidad."}
            ]
        },
    )
    assert "borrador declarado" in patched["sections"][1]["our_response_draft"].casefold()


@pytest.mark.unit
def test_apply_patch_unknown_section_and_empty() -> None:
    content = materialize_content_from_calculated(_sample_calculated())
    with pytest.raises(OfferDraftError) as unknown:
        apply_editable_patch(
            content,
            {"sections": [{"key": "missing", "our_response_draft": "x"}]},
        )
    assert unknown.value.code == "unknown_section"

    with pytest.raises(OfferDraftError):
        apply_editable_patch(content, {"statement": "   "})


@pytest.mark.unit
def test_version_conflict_and_etag_parsing() -> None:
    assert make_etag(3) == 'W/"ood-v3"'
    assert parse_expected_version(body_version=2) == 2
    assert parse_expected_version(if_match='W/"ood-v4"') == 4
    assert parse_expected_version(if_match="5") == 5
    assert parse_expected_version() is None

    assert_version_match(row_version=1, expected=1)
    with pytest.raises(OfferDraftVersionConflict) as conflict:
        assert_version_match(row_version=2, expected=1)
    assert conflict.value.status == 409
    assert conflict.value.current_version == 2

    with pytest.raises(OfferDraftError) as required:
        assert_version_match(row_version=1, expected=None)
    assert required.value.status == 428


@pytest.mark.unit
def test_plain_text_copy_has_no_internal_ids() -> None:
    content = materialize_content_from_calculated(_sample_calculated())
    plain = build_plain_text_document(content)
    assert "Oferta económica" in plain
    assert "Requisito (oficial)" in plain
    assert "borrador declarado" in plain.casefold()
    assert "11111111-1111-1111-1111-111111111111" not in plain
    assert "{" not in plain
