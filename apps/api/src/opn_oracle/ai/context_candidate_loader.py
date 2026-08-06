"""G-26 corrective · balanced candidate retrieval *before* the mixer cap.

Problem fixed
-------------
``ORDER BY created_at DESC LIMIT 400`` (global) can drop entire families when
recent tenders/entity_intel noise dominate. The in-memory mixer never sees the
older people/competitors. Diversity must be applied at retrieval time.

Strategy (smallest that works on real PostgreSQL)
-------------------------------------------------
Per-family bounded SELECTs with server-owned predicates that mirror
:func:`opn_oracle.ai.context_mix.map_context_family` (first-match exclusive).
Each family has its own ``LIMIT``; no unbounded full scan.

Classification uses the **same token sets and match order** as
``map_context_family`` (centralized imports). No free-text / LLM path.

Index note
----------
Queries always filter ``evidence_dossiers(tenant_id, dossier_id)`` then
``evidence.tenant_id`` + ``source_kind`` + optional JSONB keys on
``provenance``/``locator``. Prefer the composite PK on ``evidence_dossiers``
and tenant isolation on ``evidence``. JSONB predicates are equality/``@>`` on
server-owned keys; a GIN index on ``evidence.provenance`` is optional and not
required for correctness. Documented for ops if EXPLAIN shows sequential
filters on very large dossiers.

Safety
------
Total rows returned across families is hard-capped (``SAFETY_TOTAL_POOL_CAP``).
If a family's pool hits its own cap while more rows may exist, metadata flags
``candidate_pool_truncated`` / ``candidate_pool_truncated_before_family_floor``
(distinct from mixer ``budget_insufficient_for_all_families``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Select, and_, func, not_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from opn_oracle.ai.context_mix import (
    COMPETITOR_ROLE_TOKENS,
    CONTEXT_FAMILIES,
    ORG_ACTOR_TOKENS,
    PERSON_TOKENS,
    TENDER_DOC_ROLES,
    ContextFamily,
    map_context_family,
)

# Re-export the closed family set so callers share one taxonomy.
LOADER_VERSION = "context_family_candidate_loader.v1"

# Per-family pool sizes fed into the mixer (before item/token budget).
# Tenders dominate real corpora; still bounded so residual families fit.
DEFAULT_FAMILY_POOL_CAPS: dict[ContextFamily, int] = {
    "people": 48,
    "competitors": 48,
    "actors": 48,
    "tenders": 160,
    "documents": 64,
    "memory": 48,
    "other": 32,
}

# Hard upper bound across all family queries (no unlimited scan).
SAFETY_TOTAL_POOL_CAP = 500

# Source kinds allowed in the generic Preguntar bag.
_ALLOWED_SOURCE_KINDS = ("signal", "document", "procurement", "entity_intel", "memory_signal")

# Single taxonomy with map_context_family (imported above).
_COMPETITOR_ROLE_TOKENS = COMPETITOR_ROLE_TOKENS
_PERSON_TOKENS = PERSON_TOKENS
_ORG_ACTOR_TOKENS = ORG_ACTOR_TOKENS
_TENDER_DOC_ROLES = TENDER_DOC_ROLES
_OPPORTUNITY_MATERIALIZED = frozenset({"sv2_e2e_vivo_opportunity", "opportunity_pliego"})
_ROLE_KEYS = ("role", "entity_role", "dossier_role", "relation", "relationship")
_ENTITY_KIND_KEYS = ("entity_kind", "entity_type", "type")
_EXPLICIT_FAMILY_KEYS = ("context_family", "family")
_DOC_ROLE_KEYS = ("document_role", "content_class", "kind", "doc_kind")


@dataclass(slots=True)
class CandidateLoadResult:
    """Bounded candidate pool + retrieval metadata (no extracts / no PII)."""

    candidates: list[Any]
    metadata: dict[str, Any] = field(default_factory=dict)


def _json_text(column: Any, key: str) -> ColumnElement[Any]:
    """``column ->> key`` as text (NULL-safe)."""

    return column[key].as_string()


def _json_bool_true(column: Any, key: str) -> ColumnElement[Any]:
    """True when JSONB key is boolean true or common truthy string."""

    as_text = column[key].as_string()
    return or_(
        column.contains({key: True}),
        func.lower(func.coalesce(as_text, "")).in_(("true", "1", "yes")),
    )


def _norm_sql(expr: ColumnElement[Any]) -> ColumnElement[Any]:
    """Lowercase + replace '-'/' ' with '_' — mirrors ``_norm_token``."""

    return func.replace(
        func.replace(func.lower(func.coalesce(expr, "")), "-", "_"),
        " ",
        "_",
    )


def _meta_text_any(key: str) -> ColumnElement[Any]:
    """COALESCE(provenance.key, locator.key) as normalized token."""

    from opn_oracle.oracle.models import Evidence

    return _norm_sql(
        func.coalesce(
            _json_text(Evidence.provenance, key),
            _json_text(Evidence.locator, key),
        )
    )


def _explicit_family_is(family: str) -> ColumnElement[Any]:
    parts = [_meta_text_any(k) == family for k in _EXPLICIT_FAMILY_KEYS]
    return or_(*parts)


def _explicit_family_set() -> ColumnElement[Any]:
    parts = [_meta_text_any(k).in_(list(CONTEXT_FAMILIES)) for k in _EXPLICIT_FAMILY_KEYS]
    return or_(*parts)


def _is_competitor_sql() -> ColumnElement[Any]:
    from opn_oracle.oracle.models import Evidence

    role_hits = [
        _meta_text_any(k).in_(list(_COMPETITOR_ROLE_TOKENS)) for k in _ROLE_KEYS
    ]
    return or_(
        _json_bool_true(Evidence.provenance, "is_competitor"),
        _json_bool_true(Evidence.locator, "is_competitor"),
        *role_hits,
    )


def _is_person_sql() -> ColumnElement[Any]:
    kind_hits = [_meta_text_any(k).in_(list(_PERSON_TOKENS)) for k in _ENTITY_KIND_KEYS]
    return or_(*kind_hits, _meta_text_any("actor_type").in_(list(_PERSON_TOKENS)))


def _is_org_actor_sql() -> ColumnElement[Any]:
    kind_hits = [_meta_text_any(k).in_(list(_ORG_ACTOR_TOKENS)) for k in _ENTITY_KIND_KEYS]
    return or_(*kind_hits, _meta_text_any("actor_type").in_(list(_ORG_ACTOR_TOKENS)))


def _is_tender_document_sql() -> ColumnElement[Any]:
    role_hits = [_meta_text_any(k).in_(list(_TENDER_DOC_ROLES)) for k in _DOC_ROLE_KEYS]
    materialized = _meta_text_any("materialized_for").in_(
        ["sv2_e2e_vivo_opportunity", "opportunity_pliego"]
    )
    return or_(*role_hits, materialized)


def _is_opportunity_pliego_sql() -> ColumnElement[Any]:
    from opn_oracle.oracle.models import Evidence

    return or_(
        _meta_text_any("materialized_for").in_(list(_OPPORTUNITY_MATERIALIZED)),
        Evidence.provenance.contains({"materialized_for": "sv2_e2e_vivo_opportunity"}),
        Evidence.provenance.contains({"materialized_for": "opportunity_pliego"}),
        Evidence.locator.contains({"materialized_for": "sv2_e2e_vivo_opportunity"}),
        Evidence.locator.contains({"materialized_for": "opportunity_pliego"}),
    )


def family_sql_predicate(family: ContextFamily) -> ColumnElement[Any]:
    """Exclusive SQL predicate mirroring ``map_context_family`` first-match order.

    Each family predicate includes its positive match AND excludes higher-priority
    branches so a row is assigned to at most one family query.
    """

    from opn_oracle.oracle.models import Evidence

    sk = Evidence.source_kind
    explicit = _explicit_family_is(family)
    explicit_other = and_(_explicit_family_set(), not_(_explicit_family_is(family)))

    # Higher-priority exclusions shared by lower branches.
    is_memory = sk == "memory_signal"
    is_procurement = sk == "procurement"
    is_competitor = _is_competitor_sql()
    is_person = _is_person_sql()
    is_doc = sk == "document"
    is_tender_doc = and_(is_doc, _is_tender_document_sql())
    is_own_doc = and_(is_doc, not_(_is_tender_document_sql()))
    is_entity = sk == "entity_intel"
    is_signal = sk == "signal"
    is_org = _is_org_actor_sql()

    if family == "memory":
        return and_(not_(explicit_other), or_(explicit, is_memory))

    if family == "tenders":
        # explicit OR procurement OR tender-document; not memory
        return and_(
            not_(explicit_other),
            not_(is_memory),
            or_(explicit, is_procurement, is_tender_doc),
        )

    if family == "competitors":
        # competitor flags beat person/entity; not memory/procurement/tender-doc
        return and_(
            not_(explicit_other),
            not_(is_memory),
            not_(is_procurement),
            not_(is_tender_doc),
            or_(explicit, is_competitor),
        )

    if family == "people":
        return and_(
            not_(explicit_other),
            not_(is_memory),
            not_(is_procurement),
            not_(is_tender_doc),
            not_(is_competitor),
            or_(explicit, is_person),
        )

    if family == "documents":
        return and_(
            not_(explicit_other),
            not_(is_memory),
            not_(is_procurement),
            not_(is_competitor),
            not_(is_person),
            or_(explicit, is_own_doc),
        )

    if family == "actors":
        # entity_intel default + org-typed signal; not higher branches
        entity_actors = and_(is_entity, not_(is_competitor), not_(is_person))
        signal_actors = and_(is_signal, is_org, not_(is_competitor), not_(is_person))
        return and_(
            not_(explicit_other),
            not_(is_memory),
            not_(is_procurement),
            not_(is_tender_doc),
            not_(is_own_doc),
            or_(explicit, entity_actors, signal_actors),
        )

    # other: residual of allowed kinds
    return and_(
        not_(explicit_other),
        not_(is_memory),
        not_(is_procurement),
        not_(is_tender_doc),
        not_(is_own_doc),
        not_(is_competitor),
        not_(is_person),
        not_(and_(is_entity, not_(is_competitor), not_(is_person))),
        not_(and_(is_signal, is_org, not_(is_competitor), not_(is_person))),
        or_(
            explicit,
            sk.in_(("signal", "web_search", "legacy_unresolved")),
            and_(sk.in_(_ALLOWED_SOURCE_KINDS), not_(is_entity)),
        ),
    )


def _base_evidence_select(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    exclude_opportunity_pliego: bool,
) -> Select[Any]:
    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Evidence

    evidence_ids = select(EvidenceDossier.evidence_id).where(
        EvidenceDossier.tenant_id == tenant_id,
        EvidenceDossier.dossier_id == dossier_id,
    )
    clauses: list[ColumnElement[Any]] = [
        Evidence.id.in_(evidence_ids),
        Evidence.tenant_id == tenant_id,
        Evidence.source_kind.in_(_ALLOWED_SOURCE_KINDS),
    ]
    if exclude_opportunity_pliego:
        clauses.append(not_(_is_opportunity_pliego_sql()))
    return select(Evidence).where(and_(*clauses))


def load_balanced_context_candidates(
    session: Session | Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    family_pool_caps: Mapping[str, int] | None = None,
    exclude_opportunity_pliego: bool = True,
    safety_total_pool_cap: int = SAFETY_TOTAL_POOL_CAP,
) -> CandidateLoadResult:
    """Load a family-balanced candidate pool for G-26 mixing.

    Parameters
    ----------
    session:
        SQLAlchemy session (Flask-SQLAlchemy or plain).
    family_pool_caps:
        Per-family LIMIT overrides (defaults from ``DEFAULT_FAMILY_POOL_CAPS``).
    exclude_opportunity_pliego:
        Keep opportunity-only PCAP materializations out of the generic bag.
    safety_total_pool_cap:
        Hard cap on total candidates returned across all families.
    """

    from opn_oracle.oracle.models import Evidence

    caps: dict[str, int] = {f: DEFAULT_FAMILY_POOL_CAPS[f] for f in CONTEXT_FAMILIES}
    if family_pool_caps:
        for key, value in family_pool_caps.items():
            fam = str(key or "").strip().lower()
            if fam in CONTEXT_FAMILIES:
                caps[fam] = max(0, int(value))

    total_cap = max(0, int(safety_total_pool_cap))
    queries_run = 0
    rows_scanned_by_family: dict[str, int] = {f: 0 for f in CONTEXT_FAMILIES}
    pool_cap_hit_by_family: dict[str, bool] = {f: False for f in CONTEXT_FAMILIES}
    selected: list[Any] = []
    seen_ids: set[str] = set()
    families_truncated: list[str] = []
    candidate_pool_truncated = False
    safety_cap_hit = False

    # Stable family order for residual budget allocation under total safety cap.
    # Prefer diversity families first so a flood of tenders cannot exhaust the
    # global safety budget before people/competitors are fetched.
    fetch_order: tuple[ContextFamily, ...] = (
        "people",
        "competitors",
        "actors",
        "documents",
        "memory",
        "tenders",
        "other",
    )

    remaining_global = total_cap
    for family in fetch_order:
        if remaining_global <= 0:
            safety_cap_hit = True
            candidate_pool_truncated = True
            # Mark remaining unfetched families so floors can surface the right limitation.
            for rest in fetch_order[fetch_order.index(family) :]:
                if caps[rest] > 0 and rows_scanned_by_family.get(rest, 0) == 0:
                    families_truncated.append(rest)
                    pool_cap_hit_by_family[rest] = True
            break

        family_limit = min(caps[family], remaining_global)
        if family_limit <= 0:
            continue

        # Request one extra row when possible so we can detect "more exist".
        fetch_limit = min(family_limit + 1, max(family_limit, remaining_global))
        stmt = (
            _base_evidence_select(
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                exclude_opportunity_pliego=exclude_opportunity_pliego,
            )
            .where(family_sql_predicate(family))  # type: ignore[arg-type]
            .order_by(Evidence.created_at.desc(), Evidence.id.desc())
            .limit(fetch_limit)
        )
        queries_run += 1
        rows = list(session.scalars(stmt))

        # Parity guard + early dedupe. Fake/test sessions may ignore WHERE/LIMIT
        # and return a full bag — re-classify with map_context_family and re-cap.
        matched: list[Any] = []
        for row in rows:
            rid = str(getattr(row, "id", "") or "")
            if not rid or rid in seen_ids:
                continue
            if map_context_family(row) != family:
                continue
            matched.append(row)

        # Surplus beyond family_limit ⇒ more rows exist (pool truncated).
        if len(matched) > family_limit:
            pool_cap_hit_by_family[family] = True
            families_truncated.append(family)
            candidate_pool_truncated = True
            matched = matched[:family_limit]
        rows_scanned_by_family[family] = len(matched)

        for row in matched:
            rid = str(getattr(row, "id", "") or "")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            selected.append(row)
            remaining_global -= 1
            if remaining_global <= 0:
                safety_cap_hit = True
                candidate_pool_truncated = True
                break

    # Floors the mixer may want (default 1 per family except other=0).
    # If we truncated a family that returned zero rows under its cap, we cannot
    # know if eligible rows exist further — flag the distinct limitation.
    zero_families_with_cap_hit = [
        f
        for f in CONTEXT_FAMILIES
        if pool_cap_hit_by_family.get(f)
        and rows_scanned_by_family.get(f, 0) == 0
        and caps.get(f, 0) > 0
    ]
    # More common case: family returned some rows equal to its pool cap — may
    # still have more eligible rows; if mixer floor needs more, that's fine.
    # Flag when a diversity family returned 0 *and* we hit safety/global cap
    # before querying it, or its own query was skipped.
    truncated_before_floor = [
        f
        for f in ("people", "competitors", "actors", "documents", "memory", "tenders")
        if f in families_truncated and rows_scanned_by_family.get(f, 0) == 0
    ] or zero_families_with_cap_hit

    reason_codes: list[str] = []
    if candidate_pool_truncated:
        reason_codes.append("candidate_pool_truncated")
    if safety_cap_hit:
        reason_codes.append("safety_total_pool_cap_hit")
    if truncated_before_floor:
        reason_codes.append("candidate_pool_truncated_before_family_floor")

    # Stable order: newest first among selected (mixer re-scores anyway).
    def _created_key(row: Any) -> tuple[Any, str]:
        created = getattr(row, "created_at", None)
        return (created is None, created, str(getattr(row, "id", "")))

    selected.sort(key=_created_key, reverse=True)

    metadata = {
        "loader": LOADER_VERSION,
        "strategy": "per_family_bounded_select",
        "queries_run": int(queries_run),
        "rows_scanned_by_family": {
            f: int(rows_scanned_by_family.get(f, 0)) for f in CONTEXT_FAMILIES
        },
        "family_pool_caps": {f: int(caps[f]) for f in CONTEXT_FAMILIES},
        "pool_cap_hit_by_family": {
            f: bool(pool_cap_hit_by_family.get(f)) for f in CONTEXT_FAMILIES
        },
        "candidates_loaded": int(len(selected)),
        "candidates_loaded_by_family": _count_by_family(selected),
        "safety_total_pool_cap": int(total_cap),
        "candidate_pool_truncated": bool(candidate_pool_truncated),
        "candidate_pool_truncated_before_family_floor": bool(truncated_before_floor),
        "truncated_families": list(dict.fromkeys(families_truncated)),
        "reason_codes": reason_codes,
        "exclude_opportunity_pliego": bool(exclude_opportunity_pliego),
        # No extracts / PII — only ids count and aggregate caps.
        "index_notes": {
            "tenant_dossier": "evidence_dossiers(tenant_id, dossier_id) PK drives scope",
            "jsonb": (
                "provenance/locator equality and @> on server-owned keys; "
                "optional GIN on evidence.provenance if EXPLAIN shows seq filters"
            ),
        },
    }
    return CandidateLoadResult(candidates=selected, metadata=metadata)


def _count_by_family(rows: Sequence[Any]) -> dict[str, int]:
    counts = {f: 0 for f in CONTEXT_FAMILIES}
    for row in rows:
        fam = map_context_family(row)
        counts[fam] = counts.get(fam, 0) + 1
    return counts


def classify_family_parity_spec() -> dict[str, Any]:
    """Documented single taxonomy for SQL↔Python parity tests (no PII)."""

    return {
        "families": list(CONTEXT_FAMILIES),
        "competitor_role_tokens": sorted(_COMPETITOR_ROLE_TOKENS),
        "person_tokens": sorted(_PERSON_TOKENS),
        "org_actor_tokens": sorted(_ORG_ACTOR_TOKENS),
        "tender_doc_roles": sorted(_TENDER_DOC_ROLES),
        "match_order": [
            "explicit context_family|family",
            "memory_signal → memory",
            "procurement → tenders",
            "competitor flags/roles → competitors",
            "person entity_kind|actor_type → people",
            "document + tender role → tenders else documents",
            "entity_intel → actors",
            "signal + org → actors else other",
            "fallback → other",
        ],
        "loader": LOADER_VERSION,
    }
