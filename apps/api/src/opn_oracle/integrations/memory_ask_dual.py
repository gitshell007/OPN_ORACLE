"""MDEV-06 · dual-memory ask vertical (Oracle authority + Signal factual evidence).

Provisional under inherited MDEV-04/05 debt. Fail-closed for disabled mode and
non-citable items. Does not promote memory facts or mutate IntentRevision.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from opn_oracle.integrations.memory_contract_v1 import (
    MaterializedCitation,
    materialize_signal_item_to_evidence,
    should_inject_into_llm,
)
from opn_oracle.oracle.evidence_source_kinds import DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS

MemoryMode = Literal["disabled", "shadow", "augment"]
PROMPT_RUNTIME_ID = "RT-07"
PROMPT_RUNTIME_VERSION = "1.0.0"
SCHEMA_RUNTIME_VERSION = "dossier_question_answer.v1"

# Retryable technical failures that must preserve Celery backoff/deadline.
RETRYABLE_ERROR_CODES = frozenset(
    {
        "upstream_retryable",
        "timeout",
        "upstream_timeout",
        "transport_error",
        "rate_limit_exceeded",
        "upstream_5xx",
        "backend_unavailable",
        "memory_engine_disabled",
    }
)
PERMANENT_ERROR_CODES = frozenset(
    {
        "auth_or_scope",
        "schema_validation",
        "schema_validation_failed",
        "missing_api_key",
        "invalid_api_key",
        "tenant_not_allowed",
        "dossier_not_allowed",
        "dossier_not_authorized",
        "credential_tenant_mismatch",
        "unsupported_api_version",
        "ssrf_blocked",
        "ssrf_rebind",
    }
)


@dataclass(frozen=True)
class EvidenceMappingRow:
    """Versioned mapping memory_item/fact → Oracle Evidence → source version."""

    signal_item_id: str
    oracle_evidence_id: str
    source_ref: str
    source_version: str
    checksum: str
    classification: str
    locator: str
    mapping_version: str = "memory_evidence_map.v1"


@dataclass(frozen=True)
class DualAskContext:
    mode: MemoryMode
    oracle_authority: dict[str, Any]
    signal_factual: dict[str, Any]
    citations: tuple[MaterializedCitation, ...]
    mappings: tuple[EvidenceMappingRow, ...]
    allowed_evidence_ids: tuple[str, ...]
    coverage: dict[str, Any]
    input_manifest: dict[str, Any]
    input_manifest_hash: str
    excluded: tuple[dict[str, Any], ...]


class RetryableMemoryAskError(RuntimeError):
    """Technical failure that Celery must retry within deadline."""

    def __init__(self, message: str, *, code: str = "upstream_retryable") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = True


class PermanentMemoryAskError(RuntimeError):
    """Auth/scope/schema or non-retryable failure — terminal."""

    def __init__(self, message: str, *, code: str = "permanent") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = False


def classify_error_code(code: str | None, *, http_status: int | None = None) -> bool:
    """Return True when the failure is retryable for service→handler→Celery."""

    normalized = str(code or "").strip().lower()
    if normalized in PERMANENT_ERROR_CODES:
        return False
    if normalized in RETRYABLE_ERROR_CODES:
        return True
    if http_status is not None:
        if http_status in (401, 403, 422):
            return False
        if http_status in (408, 429) or http_status >= 500:
            return True
    return False


def _stable_hash(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    return hashlib.sha256(raw).hexdigest()


def build_oracle_authority_block(
    *,
    dossier_id: str,
    tenant_id: str,
    question: str,
    intent: Mapping[str, Any] | None = None,
    requirements: Sequence[Any] | None = None,
    offering: Mapping[str, Any] | None = None,
    objectives: Sequence[Any] | None = None,
    decisions: Sequence[Mapping[str, Any]] | None = None,
    oracle_evidence: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Oracle decisional authority — never mixed into Signal factual items."""

    return {
        "block": "oracle_authority",
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "question": str(question),
        "intent": dict(intent or {}),
        "intent_hash": str(
            (intent or {}).get("content_hash") or (intent or {}).get("intent_hash") or ""
        ),
        "requirements": list(requirements or []),
        "offering": dict(offering or {}),
        "objectives": list(objectives or []),
        "decisions": [dict(item) for item in (decisions or [])],
        "oracle_evidence": [dict(item) for item in (oracle_evidence or [])],
        "untrusted_external": False,
        "authority_loaded": bool(
            intent or requirements or offering or objectives or decisions or oracle_evidence
        ),
    }


def load_oracle_authority_from_session(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    question: str,
) -> dict[str, Any]:
    """Load tenant+dossier-scoped Oracle authority from PostgreSQL (no mocks).

    Includes accepted IntentRevision + hash, requirements, offering, objectives,
    decisions, and Evidence rows linked via EvidenceDossier for this dossier only.
    Rows belonging to other tenants/dossiers are excluded by WHERE clauses.
    """

    from sqlalchemy import select

    from opn_oracle.oracle.intent import (
        DossierIntentRevision,
        DossierOffering,
        IntelligenceRequirement,
    )
    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Decision, DossierObjective, Evidence, StrategicDossier

    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        return build_oracle_authority_block(
            dossier_id=str(dossier_id),
            tenant_id=str(tenant_id),
            question=question,
        )

    accepted_intent = None
    # getattr: legacy/fixture dossiers (SimpleNamespace, partial ORM rows) may omit the
    # column; real PG models always expose it. Never treat AttributeError as authority.
    intent_revision_id = getattr(dossier, "current_intent_revision_id", None)
    if intent_revision_id is not None:
        accepted_intent = session.scalar(
            select(DossierIntentRevision).where(
                DossierIntentRevision.id == intent_revision_id,
                DossierIntentRevision.tenant_id == tenant_id,
                DossierIntentRevision.dossier_id == dossier_id,
                DossierIntentRevision.status == "accepted",
            )
        )

    intent_payload: dict[str, Any] = {}
    if accepted_intent is not None:
        intent_payload = {
            "id": str(accepted_intent.id),
            "version": accepted_intent.version,
            "schema_key": accepted_intent.schema_key,
            "schema_version": accepted_intent.schema_version,
            "request_text": accepted_intent.request_text,
            "structured_spec": dict(accepted_intent.structured_spec or {}),
            "content_hash": accepted_intent.content_hash,
            "intent_hash": accepted_intent.content_hash,
            "status": accepted_intent.status,
        }

    requirements: list[dict[str, Any]] = []
    offering_payload: dict[str, Any] = {}
    if accepted_intent is not None:
        req_rows = list(
            session.scalars(
                select(IntelligenceRequirement)
                .where(
                    IntelligenceRequirement.tenant_id == tenant_id,
                    IntelligenceRequirement.dossier_id == dossier_id,
                    IntelligenceRequirement.intent_revision_id == accepted_intent.id,
                    IntelligenceRequirement.status == "active",
                )
                .order_by(IntelligenceRequirement.priority, IntelligenceRequirement.created_at)
                .limit(25)
            )
        )
        requirements = [
            {
                "id": str(item.id),
                "class": item.requirement_class,
                "priority": item.priority,
                "question": item.question,
                "decision_to_support": item.decision_to_support,
            }
            for item in req_rows
        ]
        offerings = list(
            session.scalars(
                select(DossierOffering)
                .where(
                    DossierOffering.tenant_id == tenant_id,
                    DossierOffering.dossier_id == dossier_id,
                    DossierOffering.intent_revision_id == accepted_intent.id,
                    DossierOffering.status == "active",
                )
                .order_by(DossierOffering.created_at)
                .limit(5)
            )
        )
        if offerings:
            first = offerings[0]
            offering_payload = {
                "id": str(first.id),
                "name": first.name,
                "aliases": list(first.aliases or []),
                "description": first.description,
                "all": [
                    {"id": str(o.id), "name": o.name, "description": o.description}
                    for o in offerings
                ],
            }

    objectives = [
        {"id": str(item.id), "title": item.title, "status": item.status}
        for item in session.scalars(
            select(DossierObjective)
            .where(
                DossierObjective.tenant_id == tenant_id,
                DossierObjective.dossier_id == dossier_id,
            )
            .order_by(DossierObjective.position)
            .limit(15)
        )
    ]

    decisions = [
        {
            "id": str(item.id),
            "title": item.title,
            "status": item.status,
            "rationale": (item.rationale or "")[:500],
        }
        for item in session.scalars(
            select(Decision)
            .where(
                Decision.tenant_id == tenant_id,
                Decision.dossier_id == dossier_id,
            )
            .order_by(Decision.updated_at.desc())
            .limit(15)
        )
    ]

    evidence_ids = select(EvidenceDossier.evidence_id).where(
        EvidenceDossier.tenant_id == tenant_id,
        EvidenceDossier.dossier_id == dossier_id,
    )
    oracle_evidence = [
        {
            "id": str(row.id),
            "source_kind": row.source_kind,
            "extract": (row.extract or "")[:1200],
            "classification": row.classification,
            "checksum": row.checksum.hex() if row.checksum else None,
        }
        for row in session.scalars(
            select(Evidence)
            .where(
                Evidence.id.in_(evidence_ids),
                Evidence.tenant_id == tenant_id,
                Evidence.source_kind.in_(DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS),
            )
            .order_by(Evidence.created_at.desc())
            .limit(40)
        )
    ]

    return build_oracle_authority_block(
        dossier_id=str(dossier_id),
        tenant_id=str(tenant_id),
        question=question,
        intent=intent_payload,
        requirements=requirements,
        offering=offering_payload,
        objectives=objectives,
        decisions=decisions,
        oracle_evidence=oracle_evidence,
    )


def _normalize_retrieval_item(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a Signal retrieval item; return None if not citable.

    Items without verifiable source_ref, version-or-checksum, extract/text and
    locator are excluded. Runtime never invents synthetic://mock, checksum or
    locator — fixtures must supply them explicitly.
    """

    text = str(raw.get("text") or raw.get("extract") or "").strip()
    if not text:
        return None
    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        return None
    source_ref = str(raw.get("source_ref") or "").strip()
    if not source_ref or source_ref.startswith("synthetic://"):
        return None
    checksum = str(raw.get("checksum") or "").strip()
    source_version = str(raw.get("source_version") or raw.get("version") or "").strip()
    # Require verifiable version-or-checksum; never invent either at runtime.
    if not checksum and not source_version:
        return None
    if not checksum:
        # Explicit version without separate checksum: use version string as checksum key.
        checksum = source_version
    locator = raw.get("locator")
    if isinstance(locator, dict):
        locator_s = json.dumps(locator, sort_keys=True, separators=(",", ":"))
    else:
        locator_s = str(locator or "").strip()
    if not locator_s:
        return None
    classification = str(raw.get("classification") or "internal").strip() or "internal"
    if classification not in {"public", "internal"}:
        classification = "internal"
    policy_version = str(raw.get("policy_version") or "").strip()
    watermark = str(raw.get("watermark") or "").strip()
    if not policy_version or not watermark:
        return None
    return {
        "id": item_id,
        "text": text[:8000],
        "source_ref": source_ref,
        "checksum": checksum,
        "locator": locator_s,
        "classification": classification,
        "policy_version": policy_version,
        "watermark": watermark,
        "source_version": source_version or checksum,
        "kind": str(raw.get("kind") or "chunk"),
        "score": raw.get("score"),
        "occurred_at": raw.get("occurred_at"),
    }


def materialize_augment_items(
    items: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str,
    dossier_id: str,
    existing_mappings: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[MaterializedCitation], list[EvidenceMappingRow], list[dict[str, Any]]]:
    """Materialize citable Evidence mappings; rematerialize or exclude on checksum change.

    Reuses an existing mapping only when tenant+dossier+source_ref+checksum+extract+locator
    match exactly. A new checksum forces rematerialization (new evidence id).
    """

    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in existing_mappings or []:
        key = (
            str(row.get("source_ref") or ""),
            str(row.get("checksum") or ""),
            str(row.get("locator") or ""),
        )
        if all(key):
            index[key] = row

    citations: list[MaterializedCitation] = []
    mappings: list[EvidenceMappingRow] = []
    excluded: list[dict[str, Any]] = []

    for raw in items:
        normalized = _normalize_retrieval_item(raw)
        if normalized is None:
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": "not_citable",
                    "id": str(raw.get("id") or "")[:80],
                }
            )
            continue
        # Tenant/dossier exactness: item-level overrides must match call scope.
        item_tenant = str(raw.get("tenant_id") or tenant_id)
        item_dossier = str(raw.get("dossier_id") or dossier_id)
        if item_tenant != str(tenant_id) or item_dossier != str(dossier_id):
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": "tenant_or_dossier_mismatch",
                    "id": normalized["id"],
                }
            )
            continue
        key = (normalized["source_ref"], normalized["checksum"], normalized["locator"])
        prior = index.get(key)
        evidence_id: str | None = None
        if prior is not None:
            prior_extract = str(prior.get("exact_excerpt") or prior.get("extract") or "")
            if (
                str(prior.get("tenant_id") or "") == str(tenant_id)
                and str(prior.get("dossier_id") or "") == str(dossier_id)
                and prior_extract[:8000] == normalized["text"][:8000]
            ):
                evidence_id = str(prior.get("oracle_evidence_id") or prior.get("evidence_id") or "")
                if not evidence_id:
                    evidence_id = None
        try:
            citation = materialize_signal_item_to_evidence(
                normalized,
                tenant_id=str(tenant_id),
                dossier_id=str(dossier_id),
                evidence_id=evidence_id,
            )
        except ValueError as exc:
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": f"materialize_failed:{exc}",
                    "id": normalized["id"],
                }
            )
            continue
        citations.append(citation)
        mappings.append(
            EvidenceMappingRow(
                signal_item_id=citation.signal_item_id,
                oracle_evidence_id=citation.oracle_evidence_id,
                source_ref=citation.source_ref,
                source_version=str(normalized["source_version"]),
                checksum=citation.checksum,
                classification=citation.classification,
                locator=citation.locator,
            )
        )
    return citations, mappings, excluded


def build_signal_factual_block(
    *,
    mode: MemoryMode,
    citations: Sequence[MaterializedCitation],
    observed_count: int,
) -> dict[str, Any]:
    """Signal factual evidence block. Shadow always has zero injectable items."""

    inject = should_inject_into_llm(mode)
    items_for_prompt: list[dict[str, Any]] = []
    if inject:
        for c in citations:
            items_for_prompt.append(
                {
                    "evidence_id": c.oracle_evidence_id,
                    "signal_item_id": c.signal_item_id,
                    "text": c.exact_excerpt,
                    "source_ref": c.source_ref,
                    "checksum": c.checksum,
                    "locator": c.locator,
                    "classification": c.classification,
                    "untrusted_external": True,
                }
            )
    return {
        "block": "signal_factual",
        "mode": mode,
        "observed_count": observed_count,
        "inject_into_llm": inject,
        "items": items_for_prompt,
        "untrusted_external": True,
        "note": (
            "shadow_zero_injection"
            if mode == "shadow"
            else ("augment_citable_only" if mode == "augment" else "disabled")
        ),
    }


def build_input_manifest(
    *,
    mode: MemoryMode,
    oracle_authority: Mapping[str, Any],
    signal_factual: Mapping[str, Any],
    allowed_evidence_ids: Sequence[str],
    coverage: Mapping[str, Any],
    prompt_runtime_id: str = PROMPT_RUNTIME_ID,
    prompt_runtime_version: str = PROMPT_RUNTIME_VERSION,
    schema_runtime_version: str = SCHEMA_RUNTIME_VERSION,
    memory_policy: str,
    job_id: str | None = None,
    message_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Reconstructible input manifest for the effective task payload (hash included)."""

    evidence_hashes = [
        {
            "evidence_id": item.get("evidence_id"),
            "checksum": item.get("checksum"),
            "source_ref": item.get("source_ref"),
        }
        for item in list(signal_factual.get("items") or [])
        if isinstance(item, dict)
    ]
    manifest = {
        "version": "ask_input_manifest.v1",
        "mode": mode,
        "prompt_runtime_id": prompt_runtime_id,
        "prompt_runtime_version": prompt_runtime_version,
        "schema_runtime_version": schema_runtime_version,
        "memory_policy": memory_policy,
        "job_id": job_id,
        "message_id": message_id,
        "oracle_authority_hash": _stable_hash(oracle_authority),
        "signal_item_count": len(list(signal_factual.get("items") or [])),
        "allowed_evidence_ids": list(allowed_evidence_ids),
        "evidence_hashes": evidence_hashes,
        "coverage_summary": {
            "requested": coverage.get("requested"),
            "used": coverage.get("used"),
            "failed": coverage.get("failed"),
            "excluded": coverage.get("excluded"),
            "truncated": coverage.get("truncated"),
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    # Shadow must deterministically show zero Signal items even if retrieval non-empty.
    if mode == "shadow":
        assert manifest["signal_item_count"] == 0
        assert manifest["allowed_evidence_ids"] == []
        assert manifest["evidence_hashes"] == []
    digest = _stable_hash(manifest)
    manifest["manifest_sha256"] = digest
    return manifest, digest


def validate_citations_allowlist(
    citations: Sequence[Mapping[str, Any]] | Sequence[Any],
    allowed_evidence_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (accepted_citations, rejected_ids). Precision must be 100% on allowlist.

    Empty allowlist rejects every citation (zero Evidence permitted). Safe answers
    with no citations return ``([], [])``.
    """

    allowed = {str(x) for x in allowed_evidence_ids}
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for raw in citations or []:
        if not isinstance(raw, Mapping):
            rejected.append("<non-object>")
            continue
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid or eid not in allowed:
            rejected.append(eid or "<missing>")
            continue
        accepted.append(dict(raw))
    return accepted, rejected


def validate_material_evidence_allowlist(
    material_items: Sequence[Mapping[str, Any]] | Sequence[Any] | None,
    allowed_evidence_ids: Sequence[str],
    *,
    kind: str = "facts",
) -> list[str]:
    """Return unauthorized evidence refs in material facts/claims.

    Empty allowlist rejects any non-empty material block (no assertions without
    Evidence). Non-empty allowlist requires every evidence_id ∈ allowlist.
    """

    allowed = {str(x).strip() for x in allowed_evidence_ids if str(x).strip()}
    rejected: list[str] = []
    items = list(material_items or [])
    if items and not allowed:
        rejected.append(f"{kind}:empty_allowlist")
        return rejected
    for raw in items:
        if not isinstance(raw, Mapping):
            rejected.append(f"{kind}:<non-object>")
            continue
        eids = raw.get("evidence_ids")
        if eids is None and raw.get("evidence_id") is not None:
            eids = [raw.get("evidence_id")]
        if not isinstance(eids, list) or not eids:
            rejected.append(f"{kind}:missing_evidence")
            continue
        for eid in eids:
            sid = str(eid or "").strip()
            if not sid or sid not in allowed:
                rejected.append(sid or f"{kind}:<missing>")
    return rejected


def link_snapshot_run_usage(
    snapshot_payload: dict[str, Any],
    *,
    run_id: str | None = None,
    usage_log_id: str | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    """Attach post-execution links without rewriting frozen snapshot core fields."""

    frozen_keys = (
        "mode",
        "items",
        "items_observed",
        "coverage",
        "input_manifest",
        "input_manifest_hash",
        "allowed_evidence_ids",
        "mappings",
        "oracle_authority_hash",
    )
    core = {k: snapshot_payload.get(k) for k in frozen_keys if k in snapshot_payload}
    links = dict(snapshot_payload.get("post_links") or {})
    if run_id:
        links["run_id"] = str(run_id)
    if usage_log_id:
        links["usage_log_id"] = str(usage_log_id)
    if attempts is not None:
        links["attempts"] = int(attempts)
    links["linked_at"] = datetime.now(UTC).isoformat()
    rest = {k: v for k, v in snapshot_payload.items() if k not in core}
    return {**core, **rest, "post_links": links}


def build_dual_ask_context(
    *,
    mode: MemoryMode,
    tenant_id: str,
    dossier_id: str,
    question: str,
    retrieval_items: Sequence[Mapping[str, Any]],
    coverage_manifest: Mapping[str, Any] | None,
    memory_policy: str,
    oracle_authority: Mapping[str, Any] | None = None,
    existing_mappings: Sequence[Mapping[str, Any]] | None = None,
    job_id: str | None = None,
    message_id: str | None = None,
) -> DualAskContext:
    """Compose dual blocks + materialization + input manifest for one ask execution."""

    authority = dict(
        oracle_authority
        or build_oracle_authority_block(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            question=question,
        )
    )
    observed = list(retrieval_items or [])
    coverage = dict(coverage_manifest or {})
    excluded: list[dict[str, Any]] = list(coverage.get("excluded") or [])
    citations: list[MaterializedCitation] = []
    mappings: list[EvidenceMappingRow] = []

    if mode == "augment":
        citations, mappings, mat_excluded = materialize_augment_items(
            observed,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            existing_mappings=existing_mappings,
        )
        excluded.extend(mat_excluded)
    elif mode == "shadow":
        # Retrieve/snapshot observed items but inject zero.
        for raw in observed:
            if _normalize_retrieval_item(raw) is None:
                excluded.append(
                    {
                        "source": "signal_item",
                        "reason": "not_citable_shadow_audit",
                        "id": str(raw.get("id") or "")[:80],
                    }
                )
    else:
        # disabled — no Signal items
        observed = []

    coverage["excluded"] = excluded
    if "used" not in coverage:
        coverage["used"] = [c.oracle_evidence_id for c in citations] if mode == "augment" else []
    if "failed" not in coverage:
        coverage["failed"] = coverage.get("failed") or []

    signal_block = build_signal_factual_block(
        mode=mode,
        citations=citations,
        observed_count=len(retrieval_items or []),
    )
    allowed = tuple(c.oracle_evidence_id for c in citations) if mode == "augment" else ()
    manifest, digest = build_input_manifest(
        mode=mode,
        oracle_authority=authority,
        signal_factual=signal_block,
        allowed_evidence_ids=allowed,
        coverage=coverage,
        memory_policy=memory_policy,
        job_id=job_id,
        message_id=message_id,
    )
    return DualAskContext(
        mode=mode,
        oracle_authority=authority,
        signal_factual=signal_block,
        citations=tuple(citations),
        mappings=tuple(mappings),
        allowed_evidence_ids=allowed,
        coverage=coverage,
        input_manifest=manifest,
        input_manifest_hash=digest,
        excluded=tuple(excluded),
    )


def dual_context_to_snapshot(ctx: DualAskContext) -> dict[str, Any]:
    return {
        "mode": ctx.mode,
        "inject_into_llm": ctx.signal_factual.get("inject_into_llm"),
        "items_observed": ctx.signal_factual.get("observed_count"),
        "items": list(ctx.signal_factual.get("items") or []),
        "allowed_evidence_ids": list(ctx.allowed_evidence_ids),
        "mappings": [asdict(m) for m in ctx.mappings],
        "coverage": ctx.coverage,
        "input_manifest": ctx.input_manifest,
        "input_manifest_hash": ctx.input_manifest_hash,
        "oracle_authority_hash": ctx.input_manifest.get("oracle_authority_hash"),
        "prompt_runtime_id": PROMPT_RUNTIME_ID,
        "prompt_runtime_version": PROMPT_RUNTIME_VERSION,
        "schema_runtime_version": SCHEMA_RUNTIME_VERSION,
    }


def persist_memory_signal_evidence(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    citations: Sequence[MaterializedCitation],
    job_id: str | None = None,
) -> list[str]:
    """Persist immutable Evidence rows (source_kind=memory_signal) + dossier links.

    Requires migration 0030. When the constraint is missing, raises so caller can
    fall back to mapping-only (fail-visible debt).
    """

    from sqlalchemy import select

    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Evidence

    ids: list[str] = []
    for c in citations:
        evidence_id = uuid.UUID(str(c.oracle_evidence_id))
        try:
            checksum = bytes.fromhex(c.checksum) if len(c.checksum) == 64 else b""
        except ValueError:
            checksum = b""
        if len(checksum) != 32:
            checksum = hashlib.sha256(c.exact_excerpt.encode("utf-8")).digest()
        existing = session.scalar(
            select(Evidence).where(Evidence.id == evidence_id, Evidence.tenant_id == tenant_id)
        )
        if existing is None:
            # Checksum/version change uses a new evidence_id (caller rematerializes).
            session.add(
                Evidence(
                    id=evidence_id,
                    tenant_id=tenant_id,
                    source_kind="memory_signal",
                    source_url=None,
                    extract=c.exact_excerpt[:8000],
                    locator={"raw": c.locator, "source_ref": c.source_ref},
                    checksum=checksum,
                    classification=c.classification
                    if c.classification in {"public", "internal"}
                    else "internal",
                    provenance={
                        "source_kind": "memory_signal",
                        "signal_item_id": c.signal_item_id,
                        "source_ref": c.source_ref,
                        "checksum": c.checksum,
                        "policy_version": c.policy_version,
                        "watermark": c.watermark,
                        "job_id": job_id,
                        "materialized_at": datetime.now(UTC).isoformat(),
                        "mapping_version": "memory_evidence_map.v1",
                    },
                    version=1,
                )
            )
            session.flush()
        else:
            # Never rewrite immutable extract/checksum; mismatch means exclude upstream.
            if existing.checksum != checksum:
                continue
        link = session.scalar(
            select(EvidenceDossier).where(
                EvidenceDossier.tenant_id == tenant_id,
                EvidenceDossier.evidence_id == evidence_id,
                EvidenceDossier.dossier_id == dossier_id,
            )
        )
        if link is None:
            session.add(
                EvidenceDossier(
                    tenant_id=tenant_id,
                    evidence_id=evidence_id,
                    dossier_id=dossier_id,
                )
            )
            session.flush()
        ids.append(str(evidence_id))
    return ids
