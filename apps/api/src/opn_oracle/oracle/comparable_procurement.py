"""Deterministic comparable-company profile and temporal evaluation.

The profile is measured from Signal award rows.  It does not call an LLM, infer
regions, repair dates or persist a second company profile.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from opn_oracle.oracle.competitive_procurement import (
    AWARD_PAGE_SIZE,
    AwardHistory,
    ProcurementHistoryClient,
    _buyer_concentration,
    _company_core,
    _cpv_codes,
    _distribution,
    _group_contracts,
    _iso_date,
    _normalized_name,
    _percent,
    _text,
    _ute_analysis,
    fetch_award_history,
    pinned_award_winners,
)
from opn_oracle.oracle.cpv_taxonomy import (
    CPVTaxonomy,
    fold_search_text,
    load_cpv_taxonomy,
    normalize_cpv_code,
)

COMPARABLE_PROFILE_SCHEMA = "procurement-comparable-profile-v1"
COMPARABLE_EVALUATION_SCHEMA = "procurement-comparable-evaluation-v1"
COMPARABLE_PROFILE_MAX_ROWS = 2_000
COMPARABLE_PROFILE_TOP_CPV = 30
COMPARABLE_PROFILE_TOP_TERMS = 30
TITLE_TERM_METHOD_VERSION = "spanish-procurement-stopwords-v1"

_TITLE_TOKEN = re.compile(r"[a-z0-9]+")
_TITLE_STOPWORDS = frozenset(
    {
        "abierto",
        "abierta",
        "abiertos",
        "abiertas",
        "adjudicacion",
        "adquisicion",
        "administrativo",
        "administrativa",
        "administrativos",
        "administrativas",
        "asi",
        "ayuntamiento",
        "basado",
        "centro",
        "centros",
        "con",
        "contratacion",
        "contrato",
        "contratos",
        "del",
        "desde",
        "durante",
        "ejecucion",
        "entidad",
        "expediente",
        "general",
        "hasta",
        "los",
        "las",
        "lote",
        "lotes",
        "mediante",
        "para",
        "por",
        "procedimiento",
        "publica",
        "publico",
        "publicas",
        "publicos",
        "realizacion",
        "servicio",
        "servicios",
        "suministro",
        "suministros",
        "una",
        "uno",
        "unos",
        "unas",
        "obra",
        "obras",
        "objeto",
        "acuerdo",
        "marco",
        "municipal",
        "municipales",
        "mixto",
        "mixta",
        "incluido",
        "incluida",
        "incluidos",
        "incluidas",
        "correspondiente",
        "correspondientes",
    }
)


def _fold_text(value: str) -> str:
    return fold_search_text(value)


def title_terms(value: Any) -> frozenset[str]:
    """Return unique deterministic search terms for one award title."""

    folded = _fold_text(_text(value))
    return frozenset(
        token
        for token in _TITLE_TOKEN.findall(folded)
        if len(token) >= 3 and not token.isdigit() and token not in _TITLE_STOPWORDS
    )


def _title_term_distribution(
    contracts: Iterable[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    contract_list = list(contracts)
    counts: Counter[str] = Counter()
    titles_with_terms = 0
    for contract in contract_list:
        terms = title_terms(contract.get("title"))
        if terms:
            titles_with_terms += 1
            counts.update(terms)
    return {
        "method": "presencia por expediente sobre título normalizado",
        "method_version": TITLE_TERM_METHOD_VERSION,
        "denominator_contracts": len(contract_list),
        "contracts_with_terms": titles_with_terms,
        "contracts_without_terms": len(contract_list) - titles_with_terms,
        "items": [
            {
                "term": term,
                "contracts": count,
                "denominator_contracts": len(contract_list),
                "share_percent": _percent(
                    Decimal(count) * 100 / Decimal(len(contract_list)) if contract_list else None
                ),
            }
            for term, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                : max(0, limit)
            ]
        ],
    }


def _cpv_distribution(
    contracts: Iterable[dict[str, Any]],
    *,
    taxonomy: CPVTaxonomy,
    limit: int,
) -> dict[str, Any]:
    contract_list = list(contracts)
    counts: Counter[str] = Counter()
    raw_examples: dict[str, set[str]] = defaultdict(set)
    invalid: Counter[str] = Counter()
    for contract in contract_list:
        raw = contract.get("primary_cpv")
        observed = next(iter(_cpv_codes(raw)), None)
        code = normalize_cpv_code(observed)
        if code is None:
            if raw is not None:
                invalid[_text(raw)] += 1
            continue
        counts[code] += 1
        raw_examples[code].add(_text(raw))

    contracts_with_cpv = sum(counts.values())
    mapped_contracts = sum(count for code, count in counts.items() if code in taxonomy.codes)
    return {
        "method": "CPV principal por expediente; normalización exacta de 8 dígitos",
        "signal_format_observed": "XXXXXXXX",
        "taxonomy": {
            "version": taxonomy.version,
            "language": taxonomy.language,
            "source_uri": taxonomy.source_uri,
            "downloaded_at": taxonomy.downloaded_at,
            "code_count": len(taxonomy.codes),
        },
        "denominator_contracts": len(contract_list),
        "contracts_with_normalized_cpv": contracts_with_cpv,
        "contracts_without_normalized_cpv": len(contract_list) - contracts_with_cpv,
        "contracts_with_taxonomy_label": mapped_contracts,
        "invalid_or_unrecognized": [
            {"raw_value": raw, "contracts": count}
            for raw, count in sorted(invalid.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
        "items": [
            {
                "code": code,
                "label": taxonomy.codes.get(code),
                "taxonomy_match": code in taxonomy.codes,
                "contracts": count,
                "denominator_contracts": len(contract_list),
                "share_percent": _percent(
                    Decimal(count) * 100 / Decimal(len(contract_list)) if contract_list else None
                ),
                "raw_examples": sorted(raw_examples[code]),
            }
            for code, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[
                : max(0, limit)
            ]
        ],
    }


def _raw_date_window(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    dated: list[tuple[date, str]] = []
    missing = 0
    invalid: Counter[str] = Counter()
    for row in rows:
        raw = _text(row.get("award_date"))
        if not raw:
            missing += 1
            continue
        parsed = _iso_date(raw)
        if parsed is None:
            invalid[raw] += 1
            continue
        dated.append((parsed, raw))
    dated.sort(key=lambda item: (item[0], item[1]))
    return {
        "method": "mínimo y máximo de fechas válidas tal como las publicó Signal; sin imputación",
        "raw_observed_start": dated[0][1] if dated else None,
        "raw_observed_end": dated[-1][1] if dated else None,
        "rows_with_valid_date": len(dated),
        "rows_without_date": missing,
        "rows_with_invalid_date": sum(invalid.values()),
        "invalid_date_examples": [
            {"raw_value": raw, "rows": count}
            for raw, count in sorted(invalid.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
    }


def profile_from_history(
    history: AwardHistory,
    *,
    company_name: str,
    taxonomy: CPVTaxonomy | None = None,
    row_cap: int = COMPARABLE_PROFILE_MAX_ROWS,
    measured_at: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate a comparable profile from a previously fetched award history."""

    resolved_taxonomy = taxonomy or load_cpv_taxonomy()
    measurement_instant = measured_at or datetime.now(UTC)
    if measurement_instant.tzinfo is None:
        raise ValueError("measured_at debe incluir zona horaria.")
    contracts, ignored_rows = _group_contracts(history.rows)
    return {
        "schema": COMPARABLE_PROFILE_SCHEMA,
        "measured_at": measurement_instant.astimezone(UTC).isoformat(),
        "company_requested": company_name,
        "company_normalized_by_signal": history.provider_company_norm,
        "identity_basis": {
            "oracle_normalized_name": _normalized_name(company_name),
            "oracle_company_core": _company_core(company_name),
            "legal_identity_verified": False,
        },
        "measurement_contract": {
            "source": "Signal Avanza · histórico PLACSP de adjudicaciones",
            "unit": "expediente adjudicado agregado por folder_id",
            "fields_used": [
                "award_amount",
                "award_date",
                "buyer",
                "cpv",
                "folder_id",
                "is_ute",
                "source_url",
                "title",
                "winner",
            ],
            "llm_calls": 0,
            "regions_inferred": False,
            "dates_repaired": False,
        },
        "corpus": {
            "provider_total_rows": history.provider_total,
            "analyzed_rows": len(history.rows),
            "row_cap": row_cap,
            "truncated": history.truncated,
            "aggregated_contracts": len(contracts),
            "ignored_rows_without_folder_id": ignored_rows,
        },
        "award_date_window": _raw_date_window(history.rows),
        "frequent_cpvs": _cpv_distribution(
            contracts,
            taxonomy=resolved_taxonomy,
            limit=COMPARABLE_PROFILE_TOP_CPV,
        ),
        "buyers": _buyer_concentration(contracts),
        "amount_distribution": _distribution(contracts),
        "title_terms": _title_term_distribution(
            contracts,
            limit=COMPARABLE_PROFILE_TOP_TERMS,
        ),
        "ute_participation": _ute_analysis(contracts, company_name),
    }


def build_comparable_profile(
    client: ProcurementHistoryClient,
    *,
    company_name: str,
    max_rows: int = COMPARABLE_PROFILE_MAX_ROWS,
    page_size: int = AWARD_PAGE_SIZE,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch and aggregate one deterministic comparable-company profile."""

    history = fetch_award_history(
        client,
        company_name=company_name,
        max_rows=max_rows,
        page_size=page_size,
        sleeper=sleeper,
    )
    return profile_from_history(history, company_name=company_name, row_cap=max_rows)


def comparable_names_from_pinned_awards(items: Iterable[Any]) -> tuple[str, ...]:
    """Offer exact observed winner labels as comparable candidates for later UI."""

    return pinned_award_winners(items)


def evaluate_comparable_history(
    history: AwardHistory,
    *,
    company_name: str,
    cpv_top_k: int = 20,
    term_top_k: int = 20,
) -> dict[str, Any]:
    """Evaluate plan recovery on the newest 20% of dated known awards."""

    contracts, ignored_rows = _group_contracts(history.rows)
    dated_contracts = [
        contract for contract in contracts if isinstance(contract.get("award_date"), date)
    ]
    dated_contracts.sort(key=lambda item: (item["award_date"], str(item["folder_id"])))
    undated_contracts = len(contracts) - len(dated_contracts)

    if len(dated_contracts) < 2:
        train_size = len(dated_contracts)
    else:
        train_size = min(len(dated_contracts) - 1, max(1, int(len(dated_contracts) * 0.8)))
    training = dated_contracts[:train_size]
    holdout = dated_contracts[train_size:]

    taxonomy = load_cpv_taxonomy()
    cpv_profile = _cpv_distribution(training, taxonomy=taxonomy, limit=cpv_top_k)
    term_profile = _title_term_distribution(training, limit=term_top_k)
    ranked_cpvs = [str(item["code"]) for item in cpv_profile["items"]]
    ranked_terms = [str(item["term"]) for item in term_profile["items"]]
    top_cpvs = set(ranked_cpvs)
    top_terms = set(ranked_terms)

    cpv_hits = 0
    term_hits = 0
    combined_hits = 0
    holdout_with_cpv = 0
    holdout_with_terms = 0
    for contract in holdout:
        observed_cpv = next(iter(_cpv_codes(contract.get("primary_cpv"))), None)
        cpv = normalize_cpv_code(observed_cpv)
        terms = title_terms(contract.get("title"))
        if cpv is not None:
            holdout_with_cpv += 1
        if terms:
            holdout_with_terms += 1
        cpv_hit = cpv in top_cpvs if cpv is not None else False
        term_hit = bool(terms & top_terms)
        cpv_hits += int(cpv_hit)
        term_hits += int(term_hit)
        combined_hits += int(cpv_hit or term_hit)

    denominator = len(holdout)

    def metric(hits: int) -> dict[str, Any]:
        return {
            "hits": hits,
            "denominator_holdout_contracts": denominator,
            "recall_percent": _percent(
                Decimal(hits) * 100 / Decimal(denominator) if denominator else None
            ),
        }

    raw_dates = _raw_date_window(history.rows)
    return {
        "schema": COMPARABLE_EVALUATION_SCHEMA,
        "company_requested": company_name,
        "company_normalized_by_signal": history.provider_company_norm,
        "corpus": {
            "provider_total_rows": history.provider_total,
            "analyzed_rows": len(history.rows),
            "truncated": history.truncated,
            "aggregated_contracts": len(contracts),
            "ignored_rows_without_folder_id": ignored_rows,
            "dated_contracts": len(dated_contracts),
            "undated_contracts_excluded_from_split": undated_contracts,
            "rows_without_date": raw_dates["rows_without_date"],
            "rows_with_invalid_date": raw_dates["rows_with_invalid_date"],
        },
        "temporal_split": {
            "method": "80% más antiguo para entrenamiento; 20% más reciente para holdout",
            "training_contracts": len(training),
            "holdout_contracts": len(holdout),
            "training_start": (training[0]["award_date"].isoformat() if training else None),
            "training_end": (training[-1]["award_date"].isoformat() if training else None),
            "holdout_start": holdout[0]["award_date"].isoformat() if holdout else None,
            "holdout_end": holdout[-1]["award_date"].isoformat() if holdout else None,
        },
        "plan": {
            "cpv_top_k": cpv_top_k,
            "term_top_k": term_top_k,
            "cpvs": ranked_cpvs,
            "terms": ranked_terms,
            "title_term_method_version": TITLE_TERM_METHOD_VERSION,
        },
        "holdout_observability": {
            "contracts_with_cpv": holdout_with_cpv,
            "contracts_with_title_terms": holdout_with_terms,
        },
        "recall": {
            "cpv": metric(cpv_hits),
            "terms": metric(term_hits),
            "combined": metric(combined_hits),
        },
    }
