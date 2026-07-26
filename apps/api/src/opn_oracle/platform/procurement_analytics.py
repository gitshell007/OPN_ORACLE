"""Platform procurement market analytics for superadmins.

Aggregates a bounded sample of open PLACSP tenders from Signal plus the
registry ``/stats`` snapshot. Rankings are computed in Oracle so the UI can
choose top-N and sort without requiring a Signal analytics contract.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from opn_oracle.integrations.procurement import (
    ProcurementClient,
    ProcurementProviderError,
    procurement_client_from_config,
    procurement_stats,
)
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy, normalize_cpv_code

AMOUNT_BUCKETS: tuple[tuple[float | None, float | None, str], ...] = (
    (0.0, 15_000.0, "Menos de 15.000 EUR"),
    (15_000.0, 50_000.0, "15.000 - 50.000 EUR"),
    (50_000.0, 200_000.0, "50.000 - 200.000 EUR"),
    (200_000.0, 1_000_000.0, "200.000 - 1 M EUR"),
    (1_000_000.0, 5_000_000.0, "1 - 5 M EUR"),
    (5_000_000.0, None, "Mas de 5 M EUR"),
)

_STOPWORDS = frozenset(
    {
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "la",
        "las",
        "los",
        "para",
        "por",
        "un",
        "una",
        "unos",
        "y",
        "o",
        "u",
        "the",
        "of",
        "and",
        "servicio",
        "servicios",
        "suministro",
        "suministros",
        "contrato",
        "contratos",
        "licitacion",
        "licitación",
        "expediente",
        "lote",
        "lotes",
    }
)
_TOKEN_RE = re.compile(r"[a-záéíóúüñ0-9]{4,}", re.IGNORECASE)


def parse_amount(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number >= 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", normalized):
        normalized = normalized.replace(".", "")
    cleaned = re.sub(r"[^\d.-]", "", normalized)
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if number >= 0 else None


def _cpv_list(value: Any) -> list[str]:
    if isinstance(value, str):
        code = normalize_cpv_code(value) or value.strip()
        return [code] if code else []
    if not isinstance(value, list):
        return []
    codes: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            codes.append(normalize_cpv_code(item) or item.strip())
        elif isinstance(item, dict):
            raw = item.get("code") or item.get("cpv")
            if isinstance(raw, str) and raw.strip():
                codes.append(normalize_cpv_code(raw) or raw.strip())
    return codes


def _text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _rank(
    counter: Counter[str],
    *,
    top_n: int,
    labels: Mapping[str, str] | None = None,
    amount_totals: Mapping[str, float] | None = None,
    sort_by: str = "count",
    direction: str = "desc",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, count in counter.items():
        rows.append(
            {
                "key": key,
                "label": (labels or {}).get(key) or key,
                "count": int(count),
                "amount_sum": float((amount_totals or {}).get(key, 0.0)),
            }
        )
    reverse = direction != "asc"
    if sort_by == "amount_sum":
        rows.sort(key=lambda row: (row["amount_sum"], row["count"], row["key"]), reverse=reverse)
    else:
        rows.sort(key=lambda row: (row["count"], row["amount_sum"], row["key"]), reverse=reverse)
    return rows[: max(1, top_n)]


def amount_bucket_label(amount: float | None) -> str:
    if amount is None:
        return "Importe no publicado"
    for low, high, label in AMOUNT_BUCKETS:
        if low is not None and amount < low:
            continue
        if high is not None and amount >= high:
            continue
        return label
    return "Importe no publicado"


def aggregate_tenders(
    items: Sequence[Mapping[str, Any]],
    *,
    top_n: int = 25,
    sort_by: str = "count",
    direction: str = "desc",
) -> dict[str, Any]:
    taxonomy = load_cpv_taxonomy()
    cpv_counts: Counter[str] = Counter()
    buyer_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    term_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    cpv_amounts: defaultdict[str, float] = defaultdict(float)
    buyer_amounts: defaultdict[str, float] = defaultdict(float)
    region_amounts: defaultdict[str, float] = defaultdict(float)
    with_amount = 0
    amount_sum = 0.0

    for item in items:
        amount = parse_amount(item.get("amount") if "amount" in item else item.get("award_amount"))
        if amount is not None:
            with_amount += 1
            amount_sum += amount
        bucket_counts[amount_bucket_label(amount)] += 1

        buyer = _text(item.get("buyer")) or "Organismo no publicado"
        buyer_counts[buyer] += 1
        if amount is not None:
            buyer_amounts[buyer] += amount

        region = _text(item.get("region")) or "Región no publicada"
        region_counts[region] += 1
        if amount is not None:
            region_amounts[region] += amount

        status = _text(item.get("canonical_status") or item.get("status")) or "unknown"
        status_counts[status] += 1

        for code in _cpv_list(item.get("cpv")):
            cpv_counts[code] += 1
            if amount is not None:
                cpv_amounts[code] += amount

        title = _text(item.get("title")) or ""
        for token in _TOKEN_RE.findall(title.casefold()):
            if token in _STOPWORDS or token.isdigit():
                continue
            term_counts[token] += 1

    cpv_labels = {code: taxonomy.label(code) or code for code in cpv_counts}
    # Preserve fixed bucket order for the amount table, but still allow sort override.
    bucket_rows = [
        {
            "key": label,
            "label": label,
            "count": int(bucket_counts.get(label, 0)),
            "amount_sum": 0.0,
        }
        for _, _, label in AMOUNT_BUCKETS
    ]
    bucket_rows.append(
        {
            "key": "Importe no publicado",
            "label": "Importe no publicado",
            "count": int(bucket_counts.get("Importe no publicado", 0)),
            "amount_sum": 0.0,
        }
    )
    if sort_by == "count":
        reverse = direction != "asc"
        bucket_rows.sort(key=lambda row: (row["count"], row["label"]), reverse=reverse)

    return {
        "sample_size": len(items),
        "with_amount": with_amount,
        "amount_sum": round(amount_sum, 2),
        "top_cpv": _rank(
            cpv_counts,
            top_n=top_n,
            labels=cpv_labels,
            amount_totals=cpv_amounts,
            sort_by=sort_by,
            direction=direction,
        ),
        "top_buyers": _rank(
            buyer_counts,
            top_n=top_n,
            amount_totals=buyer_amounts,
            sort_by=sort_by,
            direction=direction,
        ),
        "top_regions": _rank(
            region_counts,
            top_n=top_n,
            amount_totals=region_amounts,
            sort_by=sort_by,
            direction=direction,
        ),
        "top_terms": _rank(term_counts, top_n=top_n, sort_by="count", direction=direction),
        "statuses": _rank(status_counts, top_n=20, sort_by="count", direction="desc"),
        "amount_buckets": bucket_rows,
    }


MAX_ANALYTICS_SAMPLE_SIZE = 10_000
DEFAULT_ANALYTICS_SAMPLE_SIZE = 300
ALLOWED_ANALYTICS_SCOPES = frozenset({"active", "all"})


def sample_tenders(
    client: ProcurementClient,
    *,
    sample_size: int,
    scope: str = "active",
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Sample tenders from Signal for market rankings.

    ``scope=active`` keeps the provider ``active=true`` filter.
    ``scope=all`` uses ``active=false`` (Signal v1: omit is_active predicate, not
    inactive-only), so finished tenders can appear in the sample.
    """

    target = max(1, min(int(sample_size), MAX_ANALYTICS_SAMPLE_SIZE))
    # Larger samples use bigger pages to cut round-trips to Signal.
    default_page = 200 if target > 1000 else 100
    page = max(10, min(int(page_size if page_size is not None else default_page), 200))
    active_filter: bool | None = scope != "all"
    collected: list[dict[str, Any]] = []
    offset = 0
    reported_total: int | None = None
    while len(collected) < target:
        payload = client.tenders(
            keywords=None,
            cpv=None,
            min_amount=None,
            max_amount=None,
            deadline_before=None,
            buyer=None,
            region=None,
            active=active_filter,
            limit=min(page, target - len(collected)),
            offset=offset,
        )
        total = payload.get("total")
        if isinstance(total, int):
            reported_total = total
        batch = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
        if not batch:
            break
        collected.extend(batch)
        offset += len(batch)
        if reported_total is not None and offset >= reported_total:
            break
        if len(batch) < page:
            break
    return collected[:target], reported_total


def sample_open_tenders(
    client: ProcurementClient,
    *,
    sample_size: int,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Backward-compatible alias for active-only sampling."""

    return sample_tenders(
        client,
        sample_size=sample_size,
        scope="active",
        page_size=page_size,
    )


def build_procurement_analytics(
    *,
    sample_size: int = DEFAULT_ANALYTICS_SAMPLE_SIZE,
    top_n: int = 25,
    sort_by: str = "count",
    direction: str = "desc",
    scope: str = "active",
    client: ProcurementClient | None = None,
) -> dict[str, Any]:
    owns_client = client is None
    active = client or procurement_client_from_config()
    resolved_scope = scope if scope in ALLOWED_ANALYTICS_SCOPES else "active"
    clamped_sample = max(1, min(int(sample_size), MAX_ANALYTICS_SAMPLE_SIZE))
    try:
        try:
            registry = procurement_stats() if owns_client else active.stats()
        except ProcurementProviderError as exc:
            registry = {
                "error": exc.detail[:300],
                "error_code": exc.code,
            }
        sample, reported_total = sample_tenders(
            active,
            sample_size=clamped_sample,
            scope=resolved_scope,
        )
        rankings = aggregate_tenders(
            sample,
            top_n=top_n,
            sort_by=sort_by,
            direction=direction,
        )
        if resolved_scope == "all":
            note = (
                "Rankings calculados sobre una muestra acotada del índice PLACSP "
                "(activas y finalizadas presentes en Signal). No es un archivo histórico completo."
            )
            sample_scope = "all_tenders"
        else:
            note = (
                "Rankings calculados sobre una muestra acotada de licitaciones activas "
                "PLACSP. No es el universo histórico completo."
            )
            sample_scope = "active_tenders"
        return {
            "registry": registry if isinstance(registry, dict) else {},
            "sample": {
                "requested": clamped_sample,
                "collected": len(sample),
                "provider_total": reported_total,
                "scope": sample_scope,
                "note": note,
            },
            "rankings": rankings,
            "controls": {
                "sample_size": clamped_sample,
                "top_n": top_n,
                "sort_by": sort_by,
                "direction": direction,
                "scope": resolved_scope,
            },
        }
    finally:
        if owns_client:
            active.close()
