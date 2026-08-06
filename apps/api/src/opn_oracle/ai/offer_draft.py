"""Durable editable opportunity offer draft (SV2-G09-A).

Source of truth for human edits seeded from the calculated ``draft_offer``
skeleton. Recalculation of opportunity analysis never overwrites this row.
"""

from __future__ import annotations

import copy
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from opn_oracle.ai.draft_offer import _BANNER, _HUMAN_GATE, _RESPONSE_TAG

# Size limits aligned with OpportunityDraftOffer / DraftOfferSection schemas.
MAX_STATEMENT_LEN = 4000
MAX_SECTION_RESPONSE_LEN = 2000
MAX_SECTIONS = 50
MAX_CONTENT_BYTES = 120_000
MAX_GAPS_PER_SECTION = 24
MAX_CHECKLIST = 40

HONESTY_MARKERS = (
    _RESPONSE_TAG,
    "[borrador declarado",
    "no es hecho",
    "no es documento presentable",
    "declared_draft",
    "declared_generated",
    "draft_requires_human_edit",
)


class OfferDraftError(Exception):
    """Domain error with HTTP-ish code for route mapping."""

    def __init__(self, message: str, *, code: str = "validation_error", status: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class OfferDraftVersionConflict(OfferDraftError):
    def __init__(self, *, current_version: int) -> None:
        super().__init__(
            "El borrador ha cambiado; recarga y vuelve a guardar.",
            code="version_conflict",
            status=409,
        )
        self.current_version = current_version


def _as_str_list(value: Any, *, limit: int = 32, item_max: int = 800) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text[:item_max])
        if len(out) >= limit:
            break
    return out


def _as_uuid_str_list(value: Any, *, limit: int = 40) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            out.append(str(uuid.UUID(text)))
        except (TypeError, ValueError):
            continue
        if len(out) >= limit:
            break
    return out


def _normalize_section(raw: dict[str, Any], *, order: int) -> dict[str, Any] | None:
    key = str(raw.get("key") or "").strip()[:80]
    title = str(raw.get("title") or "").strip()[:300]
    requirement = str(raw.get("requirement") or "").strip()[:2000]
    response = str(raw.get("our_response_draft") or "").strip()[:MAX_SECTION_RESPONSE_LEN]
    if not key or not title or not requirement or not response:
        return None
    seed = str(raw.get("our_response_seed") or response).strip()[:MAX_SECTION_RESPONSE_LEN]
    points = raw.get("points_hint")
    points_hint = str(points).strip()[:200] if points not in (None, "") else None
    return {
        "key": key,
        "order": order,
        "title": title,
        "points_hint": points_hint,
        "requirement": requirement,
        "requirement_origin": "official",
        "official_evidence_ids": _as_uuid_str_list(raw.get("official_evidence_ids")),
        "our_response_draft": response,
        "our_response_seed": seed or response,
        "response_origin": "declared_generated",
        "declared_evidence_ids": _as_uuid_str_list(raw.get("declared_evidence_ids")),
        "gaps": _as_str_list(raw.get("gaps"), limit=MAX_GAPS_PER_SECTION),
        "prose_polished": bool(raw.get("prose_polished")),
        "prose_polish_reason": (str(raw.get("prose_polish_reason") or "").strip()[:200] or None),
    }


def _normalize_checklist_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    key = str(raw.get("key") or "").strip()[:80]
    label = str(raw.get("label") or "").strip()[:300]
    description = str(raw.get("description") or "").strip()[:500]
    if not key or not label or not description:
        return None
    status = str(raw.get("status") or "pending").strip()
    if status not in {"pending", "ready", "blocked"}:
        status = "pending"
    source = str(raw.get("source") or "pliego").strip()
    if source not in {"pliego", "admin"}:
        source = "pliego"
    return {
        "key": key,
        "label": label,
        "description": description,
        "status": status,
        "source": source,
    }


def materialize_content_from_calculated(draft_offer: dict[str, Any]) -> dict[str, Any]:
    """Build durable content snapshot from a calculated ``draft_offer`` skeleton.

    Raises OfferDraftError when the calculated draft is missing or invalid.
    """

    if not isinstance(draft_offer, dict) or not draft_offer:
        raise OfferDraftError(
            "No hay un borrador de oferta calculado válido para materializar.",
            code="draft_offer_missing",
            status=422,
        )

    statement = str(draft_offer.get("statement") or "").strip()
    if not statement:
        raise OfferDraftError(
            "El borrador calculado no tiene introducción utilizable.",
            code="draft_offer_invalid",
            status=422,
        )

    raw_sections = draft_offer.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise OfferDraftError(
            "El borrador calculado no tiene secciones de oferta.",
            code="draft_offer_invalid",
            status=422,
        )

    sections: list[dict[str, Any]] = []
    for idx, raw in enumerate(raw_sections[:MAX_SECTIONS]):
        if not isinstance(raw, dict):
            continue
        sec = _normalize_section(raw, order=idx)
        if sec is not None:
            sections.append(sec)
    if not sections:
        raise OfferDraftError(
            "El borrador calculado no tiene secciones válidas.",
            code="draft_offer_invalid",
            status=422,
        )

    checklist: list[dict[str, Any]] = []
    for raw in (draft_offer.get("administrative_checklist") or [])[:MAX_CHECKLIST]:
        if isinstance(raw, dict):
            item = _normalize_checklist_item(raw)
            if item is not None:
                checklist.append(item)

    banner = str(draft_offer.get("banner") or _BANNER).strip()[:500] or _BANNER
    human_gate = str(draft_offer.get("human_gate") or _HUMAN_GATE).strip()
    if human_gate != _HUMAN_GATE:
        human_gate = _HUMAN_GATE

    content: dict[str, Any] = {
        "banner": banner,
        "human_gate": human_gate,
        "statement": statement[:MAX_STATEMENT_LEN],
        "tender_ref": (
            str(draft_offer.get("tender_ref")).strip()[:200]
            if draft_offer.get("tender_ref") not in (None, "")
            else None
        ),
        "lot_hint": (
            str(draft_offer.get("lot_hint")).strip()[:200]
            if draft_offer.get("lot_hint") not in (None, "")
            else None
        ),
        "sections": sections,
        "administrative_checklist": checklist,
        "gaps_summary": _as_str_list(draft_offer.get("gaps_summary"), limit=20),
        "gaps": [],
        "draft_engine": (str(draft_offer.get("draft_engine") or "").strip()[:80] or None),
        "prose_engine": (str(draft_offer.get("prose_engine") or "").strip()[:80] or None),
        "drafted_as_of": (str(draft_offer.get("drafted_as_of") or "").strip()[:40] or None),
        "origin": "declared_draft",
        "based_on_verdict": (str(draft_offer.get("based_on_verdict") or "").strip()[:40] or None),
        "official_evidence_ids": _as_uuid_str_list(draft_offer.get("official_evidence_ids")),
        "declared_evidence_ids": _as_uuid_str_list(draft_offer.get("declared_evidence_ids")),
        "statement_seed": (
            str(draft_offer.get("statement_seed") or statement).strip()[:MAX_STATEMENT_LEN]
            or statement[:MAX_STATEMENT_LEN]
        ),
        "statement_prose_polished": bool(draft_offer.get("statement_prose_polished")),
        "statement_prose_polish_reason": (
            str(draft_offer.get("statement_prose_polish_reason") or "").strip()[:200] or None
        ),
        "prose_polished_count": int(draft_offer.get("prose_polished_count") or 0),
    }

    # Preserve structured gaps if present.
    raw_gaps = draft_offer.get("gaps")
    if isinstance(raw_gaps, list):
        cleaned_gaps: list[dict[str, Any]] = []
        for g in raw_gaps[:20]:
            if not isinstance(g, dict):
                continue
            code = str(g.get("code") or "").strip()[:80]
            desc = str(g.get("description") or "").strip()[:800]
            if not code or not desc:
                continue
            sev = str(g.get("severity") or "important")
            if sev not in {"blocking", "important", "info"}:
                sev = "important"
            origin = str(g.get("origin") or "verdict_condition")
            if origin not in {"verdict_condition", "pliego", "profile"}:
                origin = "verdict_condition"
            cleaned_gaps.append(
                {
                    "code": code,
                    "description": desc,
                    "severity": sev,
                    "origin": origin,
                }
            )
        content["gaps"] = cleaned_gaps

    _assert_content_size(content)
    return content


def _assert_content_size(content: dict[str, Any]) -> None:
    raw = json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_CONTENT_BYTES:
        raise OfferDraftError(
            "El borrador supera el tamaño máximo permitido.",
            code="payload_too_large",
            status=422,
        )


def make_etag(version: int) -> str:
    return f'W/"ood-v{int(version)}"'


def parse_expected_version(
    *,
    body_version: Any = None,
    if_match: str | None = None,
) -> int | None:
    """Resolve optimistic concurrency token from body and/or If-Match."""

    if body_version is not None and body_version != "":
        try:
            version = int(body_version)
        except (TypeError, ValueError) as exc:
            raise OfferDraftError(
                "La versión indicada no es válida.",
                code="schema_validation_failed",
                status=422,
            ) from exc
        if version < 1:
            raise OfferDraftError(
                "La versión debe ser un entero positivo.",
                code="schema_validation_failed",
                status=422,
            )
        return version

    if if_match:
        raw = if_match.strip()
        if raw.startswith("W/"):
            raw = raw[2:].strip()
        raw = raw.strip('"')
        if raw.startswith("ood-v"):
            try:
                return int(raw.removeprefix("ood-v"))
            except ValueError as exc:
                raise OfferDraftError(
                    "If-Match no es válido.",
                    code="schema_validation_failed",
                    status=422,
                ) from exc
        try:
            return int(raw)
        except ValueError as exc:
            raise OfferDraftError(
                "If-Match no es válido.",
                code="schema_validation_failed",
                status=422,
            ) from exc
    return None


def apply_editable_patch(
    content: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Apply editable fields only; preserves structure, origins and honesty labels."""

    if not isinstance(patch, dict):
        raise OfferDraftError(
            "El cuerpo de actualización debe ser un objeto.",
            code="schema_validation_failed",
            status=422,
        )

    next_content = copy.deepcopy(content)
    # Hard lock honesty / official structure.
    next_content["banner"] = str(content.get("banner") or _BANNER)[:500]
    next_content["human_gate"] = _HUMAN_GATE
    next_content["origin"] = "declared_draft"

    if "statement" in patch:
        statement = str(patch.get("statement") or "").strip()
        if not statement:
            raise OfferDraftError(
                "La introducción del borrador no puede quedar vacía.",
                code="schema_validation_failed",
                status=422,
            )
        if len(statement) > MAX_STATEMENT_LEN:
            raise OfferDraftError(
                f"La introducción supera {MAX_STATEMENT_LEN} caracteres.",
                code="schema_validation_failed",
                status=422,
            )
        next_content["statement"] = statement

    if "sections" in patch:
        raw_sections = patch.get("sections")
        if not isinstance(raw_sections, list):
            raise OfferDraftError(
                "sections debe ser una lista.",
                code="schema_validation_failed",
                status=422,
            )
        by_key = {
            str(sec.get("key")): sec
            for sec in (next_content.get("sections") or [])
            if isinstance(sec, dict) and sec.get("key")
        }
        if not by_key:
            raise OfferDraftError(
                "El borrador no tiene secciones editables.",
                code="draft_offer_invalid",
                status=422,
            )
        seen: set[str] = set()
        for item in raw_sections:
            if not isinstance(item, dict):
                raise OfferDraftError(
                    "Cada sección del parche debe ser un objeto.",
                    code="schema_validation_failed",
                    status=422,
                )
            key = str(item.get("key") or "").strip()
            if not key:
                raise OfferDraftError(
                    "Cada sección del parche requiere key.",
                    code="schema_validation_failed",
                    status=422,
                )
            if key not in by_key:
                raise OfferDraftError(
                    f"Sección desconocida: {key}.",
                    code="unknown_section",
                    status=422,
                )
            if key in seen:
                raise OfferDraftError(
                    f"Sección duplicada en el parche: {key}.",
                    code="schema_validation_failed",
                    status=422,
                )
            seen.add(key)
            if "our_response_draft" not in item:
                continue
            response = str(item.get("our_response_draft") or "").strip()
            if not response:
                raise OfferDraftError(
                    f"El texto de la sección {key} no puede quedar vacío.",
                    code="schema_validation_failed",
                    status=422,
                )
            if len(response) > MAX_SECTION_RESPONSE_LEN:
                raise OfferDraftError(
                    f"El texto de la sección {key} supera {MAX_SECTION_RESPONSE_LEN} caracteres.",
                    code="schema_validation_failed",
                    status=422,
                )
            # Keep honesty: if user strips the declared marker, re-prefix it.
            lowered = response.casefold()
            if "[borrador declarado" not in lowered and "no es hecho" not in lowered:
                response = f"{_RESPONSE_TAG} {response}"
                if len(response) > MAX_SECTION_RESPONSE_LEN:
                    response = response[:MAX_SECTION_RESPONSE_LEN]
            sec = by_key[key]
            sec["our_response_draft"] = response
            sec["response_origin"] = "declared_generated"
            sec["requirement_origin"] = "official"

        # Re-order preserved.
        next_content["sections"] = sorted(
            by_key.values(),
            key=lambda s: int(s.get("order") if s.get("order") is not None else 0),
        )

    # Never accept tenant/actor/origin overrides from client payload leftovers.
    for forbidden in (
        "tenant_id",
        "dossier_id",
        "last_edited_by_user_id",
        "source_artifact_id",
        "origin",
        "human_gate",
        "banner",
        "requirement_origin",
        "response_origin",
    ):
        # already locked above; ensure no leak from patch into content root
        identity_keys = {"tenant_id", "dossier_id", "last_edited_by_user_id"}
        if forbidden in patch and forbidden in identity_keys:
            raise OfferDraftError(
                "No se aceptan identidades desde el cliente.",
                code="forbidden_field",
                status=422,
            )

    _assert_content_size(next_content)
    return next_content


def serialize_offer_draft(row: Any) -> dict[str, Any]:
    """Public JSON shape (no tenant leakage beyond scoped resource ids)."""

    content = row.content if isinstance(row.content, dict) else {}
    return {
        "id": str(row.id),
        "dossier_id": str(row.dossier_id),
        "source_artifact_id": str(row.source_artifact_id),
        "version": int(row.version),
        "etag": str(row.etag),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "last_edited_by_user_id": str(row.last_edited_by_user_id),
        "content": content,
        "banner": content.get("banner") or _BANNER,
        "human_gate": content.get("human_gate") or _HUMAN_GATE,
        "statement": content.get("statement") or "",
        "tender_ref": content.get("tender_ref"),
        "lot_hint": content.get("lot_hint"),
        "sections": content.get("sections") or [],
        "administrative_checklist": content.get("administrative_checklist") or [],
        "gaps_summary": content.get("gaps_summary") or [],
        "gaps": content.get("gaps") or [],
        "origin": "declared_draft",
        "based_on_verdict": content.get("based_on_verdict"),
        "official_evidence_ids": content.get("official_evidence_ids") or [],
        "declared_evidence_ids": content.get("declared_evidence_ids") or [],
        "draft_engine": content.get("draft_engine"),
        "prose_engine": content.get("prose_engine"),
        "drafted_as_of": content.get("drafted_as_of"),
    }


def build_plain_text_document(content: dict[str, Any]) -> str:
    """Human-readable copy payload (no internal IDs / JSON)."""

    lines: list[str] = []
    banner = str(content.get("banner") or _BANNER).strip()
    if banner:
        lines.append(banner)
        lines.append("")
    statement = str(content.get("statement") or "").strip()
    if statement:
        lines.append(statement)
        lines.append("")
    meta_bits: list[str] = []
    if content.get("tender_ref"):
        meta_bits.append(str(content["tender_ref"]))
    if content.get("lot_hint"):
        meta_bits.append(str(content["lot_hint"]))
    if meta_bits:
        lines.append(" · ".join(meta_bits))
        lines.append("")
    lines.append("Secciones")
    lines.append("---------")
    for sec in content.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        title = str(sec.get("title") or "").strip() or str(sec.get("key") or "Sección")
        lines.append("")
        lines.append(title)
        if sec.get("points_hint"):
            lines.append(f"Puntos: {sec['points_hint']}")
        req = str(sec.get("requirement") or "").strip()
        if req:
            lines.append(f"Requisito (oficial): {req}")
        resp = str(sec.get("our_response_draft") or "").strip()
        if resp:
            lines.append(f"Respuesta (borrador declarado): {resp}")
        for gap in sec.get("gaps") or []:
            lines.append(f"Gap: {gap}")
    gaps = content.get("gaps_summary") or []
    if gaps:
        lines.append("")
        lines.append("Gaps de solvencia / condiciones")
        lines.append("-------------------------------")
        for g in gaps:
            lines.append(f"- {g}")
    checklist = content.get("administrative_checklist") or []
    if checklist:
        lines.append("")
        lines.append("Checklist administrativa")
        lines.append("------------------------")
        for item in checklist:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "pending")
            label = str(item.get("label") or item.get("key") or "")
            desc = str(item.get("description") or "").strip()
            lines.append(f"[{status}] {label}")
            if desc:
                lines.append(f"  {desc}")
    lines.append("")
    lines.append(
        "Nota: este texto es un borrador declarado — no es hecho oficial ni documento presentable."
    )
    return "\n".join(lines).strip() + "\n"


def utc_now() -> datetime:
    return datetime.now(UTC)


def assert_version_match(*, row_version: int, expected: int | None) -> None:
    if expected is None:
        raise OfferDraftError(
            "Se requiere version o cabecera If-Match para guardar el borrador.",
            code="precondition_required",
            status=428,
        )
    if int(row_version) != int(expected):
        raise OfferDraftVersionConflict(current_version=int(row_version))


def cas_update_offer_draft_sql(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    expected_version: int,
    next_content: dict[str, Any],
    actor_id: uuid.UUID,
    new_version: int,
    new_etag: str,
    updated_at: datetime,
) -> Any:
    """Build the atomic compare-and-swap UPDATE for opportunity_offer_drafts.

    The WHERE clause always includes tenant_id, dossier_id and version == expected.
    Callers must treat rowcount/RETURNING == 0 as version_conflict (no overwrite).
    """

    from sqlalchemy import update

    from opn_oracle.ai.models import OpportunityOfferDraft

    return (
        update(OpportunityOfferDraft)
        .where(
            OpportunityOfferDraft.tenant_id == tenant_id,
            OpportunityOfferDraft.dossier_id == dossier_id,
            OpportunityOfferDraft.version == int(expected_version),
        )
        .values(
            content=next_content,
            version=int(new_version),
            etag=new_etag,
            last_edited_by_user_id=actor_id,
            updated_at=updated_at,
        )
    )
