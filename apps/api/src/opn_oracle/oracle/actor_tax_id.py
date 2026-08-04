"""Hydrate Actor.identifiers.tax_id from pinned PLACSP awards.

Policy (SV2-NIF-ACTORES / 078-079):
- Only unmasked Spanish company CIFs (no ``*``, no person NIF).
- Emparejamiento por identidad de nombre (canónico + alias, sin forma jurídica).
- Si un actor empareja con varios CIF distintos → no hidratar (mejor vacío).
- No sobrescribir un tax_id ya presente y distinto.
- Proveniencia obligatoria en el propio identificador (award + folder_id).
- Nunca fusiona actores.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.oracle.investigations import (
    LEGAL_SUFFIXES,
    extract_company_tax_id,
    normalize_identity_name,
    normalize_spanish_company_tax_id,
)
from opn_oracle.oracle.models import Actor, DossierActor, DossierProcurementItem

_MASK_CHARS = re.compile(r"[*•xX…]")


def usable_company_tax_id(value: Any) -> str | None:
    """CIF de sociedad usable: forma fiscal + sin máscara PLACSP."""

    if value is None:
        return None
    text = str(value).strip()
    if not text or _MASK_CHARS.search(text):
        return None
    # Aggregated multi-winner collections join with "; " — not a single CIF.
    if ";" in text:
        return None
    return normalize_spanish_company_tax_id(text)


def identity_match_keys(name: str) -> set[str]:
    """Claves de emparejamiento actor↔adjudicatario (colapso de forma jurídica)."""

    keys: set[str] = set()
    full = normalize_identity_name(name, drop_legal_suffix=False)
    dropped = normalize_identity_name(name, drop_legal_suffix=True)
    if full:
        keys.add(full)
    if dropped:
        keys.add(dropped)
    tokens = full.split() if full else []
    while tokens:
        if len(tokens) >= 3 and tokens[-3:] == ["S", "L", "U"]:
            tokens = tokens[:-3]
            continue
        if len(tokens) >= 2 and tokens[-2:] in (["S", "L"], ["S", "A"]):
            tokens = tokens[:-2]
            continue
        if tokens[-1] in LEGAL_SUFFIXES:
            tokens.pop()
            continue
        break
    if tokens:
        keys.add(" ".join(tokens))
    return {key for key in keys if key}


def _actor_identity_keys(actor: Actor) -> set[str]:
    keys = identity_match_keys(actor.canonical_name)
    aliases = actor.aliases if isinstance(actor.aliases, list) else []
    for alias in aliases:
        if isinstance(alias, str) and alias.strip():
            keys |= identity_match_keys(alias)
    return keys


def iter_award_winner_tax_sources(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Extrae pares (winner, tax_id, folder_id) de un snapshot de award fijado."""

    if not isinstance(snapshot, dict):
        return []
    folder_id = str(snapshot.get("folder_id") or "").strip()
    if not folder_id:
        return []

    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(winner: Any, identifier: Any) -> None:
        winner_name = " ".join(str(winner or "").strip().split())
        tax_id = usable_company_tax_id(identifier)
        if not winner_name or not tax_id:
            return
        key = (winner_name.casefold(), tax_id)
        if key in seen:
            return
        seen.add(key)
        sources.append(
            {
                "winner_name": winner_name[:300],
                "tax_id": tax_id,
                "folder_id": folder_id[:240],
            }
        )

    entries = snapshot.get("entries")
    if isinstance(entries, list) and entries:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            identifier = (
                entry.get("winner_identifier")
                or entry.get("tax_id")
                or entry.get("nif")
                or entry.get("cif")
            )
            add(entry.get("winner"), identifier)
        return sources

    # Snapshot plano (un solo adjudicatario).
    identifier = (
        snapshot.get("winner_identifier")
        or snapshot.get("tax_id")
        or snapshot.get("nif")
        or snapshot.get("cif")
    )
    # Collections may aggregate identifiers with "; " — only accept a single CIF.
    if identifier is not None and ";" not in str(identifier):
        add(snapshot.get("winner"), identifier)
    return sources


def _tax_id_provenance(*, folder_id: str, winner_name: str, tax_id: str) -> dict[str, Any]:
    return {
        "source_kind": "procurement",
        "procurement_kind": "award",
        "source": "placsp",
        "folder_id": folder_id,
        "winner_name": winner_name,
        "tax_id": tax_id,
        "hydrated_at": datetime.now(UTC).isoformat(),
    }


def _apply_tax_id(
    actor: Actor,
    *,
    tax_id: str,
    folder_id: str,
    winner_name: str,
) -> bool:
    """Materializa tax_id + proveniencia. False si no muta."""

    identifiers = dict(actor.identifiers or {})
    existing = extract_company_tax_id(identifiers) or usable_company_tax_id(
        identifiers.get("tax_id")
    )
    provenance_block = _tax_id_provenance(
        folder_id=folder_id, winner_name=winner_name, tax_id=tax_id
    )

    if existing and existing != tax_id:
        # No envenenar un identificador ya presente y distinto.
        return False

    if existing == tax_id:
        # Refrescar proveniencia si falta; no reescribir si ya hay origen.
        current_src = identifiers.get("tax_id_source")
        if isinstance(current_src, dict) and current_src.get("folder_id"):
            return False
        identifiers["tax_id"] = tax_id
        identifiers["tax_id_scheme"] = "ES_CIF"
        identifiers["tax_id_source"] = provenance_block
        actor.identifiers = identifiers
        actor.version = int(actor.version or 1) + 1
        return True

    identifiers["tax_id"] = tax_id
    identifiers["tax_id_scheme"] = "ES_CIF"
    identifiers["tax_id_source"] = provenance_block
    actor.identifiers = identifiers
    actor.version = int(actor.version or 1) + 1

    provenance = dict(actor.provenance or {})
    provenance["tax_id_hydration"] = provenance_block
    actor.provenance = provenance
    return True


def hydrate_dossier_actor_tax_ids_from_awards(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    actor_ids: set[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    """Hidrata tax_id de actores del expediente desde pins award del mismo dossier.

    Returns:
        Lista de resultados por actor hidratado o saltado con motivo.
    """

    pins = list(
        session.scalars(
            select(DossierProcurementItem).where(
                DossierProcurementItem.tenant_id == tenant_id,
                DossierProcurementItem.dossier_id == dossier_id,
                DossierProcurementItem.kind == "award",
            )
        )
    )
    award_sources: list[dict[str, str]] = []
    for pin in pins:
        snapshot = pin.snapshot if isinstance(pin.snapshot, dict) else {}
        award_sources.extend(iter_award_winner_tax_sources(snapshot))

    if not award_sources:
        return []

    # Índice: identity_key → lista de (tax_id, folder_id, winner_name)
    by_identity: dict[str, list[dict[str, str]]] = {}
    for source in award_sources:
        for key in identity_match_keys(source["winner_name"]):
            by_identity.setdefault(key, []).append(source)

    actor_query = (
        select(Actor)
        .join(DossierActor, DossierActor.actor_id == Actor.id)
        .where(
            DossierActor.tenant_id == tenant_id,
            DossierActor.dossier_id == dossier_id,
            Actor.tenant_id == tenant_id,
            Actor.actor_type == "organization",
        )
    )
    actors = list(session.scalars(actor_query))
    if actor_ids is not None:
        actors = [actor for actor in actors if actor.id in actor_ids]

    results: list[dict[str, Any]] = []
    for actor in actors:
        keys = _actor_identity_keys(actor)
        matched: list[dict[str, str]] = []
        for key in keys:
            matched.extend(by_identity.get(key, []))
        if not matched:
            results.append(
                {
                    "actor_id": str(actor.id),
                    "name": actor.canonical_name,
                    "status": "no_match",
                }
            )
            continue

        tax_ids = {item["tax_id"] for item in matched}
        if len(tax_ids) > 1:
            results.append(
                {
                    "actor_id": str(actor.id),
                    "name": actor.canonical_name,
                    "status": "ambiguous",
                    "tax_ids": sorted(tax_ids),
                    "reason": "varios CIF posibles para el mismo actor; no se hidrata",
                }
            )
            continue

        chosen = matched[0]
        tax_id = chosen["tax_id"]
        changed = _apply_tax_id(
            actor,
            tax_id=tax_id,
            folder_id=chosen["folder_id"],
            winner_name=chosen["winner_name"],
        )
        results.append(
            {
                "actor_id": str(actor.id),
                "name": actor.canonical_name,
                "status": "hydrated" if changed else "unchanged",
                "tax_id": tax_id,
                "folder_id": chosen["folder_id"],
                "winner_name": chosen["winner_name"],
                "tax_id_source": (actor.identifiers or {}).get("tax_id_source"),
            }
        )

    return results
