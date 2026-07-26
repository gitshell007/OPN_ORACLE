"""Deterministic translation of an accepted tender-search plan.

Signal v1 does not expose a global boolean-query contract or global ordering.
Oracle therefore returns bounded, independent result blocks and never merges
them into a synthetic ranking.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

TERM_PROBE_LIMIT = 4
CPV_PROBE_LIMIT = 4
TOTAL_PROBE_LIMIT = TERM_PROBE_LIMIT + CPV_PROBE_LIMIT
PREVIEW_RESULT_LIMIT = 20
TRANSLATION_VERSION = "tender-search-plan-to-signal-v1"


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
    for item in value:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        label = item.get("label")
        if isinstance(code, str) and code:
            probes.append(
                SearchProbe(
                    kind="cpv",
                    value=code,
                    label=label if isinstance(label, str) else None,
                )
            )
    return probes


def build_search_probes(plan: dict[str, Any]) -> tuple[list[SearchProbe], list[SearchProbe]]:
    """Select visible top-N chips and return selected/skipped probes."""

    term_values = [*_strings(plan.get("include_terms")), *_strings(plan.get("synonyms"))]
    seen_terms: set[str] = set()
    term_probes: list[SearchProbe] = []
    for term in term_values:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        term_probes.append(SearchProbe(kind="term", value=term))

    cpv_probes = _cpv_candidates(plan.get("candidate_cpv"))
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


def _first(values: Any) -> str | None:
    strings = _strings(values)
    return strings[0] if strings else None


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
    buyer = _first(plan.get("buyers"))
    geography = _first(plan.get("geographies"))
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
            "buyer": buyer,
            "region": geography,
            "active": active,
            "scope": scope,
            "limit": result_limit,
            "offset": 0,
        }
        result = tender_loader(tenant_id=tenant_id, **query)
        blocks.append(
            {
                "chip": {
                    "kind": probe.kind,
                    "value": probe.value,
                    "label": probe.label,
                },
                "query": query,
                "total": int(result.get("total") or 0),
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
            "additional_buyers_applied": False,
            "additional_geographies_applied": False,
            "limitations": [
                "Los bloques conservan por separado el orden nativo de Signal.",
                "Las exclusiones no se envían: Signal v1 no ofrece un contrato NOT demostrado.",
                "Solo el primer comprador y la primera geografía se aplican a las sondas.",
            ],
        },
    }


# Prefijos CPV que suelen dar más recall en defensa/vehículos frente a ruido
# (p. ej. 3511* extinción de incendios) cuando el plan trae muchos candidatos.
_PRIORITY_CPV_PREFIXES = (
    "354",  # vehículos militares / partes
    "357",  # sistemas electrónicos militares
    "356",  # misiles
    "355",  # buques de guerra
    "353",  # armas
    "358",  # equipo individual y de apoyo
    "341",  # vehículos de motor
    "342",
    "343",
    "5011",  # gestión/reparación de flotas
)


def _primary_cpv(cpvs: list[SearchProbe]) -> SearchProbe | None:
    if not cpvs:
        return None
    for prefix in _PRIORITY_CPV_PREFIXES:
        for probe in cpvs:
            if probe.value.startswith(prefix):
                return probe
    return cpvs[0]


def _watch_keywords(plan: dict[str, Any], *, primary_cpv: SearchProbe | None) -> list[str]:
    """Signal ANDs the keyword list: more than one term often yields zero hits.

    Keep a single high-signal term for the durable watch. Immediate results use
    multi-probe execution instead of this narrow saved-search contract.
    """

    terms = [*_strings(plan.get("include_terms")), *_strings(plan.get("synonyms"))]
    terms = list(dict.fromkeys(term.strip() for term in terms if term.strip()))
    # Prefer concrete multi-word / domain terms over ultra-generic stems when possible.
    preferred = [
        term
        for term in terms
        if len(term) >= 6
        and term.casefold()
        not in {
            "defensa",
            "militar",
            "militares",
            "equipamiento",
            "accesorios",
            "transporte",
            "vehiculos",
            "vehículos",
        }
    ]
    if preferred:
        return [preferred[0][:120]]
    if terms:
        return [terms[0][:120]]
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
    if scope != "active":
        raise SearchPlanExecutionError(
            "Signal v1 solo conserva búsquedas guardadas de licitaciones activas."
        )
    cpvs = _cpv_candidates(plan.get("candidate_cpv"))
    primary = _primary_cpv(cpvs)
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
) -> dict[str, Any]:
    """Run independent probes and merge unique tenders for the results table.

    Unlike the preview UI (which keeps blocks separate), accept-and-search needs
    one list. Items keep probe hit counts; order is by hits then first appearance.
    Buyers/geographies from the plan are not applied: they over-filter Signal.
    """

    scope, active = _scope(plan)
    selected, skipped = build_search_probes(plan)
    min_amount = plan.get("min_amount")
    max_amount = plan.get("max_amount")
    # Rank CPVs first for defense-heavy plans so military codes are probed.
    ordered = sorted(
        selected,
        key=lambda probe: (
            0 if probe.kind == "cpv" and any(probe.value.startswith(p) for p in _PRIORITY_CPV_PREFIXES) else 1,
            0 if probe.kind == "cpv" else 1,
        ),
    )
    by_folder: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    probe_stats: list[dict[str, Any]] = []
    for probe in ordered:
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
            "limit": min(result_limit, PREVIEW_RESULT_LIMIT),
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
            folder_id = item.get("folder_id")
            if not isinstance(folder_id, str) or not folder_id.strip():
                continue
            key = folder_id.strip()
            hits += 1
            existing = by_folder.get(key)
            if existing is None:
                by_folder[key] = {
                    **item,
                    "_probe_hits": 1,
                    "_matched_probes": [probe.value],
                }
                order.append(key)
            else:
                existing["_probe_hits"] = int(existing.get("_probe_hits") or 0) + 1
                matched = existing.get("_matched_probes")
                if isinstance(matched, list) and probe.value not in matched:
                    matched.append(probe.value)
        probe_stats.append(
            {
                "kind": probe.kind,
                "value": probe.value,
                "label": probe.label,
                "total": int(result.get("total") or 0) if isinstance(result, dict) else 0,
                "returned": hits,
            }
        )

    ranked = sorted(
        order,
        key=lambda key: (-int(by_folder[key].get("_probe_hits") or 0), order.index(key)),
    )
    merged_items: list[dict[str, Any]] = []
    for key in ranked[:result_limit]:
        item = dict(by_folder[key])
        item.pop("_probe_hits", None)
        item.pop("_matched_probes", None)
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
            "total": len(by_folder),
            "limit": result_limit,
            "offset": 0,
            "cache_hit": False,
            "cached_seconds": 0,
            "filters": {"scope": scope},
            "semantics": {
                "oracle_scope": scope,
                "merged_results": True,
                "merge_strategy": "unique_folder_id_by_independent_probes",
                "global_order": False,
                "limitations": [
                    "Resultados unidos por folder_id a partir de sondas independientes.",
                    "No se aplica el filtro de comprador/geografía del plan (evita 0 hits).",
                    "Signal no garantiza un ranking global entre sondas.",
                ],
            },
        },
    }
