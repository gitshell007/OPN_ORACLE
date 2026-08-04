"""Pinned PLACSP procurement items for strategic dossiers."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from sqlalchemy import Text, delete, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opn_oracle.ai.models import AIArtifact, AIContextEvidence
from opn_oracle.integrations.procurement import (
    ProcurementProviderError,
    procurement_client_from_config,
)
from opn_oracle.oracle.actor_tax_id import hydrate_dossier_actor_tax_ids_from_awards
from opn_oracle.oracle.links import (
    DecisionEvidence,
    DossierActorEvidence,
    EvidenceDossier,
    HypothesisEvidence,
    InsightEvidence,
    MeetingEvidence,
    OpportunityEvidence,
    RelationshipEvidence,
    ReportEvidence,
    RiskEvidence,
)
from opn_oracle.oracle.models import DossierProcurementItem, Evidence, Opportunity
from opn_oracle.platform.audit import append_audit_event

ProcurementKind = Literal["tender", "award"]

logger = logging.getLogger(__name__)

MAX_SNAPSHOT_DOCUMENTS_PER_AWARD_ENTRY = 10
MAX_SNAPSHOT_DOCUMENTS_PER_AWARD_COLLECTION = 30
MAX_SNAPSHOT_DOCUMENT_URI_LENGTH = 1500
MAX_SNAPSHOT_DOCUMENT_TEXT_LENGTH = 240

TENDER_SNAPSHOT_KEYS: tuple[str, ...] = (
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
AWARD_SNAPSHOT_KEYS: tuple[str, ...] = (
    "folder_id",
    "lot_id",
    "title",
    "buyer",
    "winner",
    # NIF/CIF del adjudicatario (Signal: winner_identifier; alias tax_id).
    "winner_identifier",
    "winner_identifier_scheme",
    "tax_id",
    "award_amount",
    "cpv",
    "status",
    "award_date",
    "received_tender_quantity",
    "region",
    "source_url",
    "documents",
    "is_ute",
)
AWARD_PROVIDER_CONSUMED_KEYS = frozenset(
    {
        "amount",
        "awarded_amount",
        "award_value",
        "contract_amount",
        "importe_adjudicacion",
        "importe",
        "amount_eur",
        "date",
        "award_publication_date",
        "published_at",
        "publication_date",
        "updated_at",
    }
)
TENDER_PROVIDER_DISCARDED_KEYS = frozenset[str]()
AWARD_PROVIDER_DISCARDED_KEYS = frozenset[str]()


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


def _nonnegative_integer_or_none(value: Any) -> int | None:
    """Keep Signal's per-lot offer count without coercing fractional values.

    The field is contextual metadata, never a nominal participant list and never an
    aggregate across award entries: Signal may repeat it for each winner in a lot.
    """

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value >= 0 and value.is_integer() else None
    text = str(value).strip()
    if not text or not text.isdigit():
        return None
    return int(text)


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


def _provider_keys_for(
    kind: ProcurementKind,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    if kind == "tender":
        return frozenset(TENDER_SNAPSHOT_KEYS), frozenset(), TENDER_PROVIDER_DISCARDED_KEYS
    return (
        frozenset(AWARD_SNAPSHOT_KEYS),
        AWARD_PROVIDER_CONSUMED_KEYS,
        AWARD_PROVIDER_DISCARDED_KEYS,
    )


def _unclassified_snapshot_keys(kind: ProcurementKind, item: dict[str, Any]) -> set[str]:
    preserved_keys, consumed_keys, discarded_keys = _provider_keys_for(kind)
    return set(item) - preserved_keys - consumed_keys - discarded_keys


def _warn_unclassified_snapshot_keys(kind: ProcurementKind, item: dict[str, Any]) -> None:
    unknown_keys = sorted(_unclassified_snapshot_keys(kind, item))
    if unknown_keys:
        logger.warning(
            "Signal devolvió claves PLACSP sin clasificación de snapshot",
            extra={"procurement_kind": kind, "unclassified_keys": unknown_keys},
        )


def _boolean_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "si", "sí"}:
            return True
        if normalized in {"0", "false", "no", "n"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _text_or_empty(value: Any, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _normalize_document(document: dict[Any, Any]) -> dict[str, str] | None:
    uri = _text_or_empty(document.get("uri"), max_length=MAX_SNAPSHOT_DOCUMENT_URI_LENGTH)
    if not uri:
        return None
    doc_type = _text_or_empty(
        document.get("doc_type") or "additional",
        max_length=MAX_SNAPSHOT_DOCUMENT_TEXT_LENGTH,
    )
    return {
        "uri": uri,
        "doc_type": doc_type or "additional",
        "file_name": _text_or_empty(
            document.get("file_name"),
            max_length=MAX_SNAPSHOT_DOCUMENT_TEXT_LENGTH,
        ),
    }


def _normalize_documents(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    documents: list[dict[str, str]] = []
    seen_uris: set[str] = set()
    for document in value:
        if not isinstance(document, dict):
            continue
        normalized_document = _normalize_document(document)
        if normalized_document is None or normalized_document["uri"] in seen_uris:
            continue
        seen_uris.add(normalized_document["uri"])
        documents.append(normalized_document)
        if len(documents) >= MAX_SNAPSHOT_DOCUMENTS_PER_AWARD_ENTRY:
            break
    return documents


def _deduplicate_award_documents(entries: list[dict[str, Any]]) -> None:
    seen_uris: set[str] = set()
    preserved_count = 0
    for entry_index, entry in enumerate(entries):
        raw_documents = entry.get("documents")
        if not isinstance(raw_documents, list):
            continue
        preserved_documents: list[dict[str, str]] = []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue
            normalized_document = _normalize_document(document)
            if normalized_document is None or normalized_document["uri"] in seen_uris:
                continue
            seen_uris.add(normalized_document["uri"])
            preserved_documents.append(normalized_document)
            preserved_count += 1
            if preserved_count >= MAX_SNAPSHOT_DOCUMENTS_PER_AWARD_COLLECTION:
                break
        entry["documents"] = preserved_documents
        if preserved_count >= MAX_SNAPSHOT_DOCUMENTS_PER_AWARD_COLLECTION:
            for remaining_entry in entries[entry_index + 1 :]:
                if "documents" in remaining_entry:
                    remaining_entry["documents"] = []
            break


def _snapshot(kind: ProcurementKind, item: dict[str, Any], folder_id: str) -> dict[str, Any]:
    _warn_unclassified_snapshot_keys(kind, item)
    keys = TENDER_SNAPSHOT_KEYS if kind == "tender" else AWARD_SNAPSHOT_KEYS
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
        if "received_tender_quantity" in snapshot:
            snapshot["received_tender_quantity"] = _nonnegative_integer_or_none(
                snapshot["received_tender_quantity"]
            )
        if "documents" in snapshot:
            snapshot["documents"] = _normalize_documents(snapshot.get("documents"))
        if "is_ute" in snapshot:
            is_ute = _boolean_or_none(snapshot.get("is_ute"))
            if is_ute is None:
                snapshot.pop("is_ute", None)
            else:
                snapshot["is_ute"] = is_ute
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
        # NIF/CIF: prefer winner_identifier; accept tax_id/nif aliases from Signal.
        identifier = (
            snapshot.get("winner_identifier")
            or item.get("winner_identifier")
            or item.get("tax_id")
            or item.get("nif")
        )
        if identifier is not None and str(identifier).strip():
            cleaned = str(identifier).strip()[:40]
            snapshot["winner_identifier"] = cleaned
            snapshot["tax_id"] = cleaned
        else:
            snapshot.pop("winner_identifier", None)
            snapshot.pop("tax_id", None)
        scheme = snapshot.get("winner_identifier_scheme") or item.get(
            "winner_identifier_scheme"
        )
        if snapshot.get("winner_identifier") and scheme is not None and str(scheme).strip():
            snapshot["winner_identifier_scheme"] = str(scheme).strip()[:40]
        else:
            snapshot.pop("winner_identifier_scheme", None)
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
    _deduplicate_award_documents(entries)
    if total == 0:
        raise ProcurementItemError("No hay adjudicaciones PLACSP para el expediente indicado.")
    cpv_values = sorted({cpv for entry in entries for cpv in _normalize_cpv(entry.get("cpv"))})
    first_source_url = next(
        (entry.get("source_url") for entry in entries if entry.get("source_url")),
        None,
    )
    first_title = next((entry.get("title") for entry in entries if entry.get("title")), None)
    first_buyer = next((entry.get("buyer") for entry in entries if entry.get("buyer")), None)
    winners = [
        str(entry.get("winner")).strip()
        for entry in entries
        if str(entry.get("winner") or "").strip()
    ]
    winner_identifiers = []
    seen_identifiers: set[str] = set()
    for entry in entries:
        identifier = (
            entry.get("winner_identifier")
            or entry.get("tax_id")
            or entry.get("nif")
        )
        text = str(identifier).strip() if identifier is not None else ""
        if text and text.casefold() not in seen_identifiers:
            seen_identifiers.add(text.casefold())
            winner_identifiers.append(text)
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
        "winner": "; ".join(winners) if winners else None,
        "winner_identifier": "; ".join(winner_identifiers) if winner_identifiers else None,
        "nif": "; ".join(winner_identifiers) if winner_identifiers else None,
        "award_amount": sum(amounts) if amounts else None,
        "award_date": award_date,
        "cpv": cpv_values,
        "source_url": str(first_source_url) if first_source_url else None,
        "is_ute": any(entry.get("is_ute") is True for entry in entries),
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


def _entry_identifier(entry: dict[str, Any]) -> str | None:
    for key in ("winner_identifier", "tax_id", "nif"):
        value = entry.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()[:40]
    return None


def preserve_award_winner_identifiers(
    previous: dict[str, Any] | None, new_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """No borrar NIF del pin cuando Signal devuelve null (backfill incompleto).

    Si el snapshot nuevo trae el identificador, gana. Si llega vacío y el pin
    ya tenía uno, se conserva por nombre de adjudicatario (o a nivel colección).
    """

    if not isinstance(previous, dict) or not isinstance(new_snapshot, dict):
        return new_snapshot
    if new_snapshot.get("kind") != "award":
        return new_snapshot

    previous_entries = previous.get("entries")
    new_entries = new_snapshot.get("entries")
    if isinstance(previous_entries, list) and isinstance(new_entries, list) and new_entries:
        prev_by_winner: dict[str, str] = {}
        for entry in previous_entries:
            if not isinstance(entry, dict):
                continue
            winner = " ".join(str(entry.get("winner") or "").strip().split()).casefold()
            identifier = _entry_identifier(entry)
            if winner and identifier:
                prev_by_winner.setdefault(winner, identifier)
        rebuilt: list[dict[str, Any]] = []
        for entry in new_entries:
            if not isinstance(entry, dict):
                continue
            updated = dict(entry)
            if not _entry_identifier(updated):
                winner = " ".join(str(updated.get("winner") or "").strip().split()).casefold()
                restored = prev_by_winner.get(winner)
                if restored:
                    updated["winner_identifier"] = restored
                    updated["tax_id"] = restored
            rebuilt.append(updated)
        new_snapshot = dict(new_snapshot)
        new_snapshot["entries"] = rebuilt
        # Re-aggregate collection-level identifiers from (possibly restored) entries.
        identifiers: list[str] = []
        seen: set[str] = set()
        for entry in rebuilt:
            text = _entry_identifier(entry)
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                identifiers.append(text)
        if identifiers:
            joined = "; ".join(identifiers)
            new_snapshot["winner_identifier"] = joined
            new_snapshot["nif"] = joined
            if len(identifiers) == 1:
                new_snapshot["tax_id"] = identifiers[0]
        return new_snapshot

    # Snapshot plano sin entries: conservar top-level si el nuevo llega vacío.
    if not _entry_identifier(new_snapshot):
        restored = _entry_identifier(previous)
        if restored:
            new_snapshot = dict(new_snapshot)
            new_snapshot["winner_identifier"] = restored
            new_snapshot["tax_id"] = restored
            new_snapshot["nif"] = restored
    return new_snapshot


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
            "Importe total adjudicado (sin clasificación base/IVA en origen): "
            f"{_money_text(total_amount)}. "
            f"CPV: {', '.join(_normalize_cpv(snapshot.get('cpv'))) or 'No indicado'}."
        )
    amount = snapshot.get("amount")
    deadline = snapshot.get("deadline")
    # Signal/PLACSP publica un único campo `amount` sin indicar si es base de
    # licitación o IVA incluido. No inventamos la etiqueta: el consumidor debe
    # contrastar con el pliego hasta que el productor exponga ambos importes.
    return (
        f"Licitación PLACSP {snapshot.get('folder_id')}: {snapshot.get('title') or 'Sin título'}. "
        f"Órgano: {snapshot.get('buyer') or 'No indicado'}. "
        f"Importe publicado (campo amount PLACSP, sin clasificar base/IVA): {_money_text(amount)}. "
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
    # Menos sorprendente: al fijar un award, materializar CIF en actores emparejados.
    if normalized_kind == "award":
        hydrate_dossier_actor_tax_ids_from_awards(
            session, tenant_id=tenant_id, dossier_id=dossier_id
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


def _evidence_cited_by_artifacts(
    session: Session, *, tenant_id: uuid.UUID, evidence_id: uuid.UUID
) -> bool:
    """True when any AI artifact output still references this evidence UUID."""

    token = str(evidence_id)
    # Artifacts store evidence_ids inside nested JSON; a text containment check is
    # enough to preserve historical claim resolution without rewriting outputs.
    return (
        session.scalar(
            select(AIArtifact.id)
            .where(
                AIArtifact.tenant_id == tenant_id,
                sa_cast(AIArtifact.output, Text).like(f"%{token}%"),
            )
            .limit(1)
        )
        is not None
    )


def _evidence_has_hard_refs(
    session: Session, *, tenant_id: uuid.UUID, evidence_id: uuid.UUID
) -> bool:
    """True when product rows still need the Evidence row (joins / other pins)."""

    join_tables = (
        EvidenceDossier,
        OpportunityEvidence,
        HypothesisEvidence,
        RiskEvidence,
        ReportEvidence,
        DecisionEvidence,
        InsightEvidence,
        MeetingEvidence,
        RelationshipEvidence,
        DossierActorEvidence,
        AIContextEvidence,
    )
    for model in join_tables:
        if (
            session.scalar(
                select(model.evidence_id)
                .where(
                    model.tenant_id == tenant_id,
                    model.evidence_id == evidence_id,
                )
                .limit(1)
            )
            is not None
        ):
            return True
    return (
        session.scalar(
            select(DossierProcurementItem.id)
            .where(
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.evidence_id == evidence_id,
            )
            .limit(1)
        )
        is not None
    )


def dispose_procurement_evidence(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    evidence_id: uuid.UUID,
) -> dict[str, Any]:
    """Detach pin evidence from the dossier; drop only if uncited (098 rule).

    - Always unlinks ``evidence_dossiers`` for this dossier so future agent
      context cannot cite it.
    - Clears ``ai_context_evidence`` for the same triple first (RESTRICT FK).
    - If the Evidence row is still referenced by artifacts or other product
      joins, the row is kept (historical citations remain resolvable).
    - If nothing else needs it, the Evidence row is deleted.
    """

    session.execute(
        delete(AIContextEvidence).where(
            AIContextEvidence.tenant_id == tenant_id,
            AIContextEvidence.dossier_id == dossier_id,
            AIContextEvidence.evidence_id == evidence_id,
        )
    )
    session.execute(
        delete(EvidenceDossier).where(
            EvidenceDossier.tenant_id == tenant_id,
            EvidenceDossier.dossier_id == dossier_id,
            EvidenceDossier.evidence_id == evidence_id,
        )
    )
    session.flush()

    cited = _evidence_cited_by_artifacts(
        session, tenant_id=tenant_id, evidence_id=evidence_id
    )
    hard_refs = _evidence_has_hard_refs(
        session, tenant_id=tenant_id, evidence_id=evidence_id
    )
    if cited or hard_refs:
        return {
            "evidence_id": str(evidence_id),
            "disposition": "retained_uncitable",
            "cited_by_artifacts": cited,
            "hard_refs": hard_refs,
        }

    evidence = session.get(Evidence, evidence_id)
    if evidence is not None and evidence.tenant_id == tenant_id:
        session.delete(evidence)
        session.flush()
        return {
            "evidence_id": str(evidence_id),
            "disposition": "deleted",
            "cited_by_artifacts": False,
            "hard_refs": False,
        }
    return {
        "evidence_id": str(evidence_id),
        "disposition": "missing",
        "cited_by_artifacts": False,
        "hard_refs": False,
    }


def delete_procurement_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    item_id: uuid.UUID,
) -> bool | dict[str, Any]:
    item = session.scalar(
        select(DossierProcurementItem).where(
            DossierProcurementItem.id == item_id,
            DossierProcurementItem.tenant_id == tenant_id,
            DossierProcurementItem.dossier_id == dossier_id,
        )
    )
    if item is None:
        return False
    evidence_id = item.evidence_id
    kind = item.kind
    folder_id = item.folder_id
    session.delete(item)
    session.flush()
    evidence_result = dispose_procurement_evidence(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        evidence_id=evidence_id,
    )
    append_audit_event(
        session,
        action="procurement.unpinned",
        resource_type="dossier_procurement_item",
        resource_id=item_id,
        dossier_id=dossier_id,
        result="success",
        metadata={
            "kind": kind,
            "folder_id": folder_id,
            "evidence": evidence_result,
        },
    )
    return {
        "deleted": True,
        "id": str(item_id),
        "evidence": evidence_result,
    }


def refresh_procurement_item(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    item_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> tuple[DossierProcurementItem, dict[str, Any]]:
    """Re-fetch Signal snapshot for a pin without changing its identity.

    Preserves pin id, ``linked_opportunity_id`` and (when extract unchanged)
    the existing evidence id. When the citable extract changes, creates a new
    Evidence version and disposes the previous one under the 098 rule
    (cited → keep unlinked; uncited → delete).
    """

    del actor_id  # reserved for future audit actor attribution
    item = session.scalar(
        select(DossierProcurementItem)
        .where(
            DossierProcurementItem.id == item_id,
            DossierProcurementItem.tenant_id == tenant_id,
            DossierProcurementItem.dossier_id == dossier_id,
        )
        .with_for_update()
    )
    if item is None:
        raise ProcurementItemError("Referencia de contratación no encontrada.")

    normalized_kind = cast(ProcurementKind, item.kind)
    previous_evidence_id = item.evidence_id
    previous_linked = item.linked_opportunity_id
    previous_snapshot = item.snapshot if isinstance(item.snapshot, dict) else None
    snapshot = resolve_procurement_snapshot(normalized_kind, item.folder_id)
    if normalized_kind == "award":
        snapshot = preserve_award_winner_identifiers(previous_snapshot, snapshot)
    extract = procurement_evidence_extract(snapshot)
    new_checksum = _checksum(extract)
    new_source_url = _source_url(snapshot)
    snapshot_sha = hashlib.sha256(_canonical(snapshot)).hexdigest()

    item.snapshot = snapshot
    item.source_url = new_source_url

    evidence_meta: dict[str, Any] = {
        "previous_evidence_id": str(previous_evidence_id),
        "evidence_rotated": False,
        "previous_disposition": None,
    }

    previous_evidence = session.get(Evidence, previous_evidence_id)
    same_content = (
        previous_evidence is not None
        and previous_evidence.tenant_id == tenant_id
        and previous_evidence.checksum == new_checksum
    )
    if same_content and previous_evidence is not None:
        # Snapshot fields may change without altering the citable extract (e.g. NIF
        # added to structured snapshot but extract still has the same prose). Update
        # provenance pointers only — never mutate extract/checksum of an existing row.
        provenance = dict(previous_evidence.provenance or {})
        provenance["snapshot_sha256"] = snapshot_sha
        provenance["refreshed_at"] = datetime.now(UTC).isoformat()
        previous_evidence.provenance = provenance
        if new_source_url and previous_evidence.source_url != new_source_url:
            previous_evidence.source_url = new_source_url
        evidence_meta["current_evidence_id"] = str(previous_evidence_id)
    else:
        new_evidence = Evidence(
            tenant_id=tenant_id,
            source_kind="procurement",
            source_url=new_source_url,
            extract=extract[:20000],
            locator={
                "kind": "placsp_procurement",
                "procurement_kind": normalized_kind,
                "folder_id": item.folder_id,
                "source_url": new_source_url,
            },
            checksum=new_checksum,
            classification="internal",
            provenance={
                "source_kind": "procurement",
                "procurement_kind": normalized_kind,
                "folder_id": item.folder_id,
                "snapshot_sha256": snapshot_sha,
                "supersedes_evidence_id": str(previous_evidence_id),
            },
        )
        session.add(new_evidence)
        session.flush()
        item.evidence_id = new_evidence.id
        session.add(
            EvidenceDossier(
                tenant_id=tenant_id,
                evidence_id=new_evidence.id,
                dossier_id=dossier_id,
            )
        )
        session.flush()
        previous_disposition = dispose_procurement_evidence(
            session,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            evidence_id=previous_evidence_id,
        )
        evidence_meta.update(
            {
                "current_evidence_id": str(new_evidence.id),
                "evidence_rotated": True,
                "previous_disposition": previous_disposition,
            }
        )

    # Identity invariants: pin id and opportunity link must not change on refresh.
    assert item.linked_opportunity_id == previous_linked

    append_audit_event(
        session,
        action="procurement.refreshed",
        resource_type="dossier_procurement_item",
        resource_id=item.id,
        dossier_id=dossier_id,
        result="success",
        metadata={
            "kind": item.kind,
            "folder_id": item.folder_id,
            "evidence": evidence_meta,
            "linked_opportunity_id": (
                str(item.linked_opportunity_id) if item.linked_opportunity_id else None
            ),
        },
    )
    # Refresh puede traer NIF recién backfilleado en Signal; re-hidratar actores.
    if item.kind == "award":
        hydrate_dossier_actor_tax_ids_from_awards(
            session, tenant_id=tenant_id, dossier_id=dossier_id
        )
    return item, evidence_meta


def _snapshot_deadline(snapshot: dict[str, Any]) -> date | None:
    """Copy a tender closing date into Opportunity.deadline when parseable.

    PLACSP/Signal may store a plain ISO date or a datetime. Unparseable values
    are ignored (None) so promotion never fails solely because of date shape.
    """

    raw = snapshot.get("deadline")
    if raw in (None, ""):
        raw = snapshot.get("deadline_date")
    if raw in (None, ""):
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        if "T" in text or " " in text or "+" in text[10:]:
            return datetime.fromisoformat(text).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def promote_procurement_to_opportunity(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    item_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> tuple[Opportunity, bool]:
    item = session.scalar(
        select(DossierProcurementItem)
        .where(
            DossierProcurementItem.id == item_id,
            DossierProcurementItem.tenant_id == tenant_id,
            DossierProcurementItem.dossier_id == dossier_id,
        )
        .with_for_update()
    )
    if item is None:
        raise ProcurementItemError("Referencia de contratación no encontrada.")
    if item.linked_opportunity_id is not None:
        existing = session.scalar(
            select(Opportunity).where(
                Opportunity.id == item.linked_opportunity_id,
                Opportunity.tenant_id == tenant_id,
                Opportunity.dossier_id == dossier_id,
            )
        )
        if existing is not None:
            return existing, False
    title = str(item.snapshot.get("title") or f"Contratación {item.folder_id}")[:300]
    snapshot = item.snapshot if isinstance(item.snapshot, dict) else {}
    opportunity = Opportunity(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_type="public_procurement",
        title=title,
        description=procurement_evidence_extract(snapshot)[:10000],
        confidence=70,
        overall_score=0,
        score_details={
            "confidence": {
                "value": 70,
                "basis": (
                    "Una referencia oficial fijada como evidencia; evaluación humana pendiente."
                ),
                "evidence_ids": [str(item.evidence_id)],
            }
        },
        deadline=_snapshot_deadline(snapshot),
        next_action="Completar la evaluación participar/no participar.",
        owner_user_id=actor_id,
    )
    session.add(opportunity)
    session.flush()
    session.add(
        OpportunityEvidence(
            tenant_id=tenant_id,
            opportunity_id=opportunity.id,
            evidence_id=item.evidence_id,
        )
    )
    item.linked_opportunity_id = opportunity.id
    append_audit_event(
        session,
        action="procurement.promoted_to_opportunity",
        resource_type="opportunity",
        resource_id=opportunity.id,
        dossier_id=dossier_id,
        result="success",
        metadata={"procurement_item_id": str(item.id), "folder_id": item.folder_id},
    )
    return opportunity, True


def backfill_opportunity_deadlines_from_procurement(
    session: Session,
    *,
    tenant_id: uuid.UUID | None = None,
) -> int:
    """Fill Opportunity.deadline from the linked tender snapshot when still null.

    Safe contract:
    - only rows with ``linked_opportunity_id`` (promoted from procurement);
    - never overwrites a non-null ``Opportunity.deadline``;
    - ignores unparseable snapshot dates;
    - agent/manual opportunities without a linked tender stay null (no date to recover).

    Returns the number of opportunities updated.
    """

    query = (
        select(DossierProcurementItem, Opportunity)
        .join(
            Opportunity,
            (Opportunity.id == DossierProcurementItem.linked_opportunity_id)
            & (Opportunity.tenant_id == DossierProcurementItem.tenant_id),
        )
        .where(
            DossierProcurementItem.linked_opportunity_id.is_not(None),
            Opportunity.deadline.is_(None),
        )
    )
    if tenant_id is not None:
        query = query.where(DossierProcurementItem.tenant_id == tenant_id)

    updated = 0
    for item, opportunity in session.execute(query).all():
        snapshot = item.snapshot if isinstance(item.snapshot, dict) else {}
        deadline = _snapshot_deadline(snapshot)
        if deadline is None:
            continue
        opportunity.deadline = deadline
        updated += 1
    return updated


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
        "linked_opportunity_id": (
            str(item.linked_opportunity_id) if item.linked_opportunity_id else None
        ),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
