"""Deterministic grounding and post-validation for the tender search wizard."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from opn_oracle.ai.schemas import TenderSearchWizardOutput
from opn_oracle.oracle.comparable_procurement import title_terms
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy, normalize_cpv_code


class TenderSearchPlanValidationError(ValueError):
    """The candidate plan cannot safely cross the human-review boundary."""


def _clean_text_list(values: list[str], *, limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(value.split())
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def _normalized_terms(
    values: list[str],
    *,
    occupied: set[str],
    reasons: Counter[str],
) -> list[str]:
    normalized: list[str] = []
    for raw_value in values:
        tokens = sorted(title_terms(raw_value))
        if not tokens:
            reasons["term_without_search_tokens"] += 1
            continue
        for token in tokens:
            if token in occupied:
                reasons["duplicate_or_conflicting_term"] += 1
                continue
            occupied.add(token)
            normalized.append(token)
    return normalized


def postvalidate_tender_search_plan(
    raw_plan: Mapping[str, Any] | TenderSearchWizardOutput,
    *,
    reject_discards: bool = False,
) -> dict[str, Any]:
    """Return the canonical v1 plan, with only official CPVs and measurable tokens.

    Generated candidates expose discard counts to the user. Edited plans pass
    ``reject_discards=True`` so an acceptance never silently changes human input.
    """

    candidate = (
        raw_plan
        if isinstance(raw_plan, TenderSearchWizardOutput)
        else TenderSearchWizardOutput.model_validate_json(
            json.dumps(dict(raw_plan), sort_keys=True, separators=(",", ":"), default=str)
        )
    )
    if (
        candidate.min_amount is not None
        and candidate.max_amount is not None
        and candidate.min_amount > candidate.max_amount
    ):
        raise TenderSearchPlanValidationError(
            "El importe mínimo no puede superar el importe máximo."
        )

    taxonomy = load_cpv_taxonomy()
    reasons: Counter[str] = Counter()
    cpvs: list[dict[str, str]] = []
    seen_cpvs: set[str] = set()
    for raw_cpv in candidate.candidate_cpv:
        code = normalize_cpv_code(raw_cpv.code)
        if code is None:
            reasons["invalid_cpv_format"] += 1
            continue
        label = taxonomy.codes.get(code)
        if label is None:
            reasons["unknown_cpv"] += 1
            continue
        if raw_cpv.label is not None and raw_cpv.label.strip() != label:
            reasons["cpv_label_mismatch"] += 1
        if code in seen_cpvs:
            reasons["duplicate_cpv"] += 1
            continue
        seen_cpvs.add(code)
        cpvs.append({"code": code, "label": label})

    occupied_terms: set[str] = set()
    include_terms = _normalized_terms(
        candidate.include_terms,
        occupied=occupied_terms,
        reasons=reasons,
    )
    synonyms = _normalized_terms(
        candidate.synonyms,
        occupied=occupied_terms,
        reasons=reasons,
    )
    exclude_terms = _normalized_terms(
        candidate.exclude_terms,
        occupied=occupied_terms,
        reasons=reasons,
    )
    discarded_reasons = {reason: count for reason, count in sorted(reasons.items()) if count > 0}
    discarded_count = sum(discarded_reasons.values())
    if reject_discards and discarded_count:
        summary = ", ".join(f"{reason}={count}" for reason, count in discarded_reasons.items())
        raise TenderSearchPlanValidationError(
            f"El plan contiene valores que no se pueden aceptar sin cambios: {summary}."
        )

    output = candidate.model_dump(mode="json")
    output.update(
        {
            "include_terms": include_terms,
            "synonyms": synonyms,
            "exclude_terms": exclude_terms,
            "candidate_cpv": cpvs,
            "buyers": _clean_text_list(candidate.buyers, limit=30),
            "geographies": _clean_text_list(candidate.geographies, limit=30),
            "assumptions": _clean_text_list(candidate.assumptions, limit=20),
            "questions": _clean_text_list(candidate.questions, limit=20),
            "discarded_count": discarded_count,
            "discarded_reasons": discarded_reasons,
        }
    )
    return output
