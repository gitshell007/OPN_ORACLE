"""Sector-neutral lexical retrieval and ranking over the local CPV taxonomy."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from opn_oracle.oracle.comparable_procurement import title_terms
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy, normalize_cpv_code

CPV_RETRIEVAL_LIMIT = 10
_GENERIC_QUERY_TOKENS = frozenset({"diversos", "diversas", "varios", "varias"})
_MARKET_PARENT_MIN_SCORE_RATIO = 0.45


def procurement_text_tokens(value: str) -> frozenset[str]:
    return title_terms(value).difference(_GENERIC_QUERY_TOKENS)


@lru_cache(maxsize=1)
def _taxonomy_token_stats() -> tuple[int, Counter[str]]:
    taxonomy = load_cpv_taxonomy()
    frequencies: Counter[str] = Counter()
    for label in taxonomy.codes.values():
        frequencies.update(title_terms(label))
    return len(taxonomy.codes), frequencies


def procurement_token_weight(token: str) -> float:
    document_count, frequencies = _taxonomy_token_stats()
    return math.log((document_count + 1) / (frequencies.get(token, 0) + 1)) + 1.0


def cpv_label_relevance(query_tokens: frozenset[str], label: str) -> float:
    """Return an IDF-weighted lexical score with label precision."""

    if not query_tokens:
        return 0.0
    label_tokens = title_terms(label)
    overlap = query_tokens.intersection(label_tokens)
    if not overlap:
        return 0.0
    overlap_weight = sum(procurement_token_weight(token) for token in overlap)
    query_weight = sum(procurement_token_weight(token) for token in query_tokens)
    strongest_token = max(procurement_token_weight(token) for token in overlap)
    if strongest_token < 6.4 and overlap_weight / query_weight < 0.45:
        return 0.0
    label_weight = sum(procurement_token_weight(token) for token in label_tokens) or overlap_weight
    precision = overlap_weight / label_weight
    return overlap_weight * (0.7 + 0.3 * precision)


def _significant_digits(code: str) -> int:
    return len(code.rstrip("0"))


def _market_rank(
    scores: Mapping[str, float],
    *,
    overlap_counts: Mapping[str, int],
) -> dict[str, tuple[float, bool]]:
    """Promote a representative parent when it describes its best child well.

    CPV result windows are small, so spending every slot on narrow descendants
    can hide the measurable parent market. Promotion is lexical and
    hierarchical: it applies only inside one three-digit family, requires two
    query concepts in the official parent label and at least 45% of the child's
    score. This still leaves a specific code first when the parent has little
    lexical support, while reserving scarce probes for a broader measurable
    market.
    """

    ranked = {code: (score, False) for code, score in scores.items()}
    for parent_code, parent_score in scores.items():
        if overlap_counts.get(parent_code, 0) < 2:
            continue
        significant = _significant_digits(parent_code)
        if significant >= len(parent_code):
            continue
        prefix = parent_code[:significant]
        descendant_scores = [
            score
            for code, score in scores.items()
            if code[:3] == parent_code[:3]
            and _significant_digits(code) > significant
            and code.startswith(prefix)
        ]
        if not descendant_scores:
            continue
        best_descendant_score = max(descendant_scores)
        if (
            best_descendant_score > parent_score
            and parent_score >= best_descendant_score * _MARKET_PARENT_MIN_SCORE_RATIO
        ):
            ranked[parent_code] = (best_descendant_score, True)
    return ranked


def rank_cpv_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    text: str,
    prefer_specific_ties: bool = True,
) -> list[dict[str, str]]:
    """Rank validated candidates by lexical relevance and preserve ties."""

    taxonomy = load_cpv_taxonomy()
    query_tokens = procurement_text_tokens(text)
    candidates_with_scores: list[tuple[float, int, str, str]] = []
    for index, candidate in enumerate(candidates):
        code = normalize_cpv_code(candidate.get("code"))
        if code is None:
            continue
        label = taxonomy.codes.get(code)
        if label is None:
            continue
        score = cpv_label_relevance(query_tokens, label)
        candidates_with_scores.append((score, index, code, label))
    reference_scores = {code: score for score, _index, code, _label in candidates_with_scores}
    reference_overlaps = {
        code: len(query_tokens.intersection(title_terms(label)))
        for _score, _index, code, label in candidates_with_scores
    }
    parent_prefixes = [
        (code[: _significant_digits(code)], code[:3], _significant_digits(code))
        for _score, _index, code, _label in candidates_with_scores
        if _significant_digits(code) < len(code)
    ]
    if parent_prefixes:
        for code, label in taxonomy.codes.items():
            significant = _significant_digits(code)
            if not any(
                code[:3] == family and significant > parent_significant and code.startswith(prefix)
                for prefix, family, parent_significant in parent_prefixes
            ):
                continue
            score = cpv_label_relevance(query_tokens, label)
            if score <= 0:
                continue
            reference_scores[code] = score
            reference_overlaps[code] = len(query_tokens.intersection(title_terms(label)))
    market_rank = _market_rank(
        reference_scores,
        overlap_counts=reference_overlaps,
    )
    candidates_with_scores.sort(
        key=lambda item: (
            -market_rank[item[2]][0],
            0 if market_rank[item[2]][1] else 1,
            -_significant_digits(item[2]) if prefer_specific_ties else 0,
            item[1],
        )
    )
    return [
        {"code": code, "label": label} for _score, _index, code, label in candidates_with_scores
    ]


def retrieve_cpv_for_text(
    text: str,
    *,
    limit: int = CPV_RETRIEVAL_LIMIT,
) -> list[dict[str, Any]]:
    """Retrieve diverse CPV candidates from official labels, without network or LLM."""

    clean_text = " ".join(text.split())
    if not clean_text or not 1 <= limit <= 20:
        return []
    taxonomy = load_cpv_taxonomy()
    numeric = normalize_cpv_code(clean_text)
    if numeric is not None:
        label = taxonomy.codes.get(numeric)
        return [{"code": numeric, "label": label, "score": 1.0}] if label else []
    if clean_text.isdigit() and 2 <= len(clean_text) <= 8:
        matches = [
            (code, label) for code, label in taxonomy.codes.items() if code.startswith(clean_text)
        ]
        matches.sort(key=lambda item: (-_significant_digits(item[0]), item[0]))
        return [{"code": code, "label": label, "score": 1.0} for code, label in matches[:limit]]

    query_tokens = procurement_text_tokens(clean_text)
    if not query_tokens:
        return []
    total_query_weight = sum(procurement_token_weight(token) for token in query_tokens)
    scored: list[tuple[float, int, str, str, frozenset[str]]] = []
    for code, label in taxonomy.codes.items():
        label_tokens = title_terms(label)
        overlap = query_tokens.intersection(label_tokens)
        if not overlap:
            continue
        overlap_weight = sum(procurement_token_weight(token) for token in overlap)
        coverage = overlap_weight / total_query_weight
        strongest_token = max(procurement_token_weight(token) for token in overlap)
        if strongest_token < 6.4 and coverage < 0.45:
            continue
        score = cpv_label_relevance(query_tokens, label)
        scored.append((-score, -_significant_digits(code), code, label, overlap))
    market_rank = _market_rank(
        {code: -negative_score for negative_score, _, code, _, _ in scored},
        overlap_counts={code: len(overlap) for _, _, code, _, overlap in scored},
    )
    scored.sort(
        key=lambda item: (
            -market_rank[item[2]][0],
            0 if market_rank[item[2]][1] else 1,
            item[1],
            item[2],
        )
    )

    # First pass covers distinct three-digit families; a second pass fills any
    # remaining capacity with the strongest specific alternatives.
    selected: list[tuple[float, int, str, str, frozenset[str]]] = []
    selected_codes: set[str] = set()
    selected_families: set[str] = set()
    for candidate in scored:
        family = candidate[2][:3]
        if family in selected_families:
            continue
        selected.append(candidate)
        selected_codes.add(candidate[2])
        selected_families.add(family)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        for candidate in scored:
            if candidate[2] in selected_codes:
                continue
            selected.append(candidate)
            if len(selected) >= limit:
                break
    return [
        {"code": code, "label": label, "score": round(-negative_score, 6)}
        for negative_score, _specificity, code, label, _overlap in selected
    ]


def merge_cpv_candidates(
    ai_candidates: Iterable[Mapping[str, Any]],
    *,
    text: str,
    limit: int = CPV_RETRIEVAL_LIMIT,
) -> tuple[list[dict[str, str]], int]:
    """Merge validated AI candidates with local retrieval and cap by relevance."""

    taxonomy = load_cpv_taxonomy()
    ai_list = list(ai_candidates)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in [*ai_list, *retrieve_cpv_for_text(text, limit=limit)]:
        code = normalize_cpv_code(candidate.get("code"))
        if code is None or code in seen:
            continue
        label = taxonomy.codes.get(code)
        if label is None:
            continue
        seen.add(code)
        merged.append({"code": code, "label": label})
    ai_codes = {
        code
        for candidate in ai_list
        if (code := normalize_cpv_code(candidate.get("code"))) in taxonomy.codes
    }
    ranked = rank_cpv_candidates(merged, text=text)[:limit]
    if ai_codes and not any(candidate["code"] in ai_codes for candidate in ranked):
        ranked_ai = rank_cpv_candidates(
            [candidate for candidate in merged if candidate["code"] in ai_codes],
            text=text,
        )
        if ranked_ai:
            ranked = [*ranked[: max(0, limit - 1)], ranked_ai[0]]
    added = sum(1 for candidate in ranked if candidate["code"] not in ai_codes)
    return ranked, added
