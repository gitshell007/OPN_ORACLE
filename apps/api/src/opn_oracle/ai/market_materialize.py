"""G-18 · materialización diferida de fuentes cerradas → Evidence + EvidenceDossier.

No crea Evidence durante discovery. Solo tras acción humana explícita
(aceptación de candidatos + dossier de Mercado). Idempotente por
(tenant, source_id, artifact_id) vía provenance locator.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from sqlalchemy import select

from opn_oracle.ai.citable_sources import (
    SOURCE_KIND_WEB_SEARCH,
    content_checksum,
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
) -> AIArtifact:
    tenant_id = require_tenant_id()
    artifact = db.session.scalar(
        select(AIArtifact).where(
            AIArtifact.id == artifact_id,
            AIArtifact.tenant_id == tenant_id,
            AIArtifact.agent == "market_competitor_discovery",
        )
    )
    if artifact is None:
        raise MaterializeError(
            "artifact_not_found",
            "No hay artifact de discovery en este tenant.",
            status=404,
        )
    if artifact.status == "superseded":
        raise MaterializeError(
            "artifact_superseded",
            "El artifact de discovery fue sustituido; vuelve a proponer competidores.",
            status=409,
        )
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


def _candidate_index(artifact: AIArtifact) -> dict[str, dict[str, Any]]:
    output = artifact.output if isinstance(artifact.output, dict) else {}
    candidates = output.get("candidates") or []
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(candidates, list):
        return index
    for item in candidates:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split()).casefold()
        if name:
            index[name] = item
    return index


def resolve_selected_source_ids(
    artifact: AIArtifact,
    *,
    selected: list[dict[str, Any]],
) -> list[str]:
    """Validate human selection against artifact candidates + reserved sources.

    Each selection: {name?, source_ids: [...]} or {candidate_name, evidence_ids}.
    Fail-closed on alien UUIDs, unknown candidates, or modified sets.
    """

    reserved = _reserved_map(artifact)
    candidates = _candidate_index(artifact)
    if not selected:
        raise MaterializeError(
            "selection_empty",
            "Debes seleccionar al menos un candidato o source_id reservado.",
            status=422,
        )
    resolved: list[str] = []
    seen: set[str] = set()
    for row in selected:
        if not isinstance(row, dict):
            raise MaterializeError(
                "selection_invalid",
                "Cada selección debe ser un objeto con source_ids/evidence_ids.",
                status=422,
            )
        name = " ".join(str(row.get("name") or row.get("candidate_name") or "").split())
        raw_ids = row.get("source_ids") or row.get("evidence_ids") or []
        if not isinstance(raw_ids, list) or not raw_ids:
            raise MaterializeError(
                "selection_missing_sources",
                f"La selección de «{name or '?'}» no incluye source_ids.",
                status=422,
            )
        cand = candidates.get(name.casefold()) if name else None
        if name and cand is None:
            raise MaterializeError(
                "candidate_unknown",
                f"El candidato «{name}» no está en el artifact actual.",
                status=422,
            )
        cand_ids: set[str] = set()
        if cand is not None:
            for item in cand.get("evidence_ids") or []:
                try:
                    cand_ids.add(str(uuid.UUID(str(item))))
                except (ValueError, TypeError, AttributeError):
                    continue
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
            if cand_ids and sid not in cand_ids:
                raise MaterializeError(
                    "source_id_not_on_candidate",
                    f"El source_id no respalda al candidato «{name}» en el artifact.",
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


def materialize_web_search_sources(
    *,
    artifact: AIArtifact,
    dossier_id: uuid.UUID,
    source_ids: list[str],
) -> list[dict[str, Any]]:
    """Idempotent Evidence + EvidenceDossier for selected reserved sources.

    Uses a single transaction. Mid-flight failure leaves no partial rows
    (caller must not commit elsewhere). Two retries return the same evidence ids.
    """

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
        # Idempotency key: same tenant + artifact + source_id.
        existing = db.session.scalar(
            select(Evidence)
            .where(
                Evidence.tenant_id == tenant_id,
                Evidence.source_kind == SOURCE_KIND_WEB_SEARCH,
                Evidence.provenance["source_id"].as_string() == sid,
                Evidence.provenance["artifact_id"].as_string() == str(artifact.id),
            )
            .limit(1)
        )
        if existing is None:
            extract = snippet or title or url
            locator = {
                "source_id": sid,
                "artifact_id": str(artifact.id),
                "rank": piece.get("rank"),
                "provider": piece.get("provider") or "",
                "origin": SOURCE_KIND_WEB_SEARCH,
            }
            evidence = Evidence(
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
            db.session.add(evidence)
            db.session.flush()
            existing = evidence
        # Link to dossier (idempotent).
        link = db.session.scalar(
            select(EvidenceDossier).where(
                EvidenceDossier.tenant_id == tenant_id,
                EvidenceDossier.evidence_id == existing.id,
                EvidenceDossier.dossier_id == dossier_id,
            )
        )
        if link is None:
            db.session.add(
                EvidenceDossier(
                    tenant_id=tenant_id,
                    evidence_id=existing.id,
                    dossier_id=dossier_id,
                )
            )
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
    """Full human gate: load artifact → validate selection → materialize in one txn."""

    artifact = load_tenant_artifact(artifact_id, expected_version=expected_version)
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


def materialize_sha_placeholder() -> str:
    """Stable helper for tests that need a deterministic hex digest."""

    return hashlib.sha256(b"g18-web-search").hexdigest()
