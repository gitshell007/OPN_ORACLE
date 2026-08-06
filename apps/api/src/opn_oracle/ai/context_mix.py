"""G-26 · context family mixer for Preguntar a Oracle.

Permanent guard so a massive corpus of one family (especially tenders/pliegos)
cannot expel eligible people, competitors, actors, own documents or dossier
memory from the shared context bag.

Classification uses **server-owned metadata only** (``source_kind``,
``entity_kind`` / ``entity_type``, ``actor_type``, role flags, locator keys).
No free-text LLM classification and no invented claims/URLs/IDs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ContextFamily = Literal[
    "people",
    "competitors",
    "actors",
    "tenders",
    "documents",
    "memory",
    "other",
]

CONTEXT_FAMILIES: tuple[ContextFamily, ...] = (
    "people",
    "competitors",
    "actors",
    "tenders",
    "documents",
    "memory",
    "other",
)

MemoryMode = Literal["disabled", "shadow", "augment"]

MIXER_VERSION = "context_family_mix.v1"

# Soft defaults — floors are conditional (only when eligible evidence exists).
DEFAULT_FAMILY_FLOOR = 1
DEFAULT_FAMILY_SOFT_CAP = 12

# Stable priority when budget < eligible families (overridden by question intent).
DEFAULT_FAMILY_PRIORITY: tuple[ContextFamily, ...] = (
    "people",
    "competitors",
    "actors",
    "tenders",
    "documents",
    "memory",
    "other",
)

_INTENT_KEYWORDS: dict[ContextFamily, tuple[str, ...]] = {
    "people": (
        "persona",
        "personas",
        "person",
        "people",
        "quién",
        "quien",
        "administrador",
        "admin",
        "contacto",
    ),
    "competitors": (
        "competidor",
        "competidores",
        "competitor",
        "competitors",
        "rival",
        "rivales",
    ),
    "actors": (
        "actor",
        "actores",
        "partner",
        "partners",
        "colaborador",
        "instituci",
        "organismo",
    ),
    "tenders": (
        "pliego",
        "pliegos",
        "licitaci",
        "tender",
        "tenders",
        "contratac",
        "pcap",
        "adjudic",
    ),
    "documents": (
        "documento",
        "documentos",
        "document",
        "anexo",
        "pdf",
        "memoria t",
    ),
    "memory": (
        "memoria",
        "recordad",
        "recuerd",
        "antes",
        "históric",
        "historico",
        "memory",
    ),
    "other": (),
}

# Shared closed taxonomy for map_context_family + SQL candidate loader (G-26).
# Keep single source of truth — loader imports these; do not duplicate.
COMPETITOR_ROLE_TOKENS = frozenset(
    {
        "competitor",
        "competitors",
        "competidor",
        "competidores",
        "rival",
        "rivals",
    }
)
PERSON_TOKENS = frozenset({"person", "people", "persona", "individual", "human"})
ORG_ACTOR_TOKENS = frozenset(
    {
        "organization",
        "organisation",
        "company",
        "institution",
        "program",
        "research_group",
        "technology_center",
        "actor",
    }
)
TENDER_DOC_ROLES = frozenset(
    {
        "pliego",
        "pliegos",
        "pcap",
        "tender",
        "tenders",
        "procurement",
        "licitacion",
        "licitación",
        "opportunity_pliego",
    }
)
# Back-compat private aliases
_COMPETITOR_ROLE_TOKENS = COMPETITOR_ROLE_TOKENS
_PERSON_TOKENS = PERSON_TOKENS
_ORG_ACTOR_TOKENS = ORG_ACTOR_TOKENS
_TENDER_DOC_ROLES = TENDER_DOC_ROLES

# Protect short citation / id tokens when truncating long extracts.
_PROTECTED_ID_RE = re.compile(
    r"(?i)\b("
    r"evidence[_-]?id|source[_-]?ref|checksum|uuid"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|CONTR\s*\d{4}\s*\d+"
    r")\b"
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _item_get(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(key, default)
    return getattr(item, key, default)


def _meta_blob(item: Any) -> dict[str, Any]:
    """Flatten server-owned provenance + locator (+ top-level type fields)."""

    prov = _as_mapping(_item_get(item, "provenance"))
    loc = _as_mapping(_item_get(item, "locator"))
    score_details = _as_mapping(_item_get(item, "score_details"))
    blob: dict[str, Any] = {}
    blob.update(prov)
    # Locator does not override provenance keys that already exist.
    for key, value in loc.items():
        blob.setdefault(key, value)
    for key in (
        "entity_kind",
        "entity_type",
        "actor_type",
        "role",
        "entity_role",
        "dossier_role",
        "relation",
        "document_role",
        "content_class",
        "context_family",
        "family",
        "is_competitor",
    ):
        top = _item_get(item, key, None)
        if top is not None and key not in blob:
            blob[key] = top
    if score_details:
        blob.setdefault("_score_details", score_details)
    return blob


def _norm_token(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def map_context_family(item: Any) -> ContextFamily:
    """Map evidence/candidate → closed context family from server metadata.

    Mapping matrix (first match wins):

    | source_kind / metadata | family |
    |---|---|
    | explicit ``context_family`` / ``family`` in provenance|locator | that family (if known) |
    | ``memory_signal`` | ``memory`` |
    | ``procurement`` | ``tenders`` |
    | ``document`` + tender/pliego role markers | ``tenders`` |
    | ``document`` (default) | ``documents`` |
    | competitor role / ``is_competitor`` | ``competitors`` |
    | person ``entity_kind`` / ``actor_type`` | ``people`` |
    | org/institution actor markers / ``entity_intel`` company | ``actors`` |
    | ``signal`` without entity markers | ``other`` |
    | anything else | ``other`` |
    """

    blob = _meta_blob(item)
    explicit = _norm_token(blob.get("context_family") or blob.get("family"))
    if explicit in CONTEXT_FAMILIES:
        return explicit  # type: ignore[return-value]

    source_kind = _norm_token(_item_get(item, "source_kind") or blob.get("source_kind"))

    if source_kind == "memory_signal":
        return "memory"

    if source_kind == "procurement":
        return "tenders"

    # Competitor flags beat generic entity typing (company + role=competitor).
    if blob.get("is_competitor") is True or _norm_token(blob.get("is_competitor")) in {
        "1",
        "true",
        "yes",
    }:
        return "competitors"
    for role_key in ("role", "entity_role", "dossier_role", "relation", "relationship"):
        if _norm_token(blob.get(role_key)) in _COMPETITOR_ROLE_TOKENS:
            return "competitors"

    entity_kind = _norm_token(
        blob.get("entity_kind") or blob.get("entity_type") or blob.get("type")
    )
    actor_type = _norm_token(blob.get("actor_type"))

    if entity_kind in _PERSON_TOKENS or actor_type in _PERSON_TOKENS:
        return "people"

    if source_kind == "document":
        doc_role = _norm_token(
            blob.get("document_role")
            or blob.get("content_class")
            or blob.get("kind")
            or blob.get("doc_kind")
        )
        materialized = _norm_token(blob.get("materialized_for"))
        if doc_role in _TENDER_DOC_ROLES or materialized in {
            "sv2_e2e_vivo_opportunity",
            "opportunity_pliego",
        }:
            return "tenders"
        return "documents"

    if source_kind == "entity_intel":
        if entity_kind in _ORG_ACTOR_TOKENS or actor_type in _ORG_ACTOR_TOKENS:
            return "actors"
        # entity_intel without type still counts as actor-class intel (not tenders).
        return "actors"

    if source_kind == "signal":
        if entity_kind in _ORG_ACTOR_TOKENS or actor_type in _ORG_ACTOR_TOKENS:
            return "actors"
        return "other"

    if source_kind in {"web_search", "legacy_unresolved", ""}:
        return "other"

    return "other"


def intent_family_priority(question: str | None) -> tuple[ContextFamily, ...]:
    """Stable priority guided by question intent keywords (no LLM)."""

    text = (question or "").casefold()
    if not text.strip():
        return DEFAULT_FAMILY_PRIORITY
    hits: list[tuple[int, int, ContextFamily]] = []
    for index, family in enumerate(DEFAULT_FAMILY_PRIORITY):
        keywords = _INTENT_KEYWORDS.get(family) or ()
        score = sum(1 for kw in keywords if kw in text)
        # Higher intent score first; stable tie-break by default order.
        hits.append((-score, index, family))
    hits.sort()
    return tuple(family for _, _, family in hits)


def _candidate_id(item: Any, index: int) -> str:
    raw = _item_get(item, "id", None)
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return f"anon:{index}"


def _identity_key(item: Any, family: ContextFamily, item_id: str) -> str:
    """Strong identity for dedupe before consuming quota."""

    blob = _meta_blob(item)
    actor_id = blob.get("actor_id") or _item_get(item, "actor_id")
    if actor_id:
        return f"actor:{actor_id}"
    entity_name = _norm_token(blob.get("entity_name") or blob.get("canonical_name"))
    entity_kind = _norm_token(blob.get("entity_kind") or blob.get("entity_type"))
    if entity_name and entity_kind:
        return f"entity:{entity_kind}:{entity_name}"
    checksum = _item_get(item, "checksum", None)
    if checksum is not None:
        if isinstance(checksum, (bytes, bytearray)):
            return f"ck:{checksum.hex()}"
        text = str(checksum).strip()
        if text:
            return f"ck:{text}"
    source_ref = blob.get("source_ref") or blob.get("source_url") or _item_get(item, "source_url")
    if source_ref:
        return f"src:{family}:{source_ref}"
    return f"id:{item_id}"


def _base_score(item: Any) -> float:
    for key in ("overall_score", "score", "relevance", "confidence"):
        raw = _item_get(item, key, None)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    blob = _meta_blob(item)
    for key in ("overall_score", "score", "relevance"):
        raw = blob.get(key)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _relevance_bonus(extract: str, question: str | None) -> float:
    if not question:
        return 0.0
    text = (extract or "").casefold()
    if not text:
        return 0.0
    tokens = {t for t in re.split(r"[^\wáéíóúñü]+", question.casefold()) if len(t) >= 4}
    if not tokens:
        return 0.0
    return float(sum(1 for t in tokens if t in text))


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4) if text else 0


def truncate_extract_for_budget(extract: str, max_chars: int) -> str:
    """Truncate extract without orphaning short ID/citation tokens when possible."""

    if max_chars <= 0:
        return ""
    text = extract or ""
    if len(text) <= max_chars:
        return text
    if max_chars < 16:
        return text[:max_chars]
    # Prefer keeping the head (claim + leading refs). If a protected token would
    # be split at the cut, back up to the previous whitespace.
    cut = max_chars
    window = text[:cut]
    # If we cut mid-token that looks like an ID, retreat to last space.
    if cut < len(text) and not text[cut].isspace():
        sp = window.rfind(" ")
        if sp >= max(8, max_chars // 4):
            window = window[:sp]
    # Drop a trailing partial protected match.
    for match in _PROTECTED_ID_RE.finditer(window):
        if match.end() > len(window) - 2 and match.start() > 0:
            window = window[: match.start()].rstrip()
    return window


@dataclass(slots=True)
class MixCandidate:
    item: Any
    item_id: str
    family: ContextFamily
    identity_key: str
    score: float
    extract: str
    source_kind: str
    tokens: int
    order_index: int


@dataclass(slots=True)
class MixResult:
    selected: list[Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    selected_extracts: dict[str, str] = field(default_factory=dict)


def _discard_bump(discards: dict[str, dict[str, int]], reason: str, family: str) -> None:
    bucket = discards.setdefault(reason, {})
    bucket[family] = int(bucket.get(family, 0)) + 1


def mix_context_evidence(
    candidates: Sequence[Any],
    *,
    limit: int,
    question: str | None = None,
    memory_mode: MemoryMode | str = "augment",
    family_floors: Mapping[str, int] | None = None,
    family_caps: Mapping[str, int] | None = None,
    max_tokens: int | None = None,
    char_budget: int | None = None,
) -> MixResult:
    """Select evidence with conditional family floors, soft caps and token budget.

    Algorithm:
      1. Map family from server metadata; dedupe by strong identity (keep best score).
      2. Memory mode: ``disabled`` drops memory; ``shadow`` observes but never selects
         memory; ``augment`` allows memory family within the bag.
      3. Conditional floors: reserve min slots only when eligible candidates exist.
      4. Pass A — diversity/floors by intent priority (best score within family).
      5. Pass B — global fill by score; no family exceeds soft cap while another
         eligible family is still under its floor.
      6. Token/char budget: truncate extracts; never exceed max; protect IDs.
      7. Metadata: bounded counts + reason codes (no PII / no raw extracts).
    """

    requested = max(0, int(limit))
    mode = str(memory_mode or "augment").strip().lower()
    if mode not in {"disabled", "shadow", "augment"}:
        mode = "augment"
    token_budget = int(max_tokens) if max_tokens is not None and max_tokens > 0 else None
    # Character budget is authoritative when provided; else tokens*4; else unlimited.
    if char_budget is not None and char_budget > 0:
        chars_left = int(char_budget)
    elif token_budget is not None:
        chars_left = token_budget * 4
    else:
        chars_left = None

    floors_cfg = {f: DEFAULT_FAMILY_FLOOR for f in CONTEXT_FAMILIES}
    if family_floors:
        for key, value in family_floors.items():
            fam = _norm_token(key)
            if fam in CONTEXT_FAMILIES:
                floors_cfg[fam] = max(0, int(value))
    caps_cfg = {f: DEFAULT_FAMILY_SOFT_CAP for f in CONTEXT_FAMILIES}
    if family_caps:
        for key, value in family_caps.items():
            fam = _norm_token(key)
            if fam in CONTEXT_FAMILIES:
                caps_cfg[fam] = max(0, int(value))
    # Soft caps never below floor for eligible bookkeeping.
    for fam in CONTEXT_FAMILIES:
        caps_cfg[fam] = max(caps_cfg[fam], floors_cfg[fam])

    discards: dict[str, dict[str, int]] = {}
    reason_codes: list[str] = []
    raw_family_counts = {f: 0 for f in CONTEXT_FAMILIES}

    # --- build + score + dedupe ---
    best_by_identity: dict[str, MixCandidate] = {}
    for index, item in enumerate(candidates or ()):
        family = map_context_family(item)
        raw_family_counts[family] = raw_family_counts.get(family, 0) + 1
        item_id = _candidate_id(item, index)
        extract = str(_item_get(item, "extract") or "")
        # Score is order-independent for determinism across input permutations.
        # Recency comes from explicit created_at when present (not list position).
        recency = 0.0
        created = _item_get(item, "created_at", None)
        if created is not None:
            try:
                # datetime → unix; string timestamps ignored if unparsable
                ts = created.timestamp() if hasattr(created, "timestamp") else float(created)
                recency = ts / 1_000_000_000.0  # keep secondary to base/relevance
            except (TypeError, ValueError, OSError, OverflowError):
                recency = 0.0
        score = _base_score(item) * 1_000.0 + _relevance_bonus(extract, question) * 10.0 + recency
        cand = MixCandidate(
            item=item,
            item_id=item_id,
            family=family,
            identity_key=_identity_key(item, family, item_id),
            score=score,
            extract=extract,
            source_kind=_norm_token(_item_get(item, "source_kind")),
            tokens=_estimate_tokens(extract),
            order_index=index,
        )
        prev = best_by_identity.get(cand.identity_key)
        if prev is None:
            best_by_identity[cand.identity_key] = cand
            continue
        # Keep higher score; deterministic tie-break by id then order.
        if (cand.score, cand.item_id, -cand.order_index) > (
            prev.score,
            prev.item_id,
            -prev.order_index,
        ):
            _discard_bump(discards, "dedupe_identity", prev.family)
            best_by_identity[cand.identity_key] = cand
        else:
            _discard_bump(discards, "dedupe_identity", cand.family)

    pool = list(best_by_identity.values())

    # Memory mode gating
    memory_observed = sum(1 for c in pool if c.family == "memory")
    if mode == "disabled":
        kept: list[MixCandidate] = []
        for cand in pool:
            if cand.family == "memory":
                _discard_bump(discards, "memory_disabled", "memory")
                continue
            kept.append(cand)
        pool = kept
        if memory_observed:
            reason_codes.append("memory_disabled_zero")
    elif mode == "shadow":
        # Observe only — never inject memory into selected bag.
        kept = []
        for cand in pool:
            if cand.family == "memory":
                _discard_bump(discards, "memory_shadow_no_inject", "memory")
                continue
            kept.append(cand)
        pool = kept
        if memory_observed:
            reason_codes.append("memory_shadow_observe_only")

    by_family: dict[str, list[MixCandidate]] = {f: [] for f in CONTEXT_FAMILIES}
    for cand in pool:
        by_family[cand.family].append(cand)
    for family in CONTEXT_FAMILIES:
        by_family[family].sort(
            key=lambda c: (-c.score, c.item_id, c.order_index),
        )

    eligible = [f for f in CONTEXT_FAMILIES if by_family[f]]
    # Conditional floors: zero when family has no eligible evidence.
    applied_floors = {
        f: (min(floors_cfg[f], len(by_family[f])) if f in eligible else 0)
        for f in CONTEXT_FAMILIES
    }
    applied_caps = {
        f: (min(caps_cfg[f], max(len(by_family[f]), applied_floors[f])) if f in eligible else 0)
        for f in CONTEXT_FAMILIES
    }

    priority = intent_family_priority(question)
    # Restrict priority to eligible first, preserve order.
    priority_eligible = [f for f in priority if f in eligible]

    budget_insufficient = bool(requested > 0 and len(priority_eligible) > requested)
    if budget_insufficient:
        reason_codes.append("budget_insufficient_for_all_families")
    if requested <= 0:
        meta = _build_metadata(
            requested=requested,
            selected_by_family={f: 0 for f in CONTEXT_FAMILIES},
            candidates_by_family={f: len(by_family[f]) for f in CONTEXT_FAMILIES},
            raw_family_counts=raw_family_counts,
            floors=applied_floors,
            caps=applied_caps,
            discards=discards,
            reason_codes=[*reason_codes, "empty_budget"],
            eligible=eligible,
            memory_mode=mode,
            memory_observed=memory_observed,
            budget_insufficient=False,
            tokens_requested=token_budget,
            tokens_used=0,
            chars_used=0,
            char_budget=chars_left,
        )
        return MixResult(selected=[], metadata=meta)

    selected: list[MixCandidate] = []
    selected_ids: set[str] = set()
    selected_identities: set[str] = set()
    counts = {f: 0 for f in CONTEXT_FAMILIES}
    pointers = {f: 0 for f in CONTEXT_FAMILIES}
    tokens_used = 0
    chars_used = 0
    extracts: dict[str, str] = {}

    def _can_take(family: str, *, ignore_soft_cap: bool) -> bool:
        if pointers[family] >= len(by_family[family]):
            return False
        if counts[family] >= len(by_family[family]):
            return False
        return ignore_soft_cap or counts[family] < applied_caps[family]

    def _underfilled_families() -> list[str]:
        return [
            f
            for f in priority_eligible
            if counts[f] < applied_floors[f] and pointers[f] < len(by_family[f])
        ]

    def _take(family: str) -> bool:
        nonlocal tokens_used, chars_used
        if len(selected) >= requested:
            return False
        while pointers[family] < len(by_family[family]):
            cand = by_family[family][pointers[family]]
            pointers[family] += 1
            if cand.item_id in selected_ids or cand.identity_key in selected_identities:
                _discard_bump(discards, "dedupe_selected", family)
                continue
            extract = cand.extract
            if chars_left is not None:
                remaining = chars_left - chars_used
                if remaining <= 0:
                    _discard_bump(discards, "token_budget_exhausted", family)
                    return False
                if len(extract) > remaining:
                    extract = truncate_extract_for_budget(extract, remaining)
                    if not extract:
                        _discard_bump(discards, "token_budget_exhausted", family)
                        return False
                    reason_codes.append("extract_truncated")
            tok = _estimate_tokens(extract)
            if token_budget is not None and tokens_used + tok > token_budget and extract:
                # Try a tighter truncate to remaining tokens.
                remain_tok = max(0, token_budget - tokens_used)
                extract = truncate_extract_for_budget(extract, remain_tok * 4)
                if not extract:
                    _discard_bump(discards, "token_budget_exhausted", family)
                    return False
                tok = _estimate_tokens(extract)
                if tokens_used + tok > token_budget:
                    _discard_bump(discards, "token_budget_exhausted", family)
                    return False
                reason_codes.append("extract_truncated")
            selected.append(cand)
            selected_ids.add(cand.item_id)
            selected_identities.add(cand.identity_key)
            counts[family] += 1
            tokens_used += tok
            chars_used += len(extract)
            extracts[cand.item_id] = extract
            return True
        return False

    # Pass A: floors (diversity) — never fill empty floors with junk.
    for family in priority_eligible:
        need = applied_floors[family]
        while counts[family] < need and len(selected) < requested:
            # While other eligible families lack floors, do not exceed this family's floor.
            if not _can_take(family, ignore_soft_cap=True):
                break
            if not _take(family):
                break

    # If budget is too small, floors may leave some families empty — already flagged.
    # Pass B: global fill by score, respecting soft caps while floors remain open.
    def _global_pool(*, ignore_soft_cap: bool) -> list[MixCandidate]:
        out: list[MixCandidate] = []
        for family in CONTEXT_FAMILIES:
            if not by_family[family]:
                continue
            for cand in by_family[family][pointers[family] :]:
                if cand.item_id in selected_ids or cand.identity_key in selected_identities:
                    continue
                if not ignore_soft_cap and counts[family] >= applied_caps[family]:
                    continue
                out.append(cand)
        out.sort(key=lambda c: (-c.score, c.item_id, c.order_index))
        return out

    while len(selected) < requested:
        under = _underfilled_families()
        ignore_cap = False
        if under:
            # Prefer underfilled families only (hard diversity constraint).
            pool_ranked = [
                c
                for c in _global_pool(ignore_soft_cap=True)
                if c.family in under
            ]
            if not pool_ranked:
                # Cannot fill remaining floors — break to residual fill.
                reason_codes.append("floor_unsatisfied")
                break
        else:
            pool_ranked = _global_pool(ignore_soft_cap=False)
            if not pool_ranked:
                # Soft caps saturated: allow residual fill beyond soft caps.
                pool_ranked = _global_pool(ignore_soft_cap=True)
                ignore_cap = True
                if pool_ranked:
                    reason_codes.append("soft_cap_residual_fill")
        if not pool_ranked:
            break
        cand = pool_ranked[0]
        family = cand.family
        # Advance pointer to this candidate then take.
        # Ensure pointer is at/after this candidate in family list.
        fam_list = by_family[family]
        # Find candidate index
        try:
            idx = next(
                i
                for i, c in enumerate(fam_list)
                if c.item_id == cand.item_id and c.identity_key == cand.identity_key
            )
        except StopIteration:
            break
        if pointers[family] <= idx:
            pointers[family] = idx
        if not ignore_cap and counts[family] >= applied_caps[family] and under:
            # Should not happen given pool filter.
            _discard_bump(discards, "soft_cap_block", family)
            pointers[family] = idx + 1
            continue
        if not _take(family):
            # If take failed due to budget, stop; else skip.
            if chars_left is not None and chars_used >= chars_left:
                break
            if token_budget is not None and tokens_used >= token_budget:
                break
            continue

    # Residual: if still under request and floors unresolved, fill any remaining
    # by global score (may leave some families unrepresented — flagged).
    while len(selected) < requested:
        pool_ranked = _global_pool(ignore_soft_cap=True)
        if not pool_ranked:
            break
        cand = pool_ranked[0]
        family = cand.family
        fam_list = by_family[family]
        try:
            idx = next(i for i, c in enumerate(fam_list) if c.item_id == cand.item_id)
        except StopIteration:
            break
        if pointers[family] <= idx:
            pointers[family] = idx
        if not _take(family):
            break

    for family in CONTEXT_FAMILIES:
        remaining = len(by_family[family]) - counts[family]
        if remaining > 0 and len(selected) >= requested:
            discards.setdefault("over_item_budget", {})[family] = (
                discards.get("over_item_budget", {}).get(family, 0) + remaining
            )

    # Unique reason codes, stable order
    seen_rc: set[str] = set()
    ordered_rc: list[str] = []
    for code in reason_codes:
        if code not in seen_rc:
            seen_rc.add(code)
            ordered_rc.append(code)

    meta = _build_metadata(
        requested=requested,
        selected_by_family=counts,
        candidates_by_family={f: len(by_family[f]) for f in CONTEXT_FAMILIES},
        raw_family_counts=raw_family_counts,
        floors=applied_floors,
        caps=applied_caps,
        discards=discards,
        reason_codes=ordered_rc,
        eligible=eligible,
        memory_mode=mode,
        memory_observed=memory_observed,
        budget_insufficient=budget_insufficient,
        tokens_requested=token_budget,
        tokens_used=tokens_used,
        chars_used=chars_used,
        char_budget=chars_left,
    )
    return MixResult(
        selected=[c.item for c in selected],
        metadata=meta,
        selected_extracts=extracts,
    )


def _build_metadata(
    *,
    requested: int,
    selected_by_family: Mapping[str, int],
    candidates_by_family: Mapping[str, int],
    raw_family_counts: Mapping[str, int],
    floors: Mapping[str, int],
    caps: Mapping[str, int],
    discards: Mapping[str, Mapping[str, int]],
    reason_codes: Sequence[str],
    eligible: Sequence[str],
    memory_mode: str,
    memory_observed: int,
    budget_insufficient: bool,
    tokens_requested: int | None,
    tokens_used: int,
    chars_used: int,
    char_budget: int | None,
) -> dict[str, Any]:
    used = int(sum(int(v) for v in selected_by_family.values()))
    # Bounded discard view: reason → {family: count} only.
    discard_view = {
        reason: {fam: int(cnt) for fam, cnt in sorted(by_fam.items()) if cnt}
        for reason, by_fam in sorted(discards.items())
        if by_fam
    }
    return {
        "mixer": MIXER_VERSION,
        "budget_items_requested": int(requested),
        "budget_items_used": used,
        "budget_tokens_requested": tokens_requested,
        "budget_tokens_used": int(tokens_used),
        "budget_chars_requested": char_budget,
        "budget_chars_used": int(chars_used),
        "candidates_by_family": {f: int(candidates_by_family.get(f, 0)) for f in CONTEXT_FAMILIES},
        "raw_candidates_by_family": {f: int(raw_family_counts.get(f, 0)) for f in CONTEXT_FAMILIES},
        "selected_by_family": {f: int(selected_by_family.get(f, 0)) for f in CONTEXT_FAMILIES},
        "floors_applied": {f: int(floors.get(f, 0)) for f in CONTEXT_FAMILIES},
        "caps_applied": {f: int(caps.get(f, 0)) for f in CONTEXT_FAMILIES},
        "eligible_families": list(eligible),
        "discards": discard_view,
        "reason_codes": list(reason_codes),
        "budget_insufficient_for_all_families": bool(budget_insufficient),
        "memory_mode": memory_mode,
        "memory_observed": int(memory_observed),
        # Never claim full diversity when budget was insufficient.
        "diversity_complete": bool(
            not budget_insufficient
            and all(
                int(selected_by_family.get(f, 0)) >= int(floors.get(f, 0))
                for f in eligible
            )
        ),
    }


def diversify_by_context_family(
    rows: Sequence[Any],
    *,
    limit: int = 50,
    question: str | None = None,
    memory_mode: MemoryMode | str = "augment",
    max_per_family: int = DEFAULT_FAMILY_SOFT_CAP,
    family_floor: int = DEFAULT_FAMILY_FLOOR,
    max_tokens: int | None = None,
    char_budget: int | None = None,
) -> list[Any]:
    """Convenience wrapper returning only selected rows (drop metadata)."""

    floors = {f: family_floor for f in CONTEXT_FAMILIES}
    caps = {f: max_per_family for f in CONTEXT_FAMILIES}
    result = mix_context_evidence(
        rows,
        limit=limit,
        question=question,
        memory_mode=memory_mode,
        family_floors=floors,
        family_caps=caps,
        max_tokens=max_tokens,
        char_budget=char_budget,
    )
    return list(result.selected)
