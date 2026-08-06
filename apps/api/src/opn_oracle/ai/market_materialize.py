"""G-18 · materialización íntegra de fuentes cerradas → Evidence + EvidenceDossier.

No crea Evidence durante discovery. Solo tras acción humana explícita
(aceptación por candidate_id + source_ids ⊆ candidate.evidence_ids ⊆ reserved).

Garantías:
- Solo artifact status="candidate" inicia la acción (rejected/superseded/otros → 409).
- Aceptaciones concurrentes del mismo artifact se serializan con FOR UPDATE.
- Evidence PK determinista (tenant+artifact+source_id) → reintento y carrera
  terminan en 1 Evidence + 1 EvidenceDossier.
- Auditoría humana durable (AuditEvent) con UUID determinista de la selección;
  reintento idéntico → 1 evento; selección distinta → evento nuevo.
- Una sola transacción (Evidence + links + AuditEvent); fallo medio revierte todo.
- Artifact permanece en "candidate" para reintento idempotente y selección parcial.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from opn_oracle.ai.citable_sources import (
    SOURCE_KIND_WEB_SEARCH,
    content_checksum,
    deterministic_web_search_evidence_id,
    is_safe_public_http_url,
)
from opn_oracle.ai.models import AIArtifact
from opn_oracle.extensions import db
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import Evidence, StrategicDossier
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.platform.models import AuditEvent
from opn_oracle.tenants.context import get_tenant_context, require_tenant_id

# Server-owned namespace for human-accept audit event IDs (v1). Never from client JSON.
ACCEPT_AUDIT_NAMESPACE = uuid.UUID("8d4a2e1c-7b63-4f0a-9c9e-18a18f020003")

# Canonical material for deterministic AuditEvent.id (document in gate packet):
#   g18:market_accept:v1|{tenant_id}|{artifact_id}|{dossier_id}|
#   {sorted_candidate_ids_csv}|{sorted_source_ids_csv}
#
# Semantics: AIHumanReview is reserved for the separate /artifacts/.../reviews flow
# that flips artifact status. This gate records a durable AuditEvent without changing
# artifact status, so exact retry and partial second selection remain valid.


class MaterializeError(Exception):
    def __init__(self, code: str, detail: str, *, status: int = 422) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(detail)


_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


def _checksum_bytes(content_checksum_value: str) -> bytes:
    raw = str(content_checksum_value or "").strip()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    if not _HEX_RE.match(raw):
        raise MaterializeError(
            "invalid_checksum",
            "El content_checksum de la fuente reservada no es sha256 válido.",
            status=422,
        )
    return bytes.fromhex(raw)


# Agents that may materialize reserved web_search sources into Evidence (G-18/G-19).
MARKET_MATERIALIZE_AGENTS = frozenset(
    {
        "market_competitor_discovery",
        "market_actor_discovery",
    }
)

ACCEPT_AUDIT_ACTIONS: dict[str, str] = {
    "market_competitor_discovery": "ai.market_competitor_discovery.accept",
    "market_actor_discovery": "ai.market_actor_discovery.accept",
}

ACCEPT_AUDIT_GATES: dict[str, str] = {
    "market_competitor_discovery": "market_competitor_discovery.accept",
    "market_actor_discovery": "market_actor_discovery.accept",
}

CREATED_BY_PROVENANCE: dict[str, str] = {
    "market_competitor_discovery": "oracle.g18.market_competitor_materialize",
    "market_actor_discovery": "oracle.g19.market_actor_materialize",
}


def load_tenant_artifact(
    artifact_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    for_update: bool = False,
    agent: str = "market_competitor_discovery",
) -> AIArtifact:
    """Load market discovery artifact for this tenant and agent.

    ``agent`` must match the artifact's agent (competitor vs actor endpoints are
    closed: cross-agent accept fails with artifact_not_found).

    When for_update=True, takes a PostgreSQL row lock (FOR UPDATE) so concurrent
    accepts of the same artifact serialize. On SQLite the clause is ignored/no-op
    enough for sequential tests.
    """

    if agent not in MARKET_MATERIALIZE_AGENTS:
        raise MaterializeError(
            "agent_not_materializable",
            "Este agente no admite materialización de fuentes cerradas.",
            status=422,
        )
    tenant_id = require_tenant_id()
    stmt = select(AIArtifact).where(
        AIArtifact.id == artifact_id,
        AIArtifact.tenant_id == tenant_id,
        AIArtifact.agent == agent,
    )
    if for_update:
        stmt = stmt.with_for_update()
    artifact = db.session.scalar(stmt)
    if artifact is None:
        raise MaterializeError(
            "artifact_not_found",
            "No hay artifact de discovery en este tenant.",
            status=404,
        )
    status = str(artifact.status or "")
    if status != "candidate":
        # rejected, superseded, valid, or unknown → 409 (not accept path)
        if status == "superseded":
            code = "artifact_superseded"
            detail = "El artifact de discovery fue sustituido; vuelve a proponer candidatos."
        elif status == "rejected":
            code = "artifact_rejected"
            detail = "El artifact de discovery fue rechazado; no se puede materializar."
        else:
            code = "artifact_not_acceptable"
            detail = (
                f"Solo un artifact en estado «candidate» puede materializarse "
                f"(estado actual: «{status}»)."
            )
        raise MaterializeError(code, detail, status=409)
    if expected_version is not None and int(artifact.version) != int(expected_version):
        raise MaterializeError(
            "artifact_version_drift",
            "La versión del artifact no coincide (posible carrera o artifact viejo).",
            status=409,
        )
    return artifact


def _reserved_map(artifact: AIArtifact) -> dict[str, dict[str, Any]]:
    output = artifact.output if isinstance(artifact.output, dict) else {}
    reserved = output.get("reserved_citable_sources") or []
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(reserved, list):
        return out
    for item in reserved:
        if not isinstance(item, dict):
            continue
        try:
            sid = str(uuid.UUID(str(item.get("source_id"))))
        except (ValueError, TypeError, AttributeError):
            continue
        out[sid] = item
    return out


def _candidate_by_id(artifact: AIArtifact) -> dict[str, dict[str, Any]]:
    """Index surviving candidates by server-owned candidate_id."""

    output = artifact.output if isinstance(artifact.output, dict) else {}
    candidates = output.get("candidates") or []
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(candidates, list):
        return index
    for item in candidates:
        if not isinstance(item, dict):
            continue
        raw = item.get("candidate_id")
        if raw is None:
            continue
        try:
            cid = str(uuid.UUID(str(raw)))
        except (ValueError, TypeError, AttributeError):
            continue
        index[cid] = item
    return index


def resolve_selected_source_ids(
    artifact: AIArtifact,
    *,
    selected: list[dict[str, Any]],
) -> list[str]:
    """Validate human selection; return ordered unique source_ids.

    Always enforces: source_ids ⊆ candidate.evidence_ids ⊆ reserved.
    ``name`` / client actor fields in selection are display-only / ignored.
    """

    source_ids, _candidate_ids = resolve_selection(artifact, selected=selected)
    return source_ids


def resolve_selection(
    artifact: AIArtifact,
    *,
    selected: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """Validate selection → (source_ids ordered unique, candidate_ids ordered unique).

    Client-supplied ``actor_id`` / ``reviewer_user_id`` in rows are ignored.
    """

    reserved = _reserved_map(artifact)
    candidates = _candidate_by_id(artifact)
    if not selected:
        raise MaterializeError(
            "selection_empty",
            "Debes seleccionar al menos un candidato con candidate_id y source_ids.",
            status=422,
        )
    resolved: list[str] = []
    seen_sources: set[str] = set()
    candidate_order: list[str] = []
    seen_candidates: set[str] = set()
    for row in selected:
        if not isinstance(row, dict):
            raise MaterializeError(
                "selection_invalid",
                "Cada selección debe ser un objeto con candidate_id y source_ids.",
                status=422,
            )
        raw_cid = row.get("candidate_id")
        if raw_cid is None or str(raw_cid).strip() == "":
            raise MaterializeError(
                "candidate_id_required",
                "candidate_id es obligatorio (UUID server-owned del artifact).",
                status=422,
            )
        try:
            candidate_id = str(uuid.UUID(str(raw_cid)))
        except (ValueError, TypeError, AttributeError) as error:
            raise MaterializeError(
                "candidate_id_invalid",
                "candidate_id debe ser un UUID válido.",
                status=422,
            ) from error
        cand = candidates.get(candidate_id)
        if cand is None:
            raise MaterializeError(
                "candidate_unknown",
                "El candidate_id no pertenece a este artifact (ajeno, otra corrida o tenant).",
                status=422,
            )
        if candidate_id not in seen_candidates:
            seen_candidates.add(candidate_id)
            candidate_order.append(candidate_id)
        display_name = " ".join(str(cand.get("name") or "").split()) or candidate_id
        raw_ids = row.get("source_ids") or row.get("evidence_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            raise MaterializeError(
                "selection_missing_sources",
                f"La selección de «{display_name}» no incluye source_ids no vacíos.",
                status=422,
            )
        cand_ids: set[str] = set()
        for item in cand.get("evidence_ids") or []:
            try:
                cand_ids.add(str(uuid.UUID(str(item))))
            except (ValueError, TypeError, AttributeError):
                continue
        if not cand_ids:
            raise MaterializeError(
                "candidate_without_evidence",
                f"El candidato «{display_name}» no tiene evidence_ids en el artifact.",
                status=422,
            )
        # Fail closed: every candidate evidence must be in reserved (integrity of artifact).
        if not cand_ids.issubset(set(reserved)):
            raise MaterializeError(
                "candidate_evidence_not_reserved",
                f"evidence_ids del candidato «{display_name}» no están en reserved.",
                status=422,
            )
        for item in raw_ids:
            try:
                sid = str(uuid.UUID(str(item)))
            except (ValueError, TypeError, AttributeError) as error:
                raise MaterializeError(
                    "source_id_invalid",
                    "Hay un source_id que no es UUID.",
                    status=422,
                ) from error
            if sid not in reserved:
                raise MaterializeError(
                    "source_id_not_reserved",
                    "Un source_id no está reservado en este artifact (ajeno o de otra corrida).",
                    status=422,
                )
            if sid not in cand_ids:
                raise MaterializeError(
                    "source_id_not_on_candidate",
                    f"El source_id no respalda al candidato «{display_name}» en el artifact.",
                    status=422,
                )
            if sid not in seen_sources:
                seen_sources.add(sid)
                resolved.append(sid)
    if not resolved:
        raise MaterializeError(
            "selection_empty",
            "No quedó ningún source_id válido tras validar la selección.",
            status=422,
        )
    return resolved, candidate_order


def deterministic_accept_audit_event_id(
    *,
    tenant_id: uuid.UUID | str,
    artifact_id: uuid.UUID | str,
    dossier_id: uuid.UUID | str,
    candidate_ids: list[str] | tuple[str, ...],
    source_ids: list[str] | tuple[str, ...],
) -> uuid.UUID:
    """Idempotent AuditEvent PK for one human acceptance selection.

    Canonical material (v1)::

        g18:market_accept:v1|{tenant}|{artifact}|{dossier}|
        {sorted_candidate_ids}|{sorted_source_ids}

    Same selection → same id (retry/concurrent). Materially different
    source/candidate set → different id (partial second accept is distinct).
    """

    sorted_cands = sorted({str(uuid.UUID(str(c))) for c in candidate_ids})
    sorted_sources = sorted({str(uuid.UUID(str(s))) for s in source_ids})
    material = (
        f"g18:market_accept:v1|{tenant_id}|{artifact_id}|{dossier_id}|"
        f"{','.join(sorted_cands)}|{','.join(sorted_sources)}"
    )
    return uuid.uuid5(ACCEPT_AUDIT_NAMESPACE, material)


# Backward-compat alias (competitor path default).
ACCEPT_AUDIT_ACTION = ACCEPT_AUDIT_ACTIONS["market_competitor_discovery"]
ACCEPT_AUDIT_RESOURCE_TYPE = "ai_artifact"


def _require_human_actor_id() -> uuid.UUID:
    """Fail closed: human accept requires TenantContext.actor_id (no service fallback)."""

    context = get_tenant_context(required=False)
    if context is None or context.actor_id is None:
        raise MaterializeError(
            "actor_required",
            "Se requiere un actor autenticado en el servidor para registrar la aceptación.",
            status=401,
        )
    return context.actor_id


def _validate_existing_accept_audit(
    existing: AuditEvent,
    *,
    tenant_id: uuid.UUID,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    expected_action: str,
) -> AuditEvent:
    """Reuse existing idempotent event only when identity fields match.

    Never substitutes actor silently on retry.
    """

    if existing.tenant_id != tenant_id:
        raise MaterializeError(
            "audit_tenant_mismatch",
            "Conflicto de identidad de auditoría entre tenants.",
            status=409,
        )
    if existing.action != expected_action:
        raise MaterializeError(
            "audit_action_mismatch",
            "El evento de auditoría reutilizado no corresponde a esta aceptación.",
            status=409,
        )
    if existing.resource_type != ACCEPT_AUDIT_RESOURCE_TYPE or existing.resource_id != artifact.id:
        raise MaterializeError(
            "audit_resource_mismatch",
            "El evento de auditoría reutilizado no apunta a este artifact.",
            status=409,
        )
    if existing.dossier_id != dossier_id:
        raise MaterializeError(
            "audit_dossier_mismatch",
            "El evento de auditoría reutilizado no apunta a este expediente.",
            status=409,
        )
    return existing


def _record_accept_audit_event(
    *,
    tenant_id: uuid.UUID,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    candidate_ids: list[str],
    source_ids: list[str],
    evidence_ids: list[str],
    expected_version: int | None,
    agent: str = "market_competitor_discovery",
) -> AuditEvent:
    """Insert or reuse durable human-accept AuditEvent inside the outer transaction.

    Creates the row via ``append_audit_event`` (tenant/actor from TenantContext).
    Deterministic PK + SAVEPOINT on IntegrityError (not SELECT+INSERT alone).
    Metadata is ID-only (no snippets, prompt, model output, or client actor fields).
    """

    # Fail closed before any write: human gate never falls back to service actor.
    _require_human_actor_id()
    expected_action = ACCEPT_AUDIT_ACTIONS.get(agent, ACCEPT_AUDIT_ACTION)
    gate = ACCEPT_AUDIT_GATES.get(agent, f"{agent}.accept")

    event_id = deterministic_accept_audit_event_id(
        tenant_id=tenant_id,
        artifact_id=artifact.id,
        dossier_id=dossier_id,
        candidate_ids=candidate_ids,
        source_ids=source_ids,
    )
    existing = db.session.get(AuditEvent, event_id)
    if existing is not None:
        return _validate_existing_accept_audit(
            existing,
            tenant_id=tenant_id,
            artifact=artifact,
            dossier_id=dossier_id,
            expected_action=expected_action,
        )

    sorted_cands = sorted({str(uuid.UUID(str(c))) for c in candidate_ids})
    sorted_sources = sorted({str(uuid.UUID(str(s))) for s in source_ids})
    sorted_evidence = sorted({str(uuid.UUID(str(e))) for e in evidence_ids})
    metadata = {
        "gate": gate,
        "agent": agent,
        "artifact_id": str(artifact.id),
        "dossier_id": str(dossier_id),
        "expected_version": expected_version,
        "candidate_ids": sorted_cands,
        "source_ids": sorted_sources,
        "evidence_ids": sorted_evidence,
        "count": len(sorted_evidence),
    }
    try:
        with db.session.begin_nested():
            # Common audit boundary: tenant/actor/actor_type derived from context;
            # optional event_id preserves deterministic idempotent PK.
            event = append_audit_event(
                db.session,
                action=expected_action,
                resource_type=ACCEPT_AUDIT_RESOURCE_TYPE,
                result="success",
                resource_id=artifact.id,
                dossier_id=dossier_id,
                metadata=metadata,
                event_id=event_id,
            )
            db.session.flush()
        return event
    except IntegrityError:
        existing = db.session.get(AuditEvent, event_id)
        if existing is None:
            raise MaterializeError(
                "audit_conflict",
                "Conflicto al registrar la aceptación humana; reintenta.",
                status=409,
            ) from None
        return _validate_existing_accept_audit(
            existing,
            tenant_id=tenant_id,
            artifact=artifact,
            dossier_id=dossier_id,
            expected_action=expected_action,
        )


def _load_market_dossier(dossier_id: uuid.UUID) -> StrategicDossier:
    tenant_id = require_tenant_id()
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        raise MaterializeError(
            "dossier_not_found",
            "El expediente de Mercado no está disponible en este tenant.",
            status=404,
        )
    if str(dossier.dossier_type or "") != "market":
        raise MaterializeError(
            "dossier_not_market",
            "Solo un expediente de tipo market puede recibir evidencias de discovery.",
            status=422,
        )
    return dossier


def _get_or_create_web_search_evidence(
    *,
    tenant_id: uuid.UUID,
    artifact: AIArtifact,
    sid: str,
    piece: dict[str, Any],
    agent: str = "market_competitor_discovery",
) -> Evidence:
    """Idempotent Evidence with deterministic UUID PK (tenant+artifact+source_id)."""

    url = str(piece.get("url") or "").strip()
    if not is_safe_public_http_url(url):
        raise MaterializeError(
            "source_url_unsafe",
            "La URL reservada no es http(s) pública segura.",
            status=422,
        )
    title = str(piece.get("title") or "")[:300]
    snippet = str(piece.get("snippet") or "")[:800]
    checksum_hdr = str(piece.get("content_checksum") or "").strip()
    expected = content_checksum(title=title, snippet=snippet, url=url)
    if checksum_hdr != expected:
        raise MaterializeError(
            "source_checksum_mismatch",
            "El checksum de la fuente reservada no coincide con title/snippet/url.",
            status=422,
        )

    evidence_id = deterministic_web_search_evidence_id(
        tenant_id=tenant_id,
        artifact_id=artifact.id,
        source_id=sid,
    )
    existing = db.session.get(Evidence, evidence_id)
    if existing is not None:
        if existing.tenant_id != tenant_id:
            raise MaterializeError(
                "evidence_tenant_mismatch",
                "Conflicto de identidad de Evidence entre tenants.",
                status=409,
            )
        return existing

    extract = snippet or title or url
    locator = {
        "source_id": sid,
        "artifact_id": str(artifact.id),
        "rank": piece.get("rank"),
        "provider": piece.get("provider") or "",
        "origin": SOURCE_KIND_WEB_SEARCH,
    }
    evidence = Evidence(
        id=evidence_id,
        tenant_id=tenant_id,
        signal_id=None,
        source_kind=SOURCE_KIND_WEB_SEARCH,
        source_url=url,
        extract=extract[:12_000],
        locator=locator,
        checksum=_checksum_bytes(checksum_hdr),
        classification="public",
        provenance={
            "source_kind": SOURCE_KIND_WEB_SEARCH,
            "origin": SOURCE_KIND_WEB_SEARCH,
            "source_id": sid,
            "artifact_id": str(artifact.id),
            "label": piece.get("label") or title or url,
            "content_checksum": checksum_hdr,
            "created_by": CREATED_BY_PROVENANCE.get(
                agent, "oracle.g18.market_competitor_materialize"
            ),
        },
    )
    # SAVEPOINT so IntegrityError on concurrent insert does not poison the session.
    try:
        with db.session.begin_nested():
            db.session.add(evidence)
            db.session.flush()
        return evidence
    except IntegrityError:
        # Concurrent winner already inserted the same deterministic PK.
        existing = db.session.get(Evidence, evidence_id)
        if existing is None:
            raise MaterializeError(
                "evidence_conflict",
                "Conflicto al crear Evidence; reintenta la aceptación.",
                status=409,
            ) from None
        return existing


def _ensure_evidence_dossier_link(
    *,
    tenant_id: uuid.UUID,
    evidence_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> None:
    link = db.session.get(EvidenceDossier, (tenant_id, evidence_id, dossier_id))
    if link is not None:
        return
    try:
        with db.session.begin_nested():
            db.session.add(
                EvidenceDossier(
                    tenant_id=tenant_id,
                    evidence_id=evidence_id,
                    dossier_id=dossier_id,
                )
            )
            db.session.flush()
    except IntegrityError:
        # Concurrent link insert — already present.
        if db.session.get(EvidenceDossier, (tenant_id, evidence_id, dossier_id)) is None:
            raise MaterializeError(
                "link_conflict",
                "Conflicto al ligar Evidence al dossier; reintenta.",
                status=409,
            ) from None


def materialize_web_search_sources(
    *,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    source_ids: list[str],
    agent: str = "market_competitor_discovery",
) -> list[dict[str, Any]]:
    """Idempotent Evidence + EvidenceDossier for selected reserved sources.

    Single outer transaction (caller commits once). Mid-flight failure leaves
    no partial rows. Partial selection materializes only chosen sources;
    a later accept can add another source without duplicating the first.
    """

    tenant_id = require_tenant_id()
    _load_market_dossier(dossier_id)
    reserved = _reserved_map(artifact)
    created_or_existing: list[dict[str, Any]] = []
    for sid in source_ids:
        piece = reserved.get(sid)
        if piece is None:
            raise MaterializeError(
                "source_id_not_reserved",
                "Source_id no reservado en el artifact.",
                status=422,
            )
        existing = _get_or_create_web_search_evidence(
            tenant_id=tenant_id,
            artifact=artifact,
            sid=sid,
            piece=piece,
            agent=agent,
        )
        _ensure_evidence_dossier_link(
            tenant_id=tenant_id,
            evidence_id=existing.id,
            dossier_id=dossier_id,
        )
        title = str(piece.get("title") or "")[:300]
        created_or_existing.append(
            {
                "evidence_id": str(existing.id),
                "source_id": sid,
                "source_kind": SOURCE_KIND_WEB_SEARCH,
                "source_url": existing.source_url,
                "label": (existing.provenance or {}).get("label") or title,
            }
        )
    return created_or_existing


# Strong identity schemes used for identity-first Actor resolution (G-20-B corrective).
# Order is priority for stable identity-based canonical_key and lookup.
STRONG_ACTOR_ID_KEYS: tuple[str, ...] = ("rnsr", "ror", "hal_structure", "cordis_org")


def _structured_identifier_snapshot(candidate: dict[str, Any]) -> dict[str, str]:
    """Durable strong IDs from closed candidate snapshot (never invent)."""

    raw_value = candidate.get("ids")
    raw: dict[str, Any] = raw_value if isinstance(raw_value, dict) else {}
    out: dict[str, str] = {}
    for key in (*STRONG_ACTOR_ID_KEYS, "idref"):
        val = str(raw.get(key) or "").strip()
        if val:
            out[key] = val[:120]
    return out


def _strong_ids_only(ids: dict[str, Any] | None) -> dict[str, str]:
    """Return only non-empty strong identity keys from an identifiers map."""

    out: dict[str, str] = {}
    if not isinstance(ids, dict):
        return out
    for key in STRONG_ACTOR_ID_KEYS:
        val = str(ids.get(key) or "").strip()
        if val:
            out[key] = val[:120]
    return out


def actor_identity_canonical_key(ids_snap: dict[str, str], organization: str) -> str:
    """Stable Actor.canonical_key: strong-ID scheme first, else nominal name key.

    Homonyms with different ROR/RNSR must not share a nominal key; identity-based
    keys keep them as separate durable entities without mutating each other.
    """

    from opn_oracle.oracle.actor_candidates import actor_canonical_key

    for scheme in STRONG_ACTOR_ID_KEYS:
        val = str(ids_snap.get(scheme) or "").strip()
        if val:
            return f"{scheme}:{val}".casefold()[:320]
    return actor_canonical_key(organization)


def _identifier_conflicts(
    existing: dict[str, Any] | None, incoming: dict[str, str]
) -> list[dict[str, str]]:
    """Strong-ID pairs where both sides are non-empty and differ."""

    conflicts: list[dict[str, str]] = []
    base = existing if isinstance(existing, dict) else {}
    for key in STRONG_ACTOR_ID_KEYS:
        prev = str(base.get(key) or "").strip()
        new = str(incoming.get(key) or "").strip()
        if prev and new and prev != new:
            conflicts.append({"key": key, "existing": prev, "incoming": new})
    return conflicts


def _merge_actor_identifiers(
    existing: dict[str, Any] | None,
    incoming: dict[str, str],
) -> dict[str, Any]:
    """Merge strong IDs without overwriting a previously set different value.

    Missing keys are filled; conflicts on the same key keep the prior durable value
    and record the clash under ``identifier_conflicts`` (no silent overwrite).

    Identity-first import must not rely on this path for homonyms with incompatible
    IDs — those abort with 409 or create a separate identity-keyed Actor first.
    """

    base: dict[str, Any] = dict(existing or {})
    conflicts: list[dict[str, str]] = list(base.get("identifier_conflicts") or [])
    for key, value in incoming.items():
        prev = base.get(key)
        if prev is None or str(prev).strip() == "":
            base[key] = value
        elif str(prev).strip() != value:
            conflicts.append({"key": key, "kept": str(prev), "ignored": value})
    if conflicts:
        base["identifier_conflicts"] = conflicts[-20:]
    return base


def _fill_missing_identifiers_only(
    existing: dict[str, Any] | None, incoming: dict[str, str]
) -> dict[str, Any]:
    """Fill blank strong IDs only; never record conflicts or overwrite.

    Caller must have already verified compatibility (no conflicting non-empty pairs).
    """

    base: dict[str, Any] = dict(existing or {})
    for key, value in incoming.items():
        prev = base.get(key)
        if prev is None or str(prev).strip() == "":
            base[key] = value
    # Drop stale conflict notes if present after a clean identity match.
    base.pop("identifier_conflicts", None)
    return base


def _actor_has_strong_ids(actor: Any) -> bool:
    return bool(_strong_ids_only(getattr(actor, "identifiers", None)))


def _find_actors_by_strong_ids(
    *,
    tenant_id: uuid.UUID,
    ids_snap: dict[str, str],
) -> list[Any]:
    """Return distinct Actors in tenant that exact-match any strong ID of the candidate.

    Identity-first: exact RNSR/ROR/HAL/CORDIS before any nominal name lookup.
    Portable across PostgreSQL JSONB and SQLite JSON used in unit tests.
    """

    if not ids_snap:
        return []
    from opn_oracle.oracle.models import Actor

    # Narrow to tenant; match schemes in Python for engine portability.
    rows = list(db.session.scalars(select(Actor).where(Actor.tenant_id == tenant_id)).all())
    matched: dict[str, Any] = {}
    for scheme in STRONG_ACTOR_ID_KEYS:
        want = str(ids_snap.get(scheme) or "").strip()
        if not want:
            continue
        for actor in rows:
            have = _strong_ids_only(
                actor.identifiers if isinstance(actor.identifiers, dict) else {}
            )
            if have.get(scheme) == want:
                matched[str(actor.id)] = actor
    return list(matched.values())


def _plan_single_actor_resolution(
    *,
    tenant_id: uuid.UUID,
    organization: str,
    ids_snap: dict[str, str],
    candidate_id: str,
) -> tuple[Any | None, str, str]:
    """Resolve target Actor for one candidate without writing.

    Returns ``(existing_or_None, canonical_key, resolution)`` where resolution is one of:
    - ``reuse_by_id``: exact strong-ID match (idempotent import)
    - ``reuse_by_name``: name-only path (no strong IDs on candidate and compatible)
    - ``create``: new durable Actor (identity-keyed when IDs present)

    Raises MaterializeError 409 ``identity_conflict`` when a merge would corrupt
    identity (IDs point to different actors, or matched actor has incompatible IDs).
    Never reuses a nominal homonym that already holds a different strong ID.
    """

    from opn_oracle.oracle.actor_candidates import actor_canonical_key
    from opn_oracle.oracle.models import Actor

    name_key = actor_canonical_key(organization)
    identity_key = actor_identity_canonical_key(ids_snap, organization)

    if ids_snap:
        by_id = _find_actors_by_strong_ids(tenant_id=tenant_id, ids_snap=ids_snap)
        if len(by_id) > 1:
            raise MaterializeError(
                "identity_conflict",
                (
                    f"Los identificadores fuertes del candidato «{organization}» "
                    f"apuntan a {len(by_id)} actores distintos en el tenant. "
                    "No se puede importar sin corromper identidad. "
                    "Revisa RNSR/ROR/HAL/CORDIS y reintenta con un candidato inequívoco."
                ),
                status=409,
            )
        if len(by_id) == 1:
            existing = by_id[0]
            conflicts = _identifier_conflicts(
                existing.identifiers if isinstance(existing.identifiers, dict) else {},
                ids_snap,
            )
            if conflicts:
                # Matched on one scheme but another scheme disagrees — fail closed.
                detail_bits = ", ".join(
                    f"{c['key']}: existente={c['existing']} ≠ candidato={c['incoming']}"
                    for c in conflicts
                )
                raise MaterializeError(
                    "identity_conflict",
                    (
                        f"Conflicto de identidad al importar «{organization}» "
                        f"({detail_bits}). No se modifica el Actor existente. "
                        "Corrige el candidato o el Actor durable y reintenta."
                    ),
                    status=409,
                )
            return existing, str(existing.canonical_key), "reuse_by_id"

        # No exact ID match. Never attach to a name-homonym that already has IDs,
        # and never promote a name-only Actor by auto-filling strong IDs.
        name_hit = db.session.scalar(
            select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key == name_key)
        )
        if name_hit is not None:
            if _actor_has_strong_ids(name_hit):
                # Homonym with incompatible durable IDs → separate identity-keyed entity.
                # Do not mutate/link Actor A; do not leave identifier_conflicts and continue.
                return None, identity_key, "create"
            # Existing is name-only: conservative — do not promote by name to validated.
            # Create separate identity-stable Actor; leave the name-only row untouched.
            return None, identity_key, "create"

        # Free identity key (or collide with prior identity-keyed import → reuse).
        id_key_hit = db.session.scalar(
            select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key == identity_key)
        )
        if id_key_hit is not None:
            conflicts = _identifier_conflicts(
                id_key_hit.identifiers if isinstance(id_key_hit.identifiers, dict) else {},
                ids_snap,
            )
            if conflicts:
                raise MaterializeError(
                    "identity_conflict",
                    (
                        f"La clave de identidad «{identity_key}» ya existe con IDs "
                        f"incompatibles para «{organization}». No se escribe nada."
                    ),
                    status=409,
                )
            return id_key_hit, identity_key, "reuse_by_id"
        return None, identity_key, "create"

    # Candidate without strong IDs: nominal path only; never auto-validated.
    name_hit = db.session.scalar(
        select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key == name_key)
    )
    if name_hit is not None:
        # Reuse only when existing also has no conflicting strong IDs to fill from empty.
        # If existing has strong IDs, still allow link (name-only candidate → known org)
        # without changing identifiers or promoting identity_status on the durable row.
        return name_hit, str(name_hit.canonical_key), "reuse_by_name"
    return None, name_key, "create"


def plan_actor_materialization(
    *,
    artifact: AIArtifact,
    candidate_ids: list[str],
) -> list[dict[str, Any]]:
    """Pre-resolve all selected actors before any write (all-or-nothing identity gate).

    Raises MaterializeError 409 before Evidence/Actor/DossierActor/review/audit writes
    when identity cannot be resolved safely.
    """

    tenant_id = require_tenant_id()
    by_id = _candidate_by_id(artifact)
    plan: list[dict[str, Any]] = []
    for cid in candidate_ids:
        cand = by_id.get(cid)
        if cand is None:
            continue
        organization = " ".join(str(cand.get("organization") or "").split())
        if not organization:
            continue
        ids_snap = _structured_identifier_snapshot(cand)
        existing, canonical_key, resolution = _plan_single_actor_resolution(
            tenant_id=tenant_id,
            organization=organization,
            ids_snap=ids_snap,
            candidate_id=cid,
        )
        plan.append(
            {
                "candidate_id": cid,
                "candidate": cand,
                "organization": organization,
                "ids_snap": ids_snap,
                "existing": existing,
                "canonical_key": canonical_key,
                "resolution": resolution,
            }
        )
    return plan


def _materialize_selected_actors(
    *,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    candidate_ids: list[str],
    plan: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """G-20-B: create/link Actor + DossierActor for accepted market_actor candidates.

    Identity-first (corrective): exact RNSR/ROR/HAL/CORDIS before nominal name.
    Homonyms with incompatible strong IDs create a separate identity-keyed Actor
    or raise 409 — never mutate Actor A with ``identifier_conflicts`` and continue.
    Name-only existing rows are not auto-promoted to validated by name.
    Idempotent on same strong IDs. Does not mix lab vs umbrella without shared ID.
    """

    from opn_oracle.oracle.actor_candidates import set_actor_candidate_review
    from opn_oracle.oracle.models import Actor, DossierActor

    tenant_id = require_tenant_id()
    human_id = _require_human_actor_id()
    steps = (
        plan
        if plan is not None
        else plan_actor_materialization(artifact=artifact, candidate_ids=candidate_ids)
    )
    created: list[dict[str, Any]] = []
    for step in steps:
        cid = str(step["candidate_id"])
        cand = step["candidate"]
        organization = str(step["organization"])
        ids_snap: dict[str, str] = dict(step["ids_snap"] or {})
        existing = step["existing"]
        canonical_key = str(step["canonical_key"])
        resolution = str(step["resolution"])

        raw_type = str(cand.get("actor_type") or "organization").strip().lower()
        type_map = {
            "company": "organization",
            "research_group": "institution",
            "technology_center": "institution",
            "regulator": "institution",
            "potential_customer": "organization",
            "organization": "organization",
            "institution": "institution",
            "person": "person",
            "program": "program",
        }
        actor_type = type_map.get(raw_type, "institution")
        affiliation = " ".join(str(cand.get("affiliation") or "").split())[:300]
        parent = " ".join(str(cand.get("parent_organization") or "").split())[:300]
        identity_status = str(cand.get("identity_status") or "").strip().lower()
        # Conservative: no strong IDs → never durable-validated by name alone.
        if not ids_snap:
            durable_identity = "unresolved"
        elif identity_status == "validated":
            durable_identity = "validated"
        elif identity_status == "cross_referenced":
            durable_identity = "cross_referenced"
        else:
            durable_identity = "unresolved"

        provenance = {
            "source": "market_actor_discovery.accept",
            "artifact_id": str(artifact.id),
            "candidate_id": cid,
            "identity_status": durable_identity,
            "identity_resolution": resolution,
            "score_breakdown": cand.get("score_breakdown") or {},
            "ranking_reasons": list(cand.get("ranking_reasons") or [])[:20],
            "affiliation": affiliation,
            "parent_organization": parent or None,
            "candidate_key": cand.get("candidate_key"),
        }

        if existing is None:
            aliases: list[str] = []
            # When identity-keyed, keep nominal name as alias for search UX.
            if ids_snap and canonical_key.startswith(tuple(f"{k}:" for k in STRONG_ACTOR_ID_KEYS)):
                aliases = [organization[:300]]
            existing = Actor(
                tenant_id=tenant_id,
                actor_type=actor_type,
                canonical_name=organization[:300],
                canonical_key=canonical_key,
                aliases=aliases,
                identifiers=dict(ids_snap),
                actor_metadata={
                    "tags": [],
                    "discovery": provenance,
                    "affiliations": list(cand.get("affiliations") or [])[:20],
                },
                provenance=provenance,
            )
            db.session.add(existing)
            db.session.flush()
        else:
            # reuse_by_id / reuse_by_name: fill missing IDs only when compatible.
            # Compatibility already enforced in plan; never store identifier_conflicts.
            prior_ids = dict(existing.identifiers) if isinstance(existing.identifiers, dict) else {}
            identifiers_changed = False
            if resolution == "reuse_by_id" and ids_snap:
                filled = _fill_missing_identifiers_only(prior_ids, ids_snap)
                if filled != prior_ids:
                    existing.identifiers = filled
                    identifiers_changed = True
            # reuse_by_name: never promote name-only accept into new strong IDs
            # (candidate has none). Do not auto-upgrade identity_status on existing.
            meta = dict(existing.actor_metadata or {})
            meta["discovery"] = provenance
            if affiliation:
                affs = list(meta.get("affiliations") or [])
                if affiliation not in affs:
                    affs.append(affiliation)
                meta["affiliations"] = affs[:20]
            existing.actor_metadata = meta
            aliases = list(existing.aliases or [])
            if organization and organization not in aliases:
                aliases.append(organization[:300])
                existing.aliases = aliases[:40]
            # Exact retry (double-click): bump only when durable IDs actually change.
            # Metadata/alias refresh on first reuse still bumps for audit trail.
            if identifiers_changed or resolution != "reuse_by_id":
                existing.version = int(existing.version or 1) + 1
            elif not identifiers_changed and resolution == "reuse_by_id":
                # Idempotent same-ID import: leave version stable so concurrent CAS
                # and double-click do not inflate actor.version without data change.
                pass
            db.session.flush()

        link = db.session.scalar(
            select(DossierActor).where(
                DossierActor.tenant_id == tenant_id,
                DossierActor.dossier_id == dossier_id,
                DossierActor.actor_id == existing.id,
            )
        )
        if link is None:
            link = DossierActor(
                tenant_id=tenant_id,
                dossier_id=dossier_id,
                actor_id=existing.id,
                roles=["discovered_candidate"],
                notes=f"Importado desde market_actor_discovery ({durable_identity}/{resolution}).",
                influence=0,
                relevance_to_dossier=0,
                relationship_strength=0,
                accessibility=0,
                strategic_alignment=0,
                recent_activity=0,
                priority=0,
                score_details={},
            )
            db.session.add(link)
            db.session.flush()

        set_actor_candidate_review(
            db.session(),
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            candidate={
                "canonical_key": canonical_key,
                "name": organization[:300],
                "sources": [{"signal_id": sid} for sid in (cand.get("evidence_ids") or []) if sid],
            },
            status="imported",
            reviewed_by_user_id=human_id,
        )
        created.append(
            {
                "candidate_id": cid,
                "actor_id": str(existing.id),
                "dossier_actor_id": str(link.id),
                "canonical_key": canonical_key,
                "identifiers": dict(existing.identifiers or {}),
                "identity_status": durable_identity,
                "identity_resolution": resolution,
            }
        )
    return created


def accept_and_materialize(
    *,
    artifact_id: uuid.UUID,
    dossier_id: uuid.UUID,
    selected: list[dict[str, Any]],
    expected_version: int | None = None,
    agent: str = "market_competitor_discovery",
) -> dict[str, Any]:
    """Full human gate: lock → validate → materialize + human audit in one txn.

    State machine (artifact):
    - Only status=candidate may start (rejected/superseded/other → 409).
    - Status is NOT flipped to valid/rejected so exact retry stays idempotent
      and a later partial selection can still add more sources.
    - Technical provenance ``created_by`` is code identity only; the human
      decision is the AuditEvent (actor_id + selection metadata + created_at).

    ``agent`` selects competitor vs actor artifact (cross-agent accept fails).
    Actor and tenant come exclusively from ``TenantContext`` (via
    ``append_audit_event``). There is no public parameter to forge attribution.
    Context without actor fails closed before commit. Client JSON actor/reviewer
    fields are ignored.

    G-20-B: for market_actor_discovery also materializes selected Actors with
    durable RNSR/ROR/HAL/CORDIS identifiers (subset only; never the full list).
    """

    # Fail closed early: no actor in context → no writes.
    _require_human_actor_id()
    # Lock artifact row first so concurrent accepts serialize.
    artifact = load_tenant_artifact(
        artifact_id,
        expected_version=expected_version,
        for_update=True,
        agent=agent,
    )
    # G-19 actor discovery is dossier-scoped: accept only on the owning dossier.
    # Competitor pre-creation may still have dossier_id=None (attach on accept).
    if agent == "market_actor_discovery" and (
        artifact.dossier_id is None or artifact.dossier_id != dossier_id
    ):
        raise MaterializeError(
            "artifact_dossier_mismatch",
            "El artifact de descubrimiento no pertenece a este expediente.",
            status=404,
        )
    source_ids, candidate_ids = resolve_selection(artifact, selected=selected)
    # Identity gate BEFORE any Evidence/Actor write so 409 leaves zero rows.
    actor_plan: list[dict[str, Any]] | None = None
    if agent == "market_actor_discovery":
        actor_plan = plan_actor_materialization(artifact=artifact, candidate_ids=candidate_ids)
    try:
        evidences = materialize_web_search_sources(
            artifact=artifact,
            dossier_id=dossier_id,
            source_ids=source_ids,
            agent=agent,
        )
        evidence_ids = [str(row["evidence_id"]) for row in evidences]
        actors_out: list[dict[str, Any]] = []
        if agent == "market_actor_discovery":
            actors_out = _materialize_selected_actors(
                artifact=artifact,
                dossier_id=dossier_id,
                candidate_ids=candidate_ids,
                plan=actor_plan,
            )
        _record_accept_audit_event(
            tenant_id=require_tenant_id(),
            artifact=artifact,
            dossier_id=dossier_id,
            candidate_ids=candidate_ids,
            source_ids=source_ids,
            evidence_ids=evidence_ids,
            expected_version=expected_version,
            agent=agent,
        )
        db.session.commit()
    except MaterializeError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise
    result: dict[str, Any] = {
        "artifact_id": str(artifact.id),
        "dossier_id": str(dossier_id),
        "materialized": evidences,
        "count": len(evidences),
    }
    if agent == "market_actor_discovery":
        result["actors"] = actors_out
        result["actors_count"] = len(actors_out)
    return result


def materialize_web_search_sources_with_fault(
    *,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    source_ids: list[str],
    fail_after_index: int | None = None,
    agent: str = "market_competitor_discovery",
) -> list[dict[str, Any]]:
    """Same as materialize_web_search_sources but can inject a mid-flight fault.

    Used by tests to prove atomic rollback: after creating source at
    fail_after_index, raises RuntimeError before subsequent sources.
    """

    tenant_id = require_tenant_id()
    _load_market_dossier(dossier_id)
    reserved = _reserved_map(artifact)
    created_or_existing: list[dict[str, Any]] = []
    for index, sid in enumerate(source_ids):
        piece = reserved.get(sid)
        if piece is None:
            raise MaterializeError(
                "source_id_not_reserved",
                "Source_id no reservado en el artifact.",
                status=422,
            )
        existing = _get_or_create_web_search_evidence(
            tenant_id=tenant_id,
            artifact=artifact,
            sid=sid,
            piece=piece,
            agent=agent,
        )
        _ensure_evidence_dossier_link(
            tenant_id=tenant_id,
            evidence_id=existing.id,
            dossier_id=dossier_id,
        )
        title = str(piece.get("title") or "")[:300]
        created_or_existing.append(
            {
                "evidence_id": str(existing.id),
                "source_id": sid,
                "source_kind": SOURCE_KIND_WEB_SEARCH,
                "source_url": existing.source_url,
                "label": (existing.provenance or {}).get("label") or title,
            }
        )
        if fail_after_index is not None and index == fail_after_index:
            raise RuntimeError("injected_mid_materialize_failure")
    return created_or_existing


def accept_and_materialize_with_fault(
    *,
    artifact_id: uuid.UUID,
    dossier_id: uuid.UUID,
    selected: list[dict[str, Any]],
    expected_version: int | None = None,
    fail_after_index: int | None = None,
    fail_after_audit: bool = False,
    agent: str = "market_competitor_discovery",
) -> dict[str, Any]:
    """Test-only accept path that can inject failure mid-materialize or post-audit."""

    _require_human_actor_id()
    artifact = load_tenant_artifact(
        artifact_id,
        expected_version=expected_version,
        for_update=True,
        agent=agent,
    )
    source_ids, candidate_ids = resolve_selection(artifact, selected=selected)
    try:
        evidences = materialize_web_search_sources_with_fault(
            artifact=artifact,
            dossier_id=dossier_id,
            source_ids=source_ids,
            fail_after_index=fail_after_index,
            agent=agent,
        )
        evidence_ids = [str(row["evidence_id"]) for row in evidences]
        _record_accept_audit_event(
            tenant_id=require_tenant_id(),
            artifact=artifact,
            dossier_id=dossier_id,
            candidate_ids=candidate_ids,
            source_ids=source_ids,
            evidence_ids=evidence_ids,
            expected_version=expected_version,
            agent=agent,
        )
        if fail_after_audit:
            raise RuntimeError("injected_post_audit_failure")
        db.session.commit()
    except MaterializeError:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise
    return {
        "artifact_id": str(artifact.id),
        "dossier_id": str(dossier_id),
        "materialized": evidences,
        "count": len(evidences),
    }


def materialize_sha_placeholder() -> str:
    """Stable helper for tests that need a deterministic hex digest."""

    return hashlib.sha256(b"g18-web-search").hexdigest()
