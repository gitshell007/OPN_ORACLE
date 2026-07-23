from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[3] / "scripts" / "spikes"
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from investigation_sampling import (  # noqa: E402
    SignalReadOnlyClient,
    SignalReadOnlyError,
    _RejectRedirects,
    compare_signal_units,
    deduplicate_latest_entries,
    detect_borme_challenge_candidates,
    load_ephemeral_signal_key,
    normalize_signal_base_url,
    parse_borme_articles,
    parse_placsp_entries,
    placsp_units,
    redacted_placsp_manifest,
    select_borme_article_frame,
    select_placsp_challenge,
)
from oracle_exp_inv_02 import _load_borme_period  # noqa: E402


def _entry(
    *,
    family: str,
    period: str,
    complexity: str,
    collection: str,
    entry_id: str,
    folder_id: str,
    updated: str,
    groups: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    return {
        "source_family": family,
        "period": period,
        "complexity": complexity,
        "collection": collection,
        "producer": collection,
        "entry_id": entry_id,
        "folder_id": folder_id,
        "updated": updated,
        "source_url": "https://official.example/item",
        "contract_type": "services",
        "status_code": "ADJ",
        "documents": [{"url": "https://official.example/document.pdf"}],
        "flags": {
            "multilot": complexity == "complex",
            "multiwinner": False,
            "ute": False,
            "deserted_or_cancelled": False,
            "received_tender_quantity_ge_5": False,
        },
        "result_groups": groups,
    }


def _result(winner: str, *, count: int = 2) -> dict[str, object]:
    return {
        "winner_name": winner,
        "winner_identifier_present": True,
        "received_tender_quantity": count,
    }


def test_placsp_parser_handles_place_extension_contract_folder_namespace() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
      xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
      xmlns:cbc-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"
      xmlns:cac-place-ext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2">
      <entry>
        <id>urn:synthetic:entry-1</id>
        <updated>2025-01-02T00:00:00Z</updated>
        <link href="https://contrataciondelestado.es/synthetic/entry-1"/>
        <cac-place-ext:ContractFolderStatus>
          <cbc:ContractFolderID>F/SYNTHETIC</cbc:ContractFolderID>
          <cbc-place-ext:ContractFolderStatusCode>ADJ</cbc-place-ext:ContractFolderStatusCode>
          <cac-place-ext:LocatedContractingParty>
            <cac:Party>
              <cac:PartyIdentification>
                <cbc:ID schemeName="SYNTHETIC">B-1</cbc:ID>
              </cac:PartyIdentification>
              <cac:PartyName><cbc:Name>BUYER SYNTHETIC</cbc:Name></cac:PartyName>
            </cac:Party>
          </cac-place-ext:LocatedContractingParty>
          <cac:ProcurementProject><cbc:TypeCode>2</cbc:TypeCode></cac:ProcurementProject>
          <cac:TenderResult>
            <cbc:ReceivedTenderQuantity>3</cbc:ReceivedTenderQuantity>
            <cbc:AwardDate>2025-01-01</cbc:AwardDate>
            <cac:WinningParty>
              <cac:PartyIdentification>
                <cbc:ID schemeName="SYNTHETIC">W-1</cbc:ID>
              </cac:PartyIdentification>
              <cac:PartyName><cbc:Name>WINNER SYNTHETIC</cbc:Name></cac:PartyName>
            </cac:WinningParty>
          </cac:TenderResult>
        </cac-place-ext:ContractFolderStatus>
      </entry>
    </feed>"""

    rows = parse_placsp_entries(
        xml,
        source_family="hosted",
        collection="synthetic-643",
        period="recent",
        member_name="synthetic.atom",
    )

    assert len(rows) == 1
    assert rows[0]["folder_id"] == "F/SYNTHETIC"
    assert rows[0]["status_code"] == "ADJ"
    assert rows[0]["buyer_name"] == "BUYER SYNTHETIC"
    assert rows[0]["contract_type"] == "services"
    result = rows[0]["result_groups"]["__procedure__"][0]
    assert result["winner_name"] == "WINNER SYNTHETIC"
    assert result["received_tender_quantity"] == 3


def test_latest_entry_is_scoped_by_collection_and_not_folder_name() -> None:
    rows = [
        {
            "collection": "hosted",
            "entry_id": "entry-1",
            "folder_id": "SAME",
            "updated": "2025-01-01T00:00:00Z",
        },
        {
            "collection": "hosted",
            "entry_id": "entry-1",
            "folder_id": "SAME",
            "updated": "2025-01-02T00:00:00Z",
        },
        {
            "collection": "aggregated",
            "entry_id": "entry-1",
            "folder_id": "SAME",
            "updated": "2025-01-01T00:00:00Z",
        },
    ]

    result = deduplicate_latest_entries(rows)

    assert len(result) == 2
    assert [row["collection"] for row in result] == ["aggregated", "hosted"]
    assert result[1]["updated"] == "2025-01-02T00:00:00Z"


def test_placsp_units_cap_each_family_folder_and_choose_one_lot() -> None:
    rows = [
        _entry(
            family="hosted",
            period="recent",
            complexity="complex",
            collection="643",
            entry_id="entry-a",
            folder_id="F/1",
            updated="2025-01-02T00:00:00Z",
            groups={"1": [_result("WINNER A")], "2": [_result("WINNER B")]},
        ),
        _entry(
            family="hosted",
            period="recent",
            complexity="simple",
            collection="643",
            entry_id="entry-b",
            folder_id="F/1",
            updated="2025-01-03T00:00:00Z",
            groups={"__procedure__": [_result("WINNER C")]},
        ),
        _entry(
            family="aggregated",
            period="recent",
            complexity="simple",
            collection="1044",
            entry_id="entry-c",
            folder_id="F/1",
            updated="2025-01-03T00:00:00Z",
            groups={"__procedure__": [_result("WINNER D")]},
        ),
    ]

    first = placsp_units(rows, seed="fixed")
    second = placsp_units(list(reversed(rows)), seed="fixed")

    assert first == second
    assert len(first) == 2
    assert {(row["source_family"], row["folder_id"]) for row in first} == {
        ("hosted", "F/1"),
        ("aggregated", "F/1"),
    }
    assert all(row["lot_id"] in {None, "1", "2"} for row in first)


def test_placsp_units_apply_latest_folder_revision_before_result_eligibility() -> None:
    older = _entry(
        family="hosted",
        period="recent",
        complexity="simple",
        collection="643",
        entry_id="entry-old",
        folder_id="F-1",
        updated="2025-01-01T00:00:00Z",
        groups={"__procedure__": [_result("WINNER OLD")]},
    )
    latest = _entry(
        family="hosted",
        period="recent",
        complexity="simple",
        collection="643",
        entry_id="entry-new",
        folder_id="F-1",
        updated="2025-01-02T00:00:00Z",
        groups={},
    )

    assert placsp_units([older, latest], seed="fixed") == []


def test_aggregated_folder_ids_are_scoped_by_producer() -> None:
    first = _entry(
        family="aggregated",
        period="recent",
        complexity="simple",
        collection="1044",
        entry_id="entry-a",
        folder_id="COLLIDING-1",
        updated="2025-01-02T00:00:00Z",
        groups={"__procedure__": [_result("WINNER A")]},
    )
    second = {
        **_entry(
            family="aggregated",
            period="recent",
            complexity="simple",
            collection="1044",
            entry_id="entry-b",
            folder_id="COLLIDING-1",
            updated="2025-01-02T00:00:00Z",
            groups={"__procedure__": [_result("WINNER B")]},
        ),
        "producer": "autonomous-platform.example",
    }

    units = placsp_units([first, second], seed="fixed")

    assert len(units) == 2
    assert {unit["producer"] for unit in units} == {
        "1044",
        "autonomous-platform.example",
    }


def test_placsp_challenge_never_fills_an_infeasible_cell_from_another() -> None:
    units = []
    for family in ("hosted", "aggregated"):
        for period in ("recent", "historical"):
            for complexity in ("simple", "complex"):
                count = (
                    1
                    if (family, period, complexity)
                    == (
                        "aggregated",
                        "historical",
                        "complex",
                    )
                    else 2
                )
                for index in range(count):
                    units.append(
                        {
                            "sample_id": f"{family}-{period}-{complexity}-{index}",
                            "source_family": family,
                            "period": period,
                            "complexity": complexity,
                        }
                    )

    result = select_placsp_challenge(units, seed="fixed", per_cell=2)

    assert result["complete"] is False
    assert len(result["selected"]) == 15
    short = next(row for row in result["inventory"] if row["feasible"] is False)
    assert short["selected"] == 1
    assert short["required"] == 2


def test_redacted_placsp_manifest_excludes_literals_and_source_urls() -> None:
    entry = _entry(
        family="hosted",
        period="recent",
        complexity="simple",
        collection="643",
        entry_id="entry-a",
        folder_id="F/1",
        updated="2025-01-02T00:00:00Z",
        groups={"__procedure__": [_result("SECRET WINNER")]},
    )
    selection = select_placsp_challenge(placsp_units([entry], seed="fixed"), seed="fixed")

    redacted = redacted_placsp_manifest(selection)
    serialized = repr(redacted)

    assert "SECRET WINNER" not in serialized
    assert "official.example" not in serialized
    assert "F/1" not in serialized


def test_borme_article_frame_is_selected_before_candidate_detection() -> None:
    articles = [
        {
            "article_id": f"{period}-{index}",
            "period": period,
            "source_text": text,
        }
        for period in ("recent", "historical")
        for index, text in enumerate(
            (
                "Nombramientos. Adm. Unico: ENTIDAD SINTETICA SL.",
                "Texto sin acto objetivo.",
                "Fe de erratas: dato sintético.",
            )
        )
    ]
    first = select_borme_article_frame(articles, seed="fixed", per_period=2)
    changed = [{**row, "source_text": "sin coincidencias"} for row in articles]
    second = select_borme_article_frame(changed, seed="fixed", per_period=2)

    assert [row["article_id"] for row in first["selected"]] == [
        row["article_id"] for row in second["selected"]
    ]


def test_borme_xml_is_segmented_by_article_with_source_hash() -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <documento fecha_actualizacion="20250103T010203Z">
      <metadatos>
        <identificador>BORME-A-2025-1-01</identificador>
        <titulo>PROVINCIA SINTETICA</titulo>
        <fecha_publicacion>20250102</fecha_publicacion>
      </metadatos>
      <texto>
        <p class="articulo">100 - SOCIEDAD SINTETICA SL.</p>
        <p class="parrafo">Nombramientos. Adm. Unico: PERSONA SINTETICA.
        Datos registrales. S 8, H S 1, I/A 1.</p>
      </texto>
    </documento>"""

    rows = parse_borme_articles(xml, source_url="https://www.boe.es/synthetic.xml")

    assert len(rows) == 1
    assert rows[0]["document_id"] == "BORME-A-2025-1-01"
    assert rows[0]["article_number"] == "100"
    assert rows[0]["source_updated"] == "20250103T010203Z"
    assert len(rows[0]["source_content_hash"]) == 64
    assert rows[0]["annotation"]["assertions"] == []


def test_borme_404_days_are_reused_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_dir = tmp_path / "sources" / "borme" / "2022"
    source_dir.mkdir(parents=True)
    for day in range(1, 32):
        (source_dir / f"summary_202201{day:02d}.404.json").write_text(
            '{"status": 404}',
            encoding="utf-8",
        )
    monkeypatch.setattr(
        "oracle_exp_inv_02._download",
        lambda *args, **kwargs: pytest.fail("cached 404 must not access the network"),
    )

    articles, manifest = _load_borme_period(
        work_dir=tmp_path,
        year=2022,
        period="historical",
        workers=1,
    )

    assert articles == []
    assert manifest["summary_status"] == {"not_published_404": 31}
    assert manifest["summaries"] == 0
    assert manifest["documents"] == 0


def test_borme_detector_never_promotes_counterpart_kind_from_literal() -> None:
    article = {
        "article_id": "article-1",
        "source_text": (
            "Nombramientos. Adm. Unico: ENTIDAD SINTETICA SL. Socio único: PERSONA SINTETICA."
        ),
    }

    candidates = detect_borme_challenge_candidates(article)

    assert {candidate["family"] for candidate in candidates} == {
        "governance",
        "sole_shareholder",
    }
    assert {candidate["counterpart_kind"] for candidate in candidates} == {"unknown"}


def test_signal_key_loader_requires_private_regular_owned_file(tmp_path: Path) -> None:
    key_file = (tmp_path / "consumer.key").resolve()
    key_file.write_text("ephemeral-secret\n", encoding="utf-8")
    key_file.chmod(0o600)

    assert load_ephemeral_signal_key(key_file) == "ephemeral-secret"

    key_file.chmod(0o640)
    with pytest.raises(ValueError, match="permissions"):
        load_ephemeral_signal_key(key_file)


def test_signal_key_loader_rejects_symlink(tmp_path: Path) -> None:
    key_file = (tmp_path / "consumer.key").resolve()
    key_file.write_text("ephemeral-secret\n", encoding="utf-8")
    key_file.chmod(0o600)
    symlink = (tmp_path / "consumer-link.key").resolve()
    os.symlink(key_file, symlink)
    with pytest.raises(ValueError, match="non-symlink"):
        load_ephemeral_signal_key(symlink)


def test_signal_key_loader_rejects_multiline(tmp_path: Path) -> None:
    key_file = (tmp_path / "consumer.key").resolve()
    key_file.write_text("line-one\nline-two\n", encoding="utf-8")
    key_file.chmod(0o600)
    with pytest.raises(ValueError, match="one text line"):
        load_ephemeral_signal_key(key_file)


@pytest.mark.parametrize(
    "url",
    [
        "http://signal.opnconsultoria.com",
        "https://other.example",
        "https://user:secret@signal.opnconsultoria.com",
        "https://signal.opnconsultoria.com/path",
        "https://signal.opnconsultoria.com?key=value",
    ],
)
def test_signal_url_requires_exact_root_https_host(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_signal_base_url(url, allowed_host="signal.opnconsultoria.com")
    assert (
        normalize_signal_base_url(
            "https://signal.opnconsultoria.com",
            allowed_host="signal.opnconsultoria.com",
        )
        == "https://signal.opnconsultoria.com"
    )


def test_signal_allowlist_cannot_be_redefined_by_cli_input() -> None:
    with pytest.raises(ValueError):
        normalize_signal_base_url(
            "https://attacker.example",
            allowed_host="attacker.example",
        )


def test_signal_client_has_only_get_allowlisted_paths() -> None:
    client = SignalReadOnlyClient(
        base_url="https://signal.opnconsultoria.com",
        allowed_host="signal.opnconsultoria.com",
        api_key="ephemeral",
    )

    with pytest.raises(ValueError, match="GET-only"):
        client.get_json("/api/v1/registry/awards")
    with pytest.raises(ValueError, match="GET-only"):
        client.get_json("/api/v1/registry/tenders/F-1")


def test_signal_client_quotes_folder_as_one_path_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SignalReadOnlyClient(
        base_url="https://signal.opnconsultoria.com",
        allowed_host="signal.opnconsultoria.com",
        api_key="ephemeral",
    )
    seen = []

    def fake_get(path: str) -> dict[str, object]:
        seen.append(path)
        return {"folder_id": "F/1", "total": 0, "items": []}

    monkeypatch.setattr(client, "get_json", fake_get)

    assert client.awards_by_folder("F/1")["total"] == 0
    assert seen == ["/api/v1/registry/awards/F%2F1"]


def test_signal_client_rejects_redirect() -> None:
    redirect_handler = _RejectRedirects()
    with pytest.raises(SignalReadOnlyError, match="redirect"):
        redirect_handler.redirect_request(
            object(),
            None,
            302,
            "Found",
            {},
            "https://signal.opnconsultoria.com/other",
        )


def test_signal_client_rejects_partial_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SignalReadOnlyClient(
        base_url="https://signal.opnconsultoria.com",
        allowed_host="signal.opnconsultoria.com",
        api_key="ephemeral",
    )
    monkeypatch.setattr(
        client,
        "get_json",
        lambda path: {"folder_id": "F-1", "total": 2, "items": [{}]},
    )
    with pytest.raises(SignalReadOnlyError, match="partial"):
        client.awards_by_folder("F-1")


def test_signal_preflight_requires_expected_active_ephemeral_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SignalReadOnlyClient(
        base_url="https://signal.opnconsultoria.com",
        allowed_host="signal.opnconsultoria.com",
        api_key="ephemeral",
    )
    monkeypatch.setattr(
        client,
        "get_json",
        lambda path: {"slug": "shared-production", "is_active": True},
    )

    with pytest.raises(SignalReadOnlyError, match="identity"):
        client.preflight(expected_slug="opn-oracle-exp-inv-02-run")


def test_signal_preflight_rejects_non_ephemeral_expected_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SignalReadOnlyClient(
        base_url="https://signal.opnconsultoria.com",
        allowed_host="signal.opnconsultoria.com",
        api_key="ephemeral",
    )
    monkeypatch.setattr(
        client,
        "get_json",
        lambda path: pytest.fail("invalid expected slug must fail before network"),
    )

    with pytest.raises(ValueError, match="ephemeral slug"):
        client.preflight(expected_slug="shared-production")


def test_signal_comparison_separates_sources_and_groups_folder_requests() -> None:
    units = [
        {
            "source_family": "hosted",
            "folder_id": "F/1",
            "lot_id": "1",
            "winner_names": ["WINNER A"],
        },
        {
            "source_family": "hosted",
            "folder_id": "F/1",
            "lot_id": "2",
            "winner_names": ["WINNER B"],
        },
        {
            "source_family": "aggregated",
            "folder_id": "A-1",
            "lot_id": None,
            "winner_names": ["WINNER C"],
        },
    ]
    seen = []

    def fetch(folder_id: str) -> dict[str, object]:
        seen.append(folder_id)
        return {
            "folder_id": folder_id,
            "total": 2,
            "items": [
                {"lot_id": "1", "winner": "WINNER A"},
                {"lot_id": "2", "winner": "WINNER B"},
            ],
        }

    result = compare_signal_units(units, fetch_awards=fetch)

    assert seen == ["F/1"]
    assert result["requests"] == 1
    assert result["hosted_denominator"] == 2
    assert result["aggregated_denominator"] == 1
    assert result["classifications"] == {
        "revision_contract_missing": 2,
        "source_not_indexed_v1": 1,
    }
    assert result["winner_secondary_match"]["numerator"] == 2
    assert result["revision_exact_comparison_available"] is False


def test_empty_signal_result_is_folder_missing_not_zero_official_units() -> None:
    units = [
        {
            "source_family": "hosted",
            "folder_id": "F-1",
            "lot_id": None,
            "winner_names": ["WINNER"],
        }
    ]

    result = compare_signal_units(
        units,
        fetch_awards=lambda folder_id: {"folder_id": folder_id, "total": 0, "items": []},
    )

    assert result["hosted_denominator"] == 1
    assert result["classifications"] == {"folder_missing": 1, "source_not_indexed_v1": 0}
    assert result["winner_secondary_match"]["denominator"] == 1
