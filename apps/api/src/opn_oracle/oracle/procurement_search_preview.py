"""Deterministic translation of an accepted tender-search plan.

Signal v1 does not expose a global boolean-query contract or global ordering.
Preview keeps bounded probes independent; execution merges unique tenders into
a useful, explicitly Oracle-ranked table without claiming provider-global rank.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from opn_oracle.integrations.procurement import tender_is_pending_open
from opn_oracle.oracle.cpv_retrieval import (
    cpv_label_relevance,
    procurement_text_tokens,
    procurement_token_weight,
    rank_cpv_candidates,
)

TERM_PROBE_LIMIT = 4
CPV_PROBE_LIMIT = 4
TOTAL_PROBE_LIMIT = TERM_PROBE_LIMIT + CPV_PROBE_LIMIT
PREVIEW_RESULT_LIMIT = 20
EXECUTION_RESULT_WINDOW_LIMIT = 100
TRANSLATION_VERSION = "tender-search-plan-to-signal-v3"
PRECISION_FILTER_VERSION = "procurement-intent-precision-v1"

_CLOTHING_INTENT_TOKENS = frozenset(
    {
        "calzado",
        "laboral",
        "prenda",
        "prendas",
        "ropa",
        "textil",
        "textiles",
        "uniforme",
        "uniformes",
        "vestuario",
    }
)
_FACILITY_INTENT_TOKENS = frozenset(
    {
        "acondicionamiento",
        "construccion",
        "deportiva",
        "deportivas",
        "instalacion",
        "instalaciones",
        "mejora",
        "pabellon",
        "piscina",
        "polideportivo",
        "reforma",
        "vestuarios",
    }
)
_SPORTS_FACILITY_TOKENS = frozenset(
    {"instalacion", "instalaciones", "pabellon", "piscina", "polideportivo"}
)


class SearchPlanExecutionError(ValueError):
    """A valid plan cannot be represented honestly by the current provider."""


@dataclass(frozen=True, slots=True)
class SearchProbe:
    kind: str
    value: str
    label: str | None = None


TenderLoader = Callable[..., dict[str, Any]]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _cpv_candidates(value: Any) -> list[SearchProbe]:
    if not isinstance(value, list):
        return []
    probes: list[SearchProbe] = []
    seen_codes: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        label = item.get("label")
        if isinstance(code, str) and code and code not in seen_codes:
            seen_codes.add(code)
            probes.append(
                SearchProbe(
                    kind="cpv",
                    value=code,
                    label=label if isinstance(label, str) else None,
                )
            )
    return probes


def _all_search_probes(plan: dict[str, Any]) -> tuple[list[SearchProbe], list[SearchProbe]]:
    term_values = [*_strings(plan.get("include_terms")), *_strings(plan.get("synonyms"))]
    seen_terms: set[str] = set()
    term_probes: list[SearchProbe] = []
    for term in term_values:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        term_probes.append(SearchProbe(kind="term", value=term))

    return term_probes, _cpv_candidates(plan.get("candidate_cpv"))


def _plan_text(plan: dict[str, Any]) -> str:
    values = [
        plan.get("intent_summary"),
        *_strings(plan.get("include_terms")),
        *_strings(plan.get("synonyms")),
    ]
    return " ".join(value for value in values if isinstance(value, str))


def _item_cpv_codes(item: dict[str, Any]) -> list[str]:
    raw = item.get("cpv")
    if raw is None:
        raw = item.get("cpvs")
    values = raw if isinstance(raw, list) else [raw]
    codes: list[str] = []
    for value in values:
        if isinstance(value, str):
            code_value: Any = value
        elif isinstance(value, dict):
            code_value = value.get("code")
        else:
            continue
        if isinstance(code_value, str) and code_value.strip():
            codes.append(code_value.strip())
    return codes


def _precision_exclusion_reason(plan: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Reject only a clear clothing-vs-building sense mismatch.

    ``vestuario`` singular is a common clothing query in procurement. A title using
    plural ``vestuarios`` is not rejected on that fact alone: it also needs a sports
    facility marker or a construction CPV plus facility language. Explicit facility
    intent in the plan always wins and disables this narrow guard.
    """

    plan_tokens = procurement_text_tokens(_plan_text(plan))
    clothing_intent = bool(plan_tokens & _CLOTHING_INTENT_TOKENS)
    facility_intent = bool(plan_tokens & _FACILITY_INTENT_TOKENS)
    if not clothing_intent or facility_intent:
        return None

    title = item.get("title") or item.get("name") or ""
    title_tokens = procurement_text_tokens(str(title))
    facility_tokens = title_tokens & _FACILITY_INTENT_TOKENS
    construction_cpv = any(code.startswith("45") for code in _item_cpv_codes(item))
    plural_with_facility = "vestuarios" in title_tokens and bool(
        title_tokens & _SPORTS_FACILITY_TOKENS
    )
    construction_facility = construction_cpv and len(facility_tokens) >= 2
    if plural_with_facility or construction_facility:
        return "intent_mismatch_clothing_vs_facility"
    return None


def _cpv_probe_score(probe: SearchProbe, plan: dict[str, Any]) -> float:
    if probe.kind != "cpv" or not probe.label:
        return 0.0
    return cpv_label_relevance(procurement_text_tokens(_plan_text(plan)), probe.label)


def _ordered_cpv_probes(
    cpv_probes: list[SearchProbe],
    plan: dict[str, Any],
) -> list[SearchProbe]:
    probes_by_code = {probe.value: probe for probe in cpv_probes}
    ranked = rank_cpv_candidates(
        [{"code": probe.value, "label": probe.label} for probe in cpv_probes],
        text=_plan_text(plan),
        prefer_specific_ties=False,
    )
    return [probes_by_code[candidate["code"]] for candidate in ranked]


def build_search_probes(plan: dict[str, Any]) -> tuple[list[SearchProbe], list[SearchProbe]]:
    """Select visible top-N chips and return selected/skipped probes."""

    term_probes, cpv_probes = _all_search_probes(plan)
    cpv_probes = _ordered_cpv_probes(cpv_probes, plan)
    selected = [
        *term_probes[:TERM_PROBE_LIMIT],
        *cpv_probes[:CPV_PROBE_LIMIT],
    ]
    skipped = [
        *term_probes[TERM_PROBE_LIMIT:],
        *cpv_probes[CPV_PROBE_LIMIT:],
    ]
    if not selected:
        raise SearchPlanExecutionError(
            "El plan necesita al menos un término o un CPV válido para obtener una vista previa."
        )
    return selected, skipped


def _scope(plan: dict[str, Any]) -> tuple[str, bool]:
    scope = plan.get("scope")
    if scope == "historical":
        raise SearchPlanExecutionError(
            "Signal v1 no permite aislar licitaciones históricas. "
            "El histórico disponible se consulta por adjudicaciones."
        )
    if scope == "all":
        return "all", False
    if scope == "active":
        return "active", True
    raise SearchPlanExecutionError("El ámbito temporal del plan no es válido.")


def preview_search_plan(
    *,
    tenant_id: str,
    plan: dict[str, Any],
    tender_loader: TenderLoader,
    result_limit: int = PREVIEW_RESULT_LIMIT,
) -> dict[str, Any]:
    """Execute bounded independent probes with zero LLM calls."""

    scope, active = _scope(plan)
    selected, skipped = build_search_probes(plan)
    min_amount = plan.get("min_amount")
    max_amount = plan.get("max_amount")
    blocks: list[dict[str, Any]] = []
    for probe in selected:
        query = {
            "keywords": probe.value if probe.kind == "term" else None,
            "cpv": probe.value if probe.kind == "cpv" else None,
            "min_amount": str(min_amount) if min_amount is not None else None,
            "max_amount": str(max_amount) if max_amount is not None else None,
            "deadline_before": None,
            "buyer": None,
            "region": None,
            "active": active,
            "scope": scope,
            "limit": result_limit,
            "offset": 0,
        }
        result = tender_loader(tenant_id=tenant_id, **query)
        if scope == "active" and isinstance(result, dict):
            raw_items = result.get("items")
            if isinstance(raw_items, list):
                kept = [
                    item
                    for item in raw_items
                    if isinstance(item, dict) and tender_is_pending_open(item)
                ]
                result = {**result, "items": kept}
        blocks.append(
            {
                "chip": {
                    "kind": probe.kind,
                    "value": probe.value,
                    "label": probe.label,
                },
                "query": query,
                "total": int(result.get("total") or 0) if isinstance(result, dict) else 0,
                "result": result,
            }
        )

    return {
        "translation_version": TRANSLATION_VERSION,
        "scope": scope,
        "provider_requests": len(blocks),
        "probe_budget": {
            "total": TOTAL_PROBE_LIMIT,
            "term_limit": TERM_PROBE_LIMIT,
            "cpv_limit": CPV_PROBE_LIMIT,
            "selected": len(selected),
            "skipped": len(skipped),
        },
        "probes": blocks,
        "unprobed_chips": [
            {"kind": probe.kind, "value": probe.value, "label": probe.label} for probe in skipped
        ],
        "semantics": {
            "global_order": False,
            "merged_results": False,
            "keyword_blocks": "una consulta independiente por término",
            "exclude_terms_applied": False,
            "buyers_applied": False,
            "geographies_applied": False,
            "limitations": [
                "Los bloques conservan por separado el orden nativo de Signal.",
                "Las exclusiones no se envían: Signal v1 no ofrece un contrato NOT demostrado.",
                "No se aplica comprador ni geografía: su matching estricto elimina recall.",
            ],
        },
    }


def _primary_cpv(cpvs: list[SearchProbe], plan: dict[str, Any]) -> SearchProbe | None:
    if not cpvs:
        return None
    return _ordered_cpv_probes(cpvs, plan)[0]


def _execution_search_probes(
    plan: dict[str, Any],
) -> tuple[list[SearchProbe], list[SearchProbe]]:
    """Apply the execution budget after promoting high-value CPVs."""

    term_probes, cpv_probes = _all_search_probes(plan)
    ordered_cpvs = _ordered_cpv_probes(cpv_probes, plan)
    selected = [
        *term_probes[:TERM_PROBE_LIMIT],
        *ordered_cpvs[:CPV_PROBE_LIMIT],
    ]
    skipped = [
        *term_probes[TERM_PROBE_LIMIT:],
        *ordered_cpvs[CPV_PROBE_LIMIT:],
    ]
    if not selected:
        raise SearchPlanExecutionError(
            "El plan necesita al menos un término o un CPV válido para ejecutar la búsqueda."
        )
    return selected, skipped


def _watch_keywords(plan: dict[str, Any], *, primary_cpv: SearchProbe | None) -> list[str]:
    """Keep one high-signal term so the durable watch remains focused."""

    terms = [*_strings(plan.get("include_terms")), *_strings(plan.get("synonyms"))]
    terms = list(dict.fromkeys(term.strip() for term in terms if term.strip()))
    if terms:
        indexed = list(enumerate(terms))
        indexed.sort(
            key=lambda item: (
                -max(
                    (procurement_token_weight(token) for token in procurement_text_tokens(item[1])),
                    default=0.0,
                ),
                item[0],
            )
        )
        return [indexed[0][1][:120]]
    if primary_cpv and primary_cpv.label:
        # Fallback from official CPV label (first substantial token).
        for token in primary_cpv.label.replace(",", " ").split():
            clean = token.strip()
            if len(clean) >= 5:
                return [clean[:120]]
    if primary_cpv:
        return [primary_cpv.value]
    raise SearchPlanExecutionError(
        "Signal v1 exige al menos un término o CPV para guardar una vigilancia."
    )


def saved_search_payload(*, name: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Translate one accepted plan to the bounded Signal v1 saved-search contract.

    The durable watch is intentionally narrow (1 keyword + 1 CPV). Showing the
    full plan result set uses :func:`execute_search_plan` multi-probe merge.
    """

    scope, _active = _scope(plan)
    if scope == "historical":
        raise SearchPlanExecutionError(
            "Signal v1 solo conserva búsquedas guardadas de licitaciones activas."
        )
    cpvs = _cpv_candidates(plan.get("candidate_cpv"))
    primary = _primary_cpv(cpvs, plan)
    keywords = _watch_keywords(plan, primary_cpv=primary)
    filters: dict[str, Any] = {"scope": "active"}
    if primary is not None:
        filters["cpv"] = primary.value
    # Buyers/geographies del plan no se proyectan: matching estricto de Signal
    # con instituciones genéricas de la IA (p. ej. «Ministerio de Defensa»)
    # devuelve 0 aunque existan pliegos de parques/mandos.
    if plan.get("min_amount") is not None:
        filters["min_amount"] = str(plan["min_amount"])
    if plan.get("max_amount") is not None:
        filters["max_amount"] = str(plan["max_amount"])
    clean_name = " ".join(str(name).split())[:120].strip() or "Búsqueda Oracle"
    return {"name": clean_name, "keywords": keywords, "filters": filters}


def execute_search_plan(
    *,
    tenant_id: str,
    plan: dict[str, Any],
    tender_loader: TenderLoader,
    result_limit: int = 25,
    result_offset: int = 0,
) -> dict[str, Any]:
    """Run independent probes and merge unique tenders for the results table.

    Unlike the preview UI (which keeps blocks separate), accept-and-search needs
    one list. Items keep probe hit counts; order is by hits then first appearance.
    Buyers/geographies from the plan are not applied: they over-filter Signal.
    """

    if (
        result_limit < 1
        or result_offset < 0
        or result_offset + result_limit > EXECUTION_RESULT_WINDOW_LIMIT
    ):
        raise SearchPlanExecutionError(
            "La ventana de resultados debe estar entre 1 y 100 elementos."
        )

    scope, active = _scope(plan)
    selected, skipped = _execution_search_probes(plan)
    min_amount = plan.get("min_amount")
    max_amount = plan.get("max_amount")
    ordered = sorted(
        selected,
        key=lambda probe: (
            0 if probe.kind == "cpv" else 1,
            -_cpv_probe_score(probe, plan),
        ),
    )
    by_folder: dict[str, dict[str, Any]] = {}
    precision_excluded: dict[str, str] = {}
    order: list[str] = []
    order_index: dict[str, int] = {}
    probe_stats: list[dict[str, Any]] = []
    for probe in ordered:
        probe_key = (probe.kind, probe.value)
        cpv_relevance = _cpv_probe_score(probe, plan)
        query = {
            "keywords": probe.value if probe.kind == "term" else None,
            "cpv": probe.value if probe.kind == "cpv" else None,
            "min_amount": str(min_amount) if min_amount is not None else None,
            "max_amount": str(max_amount) if max_amount is not None else None,
            "deadline_before": None,
            "buyer": None,
            "region": None,
            "active": active,
            "scope": scope,
            # Always load the same bounded candidate window so page ordering and
            # totals do not change as the UI advances its offset.
            "limit": EXECUTION_RESULT_WINDOW_LIMIT,
            "offset": 0,
        }
        result = tender_loader(tenant_id=tenant_id, **query)
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            items = []
        hits = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            # Defense in depth: even if a probe leaked closed rows, drop them for active scope.
            if scope == "active" and not tender_is_pending_open(item):
                continue
            folder_id = item.get("folder_id")
            if not isinstance(folder_id, str) or not folder_id.strip():
                continue
            key = folder_id.strip()
            exclusion_reason = _precision_exclusion_reason(plan, item)
            if exclusion_reason is not None:
                precision_excluded[key] = exclusion_reason
                continue
            hits += 1
            existing = by_folder.get(key)
            if existing is None:
                by_folder[key] = {
                    **item,
                    "_matched_probe_keys": {probe_key},
                    "_matched_probes": [probe.value],
                    "_cpv_relevance": cpv_relevance,
                }
                order_index[key] = len(order)
                order.append(key)
            else:
                matched_keys = existing.get("_matched_probe_keys")
                if isinstance(matched_keys, set):
                    matched_keys.add(probe_key)
                matched = existing.get("_matched_probes")
                if isinstance(matched, list) and probe.value not in matched:
                    matched.append(probe.value)
                existing["_cpv_relevance"] = max(
                    float(existing.get("_cpv_relevance") or 0.0),
                    cpv_relevance,
                )
        probe_stats.append(
            {
                "kind": probe.kind,
                "value": probe.value,
                "label": probe.label,
                "total": int(result.get("total") or 0) if isinstance(result, dict) else 0,
                "returned": hits,
            }
        )

    def _rank_key(folder_key: str) -> tuple[float, int, int, int]:
        item = by_folder[folder_key]
        matched_keys = item.get("_matched_probe_keys")
        hits = len(matched_keys) if isinstance(matched_keys, set) else 0
        relevance = float(item.get("_cpv_relevance") or 0.0)
        raw_cpvs = item.get("cpv")
        cpv_list = raw_cpvs if isinstance(raw_cpvs, list) else []
        # Penaliza paquetes SDA con decenas de CPV (ruido de coincidencia accidental).
        bloat = int(len(cpv_list) > 15)
        return (-relevance, bloat, -hits, order_index[folder_key])

    ranked = sorted(order, key=_rank_key)[:EXECUTION_RESULT_WINDOW_LIMIT]
    merged_items: list[dict[str, Any]] = []
    for key in ranked[result_offset : result_offset + result_limit]:
        item = dict(by_folder[key])
        item.pop("_matched_probe_keys", None)
        item.pop("_matched_probes", None)
        item.pop("_cpv_relevance", None)
        merged_items.append(item)

    return {
        "translation_version": TRANSLATION_VERSION,
        "scope": scope,
        "provider_requests": len(ordered),
        "probes": probe_stats,
        "unprobed_chips": [
            {"kind": probe.kind, "value": probe.value, "label": probe.label} for probe in skipped
        ],
        "results": {
            "items": merged_items,
            "total": len(ranked),
            "limit": result_limit,
            "offset": result_offset,
            "cache_hit": False,
            "cached_seconds": 0,
            "filters": {"scope": scope},
            "semantics": {
                "oracle_scope": scope,
                "merged_results": True,
                "merge_strategy": "unique_folder_id_by_independent_probes",
                "global_order": False,
                "result_window_cap": EXECUTION_RESULT_WINDOW_LIMIT,
                "matched_before_window_cap": len(by_folder),
                "precision_filter": {
                    "version": PRECISION_FILTER_VERSION,
                    "excluded": len(precision_excluded),
                    "reason_counts": dict(Counter(precision_excluded.values())),
                },
                "limitations": [
                    "Resultados unidos por folder_id a partir de sondas independientes.",
                    "No se aplica el filtro de comprador/geografía del plan (evita 0 hits).",
                    "Signal no garantiza un ranking global entre sondas.",
                    "Se excluyen solo desajustes léxicos inequívocos y explicables de intención.",
                ],
            },
        },
    }
