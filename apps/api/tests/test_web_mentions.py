from __future__ import annotations

import pytest

from opn_oracle.common.web_mentions import filter_entity_web_mentions


@pytest.mark.unit
def test_iturri_web_results_are_all_rejected_with_auditable_reasons() -> None:
    items = [
        {"title": "ITURRI | Your safety matters", "url": "https://iturri.com/"},
        {
            "title": "ITURRI S.A. - Licitaciones y contratos públicos",
            "url": "https://el-vinculo.com/iturri",
        },
        {
            "title": "Ropa, vestuario, accesorios y complementos",
            "url": "https://shop.iturri.com/",
        },
        {
            "title": "Iturria SA - Guía Industrial Argentina",
            "url": "https://guiaindustrial.com.ar/",
        },
        {
            "title": "Grupo Iturri: empresa familiar andaluza",
            "url": "https://catedraempresafamiliar.test/iturri",
        },
        {"title": "Iturri Enea, la marca vasca", "url": "https://orain.eus/iturri-enea"},
        {"title": "Conservas Iturri - Productos Navarra", "url": "https://conservasiturri.es/"},
        {"title": "ITURRI LTD", "url": "https://netetrade.com/iturri-ltd"},
    ]

    filtered = filter_entity_web_mentions(
        {"items": items},
        entity_name="ITURRI SA",
        entity_kind="company",
    )

    assert filtered["items"] == []
    assert filtered["source_total"] == 8
    assert filtered["attributed_items"] == 0
    assert filtered["discarded_count"] == 8
    assert filtered["discarded_reasons"] == {
        "first_party_domain": 2,
        "duplicate_procurement_directory": 1,
        "insufficient_attribution": 5,
        "invalid_url": 0,
    }


@pytest.mark.unit
def test_clean_external_results_keep_order_without_a_discard_warning() -> None:
    items = [
        {"title": "ACME SOCIEDAD ANONIMA presenta resultados", "url": "https://medio-a.test/acme"},
        {"title": "Entrevista con ACME S.A.", "url": "https://medio-b.test/acme"},
    ]

    filtered = filter_entity_web_mentions(
        {"items": items},
        entity_name="ACME SOCIEDAD ANONIMA",
        entity_kind="company",
    )

    assert [item["title"] for item in filtered["items"]] == [item["title"] for item in items]
    assert filtered["attributed_items"] == 2
    assert filtered["discarded_count"] == 0
    assert filtered["has_publication_dates"] is False


@pytest.mark.unit
def test_person_identity_does_not_treat_a_surname_as_a_company_suffix_or_domain() -> None:
    filtered = filter_entity_web_mentions(
        {
            "items": [
                {
                    "title": "Entrevista a Ana Sa",
                    "url": "https://anasa.com/entrevista",
                }
            ]
        },
        entity_name="Ana Sa",
        entity_kind="person",
    )

    assert [item["title"] for item in filtered["items"]] == ["Entrevista a Ana Sa"]
    assert filtered["discarded_count"] == 0


@pytest.mark.unit
def test_non_http_result_is_never_exposed_even_with_an_exact_entity_name() -> None:
    filtered = filter_entity_web_mentions(
        {"items": [{"title": "ITURRI SA", "url": "javascript:alert(1)"}]},
        entity_name="ITURRI SA",
        entity_kind="company",
    )

    assert filtered["items"] == []
    assert filtered["discarded_reasons"]["invalid_url"] == 1
