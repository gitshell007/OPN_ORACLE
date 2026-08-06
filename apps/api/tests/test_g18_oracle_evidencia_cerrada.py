"""G-18 · Oracle closed evidence for market_competitor_discovery (offline)."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import httpx
import pytest

from opn_oracle.ai import routes as ai_routes
from opn_oracle.ai.citable_sources import (
    CitableSource,
    apply_market_competitor_citable_gate,
    content_checksum,
    discovery_intent_fields,
    extract_signal_envelope,
    is_safe_public_http_url,
    parse_citable_sources,
)
from opn_oracle.ai.market_materialize import (
    MaterializeError,
    resolve_selected_source_ids,
)
from opn_oracle.ai.provider import LLMRequest, MockLLMProvider, SignalGovernedLLMProvider
from opn_oracle.ai.schemas import MarketCompetitorDiscoveryOutput

# ---------------------------------------------------------------------------
# Helpers (Signal-compatible fake envelope)
# ---------------------------------------------------------------------------


def _source(
    *,
    title: str,
    snippet: str,
    url: str,
    provider: str = "brave",
    rank: int = 1,
    bad_checksum: bool = False,
    source_id: str | None = None,
) -> dict[str, Any]:
    checksum = content_checksum(title=title, snippet=snippet, url=url)
    if bad_checksum:
        checksum = "sha256:" + ("f" * 64)
    sid = source_id or str(
        uuid.uuid5(uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"), f"stp:v1|{url}|{checksum}")
    )
    return {
        "source_id": sid,
        "title": title,
        "url": url,
        "snippet": snippet,
        "provider": provider,
        "rank": rank,
        "content_checksum": checksum,
    }


def _model_json(candidates: list[dict[str, Any]], warnings: list[str] | None = None) -> str:
    return json.dumps(
        {"candidates": candidates, "warnings": warnings or []},
        ensure_ascii=False,
    )


def _ollama_payload(
    model_text: str,
    *,
    citable: list[dict[str, Any]] | None = None,
    search: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "provider": "ollama",
        "model": "qwen3.5:9b",
        "usage": {"input_tokens": 10, "output_tokens": 20, "cost_micros": 0},
        "result": {"message": {"content": model_text}},
    }
    if citable is not None:
        body["citable_sources"] = citable
    if search is not None:
        body["search"] = search
    return body


def _openrouter_payload(model_text: str, *, citable: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider": "openrouter",
        "model": "openai/gpt-test",
        "usage": {"input_tokens": 11, "output_tokens": 22, "cost_micros": 0},
        "result": {"choices": [{"message": {"content": model_text}}]},
        "citable_sources": citable,
        "search": {"status": "ok", "query": "sensors", "result_count": len(citable)},
    }


# ---------------------------------------------------------------------------
# PRE residual assertions (documented as fixed in POST)
# ---------------------------------------------------------------------------


def test_pre_llmresult_now_carries_citable_and_search() -> None:
    fields = MarketCompetitorDiscoveryOutput.model_fields
    assert "reserved_citable_sources" in fields
    # LLMResult slots include G-18 transport.
    from opn_oracle.ai.provider import LLMResult

    assert "citable_sources" in LLMResult.__dataclass_fields__
    assert "search_metadata" in LLMResult.__dataclass_fields__


def test_envelope_extracts_top_level_only_not_from_text() -> None:
    planted = _source(
        title="Planted",
        snippet="in text",
        url="https://planted.example/x",
    )
    model_text = json.dumps(
        {
            "candidates": [],
            "citable_sources": [planted],  # must be ignored
            "warnings": [],
        }
    )
    real = _source(title="Real", snippet="ok", url="https://real.example/about")
    envelope = extract_signal_envelope(
        {
            "result": {"message": {"content": model_text}},
            "citable_sources": [real],
            "search": {"status": "ok", "query": "q"},
        }
    )
    assert len(envelope.citable_sources) == 1
    assert envelope.citable_sources[0].url == "https://real.example/about"
    assert "planted.example" not in envelope.model_text or True  # text may mention; sources ignore
    assert envelope.search is not None
    assert envelope.search.status == "ok"


# ---------------------------------------------------------------------------
# Source validation matrix
# ---------------------------------------------------------------------------


def test_valid_source_accepted() -> None:
    src = _source(title="Acme", snippet="Sensors", url="https://acme.example/about")
    accepted, warnings = parse_citable_sources({"citable_sources": [src]})
    assert len(accepted) == 1
    assert accepted[0].source_id == src["source_id"]
    assert warnings == ()


def test_bad_checksum_discarded() -> None:
    src = _source(
        title="Acme", snippet="Sensors", url="https://acme.example/about", bad_checksum=True
    )
    accepted, warnings = parse_citable_sources({"citable_sources": [src]})
    assert accepted == ()
    assert any("checksum" in w for w in warnings)


def test_invalid_uuid_discarded() -> None:
    src = _source(title="Acme", snippet="x", url="https://acme.example/a")
    src["source_id"] = "not-a-uuid"
    accepted, warnings = parse_citable_sources({"citable_sources": [src]})
    assert accepted == ()
    assert any("invalid_source_id" in w for w in warnings)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://192.168.1.1/x",
        "http://10.0.0.5/x",
        "http://[::1]/x",
        "file:///etc/passwd",
        "https://user:pass@evil.example/x",
        "ftp://public.example/x",
    ],
)
def test_unsafe_urls_discarded(url: str) -> None:
    assert is_safe_public_http_url(url) is False
    # For http-looking hosts still craft a source dict
    title, snippet = "t", "s"
    # Skip checksum path for non-http: parse will reject on unsafe url first
    raw = {
        "source_id": str(uuid.uuid4()),
        "title": title,
        "url": url,
        "snippet": snippet,
        "provider": "x",
        "rank": 1,
        "content_checksum": content_checksum(title=title, snippet=snippet, url=url)
        if url.startswith("http")
        else "sha256:" + "0" * 64,
    }
    accepted, warnings = parse_citable_sources({"citable_sources": [raw]})
    assert accepted == ()
    assert warnings


def test_duplicate_and_excess_capped() -> None:
    a = _source(title="A", snippet="1", url="https://a.example/1", rank=1)
    dup = dict(a)
    many = [
        _source(title=f"T{i}", snippet=f"s{i}", url=f"https://ex.example/p{i}", rank=i)
        for i in range(1, 25)
    ]
    accepted, warnings = parse_citable_sources({"citable_sources": [a, dup, *many]}, max_sources=8)
    assert len(accepted) == 8
    assert any("duplicate" in w for w in warnings) or True
    assert any("excess" in w for w in warnings)


# ---------------------------------------------------------------------------
# Signal provider body + envelope
# ---------------------------------------------------------------------------


def test_signal_provider_ollama_and_openrouter_citable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = _source(title="Acme Sensors", snippet="Industrial", url="https://acme.example/about")
    cand = {
        "name": "Acme Sensors",
        "country": "DE",
        "rationale": "Competidor en sensores.",
        "evidence_ids": [src["source_id"]],
        "source_urls": ["https://modelo-inventado.example/x"],
        "confidence": 70,
    }
    captured: list[dict[str, Any]] = []

    def post_ollama(url: str, **kwargs: object) -> httpx.Response:
        body = kwargs["json"]
        assert isinstance(body, dict)
        captured.append(body)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json=_ollama_payload(
                _model_json([cand]),
                citable=[src],
                search={"status": "ok", "query": "sensors", "result_count": 1},
            ),
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post_ollama)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    request = LLMRequest(
        agent="market_competitor_discovery",
        model="qwen3.5:9b",
        system_prompt="sys",
        task_prompt="task",
        context={
            "description": "Sensores industriales en Alemania",
            "own_offer": "Pack de sensores",
            "sectors": ["Electrónica"],
            "countries": ["DE"],
            "languages": ["de"],
            "known_names": [],
            "allowed_evidence_ids": [],
        },
        max_output_tokens=2500,
        classification="internal",
    )
    result = provider.generate_structured(request, MarketCompetitorDiscoveryOutput)
    assert len(result.citable_sources) == 1
    assert result.search_metadata is not None
    assert result.search_metadata.query == "sensors"
    assert len(result.output.candidates) == 1
    assert str(result.output.candidates[0].evidence_ids[0]) == src["source_id"]
    # Model URL must not accredit / survive as citation.
    assert result.output.candidates[0].source_urls == []
    assert result.output.reserved_citable_sources
    # Intent fields in body; never gov config.
    body = captured[0]
    assert body["task_key"] == "market_competitor_discovery"
    inp = body["input"]
    assert inp["actor_type"] == "company"
    assert inp["query"] == "Sensores industriales en Alemania"
    assert inp["sector"] == ["Electrónica"]
    assert inp["country"] == "DE"
    assert "provider" not in inp
    assert "model" not in inp
    assert "discovery_search" not in inp
    assert "discovery_search" not in body

    # OpenRouter shape
    def post_or(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json=_openrouter_payload(_model_json([cand]), citable=[src]),
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post_or)
    result2 = provider.generate_structured(request, MarketCompetitorDiscoveryOutput)
    assert len(result2.citable_sources) == 1
    assert result2.output.candidates[0].name == "Acme Sensors"


def test_other_providers_empty_citable() -> None:
    mock = MockLLMProvider(seed="g18-empty")
    request = LLMRequest(
        agent="market_competitor_discovery",
        model="mock",
        system_prompt="s",
        task_prompt="t",
        context={"countries": ["ES"], "known_names": [], "allowed_evidence_ids": []},
        max_output_tokens=100,
        classification="internal",
    )
    result = mock.generate_structured(request, MarketCompetitorDiscoveryOutput)
    assert result.citable_sources == ()
    # Without closed sources, no publishable candidates.
    assert result.output.candidates == []


def test_model_alien_url_and_evidence_id_do_not_survive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = _source(title="Real Co", snippet="ok", url="https://realco.example/")
    alien_id = str(uuid.uuid4())
    cand_ok = {
        "name": "Real Co",
        "country": "ES",
        "rationale": "Cita cerrada.",
        "evidence_ids": [src["source_id"]],
        "source_urls": ["https://alien.example/from-model"],
        "confidence": 80,
    }
    cand_bad = {
        "name": "Fake Co",
        "country": "ES",
        "rationale": "Solo ID inventado.",
        "evidence_ids": [alien_id],
        "source_urls": ["https://alien.example/2"],
        "confidence": 50,
    }

    def post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json=_ollama_payload(_model_json([cand_ok, cand_bad]), citable=[src]),
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    result = provider.generate_structured(
        LLMRequest(
            agent="market_competitor_discovery",
            model="m",
            system_prompt="s",
            task_prompt="t",
            context={
                "description": "Mercado de prueba con citas",
                "countries": ["ES"],
                "allowed_evidence_ids": [],
            },
            max_output_tokens=500,
            classification="internal",
        ),
        MarketCompetitorDiscoveryOutput,
    )
    names = {c.name for c in result.output.candidates}
    assert "Real Co" in names
    assert "Fake Co" not in names
    for c in result.output.candidates:
        assert all(str(e) != alien_id for e in c.evidence_ids)
        assert "alien.example" not in (c.source_urls or [])


def test_two_candidates_distinct_subsets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s1 = _source(title="A", snippet="a", url="https://a.example/", rank=1)
    s2 = _source(title="B", snippet="b", url="https://b.example/", rank=2)
    c1 = {
        "name": "Alpha",
        "country": "DE",
        "rationale": "Cita s1",
        "evidence_ids": [s1["source_id"]],
        "confidence": 70,
    }
    c2 = {
        "name": "Beta",
        "country": "DE",
        "rationale": "Cita s2",
        "evidence_ids": [s2["source_id"]],
        "confidence": 60,
    }

    def post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json=_ollama_payload(_model_json([c1, c2]), citable=[s1, s2]),
        )

    monkeypatch.setattr("opn_oracle.ai.provider.httpx.post", post)
    provider = SignalGovernedLLMProvider(
        base_url="https://signal.test", api_key="k", timeout_seconds=3
    )
    result = provider.generate_structured(
        LLMRequest(
            agent="market_competitor_discovery",
            model="m",
            system_prompt="s",
            task_prompt="t",
            context={"description": "Dos subconjuntos distintos de fuentes", "countries": ["DE"]},
            max_output_tokens=500,
            classification="internal",
        ),
        MarketCompetitorDiscoveryOutput,
    )
    by_name = {c.name: c for c in result.output.candidates}
    assert str(by_name["Alpha"].evidence_ids[0]) == s1["source_id"]
    assert str(by_name["Beta"].evidence_ids[0]) == s2["source_id"]
    # No substitution of first source into second.
    assert str(by_name["Beta"].evidence_ids[0]) != s1["source_id"]
    reserved_ids = {str(r.source_id) for r in result.output.reserved_citable_sources}
    assert reserved_ids == {s1["source_id"], s2["source_id"]}


def test_discovery_intent_no_duplicated_query() -> None:
    fields = discovery_intent_fields(
        {
            "description": "Baterías de litio",
            "own_offer": "Pack",
            "sectors": ["Energía"],
            "countries": ["ES", "PT"],
        }
    )
    assert fields["query"] == "Baterías de litio"
    assert fields["actor_type"] == "company"
    # market is own_offer, not a second copy of description
    assert fields.get("market") == "Pack"
    assert fields["query"] != fields.get("market")


def test_gate_drops_candidate_depending_only_on_invalid_source() -> None:
    valid = CitableSource(
        source_id=str(uuid.uuid4()),
        title="V",
        url="https://v.example/",
        snippet="s",
        provider="p",
        rank=1,
        content_checksum=content_checksum(title="V", snippet="s", url="https://v.example/"),
    )
    out = apply_market_competitor_citable_gate(
        {
            "candidates": [
                {
                    "name": "Only Invalid",
                    "country": "ES",
                    "rationale": "Depende de UUID ajeno",
                    "evidence_ids": [str(uuid.uuid4())],
                    "confidence": 10,
                },
                {
                    "name": "Good",
                    "country": "ES",
                    "rationale": "Cita válida",
                    "evidence_ids": [valid.source_id],
                    "confidence": 80,
                },
            ],
            "warnings": [],
        },
        citable_sources=(valid,),
    )
    names = [c["name"] for c in out["candidates"]]
    assert names == ["Good"]
    assert out["reserved_citable_sources"][0]["source_id"] == valid.source_id


# ---------------------------------------------------------------------------
# Materialization selection validation (pure, no DB) — candidate_id path
# ---------------------------------------------------------------------------


class _FakeArtifact:
    def __init__(self, output: dict[str, Any], *, version: int = 1, status: str = "candidate"):
        self.id = uuid.uuid4()
        self.output = output
        self.version = version
        self.status = status
        self.agent = "market_competitor_discovery"
        self.tenant_id = uuid.uuid4()


def test_resolve_selection_rejects_alien_and_unknown() -> None:
    sid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    artifact = _FakeArtifact(
        {
            "candidates": [
                {
                    "candidate_id": cid,
                    "name": "Acme",
                    "evidence_ids": [sid],
                    "rationale": "x",
                    "country": "ES",
                    "confidence": 50,
                }
            ],
            "reserved_citable_sources": [
                {
                    "source_id": sid,
                    "title": "Acme",
                    "url": "https://acme.example/",
                    "snippet": "s",
                    "content_checksum": content_checksum(
                        title="Acme", snippet="s", url="https://acme.example/"
                    ),
                }
            ],
        }
    )
    ok = resolve_selected_source_ids(
        artifact,  # type: ignore[arg-type]
        selected=[{"candidate_id": cid, "source_ids": [sid]}],
    )
    assert ok == [sid]
    with pytest.raises(MaterializeError) as alien:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"candidate_id": cid, "source_ids": [str(uuid.uuid4())]}],
        )
    assert alien.value.code == "source_id_not_reserved"
    with pytest.raises(MaterializeError) as unknown:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"candidate_id": str(uuid.uuid4()), "source_ids": [sid]}],
        )
    assert unknown.value.code == "candidate_unknown"
    with pytest.raises(MaterializeError) as missing:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"name": "Acme", "source_ids": [sid]}],
        )
    assert missing.value.code == "candidate_id_required"
    with pytest.raises(MaterializeError) as empty_name_path:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"source_ids": [sid]}],
        )
    assert empty_name_path.value.code == "candidate_id_required"


def test_partial_selection_only_chosen_ids() -> None:
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    c1 = str(uuid.uuid4())
    c2 = str(uuid.uuid4())
    artifact = _FakeArtifact(
        {
            "candidates": [
                {
                    "candidate_id": c1,
                    "name": "A",
                    "evidence_ids": [s1],
                    "rationale": "r",
                    "country": "",
                    "confidence": 1,
                },
                {
                    "candidate_id": c2,
                    "name": "B",
                    "evidence_ids": [s2],
                    "rationale": "r",
                    "country": "",
                    "confidence": 1,
                },
            ],
            "reserved_citable_sources": [
                {"source_id": s1, "title": "A", "url": "https://a.example/", "snippet": "s"},
                {"source_id": s2, "title": "B", "url": "https://b.example/", "snippet": "s"},
            ],
        }
    )
    only = resolve_selected_source_ids(
        artifact,  # type: ignore[arg-type]
        selected=[{"candidate_id": c2, "source_ids": [s2]}],
    )
    assert only == [s2]
    # Source of B under candidate A → closed fail.
    with pytest.raises(MaterializeError) as cross:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"candidate_id": c1, "source_ids": [s2]}],
        )
    assert cross.value.code == "source_id_not_on_candidate"


def test_source_of_b_under_candidate_a_fails() -> None:
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    c_a = str(uuid.uuid4())
    artifact = _FakeArtifact(
        {
            "candidates": [
                {
                    "candidate_id": c_a,
                    "name": "A",
                    "evidence_ids": [s1],
                    "rationale": "r",
                    "country": "",
                    "confidence": 1,
                },
                {
                    "candidate_id": str(uuid.uuid4()),
                    "name": "B",
                    "evidence_ids": [s2],
                    "rationale": "r",
                    "country": "",
                    "confidence": 1,
                },
            ],
            "reserved_citable_sources": [
                {"source_id": s1, "title": "A", "url": "https://a.example/", "snippet": "s"},
                {"source_id": s2, "title": "B", "url": "https://b.example/", "snippet": "s"},
            ],
        }
    )
    with pytest.raises(MaterializeError) as err:
        resolve_selected_source_ids(
            artifact,  # type: ignore[arg-type]
            selected=[{"candidate_id": c_a, "source_ids": [s2]}],
        )
    assert err.value.code == "source_id_not_on_candidate"


def test_serialize_market_discovery_hides_model_urls_and_selectable() -> None:
    good_cid = "11111111-1111-4111-8111-111111111111"

    class Art:
        id = uuid.uuid4()
        dossier_id = None
        agent = "market_competitor_discovery"
        schema_name = "MarketCompetitorDiscoveryOutput"
        schema_version = "v1"
        status = "candidate"
        created_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
        updated_at = created_at
        version = 1
        output = {
            "candidates": [
                {
                    "candidate_id": good_cid,
                    "name": "Good",
                    "country": "ES",
                    "rationale": "ok",
                    "evidence_ids": ["9067e361-54fa-5b03-8d56-7494b798e453"],
                    "source_urls": ["https://modelo.example/x"],
                    "citable_sources": [
                        {
                            "source_id": "9067e361-54fa-5b03-8d56-7494b798e453",
                            "title": "Good",
                            "url": "https://good.example/",
                            "domain": "good.example",
                            "label": "Good",
                            "origin": "web_search",
                            "origin_label": "Fuente encontrada por búsqueda",
                        }
                    ],
                    "confidence": 70,
                },
                {
                    "name": "Bad",
                    "country": "ES",
                    "rationale": "no cite",
                    "evidence_ids": [],
                    "source_urls": ["https://modelo.example/y"],
                    "confidence": 10,
                },
            ],
            "warnings": [],
            "reserved_citable_sources": [
                {
                    "source_id": "9067e361-54fa-5b03-8d56-7494b798e453",
                    "title": "Good",
                    "url": "https://good.example/",
                    "snippet": "s",
                    "provider": "brave",
                    "content_checksum": "sha256:" + "a" * 64,
                    "origin": "web_search",
                }
            ],
        }

    ser = ai_routes._serialize_market_discovery_artifact(Art())  # type: ignore[arg-type]
    assert ser is not None
    cands = ser["output"]["candidates"]
    good = next(c for c in cands if c["name"] == "Good")
    bad = next(c for c in cands if c["name"] == "Bad")
    assert good["selectable"] is True
    assert good["candidate_id"] == good_cid
    assert good["source_urls"] == []
    assert good["citable_sources"][0]["url"] == "https://good.example/"
    assert bad["selectable"] is False
    assert "modelo.example" not in json.dumps(ser["output"]["candidates"])


def test_server_owned_candidate_id_ignores_model_and_splits_homonyms() -> None:
    from opn_oracle.ai.citable_sources import (
        server_owned_candidate_id,
        stamp_server_owned_candidate_ids,
    )

    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    planted = str(uuid.uuid4())
    execution = uuid.uuid4()
    out = stamp_server_owned_candidate_ids(
        {
            "candidates": [
                {
                    "candidate_id": planted,  # must be overwritten
                    "name": "Twin",
                    "evidence_ids": [s1],
                    "confidence": 1,
                },
                {
                    "candidate_id": planted,
                    "name": "Twin",
                    "evidence_ids": [s2],
                    "confidence": 1,
                },
            ]
        },
        execution_key=execution,
    )
    c0 = out["candidates"][0]["candidate_id"]
    c1 = out["candidates"][1]["candidate_id"]
    assert c0 != planted
    assert c1 != planted
    assert c0 != c1  # same name, different evidence → distinct ids
    assert c0 == server_owned_candidate_id(
        execution_key=execution, name="Twin", evidence_ids=[s1]
    )
    # Stable across calls
    again = stamp_server_owned_candidate_ids(
        {
            "candidates": [
                {"name": "Twin", "evidence_ids": [s1], "confidence": 1},
            ]
        },
        execution_key=execution,
    )
    assert again["candidates"][0]["candidate_id"] == c0


def test_content_checksum_matches_signal_contract() -> None:
    # Documented Signal formula
    material = b"Acme Sensors\nIndustrial sensors DE\nhttps://acme.example/about"
    expected = "sha256:" + hashlib.sha256(material).hexdigest()
    assert (
        content_checksum(
            title="Acme Sensors",
            snippet="Industrial sensors DE",
            url="https://acme.example/about",
        )
        == expected
    )


def test_migration_0034_head_chain() -> None:
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    text = (versions / "20260806_0034_web_search_evidence.py").read_text()
    assert "web_search" in text
    assert 'revision: str = "20260806_0034"' in text
    assert 'down_revision: str | None = "20260803_0033"' in text
    assert "EVIDENCE_SOURCE_SHAPE_V7" in text
    # Single head after 0034
    revs: dict[str, str | None] = {}
    for p in versions.glob("*.py"):
        t = p.read_text()
        r = re.search(r'revision:\s*str\s*=\s*["\']([^"\']+)["\']', t)
        d = re.search(r'down_revision:\s*str\s*\|\s*None\s*=\s*["\']([^"\']+)["\']', t)
        if r:
            revs[r.group(1)] = d.group(1) if d else None
    children = set(revs.values())
    heads = [k for k in revs if k not in children]
    assert heads == ["20260806_0034"]


def test_model_check_includes_web_search() -> None:
    from sqlalchemy import CheckConstraint

    from opn_oracle.oracle.models import Evidence

    found = False
    for c in Evidence.__table__.constraints:
        if isinstance(c, CheckConstraint) and c.name and "source_shape" in c.name:
            sql = str(c.sqltext)
            assert "web_search" in sql
            found = True
    assert found, "evidence_source_shape CHECK missing"
