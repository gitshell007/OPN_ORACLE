"""G-18 · materialización íntegra de fuentes cerradas → Evidence + EvidenceDossier.

No crea Evidence durante discovery. Solo tras acción humana explícita
(aceptación por candidate_id + source_ids ⊆ candidate.evidence_ids ⊆ reserved).

Garantías:
- Solo artifact status="candidate" inicia la acción (rejected/superseded/otros → 409).
- Aceptaciones concurrentes del mismo artifact se serializan con FOR UPDATE.
- Evidence PK determinista (tenant+artifact+source_id) → reintento y carrera
  terminan en 1 Evidence + 1 EvidenceDossier.
- Una sola transacción; fallo medio revierte todo (sin commits internos).
- Artifact permanece en "candidate" para reintento idempotente.
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
from opn_oracle.tenants.context import require_tenant_id


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


def load_tenant_artifact(
    artifact_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    for_update: bool = False,
) -> AIArtifact:
    """Load market_competitor_discovery artifact for this tenant.

    When for_update=True, takes a PostgreSQL row lock (FOR UPDATE) so concurrent
    accepts of the same artifact serialize. On SQLite the clause is ignored/no-op
    enough for sequential tests.
    """

    tenant_id = require_tenant_id()
    stmt = select(AIArtifact).where(
        AIArtifact.id == artifact_id,
        AIArtifact.tenant_id == tenant_id,
        AIArtifact.agent == "market_competitor_discovery",
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
            detail = "El artifact de discovery fue sustituido; vuelve a proponer competidores."
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
    """Validate human selection: candidate_id + non-empty source_ids.

    Always enforces: source_ids ⊆ candidate.evidence_ids ⊆ reserved.
    No empty-name / name-only permissive path on new writes.
    ``name`` in selection is display-only and ignored for identity.
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
    seen: set[str] = set()
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
            if sid not in seen:
                seen.add(sid)
                resolved.append(sid)
    if not resolved:
        raise MaterializeError(
            "selection_empty",
            "No quedó ningún source_id válido tras validar la selección.",
            status=422,
        )
    return resolved


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
            "created_by": "oracle.g18.market_competitor_materialize",
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


def accept_and_materialize(
    *,
    artifact_id: uuid.UUID,
    dossier_id: uuid.UUID,
    selected: list[dict[str, Any]],
    expected_version: int | None = None,
) -> dict[str, Any]:
    """Full human gate: lock artifact → validate → materialize in one txn.

    State machine:
    - Only status=candidate may start.
    - Artifact status is NOT flipped to valid/rejected here so exact retry remains
      idempotent (same evidence_id + count, no new rows).
    - Human audit of acceptance is recorded in Evidence.provenance.created_by
      and locator.artifact_id (existing path); optional AIHumanReview is separate.
    """

    # Lock artifact row first so concurrent accepts serialize.
    artifact = load_tenant_artifact(
        artifact_id,
        expected_version=expected_version,
        for_update=True,
    )
    source_ids = resolve_selected_source_ids(artifact, selected=selected)
    try:
        evidences = materialize_web_search_sources(
            artifact=artifact,
            dossier_id=dossier_id,
            source_ids=source_ids,
        )
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


def materialize_web_search_sources_with_fault(
    *,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    source_ids: list[str],
    fail_after_index: int | None = None,
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
) -> dict[str, Any]:
    """Test-only accept path that can inject a failure after N sources."""

    artifact = load_tenant_artifact(
        artifact_id,
        expected_version=expected_version,
        for_update=True,
    )
    source_ids = resolve_selected_source_ids(artifact, selected=selected)
    try:
        evidences = materialize_web_search_sources_with_fault(
            artifact=artifact,
            dossier_id=dossier_id,
            source_ids=source_ids,
            fail_after_index=fail_after_index,
        )
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
