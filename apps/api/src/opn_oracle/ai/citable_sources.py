"""G-18 · fuentes cerradas Signal → Oracle (cero confianza).

Solo se aceptan piezas del top-level ``citable_sources`` de la respuesta de Signal.
El modelo nunca aporta URLs confiables; ``source_urls`` del output no acreditan.
Checksum canónico alineado con Signal ``search_then_prompt._content_checksum``:
``sha256:`` + SHA-256(f"{title}\\n{snippet}\\n{url}").
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

# Bounds closed (mirror Signal G-18).
_MAX_CITABLE_SOURCES = 20
_TITLE_MAX = 300
_SNIPPET_MAX = 800
_PROVIDER_MAX = 40
_URL_MAX = 2048

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

ORIGIN_WEB_SEARCH = "web_search"
SOURCE_KIND_WEB_SEARCH = "web_search"
ORIGIN_STRUCTURED = "structured"
SOURCE_KIND_STRUCTURED = "structured"

# Server-owned deterministic namespaces (v1). Never accept model-emitted IDs.
CANDIDATE_ID_NAMESPACE = uuid.UUID("6b2e0c9a-5f41-4d8e-9a7c-18a18ca10001")
EVIDENCE_ID_NAMESPACE = uuid.UUID("7c3f1d0b-6a52-4e9f-8b8d-18a18e010002")


def server_owned_candidate_id(
    *,
    execution_key: str | uuid.UUID,
    name: str,
    evidence_ids: list[str] | tuple[str, ...],
) -> str:
    """Deterministic candidate_id after the model gate (never from model JSON).

    Material: versioned namespace + execution/artifact identity + normalized name
    + sorted evidence_ids. Homonyms with distinct evidence sets get distinct IDs.
    """

    normalized = " ".join(str(name or "").split()).casefold()
    sorted_ids: list[str] = []
    for item in evidence_ids:
        try:
            sorted_ids.append(str(uuid.UUID(str(item))))
        except (ValueError, TypeError, AttributeError):
            continue
    sorted_ids = sorted(set(sorted_ids))
    material = f"g18:candidate:v1|{execution_key}|{normalized}|{','.join(sorted_ids)}"
    return str(uuid.uuid5(CANDIDATE_ID_NAMESPACE, material))


def deterministic_web_search_evidence_id(
    *,
    tenant_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    source_id: str | uuid.UUID,
) -> uuid.UUID:
    """Idempotent Evidence PK for a reserved source under one artifact+tenant."""

    material = f"g18:evidence:v1|{tenant_id}|{artifact_id}|{source_id}"
    return uuid.uuid5(EVIDENCE_ID_NAMESPACE, material)


def _candidate_identity_name(row: dict[str, Any]) -> str:
    """Stable display identity for competitor (name) or actor (organization)."""

    return str(row.get("organization") or row.get("name") or "")


def stamp_server_owned_candidate_ids(
    output: dict[str, Any],
    *,
    execution_key: str | uuid.UUID,
) -> dict[str, Any]:
    """Strip any model-emitted candidate_id and assign server-owned UUIDs.

    Must run after the citable gate so evidence_ids are already closed.
    Identity material uses organization (actor) or name (competitor).
    """

    result = dict(output)
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return result
    stamped: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        # Never trust model / client candidate_id.
        row.pop("candidate_id", None)
        name = _candidate_identity_name(row)
        eids = row.get("evidence_ids") or []
        if not isinstance(eids, list):
            eids = []
        row["candidate_id"] = server_owned_candidate_id(
            execution_key=execution_key,
            name=name,
            evidence_ids=[str(x) for x in eids],
        )
        stamped.append(row)
    result["candidates"] = stamped
    return result


@dataclass(frozen=True, slots=True)
class CitableSource:
    """Pieza citable validada; inmutable y serializable."""

    source_id: str
    title: str
    url: str
    snippet: str
    provider: str
    rank: int
    content_checksum: str

    def to_public_dict(self) -> dict[str, Any]:
        """UI-safe: label/dominio/url; sin provider ni checksum."""

        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "rank": self.rank,
            "domain": _url_domain(self.url),
            "label": self.title or _url_domain(self.url) or self.url,
            "origin": ORIGIN_WEB_SEARCH,
            "origin_label": "Fuente encontrada por búsqueda",
        }

    def to_audit_dict(self) -> dict[str, Any]:
        """Full server/audit representation (includes provider + checksum)."""

        return {
            "source_id": self.source_id,
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "provider": self.provider,
            "rank": self.rank,
            "content_checksum": self.content_checksum,
            "origin": ORIGIN_WEB_SEARCH,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchMetadata:
    """Metadata top-level ``search`` de Signal (solo lectura/auditoría)."""

    status: str | None = None
    query: str | None = None
    result_count: int | None = None
    provider: str | None = None
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.status is not None:
            out["status"] = self.status
        if self.query is not None:
            out["query"] = self.query
        if self.result_count is not None:
            out["result_count"] = self.result_count
        if self.provider is not None:
            out["provider"] = self.provider
        return out


@dataclass(frozen=True, slots=True)
class SignalEnvelope:
    """Extracción tipada única del envelope Signal (texto modelo + fuentes + search)."""

    model_text: str
    citable_sources: tuple[CitableSource, ...]
    search: SearchMetadata | None
    source_warnings: tuple[str, ...]


def content_checksum(*, title: str, snippet: str, url: str) -> str:
    """Canonical checksum agreed with Signal G-18."""

    material = f"{title}\n{snippet}\n{url}".encode()
    return "sha256:" + hashlib.sha256(material).hexdigest()


def canonical_url(url: str) -> str:
    """Stable URL key (scheme/host lower, drop fragment, strip default ports)."""

    parsed = urlparse(str(url).strip())
    scheme = (parsed.scheme or "https").lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    else:
        netloc = host
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    query = parsed.query
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_safe_public_http_url(url: Any) -> bool:
    """Structural SSRF/data gate (offline-safe; no DNS). Fail-closed."""

    text = str(url or "").strip()
    if not text or len(text) > _URL_MAX:
        return False
    try:
        parsed = urlparse(text)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    except ValueError:
        pass
    return "@" not in (parsed.netloc or "")


def _strip_controls(text: str) -> str:
    return _CONTROL_CHARS_RE.sub("", text)


def _url_domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _parse_uuid(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def validate_citable_source(
    raw: Any,
    *,
    seen_ids: set[str],
    seen_urls: set[str],
) -> tuple[CitableSource | None, str | None]:
    """Validate one top-level source. Returns (source, warning_reason)."""

    if not isinstance(raw, dict):
        return None, "citable_source_not_object"
    sid = _parse_uuid(raw.get("source_id"))
    if sid is None:
        return None, "citable_source_invalid_source_id"
    if sid in seen_ids:
        return None, "citable_source_duplicate_id"
    url_raw = str(raw.get("url") or "").strip()
    if not is_safe_public_http_url(url_raw):
        return None, "citable_source_unsafe_url"
    try:
        canon = canonical_url(url_raw)
    except Exception:
        return None, "citable_source_url_canonical_fail"
    if not canon.startswith("http"):
        return None, "citable_source_url_not_http"
    if canon in seen_urls:
        return None, "citable_source_duplicate_url"
    title = _strip_controls(str(raw.get("title") or ""))[:_TITLE_MAX].strip()
    snippet = _strip_controls(str(raw.get("snippet") or raw.get("content") or ""))[
        :_SNIPPET_MAX
    ].strip()
    provider = _strip_controls(str(raw.get("provider") or ""))[:_PROVIDER_MAX]
    try:
        rank = int(raw.get("rank") or 0)
    except (TypeError, ValueError):
        rank = 0
    if rank < 1:
        rank = 0
    expected = content_checksum(title=title, snippet=snippet, url=canon)
    got = str(raw.get("content_checksum") or "").strip()
    if not got.startswith("sha256:") or len(got) != len(expected):
        return None, "citable_source_checksum_format"
    if got != expected:
        return None, "citable_source_checksum_mismatch"
    return (
        CitableSource(
            source_id=sid,
            title=title,
            url=canon,
            snippet=snippet,
            provider=provider,
            rank=rank or 1,
            content_checksum=got,
        ),
        None,
    )


def parse_citable_sources(
    payload: dict[str, Any] | None,
    *,
    max_sources: int = _MAX_CITABLE_SOURCES,
) -> tuple[tuple[CitableSource, ...], tuple[str, ...]]:
    """Parse top-level ``citable_sources`` only (never from text/choices)."""

    if not isinstance(payload, dict):
        return (), ()
    raw_list = payload.get("citable_sources")
    if raw_list is None:
        return (), ()
    if not isinstance(raw_list, list):
        return (), ("citable_sources_not_list",)
    limit = max(1, min(int(max_sources or _MAX_CITABLE_SOURCES), _MAX_CITABLE_SOURCES))
    accepted: list[CitableSource] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    excess = 0
    for item in raw_list:
        if len(accepted) >= limit:
            excess += 1
            continue
        source, reason = validate_citable_source(item, seen_ids=seen_ids, seen_urls=seen_urls)
        if source is None:
            msg = f"citable_source_discarded:{reason}"
            warnings.append(msg)
            logger.warning("oracle.g18.citable_source_discarded reason=%s", reason)
            continue
        accepted.append(source)
        seen_ids.add(source.source_id)
        seen_urls.add(source.url)
    if excess:
        warnings.append(f"citable_sources_excess_truncated:{excess}")
        logger.warning("oracle.g18.citable_sources_excess_truncated count=%s", excess)
    return tuple(accepted), tuple(warnings)


def parse_search_metadata(payload: dict[str, Any] | None) -> SearchMetadata | None:
    """Parse top-level ``search`` only."""

    if not isinstance(payload, dict):
        return None
    raw = payload.get("search")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return SearchMetadata(status="invalid", raw={"type": type(raw).__name__})
    status = raw.get("status")
    query = raw.get("query")
    result_count = raw.get("result_count")
    provider = raw.get("provider")
    try:
        count: int | None = int(result_count) if result_count is not None else None
    except (TypeError, ValueError):
        count = None
    return SearchMetadata(
        status=str(status)[:80] if status is not None else None,
        query=str(query)[:400] if query is not None else None,
        result_count=count,
        provider=str(provider)[:40] if provider is not None else None,
        raw={k: raw[k] for k in list(raw)[:20]},
    )


def extract_model_text_from_result(result_payload: dict[str, Any]) -> str:
    """Extract model text from Signal ``result`` (Ollama / OpenRouter / generate)."""

    message = result_payload.get("message")
    output_payload = message.get("content") if isinstance(message, dict) else None
    output_payload = output_payload or result_payload.get("response")
    if not isinstance(output_payload, str):
        choices = result_payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice_message = choices[0].get("message")
            if isinstance(choice_message, dict):
                output_payload = choice_message.get("content")
    if not isinstance(output_payload, str):
        raise ValueError("signal_result_missing_model_text")
    normalized = output_payload.strip()
    if normalized.startswith("```"):
        normalized = normalized.split("\n", 1)[1] if "\n" in normalized else ""
        if normalized.endswith("```"):
            normalized = normalized[:-3].strip()
    return normalized


def extract_signal_envelope(payload: dict[str, Any]) -> SignalEnvelope:
    """Typed single-pass extraction of Signal AI response envelope.

    Model text from ``result`` paths only; sources exclusively from top-level
    ``citable_sources``; search exclusively from top-level ``search``.
    """

    if not isinstance(payload, dict):
        raise ValueError("signal_payload_not_object")
    result_payload = payload.get("result")
    if not isinstance(result_payload, dict):
        raise ValueError("signal_result_missing")
    model_text = extract_model_text_from_result(result_payload)
    sources, warnings = parse_citable_sources(payload)
    search = parse_search_metadata(payload)
    return SignalEnvelope(
        model_text=model_text,
        citable_sources=sources,
        search=search,
        source_warnings=warnings,
    )


def discovery_intent_fields(context: dict[str, Any]) -> dict[str, Any]:
    """Limited domain-intent fields for Signal discovery tasks (no gov config).

    Derived from validated Oracle context. Never includes provider/model/
    discovery_search/options. Avoids concatenating the same text into multiple
    query-bearing fields (Signal joins them).

    For G-19 actor discovery, ``discovery_intent`` is the sole query text
    (never title/goal concatenation). ``actor_type`` comes from context.
    """

    def _clean_str(value: Any, *, max_len: int) -> str:
        text = " ".join(str(value or "").split()).strip()
        return text[:max_len]

    def _clean_list(value: Any, *, max_len: int, item_max: int = 120) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            part = _clean_str(item, max_len=item_max)
            if not part or part.casefold() in seen:
                continue
            seen.add(part.casefold())
            out.append(part)
            if len(out) >= max_len:
                break
        return out

    from opn_oracle.ai.schemas import MARKET_ACTOR_TYPES

    raw_type = str(context.get("actor_type") or "company").strip().lower()
    actor_type = raw_type if raw_type in MARKET_ACTOR_TYPES else "company"
    # Prefer free-text discovery_intent (G-19); fall back to description (G-06 competitor).
    intent = _clean_str(context.get("discovery_intent"), max_len=400)
    description = _clean_str(context.get("description"), max_len=400)
    own_offer = _clean_str(context.get("own_offer"), max_len=120)
    sectors = _clean_list(context.get("sectors"), max_len=10)
    countries = _clean_list(context.get("countries"), max_len=27, item_max=3)
    fields: dict[str, Any] = {
        "actor_type": actor_type,
    }
    query = intent or description
    if query:
        fields["query"] = query
    if sectors:
        fields["sector"] = sectors
    if own_offer and own_offer.casefold() not in (query or "").casefold():
        fields["market"] = own_offer
    if countries:
        fields["geography"] = countries
        fields["country"] = countries[0]
    keywords = _clean_list(context.get("keywords"), max_len=12) if context.get("keywords") else []
    if keywords:
        fields["keywords"] = keywords
    return fields


def filter_candidates_by_citable_allowlist(
    candidates: list[dict[str, Any]],
    *,
    allowed_source_ids: set[str],
    source_by_id: dict[str, CitableSource],
) -> tuple[list[dict[str, Any]], list[str], list[CitableSource]]:
    """Keep only candidates with ≥1 allowed evidence_id; strip alien IDs.

    - Alien / invented / cross-run UUIDs → removed from candidate; never replaced.
    - Candidate with zero remaining IDs → dropped with warning (not publishable).
    - ``source_urls`` never accredit; cleared on surviving candidates for new write.
    Returns (candidates, warnings, cited_reserved_sources).
    """

    warnings: list[str] = []
    kept: list[dict[str, Any]] = []
    cited_ids: list[str] = []
    cited_set: set[str] = set()

    for raw in candidates:
        row = dict(raw)
        name = _candidate_identity_name(row)[:80]
        raw_ids = row.get("evidence_ids") or []
        if not isinstance(raw_ids, list):
            raw_ids = []
        clean_ids: list[str] = []
        alien = 0
        for item in raw_ids:
            sid = _parse_uuid(item)
            if sid is None:
                alien += 1
                continue
            if sid not in allowed_source_ids:
                alien += 1
                continue
            if sid not in clean_ids:
                clean_ids.append(sid)
        if alien:
            warnings.append(
                f"candidate_dropped_or_trimmed_unauthorized_evidence:{name or '?'}:{alien}"
            )
            logger.warning(
                "oracle.g18.candidate_unauthorized_evidence name=%s alien=%s",
                name,
                alien,
            )
        if not clean_ids:
            warnings.append(f"candidate_not_publishable_without_citable_source:{name or '?'}")
            logger.warning(
                "oracle.g18.candidate_not_publishable name=%s",
                name,
            )
            continue
        row["evidence_ids"] = clean_ids
        # Model URLs never accredit and must not drive UI citations.
        row["source_urls"] = []
        row["source_urls_meta"] = []
        row["source_urls_status"] = None
        row["source_urls_label"] = None
        # Never accept candidate_id from the model JSON (server stamps later).
        row.pop("candidate_id", None)
        # UI-facing source summary from closed set (label/domain only).
        row["citable_sources"] = [
            source_by_id[sid].to_public_dict() for sid in clean_ids if sid in source_by_id
        ]
        kept.append(row)
        for sid in clean_ids:
            if sid not in cited_set and sid in source_by_id:
                cited_set.add(sid)
                cited_ids.append(sid)

    reserved = [source_by_id[sid] for sid in cited_ids if sid in source_by_id]
    return kept, warnings, reserved


def reserved_sources_for_output(
    sources: tuple[CitableSource, ...] | list[CitableSource],
) -> list[dict[str, Any]]:
    """Server-owned reserved block for artifact (audit fields kept)."""

    return [
        {
            **s.to_audit_dict(),
            "domain": _url_domain(s.url),
            "label": s.title or _url_domain(s.url) or s.url,
            "origin_label": "Fuente encontrada por búsqueda",
        }
        for s in sources
    ]


def _apply_discovery_citable_gate(
    output: dict[str, Any],
    *,
    citable_sources: tuple[CitableSource, ...] | list[CitableSource],
    extra_warnings: tuple[str, ...] | list[str] = (),
    execution_key: str | uuid.UUID | None = None,
    citation_note: str,
) -> dict[str, Any]:
    """Shared G-18/G-19 closed-source gate for market discovery family."""

    result = dict(output)
    source_list = list(citable_sources)
    source_by_id = {s.source_id: s for s in source_list}
    allowed = set(source_by_id)
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        candidates = []
    kept, filter_warnings, reserved = filter_candidates_by_citable_allowlist(
        candidates,
        allowed_source_ids=allowed,
        source_by_id=source_by_id,
    )
    result["candidates"] = kept
    result["reserved_citable_sources"] = reserved_sources_for_output(reserved)
    warnings: list[str] = []
    if isinstance(result.get("warnings"), list):
        warnings.extend(str(w) for w in result["warnings"] if w is not None)
    for w in extra_warnings:
        if w and w not in warnings:
            warnings.append(str(w))
    for w in filter_warnings:
        if w not in warnings:
            warnings.append(w)
    if citation_note not in warnings:
        warnings.append(citation_note)
    result["warnings"] = warnings[:20]
    if execution_key is not None:
        result = stamp_server_owned_candidate_ids(result, execution_key=execution_key)
    return result


def apply_market_competitor_citable_gate(
    output: dict[str, Any],
    *,
    citable_sources: tuple[CitableSource, ...] | list[CitableSource],
    extra_warnings: tuple[str, ...] | list[str] = (),
    execution_key: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    """Server-owned gate: filter candidates + attach reserved_citable_sources.

    When ``execution_key`` is provided, stamps deterministic ``candidate_id``
    values after the allowlist filter (never from model JSON).
    """

    note = (
        "Las citas de competidores solo provienen de citable_sources de Signal "
        f"(origin={ORIGIN_WEB_SEARCH}); las source_urls del modelo no acreditan."
    )
    return _apply_discovery_citable_gate(
        output,
        citable_sources=citable_sources,
        extra_warnings=extra_warnings,
        execution_key=execution_key,
        citation_note=note,
    )


def apply_market_actor_citable_gate(
    output: dict[str, Any],
    *,
    citable_sources: tuple[CitableSource, ...] | list[CitableSource],
    extra_warnings: tuple[str, ...] | list[str] = (),
    execution_key: str | uuid.UUID | None = None,
    expected_actor_type: str | None = None,
    expected_countries: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """G-19 gate: closed sources + actor_type/country concordance with intent.

    Wrong country or actor_type relative to the request is dropped with an
    honest warning (not silently published as matching).
    """

    note = (
        "Las citas de actores solo provienen de citable_sources de Signal "
        f"(origin={ORIGIN_WEB_SEARCH}); las source_urls del modelo no acreditan."
    )
    result = _apply_discovery_citable_gate(
        output,
        citable_sources=citable_sources,
        extra_warnings=extra_warnings,
        execution_key=None,  # stamp after type/country filter
        citation_note=note,
    )
    wanted_type = (expected_actor_type or "").strip().lower() or None
    wanted_countries = {
        str(c).strip().upper() for c in (expected_countries or []) if str(c).strip()
    }
    kept: list[dict[str, Any]] = []
    warnings = list(result.get("warnings") or [])
    for raw in result.get("candidates") or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        org = _candidate_identity_name(row)[:80] or "?"
        row_type = str(row.get("actor_type") or "").strip().lower()
        row_country = str(row.get("country") or "").strip().upper()
        if wanted_type and row_type and row_type != wanted_type:
            msg = f"candidate_dropped_actor_type_mismatch:{org}:{row_type}!={wanted_type}"
            if msg not in warnings:
                warnings.append(msg)
            logger.warning(
                "oracle.g19.candidate_actor_type_mismatch org=%s got=%s want=%s",
                org,
                row_type,
                wanted_type,
            )
            continue
        if wanted_countries and row_country and row_country not in wanted_countries:
            msg = f"candidate_dropped_country_mismatch:{org}:{row_country}"
            if msg not in warnings:
                warnings.append(msg)
            logger.warning(
                "oracle.g19.candidate_country_mismatch org=%s country=%s allowed=%s",
                org,
                row_country,
                sorted(wanted_countries),
            )
            continue
        if wanted_type and not row_type:
            row["actor_type"] = wanted_type
        kept.append(row)
    result["candidates"] = kept
    # Rebuild reserved from surviving candidates only.
    surviving_ids: list[str] = []
    seen: set[str] = set()
    for row in kept:
        for sid in row.get("evidence_ids") or []:
            try:
                key = str(uuid.UUID(str(sid)))
            except (ValueError, TypeError, AttributeError):
                continue
            if key not in seen:
                seen.add(key)
                surviving_ids.append(key)
    source_by_id = {s.source_id: s for s in citable_sources}
    reserved = [source_by_id[sid] for sid in surviving_ids if sid in source_by_id]
    result["reserved_citable_sources"] = reserved_sources_for_output(reserved)
    if not kept and not any("abstenc" in str(w).casefold() for w in warnings):
        abstain = (
            "Abstención: no hay candidatos publicables con cita cerrada que "
            "concuerden con actor_type y países de la intención."
        )
        if abstain not in warnings:
            warnings.append(abstain)
    result["warnings"] = warnings[:20]
    if execution_key is not None:
        result = stamp_server_owned_candidate_ids(result, execution_key=execution_key)
    return result


# Shared family of dossierless market discovery agents (G-18 + G-19).
MARKET_DISCOVERY_AGENTS = frozenset(
    {
        "market_competitor_discovery",
        "market_actor_discovery",
    }
)
