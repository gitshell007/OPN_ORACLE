"""Pinned PLACSP procurement items for strategic dossiers."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opn_oracle.integrations.procurement import (
    ProcurementProviderError,
    procurement_client_from_config,
)
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import DossierProcurementItem, Evidence
from opn_oracle.platform.audit import append_audit_event

ProcurementKind = Literal["tender", "award"]


class ProcurementItemError(RuntimeError):
    """Raised when a procurement item cannot be pinned to a dossier."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def _checksum(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _normalize_cpv(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _numeric_or_none(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value if isinstance(value, int) or math.isfinite(value) else None
    text = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif (
        "." in text
        and all(part.isdigit() for part in text.split("."))
        and len(text.rsplit(".", 1)[1]) == 3
    ):
        text = text.replace(".", "")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    if parsed == parsed.to_integral_value():
        return int(parsed)
    return float(parsed)


def _first_text(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lot_id_or_none(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if len(candidate) == 9 and candidate[0].isalpha() and candidate[1:].isdigit():
        return None
    return candidate


def _snapshot(kind: ProcurementKind, item: dict[str, Any], folder_id: str) -> dict[str, Any]:
    keys: tuple[str, ...]
    if kind == "tender":
        keys = (
            "folder_id",
            "title",
            "summary_feed",
            "buyer",
            "status",
            "cpv",
            "amount",
            "deadline",
            "region",
            "source_url",
            "is_active",
            "feed_updated_at",
            "llm_summary",
            "llm_summary_model",
            "llm_summary_at",
        )
    else:
        keys = (
            "folder_id",
            "lot_id",
            "title",
            "buyer",
            "winner",
            "award_amount",
            "cpv",
            "status",
            "award_date",
            "region",
            "source_url",
        )
    snapshot = {key: item.get(key) for key in keys if key in item}
    snapshot["folder_id"] = str(snapshot.get("folder_id") or folder_id)
    snapshot["kind"] = kind
    snapshot["cpv"] = _normalize_cpv(snapshot.get("cpv"))
    if kind == "tender":
        amount = _numeric_or_none(snapshot.get("amount"))
        if amount is not None:
            snapshot["amount"] = amount
    else:
        lot_id = _lot_id_or_none(snapshot.get("lot_id"))
        if lot_id:
            snapshot["lot_id"] = lot_id
        else:
            snapshot.pop("lot_id", None)
        amount = _numeric_or_none(
            snapshot.get("award_amount")
            or item.get("amount")
            or item.get("awarded_amount")
            or item.get("award_value")
            or item.get("contract_amount")
            or item.get("importe_adjudicacion")
            or item.get("importe")
            or item.get("amount_eur")
        )
        if amount is not None:
            snapshot["award_amount"] = amount
        date = snapshot.get("award_date") or _first_text(
            item,
            (
                "date",
                "award_publication_date",
                "published_at",
                "publication_date",
                "updated_at",
            ),
        )
        if date:
            snapshot["award_date"] = str(date)
    return snapshot


def _source_url(snapshot: dict[str, Any]) -> str | None:
    value = snapshot.get("source_url")
    if value is None and snapshot.get("kind") == "award":
        entries = snapshot.get("entries")
        if isinstance(entries, list):
            value = next(
                (
                    entry.get("source_url")
                    for entry in entries
                    if isinstance(entry, dict) and entry.get("source_url")
                ),
                None,
            )
    return str(value)[:1500] if value else None


def _award_collection_snapshot(payload: dict[str, Any], folder_id: str) -> dict[str, Any]:
    items = payload.get("items")
    total = payload.get("total")
    if not isinstance(items, list) or not items:
        raise ProcurementItemError("No hay adjudicaciones PLACSP para el expediente indicado.")
    entries = [_snapshot("award", item, folder_id) for item in items if isinstance(item, dict)]
    if not entries:
        raise ProcurementItemError("No hay adjudicaciones PLACSP para el expediente indicado.")
    if total == 0:
        raise ProcurementItemError("No hay adjudicaciones PLACSP para el expediente indicado.")
    cpv_values = sorted({cpv for entry in entries for cpv in _normalize_cpv(entry.get("cpv"))})
    first_source_url = next(
        (entry.get("source_url") for entry in entries if entry.get("source_url")),
        None,
    )
    first_title = next((entry.get("title") for entry in entries if entry.get("title")), None)
    first_buyer = next((entry.get("buyer") for entry in entries if entry.get("buyer")), None)
    amounts = [
        value
        for value in (_numeric_or_none(entry.get("award_amount")) for entry in entries)
        if value is not None
    ]
    dates = sorted(
        {
            str(entry["award_date"])
            for entry in entries
            if isinstance(entry.get("award_date"), str) and str(entry["award_date"]).strip()
        }
    )
    award_date = None
    if len(dates) == 1:
        award_date = dates[0]
    elif len(dates) > 1:
        award_date = f"{dates[0]}/{dates[-1]}"
    return {
        "kind": "award",
        "folder_id": str(payload.get("folder_id") or folder_id),
        "total": int(total) if isinstance(total, int) else len(entries),
        "entries": entries,
        "title": first_title,
        "buyer": first_buyer,
        "award_amount": sum(amounts) if amounts else None,
        "award_date": award_date,
        "cpv": cpv_values,
        "source_url": str(first_source_url) if first_source_url else None,
    }


def resolve_procurement_snapshot(kind: ProcurementKind, folder_id: str) -> dict[str, Any]:
    client = procurement_client_from_config()
    try:
        if kind == "tender":
            try:
                payload = client.tender_by_folder(folder_id=folder_id)
            except ProcurementProviderError as exc:
                if exc.status_code == 404:
                    raise ProcurementItemError(
                        "No se encontró la licitación PLACSP indicada en Signal."
                    ) from exc
                raise
            item = payload.get("item")
            if not isinstance(item, dict):
                raise ProcurementItemError("Signal devolvió una licitación PLACSP no válida.")
            return _snapshot("tender", item, folder_id)
        else:
            payload = client.awards_by_folder(folder_id=folder_id)
            if payload.get("total") == 0:
                raise ProcurementItemError(
                    "No hay adjudicaciones PLACSP para el expediente indicado."
                )
            return _award_collection_snapshot(payload, folder_id)
    finally:
        client.close()


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money_text(value: Any) -> str:
    amount = _decimal_or_none(value)
    if amount is None or not amount.is_finite():
        return "No indicado"
    return f"{amount.quantize(Decimal('0.01'))}"


def procurement_evidence_extract(snapshot: dict[str, Any]) -> str:
    if snapshot.get("kind") == "award":
        entries = [entry for entry in snapshot.get("entries", []) if isinstance(entry, dict)]
        amounts = [
            parsed
            for parsed in (_decimal_or_none(entry.get("award_amount")) for entry in entries)
            if parsed is not None
        ]
        winners = sorted(
            {
                str(entry.get("winner")).strip()
                for entry in entries
                if str(entry.get("winner") or "").strip()
            }
        )
        winner_summary = ", ".join(winners[:5]) if winners else "Adjudicatarios no indicados"
        if len(winners) > 5:
            winner_summary = f"{winner_summary} y {len(winners) - 5} más"
        total_amount = sum(amounts, Decimal("0")) if amounts else None
        return (
            f"Adjudicación PLACSP {snapshot.get('folder_id')}: "
            f"{snapshot.get('title') or 'Sin título'}. "
            f"Órgano: {snapshot.get('buyer') or 'No indicado'}. "
            f"Lotes: {len(entries) or snapshot.get('total') or 'No indicado'}. "
            f"Adjudicatarios: {winner_summary}. "
            "Importe total adjudicado: "
            f"{_money_text(total_amount)}. "
            f"CPV: {', '.join(_normalize_cpv(snapshot.get('cpv'))) or 'No indicado'}."
        )
    amount = snapshot.get("amount")
    deadline = snapshot.get("deadline")
    return (
        f"Licitación PLACSP {snapshot.get('folder_id')}: {snapshot.get('title') or 'Sin título'}. "
        f"Órgano: {snapshot.get('buyer') or 'No indicado'}. "
        f"Importe: {_money_text(amount)}. "
        f"Deadline: {deadline or 'No indicado'}. "
        f"Estado: {snapshot.get('status') or 'No indicado'}. "
        f"CPV: {', '.join(_normalize_cpv(snapshot.get('cpv'))) or 'No indicado'}."
    )


def pin_procurement_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    kind: str,
    folder_id: str,
    actor_id: uuid.UUID,
) -> tuple[DossierProcurementItem, bool]:
    normalized_kind = kind.strip().lower()
    if normalized_kind not in {"tender", "award"}:
        raise ProcurementItemError("kind debe ser 'tender' o 'award'.")
    normalized_folder_id = folder_id.strip()
    if not normalized_folder_id or len(normalized_folder_id) > 240:
        raise ProcurementItemError("folder_id es obligatorio y admite hasta 240 caracteres.")
    existing = session.scalar(
        select(DossierProcurementItem).where(
            DossierProcurementItem.tenant_id == tenant_id,
            DossierProcurementItem.dossier_id == dossier_id,
            DossierProcurementItem.kind == normalized_kind,
            DossierProcurementItem.folder_id == normalized_folder_id,
        )
    )
    if existing is not None:
        return existing, False
    snapshot = resolve_procurement_snapshot(
        cast(ProcurementKind, normalized_kind),
        normalized_folder_id,
    )
    extract = procurement_evidence_extract(snapshot)
    evidence = Evidence(
        tenant_id=tenant_id,
        source_kind="procurement",
        source_url=_source_url(snapshot),
        extract=extract[:20000],
        locator={
            "kind": "placsp_procurement",
            "procurement_kind": normalized_kind,
            "folder_id": normalized_folder_id,
            "source_url": _source_url(snapshot),
        },
        checksum=_checksum(extract),
        classification="internal",
        provenance={
            "source_kind": "procurement",
            "procurement_kind": normalized_kind,
            "folder_id": normalized_folder_id,
            "snapshot_sha256": hashlib.sha256(_canonical(snapshot)).hexdigest(),
        },
    )
    session.add(evidence)
    session.flush()
    item = DossierProcurementItem(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        kind=normalized_kind,
        folder_id=normalized_folder_id,
        snapshot=snapshot,
        source_url=_source_url(snapshot),
        evidence_id=evidence.id,
        pinned_by_user_id=actor_id,
    )
    session.add(item)
    session.add(
        EvidenceDossier(tenant_id=tenant_id, evidence_id=evidence.id, dossier_id=dossier_id)
    )
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(DossierProcurementItem).where(
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.dossier_id == dossier_id,
                DossierProcurementItem.kind == normalized_kind,
                DossierProcurementItem.folder_id == normalized_folder_id,
            )
        )
        if existing is None:
            raise
        return existing, False
    append_audit_event(
        session,
        action="procurement.pinned",
        resource_type="dossier_procurement_item",
        resource_id=item.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"kind": normalized_kind, "folder_id": normalized_folder_id},
    )
    return item, True


def list_procurement_items(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> list[DossierProcurementItem]:
    return list(
        session.scalars(
            select(DossierProcurementItem)
            .where(
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.dossier_id == dossier_id,
            )
            .order_by(DossierProcurementItem.created_at.desc(), DossierProcurementItem.id)
        )
    )


def delete_procurement_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    item_id: uuid.UUID,
) -> bool:
    item = session.scalar(
        select(DossierProcurementItem).where(
            DossierProcurementItem.id == item_id,
            DossierProcurementItem.tenant_id == tenant_id,
            DossierProcurementItem.dossier_id == dossier_id,
        )
    )
    if item is None:
        return False
    session.delete(item)
    append_audit_event(
        session,
        action="procurement.unpinned",
        resource_type="dossier_procurement_item",
        resource_id=item_id,
        dossier_id=dossier_id,
        result="success",
        metadata={"kind": item.kind, "folder_id": item.folder_id},
    )
    return True


def serialize_procurement_item(item: DossierProcurementItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "tenant_id": str(item.tenant_id),
        "dossier_id": str(item.dossier_id),
        "kind": item.kind,
        "folder_id": item.folder_id,
        "snapshot": item.snapshot,
        "source_url": item.source_url,
        "evidence_id": str(item.evidence_id),
        "pinned_by_user_id": str(item.pinned_by_user_id) if item.pinned_by_user_id else None,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
