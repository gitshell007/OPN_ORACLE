"""Deterministic attribution filter for Signal web-search results."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

WEB_MENTION_FILTER_VERSION = "exact_identity_external_v1"

_LEGAL_SUFFIXES = {
    "ag",
    "bv",
    "corp",
    "corporation",
    "inc",
    "limited",
    "ltd",
    "nv",
    "plc",
    "sa",
    "sau",
    "sas",
    "sl",
    "slu",
}
_DOMAIN_SUFFIXES_WITH_SECOND_LEVEL = {
    ("co", "uk"),
    ("com", "ar"),
    ("com", "br"),
    ("com", "es"),
    ("com", "mx"),
}


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return without_marks.casefold()


def _tokens(value: str) -> list[str]:
    raw = re.findall(r"[a-z0-9]+", _fold(value))
    collapsed: list[str] = []
    index = 0
    while index < len(raw):
        if index + 1 < len(raw):
            long_suffix = {
                ("sociedad", "anonima"): "sa",
                ("sociedad", "limitada"): "sl",
            }.get((raw[index], raw[index + 1]))
            if long_suffix:
                collapsed.append(long_suffix)
                index += 2
                continue
        if index + 1 < len(raw) and len(raw[index]) == len(raw[index + 1]) == 1:
            pair = raw[index] + raw[index + 1]
            if pair in _LEGAL_SUFFIXES:
                collapsed.append(pair)
                index += 2
                continue
        collapsed.append(raw[index])
        index += 1
    return collapsed


def _entity_identity(name: str, *, entity_kind: str) -> tuple[list[str], str | None]:
    tokens = _tokens(name)
    if entity_kind == "person":
        return tokens, None
    legal_suffix: str | None = None
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        legal_suffix = legal_suffix or tokens[-1]
        tokens.pop()
    return tokens, legal_suffix


def _contains_sequence(tokens: list[str], sequence: list[str]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    return any(tokens[index : index + len(sequence)] == sequence for index in range(len(tokens)))


def _domain_identity_label(url: str) -> str:
    try:
        hostname = (urlparse(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    labels = [label for label in hostname.split(".") if label and label != "www"]
    if len(labels) < 2:
        return ""
    if len(labels) >= 3 and tuple(labels[-2:]) in _DOMAIN_SUFFIXES_WITH_SECOND_LEVEL:
        return re.sub(r"[^a-z0-9]", "", _fold(labels[-3]))
    return re.sub(r"[^a-z0-9]", "", _fold(labels[-2]))


def _is_first_party_domain(url: str, identity_tokens: list[str]) -> bool:
    domain_label = _domain_identity_label(url)
    if not domain_label:
        return False
    candidates = {re.sub(r"[^a-z0-9]", "", "".join(identity_tokens))}
    if len(identity_tokens) == 1 and len(identity_tokens[0]) >= 5:
        candidates.add(identity_tokens[0])
    return domain_label in candidates


def _is_attributable(
    item: dict[str, Any],
    *,
    identity_tokens: list[str],
    legal_suffix: str | None,
) -> bool:
    title = str(item.get("title") or item.get("headline") or item.get("name") or "")
    snippet = str(
        item.get("snippet")
        or item.get("summary")
        or item.get("description")
        or item.get("text")
        or ""
    )
    if not identity_tokens:
        return False

    required = [*identity_tokens, legal_suffix] if legal_suffix else identity_tokens
    return _contains_sequence(_tokens(title), required) or _contains_sequence(
        _tokens(snippet), required
    )


def _is_duplicate_procurement_directory(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or item.get("headline") or item.get("name") or "")
    title_tokens = _tokens(title)
    return "licitaciones" in title_tokens and _contains_sequence(
        title_tokens, ["contratos", "publicos"]
    )


def filter_entity_web_mentions(
    data: dict[str, Any],
    *,
    entity_name: str,
    entity_kind: str,
) -> dict[str, Any]:
    """Keep only externally attributable results and return aggregate discard metadata.

    The function is idempotent so both the HTTP proxy and report boundary can
    enforce the same contract. Discarded titles do not cross the API boundary.
    """

    raw_items = data.get("items")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    identity_tokens, legal_suffix = _entity_identity(entity_name, entity_kind=entity_kind)
    kept: list[dict[str, Any]] = []
    discarded_reasons = {
        "first_party_domain": 0,
        "duplicate_procurement_directory": 0,
        "insufficient_attribution": 0,
        "invalid_url": 0,
    }

    for item in items:
        source_url = str(
            item.get("url") or item.get("source_url") or item.get("link") or item.get("href") or ""
        )
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            discarded_reasons["invalid_url"] += 1
            continue
        if entity_kind == "company" and _is_first_party_domain(source_url, identity_tokens):
            discarded_reasons["first_party_domain"] += 1
            continue
        if _is_duplicate_procurement_directory(item):
            discarded_reasons["duplicate_procurement_directory"] += 1
            continue
        if not _is_attributable(
            item,
            identity_tokens=identity_tokens,
            legal_suffix=legal_suffix,
        ):
            discarded_reasons["insufficient_attribution"] += 1
            continue
        kept.append({**item, "oracle_attribution": "exact_entity_name"})

    raw_previous_reasons = data.get("discarded_reasons")
    previous_reasons: dict[str, Any] = (
        raw_previous_reasons
        if data.get("attribution_filter_version") == WEB_MENTION_FILTER_VERSION
        and isinstance(raw_previous_reasons, dict)
        else {}
    )
    combined_reasons = {
        reason: count
        + (
            int(previous_reasons.get(reason, 0))
            if isinstance(previous_reasons.get(reason, 0), int)
            else 0
        )
        for reason, count in discarded_reasons.items()
    }
    previous_total = data.get("source_total")
    received_items = (
        previous_total
        if isinstance(previous_total, int)
        and not isinstance(previous_total, bool)
        and previous_total >= len(items)
        else len(items)
    )
    discarded_count = max(sum(combined_reasons.values()), received_items - len(kept))
    return {
        **data,
        "items": kept,
        "source_total": received_items,
        "received_items": received_items,
        "attributed_items": len(kept),
        "discarded_count": discarded_count,
        "discarded_reasons": combined_reasons,
        "attribution_filter_version": WEB_MENTION_FILTER_VERSION,
        "has_publication_dates": False,
    }
