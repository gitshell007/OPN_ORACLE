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


def saved_search_payload(*, name: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Translate one accepted plan to the bounded Signal v1 saved-search contract."""

    scope, _active = _scope(plan)
    if scope != "active":
        raise SearchPlanExecutionError(
            "Signal v1 solo conserva búsquedas guardadas de licitaciones activas."
        )
    terms = [*_strings(plan.get("include_terms")), *_strings(plan.get("synonyms"))]
    terms = list(dict.fromkeys(terms))[:20]
    if not terms:
        raise SearchPlanExecutionError(
            "Signal v1 exige al menos un término para guardar una vigilancia."
        )
    cpvs = _cpv_candidates(plan.get("candidate_cpv"))
    filters: dict[str, Any] = {"scope": "active"}
    if cpvs:
        filters["cpv"] = cpvs[0].value
    buyer = _first(plan.get("buyers"))
    geography = _first(plan.get("geographies"))
    if buyer:
        filters["buyer"] = buyer
    if geography:
        filters["region"] = geography
    if plan.get("min_amount") is not None:
        filters["min_amount"] = str(plan["min_amount"])
    if plan.get("max_amount") is not None:
        filters["max_amount"] = str(plan["max_amount"])
    return {"name": name, "keywords": terms, "filters": filters}
