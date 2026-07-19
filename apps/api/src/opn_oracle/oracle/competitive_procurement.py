"""Deterministic procurement aggregates for competitive intelligence reports.

Signal is the producer of public registry rows. Oracle owns pagination, arithmetic,
coverage disclosure and the conservative UTE parsing heuristic. No LLM participates
in these calculations.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import partial
from statistics import median
from typing import Any, Protocol

from opn_oracle.integrations.procurement import ProcurementProviderError

COMPETITIVE_PROCUREMENT_AGENT = "competitive_procurement_intelligence"
COMPETITIVE_PROCUREMENT_JOB = "oracle.competitive_procurement_report.generate"
COMPETITIVE_PROCUREMENT_TEMPLATE = "competitive_procurement"

AWARD_PAGE_SIZE = 100
MAX_AWARD_ROWS = 1_000
MIN_DISCOUNT_COVERAGE = Decimal("0.80")
MIN_DISCOUNT_SAMPLE = 3

# El corpus completo son ~11 páginas seguidas contra Signal, y su rate limit salta con
# ráfagas (429 observado en producción con tres peticiones en 100 ms). El 429 se maneja
# DENTRO del bucle de paginación: si se dejara subir, Celery reintentaría el job entero
# desde la página cero, quemando el presupuesto de peticiones en cada reintento sin
# poder terminar jamás.
PAGE_THROTTLE_SECONDS = 0.35
RATE_LIMIT_STATUS = 429
RATE_LIMIT_MAX_RETRIES = 6
RATE_LIMIT_BACKOFF_CAP_SECONDS = 30.0

# La sonda de cobertura de la baja hace un lookup de licitación por contrato. Sin tope,
# un adjudicatario grande (ITURRI: ~600 contratos únicos) son cientos de peticiones en
# serie solo para descubrir que la cobertura es ~0%. Se sondean los contratos más
# recientes hasta este máximo y el recorte se declara en la salida.
DISCOUNT_PROBE_MAX = 60

_MONEY_QUANTUM = Decimal("0.01")
_PERCENT_QUANTUM = Decimal("0.1")
_UTE_MARKERS = re.compile(
    r"(?i)\b(?:UTE|U\.T\.E\.|UNION TEMPORAL DE EMPRESAS|LEY\s+18/1982|A CONSTITUIR)\b"
)
_PARTNER_SEPARATORS = re.compile(r"\s+(?:Y|E)\s+|\s*[-\u2013\u2014]\s*|,\s+")
_LEGAL_ONLY = re.compile(r"(?i)^(?:S\.?\s*A\.?|S\.?\s*L\.?(?:\s*U\.?)?|SLP|SAU|UTE|U\.T\.E\.?)$")


class ProcurementHistoryClient(Protocol):
    def awards(
        self,
        *,
        company: str | None,
        buyer: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]: ...

    def tender_by_folder(self, *, folder_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AwardHistory:
    rows: tuple[dict[str, Any], ...]
    provider_total: int
    truncated: bool
    provider_company_norm: str


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _money(value: Decimal | None) -> str | None:
    return (
        str(value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)) if value is not None else None
    )


def _percent(value: Decimal | None) -> str | None:
    return (
        str(value.quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)) if value is not None else None
    )


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _iso_date(value: Any) -> date | None:
    text = _text(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _normalized_name(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def _company_core(value: str) -> str:
    normalized = _normalized_name(value)
    for spaced, compact in (
        (r"\bS\s+A\s+U\b", "SAU"),
        (r"\bS\s+L\s+U\b", "SLU"),
        (r"\bS\s+L\s+P\b", "SLP"),
        (r"\bS\s+A\b", "SA"),
        (r"\bS\s+L\b", "SL"),
    ):
        normalized = re.sub(spaced, compact, normalized)
    tokens = normalized.split()
    legal_tokens = {"SA", "SL", "SLU", "SAU", "SLP", "SOCIEDAD", "ANONIMA", "LIMITADA"}
    core = [token for token in tokens if token not in legal_tokens]
    return " ".join(core or tokens)


def pinned_award_winners(items: Iterable[Any]) -> tuple[str, ...]:
    """Return exact winner labels available in pinned award snapshots."""

    winners: dict[str, str] = {}
    for item in items:
        if getattr(item, "kind", None) != "award":
            continue
        snapshot = getattr(item, "snapshot", None)
        if not isinstance(snapshot, dict):
            continue
        values: list[Any] = [snapshot.get("winner")]
        entries = snapshot.get("entries")
        if isinstance(entries, list):
            values.extend(entry.get("winner") for entry in entries if isinstance(entry, dict))
        for value in values:
            label = _text(value)
            if label:
                winners.setdefault(label.casefold(), label)
    return tuple(winners.values())


def _call_waiting_out_rate_limit(
    call: Callable[[], dict[str, Any]],
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    """Run a Signal call, absorbing up to RATE_LIMIT_MAX_RETRIES 429s in place.

    Cualquier otro error del proveedor sube intacto: si el 429 escapara de aquí,
    Celery reintentaría el job entero desde cero, quemando el presupuesto de
    peticiones en cada reintento sin poder terminar jamás.
    """

    rate_limited = 0
    while True:
        try:
            return call()
        except ProcurementProviderError as error:
            status = getattr(error, "status_code", None)
            if status != RATE_LIMIT_STATUS or rate_limited >= RATE_LIMIT_MAX_RETRIES:
                raise
            rate_limited += 1
            sleeper(min(1.5 * 2 ** (rate_limited - 1), RATE_LIMIT_BACKOFF_CAP_SECONDS))


def fetch_award_history(
    client: ProcurementHistoryClient,
    *,
    company_name: str,
    max_rows: int = MAX_AWARD_ROWS,
    page_size: int = AWARD_PAGE_SIZE,
    sleeper: Callable[[float], None] = time.sleep,
) -> AwardHistory:
    """Page awards until Signal is exhausted or the declared cap is reached."""

    rows: list[dict[str, Any]] = []
    provider_total = 0
    provider_company_norm = ""
    offset = 0
    while len(rows) < max_rows:
        limit = min(page_size, max_rows - len(rows))
        payload = _call_waiting_out_rate_limit(
            partial(
                client.awards,
                company=company_name,
                buyer=None,
                limit=limit,
                offset=offset,
            ),
            sleeper,
        )
        page = payload.get("items")
        if not isinstance(page, list):
            raise ValueError("Signal devolvió adjudicaciones con un formato inesperado.")
        provider_total = max(provider_total, int(payload.get("total") or 0))
        provider_company_norm = _text(payload.get("company_norm"))
        accepted = [dict(item) for item in page if isinstance(item, dict)]
        rows.extend(accepted)
        offset += len(page)
        if not page or len(page) < limit or offset >= provider_total:
            break
        if len(rows) < max_rows:
            sleeper(PAGE_THROTTLE_SECONDS)
    return AwardHistory(
        rows=tuple(rows[:max_rows]),
        provider_total=provider_total,
        truncated=provider_total > len(rows[:max_rows]),
        provider_company_norm=provider_company_norm,
    )


def _group_contracts(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ignored = 0
    seen: set[bytes] = set()
    for row in rows:
        folder_id = _text(row.get("folder_id"))
        if not folder_id:
            ignored += 1
            continue
        signature = hashlib.sha256(_canonical(row)).digest()
        if signature in seen:
            continue
        seen.add(signature)
        grouped[folder_id].append(row)

    contracts: list[dict[str, Any]] = []
    for folder_id, entries in grouped.items():
        buyers = Counter(_text(item.get("buyer")) for item in entries if _text(item.get("buyer")))
        titles = Counter(_text(item.get("title")) for item in entries if _text(item.get("title")))
        winners = sorted(
            {_text(item.get("winner")) for item in entries if _text(item.get("winner"))},
            key=str.casefold,
        )
        cpv_codes = Counter(code for item in entries for code in _cpv_codes(item.get("cpv"))[:1])
        source_urls = sorted(
            {_text(item.get("source_url")) for item in entries if _text(item.get("source_url"))},
            key=str.casefold,
        )
        amounts = [
            amount for item in entries if (amount := _decimal(item.get("award_amount"))) is not None
        ]
        dates = sorted(
            parsed for item in entries if (parsed := _iso_date(item.get("award_date"))) is not None
        )
        contracts.append(
            {
                "folder_id": folder_id,
                "buyer": buyers.most_common(1)[0][0] if buyers else "Organismo no publicado",
                "title": titles.most_common(1)[0][0] if titles else "",
                "winner_variants": winners,
                "award_amount": sum(amounts, Decimal("0")) if amounts else None,
                "award_date": dates[-1] if dates else None,
                "is_ute": any(item.get("is_ute") is True for item in entries),
                "primary_cpv": (
                    sorted(cpv_codes.items(), key=lambda item: (-item[1], item[0]))[0][0]
                    if cpv_codes
                    else None
                ),
                "source_url": source_urls[0] if source_urls else None,
                "row_count": len(entries),
            }
        )
    contracts.sort(
        key=lambda item: (
            item["award_date"] or date.min,
            item["folder_id"],
        ),
        reverse=True,
    )
    return contracts, ignored


def _cpv_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        values = value
    elif isinstance(value, str):
        values = [value]
    else:
        return []
    return [text for item in values if (text := _text(item))]


def _distribution(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    values = sorted(
        amount for item in contracts if isinstance((amount := item["award_amount"]), Decimal)
    )
    count = len(values)
    buckets = (
        ("Menos de 50.000 €", None, Decimal("50000")),
        ("50.000-249.999 €", Decimal("50000"), Decimal("250000")),
        ("250.000-999.999 €", Decimal("250000"), Decimal("1000000")),
        ("1-4,99 M€", Decimal("1000000"), Decimal("5000000")),
        ("5 M€ o más", Decimal("5000000"), None),
    )
    bucket_rows = []
    for label, lower, upper in buckets:
        bucket_count = sum(
            1
            for value in values
            if (lower is None or value >= lower) and (upper is None or value < upper)
        )
        bucket_rows.append(
            {
                "label": label,
                "count": bucket_count,
                "denominator": count,
                "share_percent": _percent(
                    Decimal(bucket_count) * 100 / Decimal(count) if count else None
                ),
            }
        )
    total = sum(values, Decimal("0")) if values else None
    return {
        "contracts_with_amount": count,
        "contracts_without_amount": len(contracts) - count,
        "denominator_contracts": len(contracts),
        "total_awarded_eur": _money(total),
        "mean_awarded_eur": _money(total / Decimal(count) if total is not None and count else None),
        "median_awarded_eur": _money(median(values) if values else None),
        "minimum_awarded_eur": _money(values[0] if values else None),
        "maximum_awarded_eur": _money(values[-1] if values else None),
        "buckets": bucket_rows,
    }


def _buyer_concentration(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_buyer: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for contract in contracts:
        by_buyer[str(contract["buyer"])].append(contract)
    total_contracts = len(contracts)
    rows: list[dict[str, Any]] = []
    for buyer, items in by_buyer.items():
        amounts = sorted(
            amount for item in items if isinstance((amount := item["award_amount"]), Decimal)
        )
        total_amount = sum(amounts, Decimal("0")) if amounts else None
        rows.append(
            {
                "buyer": buyer,
                "contracts": len(items),
                "denominator_contracts": total_contracts,
                "contract_share_percent": _percent(
                    Decimal(len(items)) * 100 / Decimal(total_contracts)
                    if total_contracts
                    else None
                ),
                "contracts_with_amount": len(amounts),
                "total_awarded_eur": _money(total_amount),
                "median_awarded_eur": _money(median(amounts) if amounts else None),
            }
        )
    rows.sort(
        key=lambda item: (
            -int(item["contracts"]),
            -(Decimal(str(item["total_awarded_eur"])) if item["total_awarded_eur"] else Decimal(0)),
            str(item["buyer"]).casefold(),
        )
    )
    return rows[:20]


def _year_distribution(contracts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for contract in contracts:
        awarded_at = contract.get("award_date")
        if isinstance(awarded_at, date):
            by_year[awarded_at.year].append(contract)
    rows: list[dict[str, Any]] = []
    for year in sorted(by_year):
        items = by_year[year]
        amounts = [
            amount for item in items if isinstance((amount := item.get("award_amount")), Decimal)
        ]
        rows.append(
            {
                "year": year,
                "contracts": len(items),
                "contracts_with_amount": len(amounts),
                "contracts_without_amount": len(items) - len(amounts),
                "total_awarded_eur": _money(sum(amounts, Decimal("0")) if amounts else None),
            }
        )
    return rows


def _undated_awards(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    """Adjudicaciones que quedan fuera del desglose anual, con su importe.

    `_year_distribution` solo agrupa las que traen `award_date` como fecha válida, así
    que sin esto la suma de los años no cuadra con `total_awarded_eur` y el lector no
    tiene forma de saber por qué. Se declara el hueco en vez de esconderlo.
    """

    undated = [c for c in contracts if not isinstance(c.get("award_date"), date)]
    amounts = [
        amount for item in undated if isinstance((amount := item.get("award_amount")), Decimal)
    ]
    return {
        "contracts": len(undated),
        "contracts_with_amount": len(amounts),
        "total_awarded_eur": _money(sum(amounts, Decimal("0")) if amounts else None),
    }


def _cpv_distribution(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(code) for contract in contracts if (code := contract.get("primary_cpv")))
    denominator = sum(counts.values())
    return {
        "method": "primer CPV publicado por expediente; moda en adjudicaciones multilote",
        "contracts_with_primary_cpv": denominator,
        "contracts_without_primary_cpv": len(contracts) - denominator,
        "denominator_contracts": len(contracts),
        "items": [
            {
                "cpv": cpv,
                "contracts": count,
                "denominator_contracts_with_cpv": denominator,
                "share_percent": _percent(
                    Decimal(count) * 100 / Decimal(denominator) if denominator else None
                ),
            }
            for cpv, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
    }


def _partners_for_winner(winner: str, company_name: str) -> list[str]:
    company_core = _company_core(company_name)
    cleaned = _UTE_MARKERS.sub(" ", winner)
    partners: list[str] = []
    for raw in _PARTNER_SEPARATORS.split(cleaned):
        candidate = re.sub(r"\s+", " ", raw).strip(" .,:;()")
        normalized = _normalized_name(candidate)
        if (
            not candidate
            or not normalized
            or _LEGAL_ONLY.fullmatch(candidate)
            or (company_core and company_core in normalized)
        ):
            continue
        partners.append(candidate)
    return partners


def _ute_analysis(contracts: list[dict[str, Any]], company_name: str) -> dict[str, Any]:
    ute_contracts = [item for item in contracts if item["is_ute"]]
    partner_counts: Counter[str] = Counter()
    partner_labels: dict[str, str] = {}
    parsed_contracts = 0
    for contract in ute_contracts:
        contract_partners: set[str] = set()
        for winner in contract["winner_variants"]:
            for partner in _partners_for_winner(winner, company_name):
                key = _normalized_name(partner)
                if key:
                    partner_labels.setdefault(key, partner)
                    contract_partners.add(key)
        if contract_partners:
            parsed_contracts += 1
            partner_counts.update(contract_partners)
    return {
        "method": "heuristic_free_text_winner_v1",
        "verified": False,
        "confidence": "low",
        "warning": (
            "Los socios se infieren por separación conservadora del texto libre winner; "
            "no son entidades estructuradas ni verificadas."
        ),
        "ute_contracts": len(ute_contracts),
        "denominator_contracts": len(contracts),
        "ute_share_percent": _percent(
            Decimal(len(ute_contracts)) * 100 / Decimal(len(contracts)) if contracts else None
        ),
        "parsed_ute_contracts": parsed_contracts,
        "unparsed_ute_contracts": len(ute_contracts) - parsed_contracts,
        "partners": [
            {
                "name": partner_labels[key],
                "contracts": count,
                "denominator_ute_contracts": len(ute_contracts),
            }
            for key, count in partner_counts.most_common(20)
        ],
    }


def _analysis_from_history(
    history: AwardHistory,
    *,
    company_name: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contracts, ignored_rows = _group_contracts(history.rows)
    dated = sorted(item["award_date"] for item in contracts if isinstance(item["award_date"], date))
    winner_counts: Counter[str] = Counter()
    for contract in contracts:
        winner_counts.update(set(contract["winner_variants"]))
    return (
        {
            "schema": "competitive-procurement-analysis-v1",
            "company_requested": company_name,
            "company_normalized_by_signal": history.provider_company_norm,
            "scope_warning": (
                "El corpus contiene adjudicaciones publicadas, no todas las ofertas presentadas. "
                "No permite saber dónde compitió sin resultar adjudicatario ni calcular una tasa "
                "de éxito."
            ),
            "identity_warning": (
                "Signal normaliza la consulta por nombre y puede incluir variantes registrales "
                "o UTE. Oracle no dispone de CIF para desambiguar ni afirma identidad jurídica "
                "entre variantes u homónimos."
            ),
            "corpus": {
                "source": "Signal Avanza · histórico PLACSP de adjudicaciones",
                "pagination": "limit/offset",
                "provider_total_rows": history.provider_total,
                "analyzed_rows": len(history.rows),
                "row_cap": MAX_AWARD_ROWS,
                "truncated": history.truncated,
                "unique_contracts": len(contracts),
                "ignored_rows_without_folder_id": ignored_rows,
                "period_start": dated[0].isoformat() if dated else None,
                "period_end": dated[-1].isoformat() if dated else None,
                "dated_contracts": len(dated),
                "denominator_contracts": len(contracts),
            },
            "winner_variants": [
                {"winner": winner, "contracts": count}
                for winner, count in winner_counts.most_common(20)
            ],
            "awards_by_year": _year_distribution(contracts),
            "awards_without_date": _undated_awards(contracts),
            "buyer_concentration": _buyer_concentration(contracts),
            "amount_distribution": _distribution(contracts),
            "primary_cpv_distribution": _cpv_distribution(contracts),
            "ute_partners": _ute_analysis(contracts, company_name),
        },
        contracts,
    )


def _citable_award_sample(
    contracts: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    sourceable = [contract for contract in contracts if contract.get("source_url")]
    sourceable.sort(
        key=lambda item: (
            isinstance(item.get("award_amount"), Decimal),
            item.get("award_amount")
            if isinstance(item.get("award_amount"), Decimal)
            else Decimal("-1"),
            item.get("award_date") if isinstance(item.get("award_date"), date) else date.min,
            str(item.get("folder_id")),
        ),
        reverse=True,
    )
    return [
        {
            "folder_id": str(contract["folder_id"]),
            "title": str(contract.get("title") or ""),
            "buyer": str(contract["buyer"]),
            "winner": " · ".join(str(value) for value in contract["winner_variants"]),
            "award_amount": _money(
                contract["award_amount"]
                if isinstance(contract.get("award_amount"), Decimal)
                else None
            ),
            "award_date": (
                contract["award_date"].isoformat()
                if isinstance(contract.get("award_date"), date)
                else None
            ),
            "primary_cpv": contract.get("primary_cpv"),
            "is_ute": bool(contract.get("is_ute")),
            "source_url": str(contract["source_url"]),
            "row_count": int(contract["row_count"]),
        }
        for contract in sourceable[: max(0, limit)]
    ]


def build_entity_procurement_analysis(
    client: ProcurementHistoryClient,
    *,
    company_name: str,
    source_limit: int,
    max_rows: int = MAX_AWARD_ROWS,
    page_size: int = AWARD_PAGE_SIZE,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Build entity-report aggregates and a bounded citable sample without tender probes."""

    history = fetch_award_history(
        client,
        company_name=company_name,
        max_rows=max_rows,
        page_size=page_size,
        sleeper=sleeper,
    )
    analysis, contracts = _analysis_from_history(history, company_name=company_name)
    analysis["corpus"]["row_cap"] = max_rows
    sources = _citable_award_sample(contracts, limit=source_limit)
    sourceable_contracts = sum(1 for item in contracts if item.get("source_url"))
    return {
        "computed_metrics": analysis,
        "award_sources": sources,
        "source_sampling": {
            "limit": source_limit,
            "selected": len(sources),
            "total_contracts": len(contracts),
            "sourceable_contracts": sourceable_contracts,
            "contracts_without_source_url": len(contracts) - sourceable_contracts,
            "truncated_by_oracle": sourceable_contracts > len(sources),
            "selection": "mayor importe adjudicado; desempate por fecha y folder_id",
        },
    }


def _tender_item(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("item")
    return item if isinstance(item, dict) else payload


def _discount_coverage(
    client: ProcurementHistoryClient,
    contracts: list[dict[str, Any]],
    *,
    probe_max: int = DISCOUNT_PROBE_MAX,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    # Sonda determinista: los contratos más recientes primero (los comercialmente
    # relevantes), con desempate estable por folder_id.
    probed = sorted(
        contracts,
        key=lambda item: (
            item["award_date"] if isinstance(item["award_date"], date) else date.min,
            str(item["folder_id"]),
        ),
        reverse=True,
    )[: max(probe_max, 0)]
    observed: list[Decimal] = []
    reasons = Counter[str]()
    for index, contract in enumerate(probed):
        if index:
            sleeper(PAGE_THROTTLE_SECONDS)
        try:
            payload = _call_waiting_out_rate_limit(
                partial(client.tender_by_folder, folder_id=str(contract["folder_id"])),
                sleeper,
            )
        except ProcurementProviderError as error:
            if error.status_code == 404:
                reasons["tender_not_found"] += 1
                continue
            raise
        initial = _decimal(_tender_item(payload).get("amount"))
        awarded = contract["award_amount"]
        if initial is None or initial <= 0:
            reasons["tender_amount_missing"] += 1
            continue
        if not isinstance(awarded, Decimal):
            reasons["award_amount_missing"] += 1
            continue
        observed.append((initial - awarded) * 100 / initial)

    total = len(probed)
    computable = len(observed)
    coverage = Decimal(computable) / Decimal(total) if total else Decimal("0")
    publishable = coverage >= MIN_DISCOUNT_COVERAGE and computable >= MIN_DISCOUNT_SAMPLE
    unavailable = total - computable
    sampled = len(contracts) > total
    reason = None
    if not publishable:
        scope = (
            f"las {total} adjudicaciones más recientes de {len(contracts)} del corpus"
            if sampled
            else f"{total} adjudicaciones del corpus acotado"
        )
        reason = (
            "No se publica una baja media: solo "
            f"{computable} de {scope} "
            "tienen importe inicial y adjudicado comparables; calcularla sobre ese "
            "subconjunto introduciría sesgo de supervivencia."
        )
    return {
        "computable": publishable,
        "computed_contracts": computable,
        "not_computable_contracts": unavailable,
        "denominator_contracts": total,
        "probe_cap": probe_max,
        "probed_contracts": total,
        "unprobed_contracts": len(contracts) - total,
        "probe_sampled": sampled,
        "coverage_percent": _percent(coverage * 100),
        "minimum_coverage_percent": _percent(MIN_DISCOUNT_COVERAGE * 100),
        "minimum_sample": MIN_DISCOUNT_SAMPLE,
        "mean_discount_percent": _percent(
            sum(observed, Decimal("0")) / Decimal(computable)
            if publishable and computable
            else None
        ),
        "median_discount_percent": _percent(median(observed) if publishable else None),
        "non_computable_reasons": {
            "tender_not_found": reasons["tender_not_found"],
            "tender_amount_missing": reasons["tender_amount_missing"],
            "award_amount_missing": reasons["award_amount_missing"],
        },
        "reason": reason,
    }


def build_competitive_procurement_analysis(
    client: ProcurementHistoryClient,
    *,
    company_name: str,
    max_rows: int = MAX_AWARD_ROWS,
    page_size: int = AWARD_PAGE_SIZE,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    history = fetch_award_history(
        client,
        company_name=company_name,
        max_rows=max_rows,
        page_size=page_size,
        sleeper=sleeper,
    )
    analysis, contracts = _analysis_from_history(history, company_name=company_name)
    analysis["corpus"]["row_cap"] = max_rows
    analysis["discount_coverage"] = _discount_coverage(client, contracts, sleeper=sleeper)
    return analysis


def analysis_evidence_extract(analysis: dict[str, Any]) -> str:
    """Build a citable, deterministic synopsis of the Python calculations."""

    corpus = analysis["corpus"]
    amounts = analysis["amount_distribution"]
    discount = analysis["discount_coverage"]
    buyers = analysis["buyer_concentration"]
    top_buyer = buyers[0] if buyers else None
    return (
        f"Análisis competitivo PLACSP calculado por Oracle para "
        f"{analysis['company_requested']}. Corpus: {corpus['analyzed_rows']} filas de "
        f"{corpus['provider_total_rows']} disponibles, {corpus['unique_contracts']} expedientes "
        f"únicos, periodo {corpus['period_start'] or 'no disponible'} a "
        f"{corpus['period_end'] or 'no disponible'}, truncado={corpus['truncated']}. "
        f"Importes conocidos: {amounts['contracts_with_amount']} de "
        f"{amounts['denominator_contracts']}; mediana adjudicada "
        f"{amounts['median_awarded_eur'] or 'no calculable'} EUR. "
        f"Primer organismo por frecuencia: "
        f"{top_buyer['buyer'] if top_buyer else 'no disponible'} "
        f"({top_buyer['contracts'] if top_buyer else 0} de "
        f"{top_buyer['denominator_contracts'] if top_buyer else 0}). "
        f"Cobertura de baja: {discount['computed_contracts']} de "
        f"{discount['denominator_contracts']} ({discount['coverage_percent']} %); "
        f"media publicada={discount['mean_discount_percent'] or 'no calculable'}. "
        f"Alcance: {analysis['scope_warning']} "
        "Los socios UTE son una inferencia heurística sobre texto libre y no un dato verificado."
    )
