from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError

SPIKE_DIR = Path(__file__).resolve().parents[3] / "scripts" / "spikes"
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from investigation_documents import (  # noqa: E402
    CANDIDATE_CHUNK_SCHEMA_VERSION,
    CANDIDATE_SCHEMA_VERSION,
    AcquisitionResult,
    ParticipationCandidateOutput,
    ParticipationChunkOutput,
    acquire_reference,
    build_blinded_annotation_packs,
    candidate_fingerprint,
    candidate_page_hashes,
    chunk_candidate_fingerprint,
    curl_command,
    curl_environment,
    load_product_parser_module,
    load_reusable_quarantined_references,
    merge_chunk_candidates,
    parse_authorized_acquisition,
    select_candidate_pages,
    select_double_blind_units,
    select_participation_windows,
    sniff_document,
    source_reference_id,
    split_candidate_pages_into_chunks,
    validate_candidate_against_pages,
    validate_chunk_candidate_against_chunk,
    validate_reference_url,
)


def _unit(
    family: str,
    period: str,
    complexity: str,
    index: int,
    *,
    documents: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "sample_id": f"{family}-{period}-{complexity}-{index:02d}",
        "source_family": family,
        "period": period,
        "complexity": complexity,
        "documents": documents or [],
        "winner_names": ["SHOULD NOT ENTER BLIND PACK"],
    }


def _frame() -> list[dict[str, object]]:
    return [
        _unit(family, period, complexity, index)
        for family in ("hosted", "aggregated")
        for period in ("recent", "historical")
        for complexity in ("simple", "complex")
        for index in range(12)
    ]


def _candidate(
    *,
    document_id: str = "doc-1",
    document_sha256: str = "a" * 64,
    page: int = 1,
    quote: str = "Se admite la oferta de ALFA SINTÉTICA, S.L.",
    literal_name: str = "ALFA SINTÉTICA, S.L.",
    role: str = "admitted_bidder",
) -> ParticipationCandidateOutput:
    return ParticipationCandidateOutput.model_validate(
        {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "document_id": document_id,
            "document_sha256": document_sha256,
            "pages_seen": [page],
            "assessment": {
                "participant_content": "present",
                "list_completeness": "partial",
            },
            "assertions": [
                {
                    "candidate_ordinal": 1,
                    "literal_name": literal_name,
                    "identifier_literal": None,
                    "lot_literal": None,
                    "role": role,
                    "ute_status": "unknown",
                    "ute_members": [],
                    "citations": [
                        {
                            "page": page,
                            "quote": quote,
                            "supports": ["name", "role"],
                        }
                    ],
                    "ambiguity_reasons": [],
                    "needs_human_review": True,
                }
            ],
            "limitations": [],
        }
    )


def test_double_blind_selection_is_three_per_cell_and_ignores_documents() -> None:
    original = _frame()
    changed = [dict(row) | {"documents": [{"url": "https://example.invalid"}]} for row in original]
    selected = select_double_blind_units(original)
    changed_selected = select_double_blind_units(changed)
    assert len(selected) == 24
    assert [row["sample_id"] for row in selected] == [row["sample_id"] for row in changed_selected]
    counts: dict[tuple[object, object, object], int] = {}
    for row in selected:
        key = (row["source_family"], row["period"], row["complexity"])
        counts[key] = counts.get(key, 0) + 1
    assert set(counts.values()) == {3}


def test_double_blind_selection_fails_instead_of_refilling_cell() -> None:
    frame = _frame()
    frame = [
        row
        for row in frame
        if not (
            row["source_family"] == "hosted"
            and row["period"] == "recent"
            and row["complexity"] == "simple"
            and int(str(row["sample_id"]).rsplit("-", 1)[-1]) > 1
        )
    ]
    with pytest.raises(ValueError, match="infeasible"):
        select_double_blind_units(frame)


def test_blinded_packs_hide_sample_mapping_and_winner() -> None:
    frame = _frame()
    double = select_double_blind_units(frame)
    packs = build_blinded_annotation_packs(frame, double)
    assert len(packs["annotator_a"]) == 96
    assert len(packs["annotator_b"]) == 24
    assert len(packs["coordinator"]) == 96
    serialized = json.dumps(packs["annotator_a"] + packs["annotator_b"])
    assert "sample_id" not in serialized
    assert "SHOULD NOT ENTER" not in serialized


@pytest.mark.parametrize(
    "url",
    [
        (
            "https://contrataciondelestado.es/FileSystem/servlet/"
            "GetDocumentByIdServlet?DocumentIdParam=abc&cifrado=def"
        ),
        (
            "https://contrataciondelestado.es/wps/wcm/connect/PLACE_es/Site/area/"
            "docAccCmpnt?srv=cmpnt&cmpntname=GetDocumentsById&source=library"
            "&DocumentIdParam=2025-abc"
        ),
        "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC123",
        (
            "https://www.contratacion.euskadi.eus/ac70cPublicidadWar/"
            "downloadDokusiREST/descargaFicheroPorOid?R01HNoPortal=true&oiddokusi=abc"
        ),
        ("https://contratos-publicos.comunidad.madrid/sites/default/files/PCON/2024-08/pcap.pdf"),
    ],
)
def test_reference_allowlist_accepts_observed_endpoint_shapes(url: str) -> None:
    assert validate_reference_url(url).host


@pytest.mark.parametrize(
    "url",
    [
        "http://www.bilbao.eus/cs/Satellite?blob=1",
        "http://contractaciopublica.cat/portal-api/descarrega-document/123/ABC123",
        "https://user:pass@contrataciondelestado.es/FileSystem/x",
        "https://contrataciondelestado.es:444/FileSystem/x",
        "https://contrataciondelestado.es/FileSystem/../private",
        "https://contrataciondelestado.es/FileSystem/%2fprivate",
        "https://contrataciondelestado.es/FileSystem/x#fragment",
        'https://contractaciopublica.cat/portal-api/descarrega-document/123/"ABC"',
        "https://evil.example/portal-api/descarrega-document/123/ABC",
    ],
)
def test_reference_allowlist_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_reference_url(url)


def test_source_reference_identity_does_not_trust_document_id() -> None:
    left = source_reference_id("sample-1", "https://example.test/a")
    right = source_reference_id("sample-1", "https://example.test/b")
    other_sample = source_reference_id("sample-2", "https://example.test/a")
    assert len({left, right, other_sample}) == 3


def test_curl_command_pins_peer_and_never_follows_redirects(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    command = curl_command(
        url,
        address="203.0.113.10",
        output_path=tmp_path / "body",
        header_path=tmp_path / "headers",
        timeout_seconds=45,
        max_bytes=1_000,
    )
    assert "--resolve" in command
    assert "contractaciopublica.cat:443:203.0.113.10" in command
    assert command[command.index("--max-redirs") + 1] == "0"
    assert "-L" not in command and "--location" not in command
    assert command[command.index("--noproxy") + 1] == "*"
    assert "--config" in command
    assert url not in command


def test_curl_environment_drops_proxy_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9999")
    monkeypatch.setenv("INV03_SAFE_VALUE", "yes")
    environment = curl_environment()
    assert "HTTPS_PROXY" not in environment
    assert "http_proxy" not in environment
    assert environment["INV03_SAFE_VALUE"] == "yes"


def test_sniff_document_uses_magic_not_extension_or_mime() -> None:
    assert sniff_document(b"%PDF-1.7\nbody", "text/html") == "pdf"
    assert (
        sniff_document(
            b"<html>Web Application Firewall has denied your transaction</html>",
            "application/pdf",
        )
        == "blocked_waf"
    )
    assert sniff_document(b"<html>ordinary portal</html>", "text/html") == "unsupported_html"


def test_sniff_document_recognizes_real_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    assert (
        sniff_document(
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        == "docx"
    )


def _fake_curl(
    payload: bytes,
    headers: bytes,
    *,
    returncode: int = 0,
) -> object:
    def run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        output = Path(command[command.index("--output") + 1])
        header = Path(command[command.index("--dump-header") + 1])
        output.write_bytes(payload)
        header.write_bytes(headers)
        return subprocess.CompletedProcess(command, returncode, "", "")

    return run


def test_acquisition_quarantines_pdf_with_private_sidecar(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    result = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path,
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"%PDF-1.7\nfixture",
            b"HTTP/2 200\r\nContent-Type: application/pdf\r\n\r\n",
        ),
    )
    assert result.status == "downloaded_quarantined"
    assert result.scan_status == "not_scanned"
    assert result.object_path is not None
    assert stat.S_IMODE(Path(result.object_path).stat().st_mode) == 0o600
    sidecar = tmp_path / f"{result.source_ref_id}.json"
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_acquisition_reuses_only_hash_verified_sidecar(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    first = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path,
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"%PDF-1.7\nfixture",
            b"HTTP/2 200\r\nContent-Type: application/pdf\r\n\r\n",
        ),
    )
    called = False

    def should_not_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        raise AssertionError("verified object should be reused")

    second = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path,
        resolve=lambda _: ("203.0.113.10",),
        run_command=should_not_run,
    )
    assert first.sha256 == second.sha256
    assert second.status == "reused_quarantined"
    assert called is False


def test_offline_quarantine_reuse_rechecks_sidecar_and_object_hash(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    acquired = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path,
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"%PDF-1.7\nfixture",
            b"HTTP/2 200\r\nContent-Type: application/pdf\r\n\r\n",
        ),
    )
    reused = load_reusable_quarantined_references(tmp_path)
    assert [(item.source_ref_id, item.status) for item in reused] == [
        (acquired.source_ref_id, "reused_quarantined")
    ]
    assert reused[0].sha256 == acquired.sha256
    Path(str(acquired.object_path)).write_bytes(b"%PDF-1.7\ntampered")
    with pytest.raises(ValueError, match="integrity mismatch"):
        load_reusable_quarantined_references(tmp_path)


def test_acquisition_does_not_store_waf_html_as_document(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    result = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path,
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"<html>Web Application Firewall has denied your transaction</html>",
            b"HTTP/2 200\r\nContent-Type: text/html\r\n\r\n",
        ),
    )
    assert result.status == "blocked_waf"
    assert not list(tmp_path.glob("*.pdf"))
    assert not list(tmp_path.glob("*.docx"))


def test_acquisition_rejects_redirect_and_content_encoding(tmp_path: Path) -> None:
    url = "https://contractaciopublica.cat/portal-api/descarrega-document/123/ABC"
    redirected = acquire_reference(
        sample_id="sample-1",
        url=url,
        quarantine_dir=tmp_path / "redirect",
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"",
            b"HTTP/2 302\r\nLocation: https://example.test/file\r\n\r\n",
        ),
    )
    encoded = acquire_reference(
        sample_id="sample-2",
        url=url,
        quarantine_dir=tmp_path / "encoded",
        resolve=lambda _: ("203.0.113.10",),
        run_command=_fake_curl(
            b"%PDF-1.7",
            (b"HTTP/2 200\r\nContent-Type: application/pdf\r\nContent-Encoding: gzip\r\n\r\n"),
        ),
    )
    assert redirected.status == "redirect_rejected"
    assert encoded.status == "content_encoding_rejected"


def test_candidate_schema_forces_human_review_and_cited_material_fields() -> None:
    candidate = _candidate()
    assert candidate.assertions[0].needs_human_review is True
    invalid = candidate.model_dump()
    invalid["assertions"][0]["needs_human_review"] = False
    with pytest.raises(ValidationError):
        ParticipationCandidateOutput.model_validate(invalid)
    invalid = candidate.model_dump()
    invalid["assertions"][0]["identifier_literal"] = "B00000001"
    with pytest.raises(ValidationError, match="identifier citation"):
        ParticipationCandidateOutput.model_validate(invalid)


def test_candidate_validator_binds_quote_and_name_to_exact_page() -> None:
    page = "Se admite la oferta de ALFA SINTÉTICA, S.L."
    valid = validate_candidate_against_pages(
        _candidate(quote=page),
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        pages={1: page},
    )
    assert valid["valid"] is True
    wrong_page = validate_candidate_against_pages(
        _candidate(page=2, quote=page),
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        pages={1: page},
    )
    assert "pages_seen_outside_context" in wrong_page["errors"]
    assert "citation_page_missing" in wrong_page["errors"]
    invented_quote = validate_candidate_against_pages(
        _candidate(quote="ALFA SINTÉTICA, S.L. ganó el contrato"),
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        pages={1: page},
    )
    assert "citation_quote_missing" in invented_quote["errors"]


def test_candidate_fingerprint_cannot_depend_on_gold() -> None:
    page_hashes = candidate_page_hashes({1: "fixture"})
    first = candidate_fingerprint(
        document_sha256="a" * 64,
        page_hashes=page_hashes,
        model_manifest={"model": "fixture", "digest": "one"},
    )
    expected_labels = {"gold": "changed"}
    del expected_labels
    second = candidate_fingerprint(
        document_sha256="a" * 64,
        page_hashes=page_hashes,
        model_manifest={"model": "fixture", "digest": "one"},
    )
    assert first == second


def test_candidate_fingerprint_includes_inference_parameters() -> None:
    page_hashes = candidate_page_hashes({1: "fixture"})
    first = candidate_fingerprint(
        document_sha256="a" * 64,
        page_hashes=page_hashes,
        model_manifest={"model": "fixture", "digest": "one"},
        inference_params={"num_ctx": 4096, "max_output_tokens": 800},
    )
    second = candidate_fingerprint(
        document_sha256="a" * 64,
        page_hashes=page_hashes,
        model_manifest={"model": "fixture", "digest": "one"},
        inference_params={"num_ctx": 4096, "max_output_tokens": 1600},
    )
    assert first != second


def test_product_parser_load_does_not_cross_runtime_boundary() -> None:
    module, provenance = load_product_parser_module()
    assert module.PARSER_VERSION == "documents-parser-v1"
    assert provenance["runtime_modules_loaded"] == []
    assert len(provenance["source_sha256"]) == 64


def _write_docx(path: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                "Se admite la oferta de ALFA SINTÉTICA, S.L."
                "</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    payload = buffer.getvalue()
    path.write_bytes(payload)
    return payload


def test_internal_authorization_allows_unscanned_offline_parse(tmp_path: Path) -> None:
    path = tmp_path / "fixture.docx"
    payload = _write_docx(path)
    acquisition = AcquisitionResult(
        source_ref_id="a" * 64,
        host="official.example",
        status="downloaded_quarantined",
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_kind="docx",
        scan_status="not_scanned",
        object_path=str(path),
    )
    blocked = parse_authorized_acquisition(
        acquisition,
        allow_unscanned_internal=False,
    )
    allowed = parse_authorized_acquisition(
        acquisition,
        allow_unscanned_internal=True,
    )
    assert blocked.status == "blocked_unscanned"
    assert allowed.status == "parsed_native"
    assert allowed.authorization == "internal_unscanned_authorized"
    assert allowed.blocks[0]["locator"] == {"paragraph": 1}


def test_internal_parse_rechecks_quarantine_integrity(tmp_path: Path) -> None:
    path = tmp_path / "fixture.docx"
    payload = _write_docx(path)
    acquisition = AcquisitionResult(
        source_ref_id="b" * 64,
        host="official.example",
        status="reused_quarantined",
        bytes=len(payload),
        sha256="0" * 64,
        media_kind="docx",
        scan_status="not_scanned",
        object_path=str(path),
    )
    result = parse_authorized_acquisition(
        acquisition,
        allow_unscanned_internal=True,
    )
    assert result.status == "quarantine_integrity_mismatch"
    assert result.blocks == ()


def test_candidate_page_selection_is_bounded_and_prefers_participation() -> None:
    blocks = [
        {"text": "Condiciones generales del servicio.", "locator": {"page": 1}},
        {
            "text": "La mesa admite la oferta de ALFA y excluye la oferta de BETA.",
            "locator": {"page": 3},
        },
        {"text": "Calendario de ejecución.", "locator": {"page": 2}},
    ]
    selected = select_candidate_pages(blocks, max_pages=2, max_characters=1_000)
    assert list(selected) == [1, 3]
    assert "admite" in selected[3]


def test_candidate_chunks_are_bounded_per_physical_page() -> None:
    pages = {2: "Párrafo inicial.\n\n" + ("licitador ALFA " * 120)}
    chunks = split_candidate_pages_into_chunks(
        pages,
        max_chunk_characters=300,
        max_chunks_per_page=3,
    )
    assert [chunk["chunk_id"] for chunk in chunks] == [
        "p0002-c01",
        "p0002-c02",
        "p0002-c03",
    ]
    assert {chunk["page"] for chunk in chunks} == {2}
    assert all(len(chunk["text"]) <= 300 for chunk in chunks)
    assert all(len(str(chunk["sha256"])) == 64 for chunk in chunks)


def test_participation_windows_are_literal_bounded_and_stable() -> None:
    page = (
        "Encabezado de la mesa de contratación.\n"
        + ("Contexto previo. " * 40)
        + "\nSe admite la oferta de ALFA SINTÉTICA, S.L.\n"
        + ("Relleno. " * 80)
        + "\nLa licitadora BETA SINTÉTICA, S.A. presenta oferta."
    )
    windows = select_participation_windows(
        {3: page},
        max_window_characters=300,
        context_before_characters=80,
    )
    assert [window["chunk_id"] for window in windows] == [
        "p0003-w01",
        "p0003-w02",
        "p0003-w03",
    ]
    assert all(window["selection_strategy"] == "participation_window/v1" for window in windows)
    assert all(len(str(window["text"])) <= 300 for window in windows)
    assert all(str(window["text"]) in page for window in windows)
    assert "ALFA SINTÉTICA, S.L." in windows[1]["text"]


def test_participation_windows_fall_back_without_matching_vocabulary() -> None:
    page = "Condiciones generales del servicio.\n\nCalendario de ejecución."
    windows = select_participation_windows(
        {1: page},
        max_window_characters=300,
        context_before_characters=80,
    )
    assert [window["chunk_id"] for window in windows] == ["p0001-c01"]
    assert windows[0]["selection_strategy"] == "fallback_chunk/v1"
    assert windows[0]["text"] == page


def _chunk_output(
    *,
    chunk_id: str,
    page: int,
    quote: str,
    literal_name: str = "ALFA SINTÉTICA, S.L.",
    role: str = "admitted_bidder",
) -> ParticipationChunkOutput:
    return ParticipationChunkOutput.model_validate(
        {
            "schema_version": CANDIDATE_CHUNK_SCHEMA_VERSION,
            "document_id": "doc-1",
            "document_sha256": "a" * 64,
            "chunk_id": chunk_id,
            "page": page,
            "assessment": {
                "participant_content": "present",
                "list_completeness": "partial",
            },
            "assertions": [
                {
                    "candidate_ordinal": 1,
                    "literal_name": literal_name,
                    "identifier_literal": None,
                    "lot_literal": None,
                    "role": role,
                    "ute_status": "unknown",
                    "quote": quote,
                    "ambiguity_reasons": ["fragmento"],
                    "needs_human_review": True,
                }
            ],
            "limitations": ["chunk"],
        }
    )


def test_chunk_candidate_validation_and_merge_preserve_exact_citations() -> None:
    quote = "Se admite la oferta de ALFA SINTÉTICA, S.L."
    chunk = {
        "chunk_id": "p0001-c01",
        "page": 1,
        "text": quote,
        "sha256": hashlib.sha256(quote.encode()).hexdigest(),
    }
    output = _chunk_output(chunk_id="p0001-c01", page=1, quote=quote)
    structural = validate_chunk_candidate_against_chunk(
        output,
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        chunk=chunk,
    )
    assert structural["valid"] is True
    invalid = validate_chunk_candidate_against_chunk(
        _chunk_output(
            chunk_id="p0001-c01",
            page=1,
            quote=quote,
            literal_name="BETA SINTÉTICA, S.L.",
        ),
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        chunk=chunk,
    )
    assert "name_not_in_quote" in invalid["errors"]
    merged = merge_chunk_candidates(
        document_id="doc-1",
        document_sha256="a" * 64,
        pages={1: quote},
        chunks=[
            output,
            _chunk_output(chunk_id="p0001-c02", page=1, quote=quote),
        ],
    )
    assert len(merged.assertions) == 1
    assert merged.assertions[0].needs_human_review is True
    assert merged.assertions[0].citations[0].quote == quote
    final = validate_candidate_against_pages(
        merged,
        expected_document_id="doc-1",
        expected_document_sha256="a" * 64,
        pages={1: quote},
    )
    assert final["valid"] is True


def test_chunk_fingerprint_changes_with_chunk_or_parameters() -> None:
    chunk = {"chunk_id": "p0001-c01", "page": 1, "sha256": "b" * 64}
    first = chunk_candidate_fingerprint(
        document_sha256="a" * 64,
        chunk=chunk,
        model_manifest={"model": "fixture"},
        inference_params={"num_ctx": 4096, "max_output_tokens": 800},
    )
    different_params = chunk_candidate_fingerprint(
        document_sha256="a" * 64,
        chunk=chunk,
        model_manifest={"model": "fixture"},
        inference_params={"num_ctx": 4096, "max_output_tokens": 900},
    )
    different_chunk = chunk_candidate_fingerprint(
        document_sha256="a" * 64,
        chunk=chunk | {"sha256": "c" * 64},
        model_manifest={"model": "fixture"},
        inference_params={"num_ctx": 4096, "max_output_tokens": 800},
    )
    assert first != different_params
    assert first != different_chunk
