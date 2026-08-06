"""Actor tax_id identity: normalization, durable column, uniqueness, conflicts.

G-16 structural phase. Single source of truth for company CIF handling.

Policy:
- Only unmasked Spanish company CIFs (no ``*``, no person NIF, no multi-ID strings).
- Column ``actors.tax_id`` is the durable identity when present; name is fallback.
- Partial unique index (tenant_id, tax_id) WHERE tax_id IS NOT NULL resists races.
- Assigning an occupied tax_id raises :class:`TaxIdConflictError` (never silent overwrite).
- Backfill records losers as resolvable conflicts; never deletes or merges actors.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from opn_oracle.oracle.investigations import (
    LEGAL_SUFFIXES,
    extract_company_tax_id,
    normalize_identity_name,
    normalize_spanish_company_tax_id,
)
from opn_oracle.oracle.models import Actor, ActorTaxIdConflict, DossierActor, DossierProcurementItem

_MASK_CHARS = re.compile(r"[*•xX…]")
TAX_ID_SCHEME_ES_CIF = "ES_CIF"
TAX_ID_COUNTRY_ES = "ES"
COMPANY_ACTOR_TYPES = frozenset({"organization", "institution"})


class TaxIdConflictError(RuntimeError):
    """NIF/CIF already held by another active actor in the same tenant."""

    def __init__(
        self,
        message: str,
        *,
        tax_id: str,
        canonical_actor_id: uuid.UUID,
        canonical_actor_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tax_id = tax_id
        self.canonical_actor_id = canonical_actor_id
        self.canonical_actor_name = canonical_actor_name


class TaxIdValidationError(ValueError):
    """Rejected tax_id (masked, person NIF, multiple IDs, empty, etc.)."""


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


def require_usable_company_tax_id(value: Any, *, actor_type: str | None = None) -> str:
    """Validate and return normalized CIF; raise on reject."""

    if actor_type is not None and actor_type not in COMPANY_ACTOR_TYPES:
        # Person / program actors must not receive company tax identity.
        if value not in (None, ""):
            raise TaxIdValidationError(
                "Solo actores organización/institución pueden llevar CIF de sociedad."
            )
        raise TaxIdValidationError("tax_id vacío.")
    tax_id = usable_company_tax_id(value)
    if tax_id is None:
        raise TaxIdValidationError(
            "tax_id debe ser un CIF de sociedad español no enmascarado "
            "(sin NIF de persona, sin múltiples IDs)."
        )
    return tax_id


def tax_id_canonical_key(tax_id: str) -> str:
    """Stable identity key when tax_id governs the actor."""

    return f"tax:es:{tax_id}"[:320]


def actor_identity_canonical_key(*, name: str, tax_id: str | None = None) -> str:
    """Prefer tax_id identity; fall back to name-derived key."""

    from opn_oracle.oracle.actor_candidates import actor_canonical_key

    if tax_id:
        return tax_id_canonical_key(tax_id)
    return actor_canonical_key(name)


def actor_durable_tax_id(actor: Actor) -> str | None:
    """Read durable tax_id: column first, then identifiers via shared normalizer."""

    if getattr(actor, "tax_id", None):
        return usable_company_tax_id(actor.tax_id)
    identifiers = actor.identifiers if isinstance(actor.identifiers, dict) else {}
    return extract_company_tax_id(identifiers) or usable_company_tax_id(identifiers.get("tax_id"))


def find_actor_by_tax_id(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tax_id: str,
) -> Actor | None:
    normalized = usable_company_tax_id(tax_id)
    if not normalized:
        return None
    return session.scalar(
        select(Actor).where(Actor.tenant_id == tenant_id, Actor.tax_id == normalized)
    )


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

    identifier = (
        snapshot.get("winner_identifier")
        or snapshot.get("tax_id")
        or snapshot.get("nif")
        or snapshot.get("cif")
    )
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


def _sync_identifier_block(
    identifiers: dict[str, Any],
    *,
    tax_id: str,
    declared: str | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(identifiers or {})
    out["tax_id"] = tax_id
    out["tax_id_scheme"] = TAX_ID_SCHEME_ES_CIF
    if declared is not None:
        out.setdefault("tax_id_declared", declared)
    if source is not None:
        out["tax_id_source"] = source
    return out


def _maybe_set_tax_canonical_key(session: Session, actor: Actor, tax_id: str) -> None:
    """Move actor to tax-based canonical_key when the key is free."""

    tax_key = tax_id_canonical_key(tax_id)
    if actor.canonical_key == tax_key:
        return
    taken = session.scalar(
        select(Actor.id).where(
            Actor.tenant_id == actor.tenant_id,
            Actor.canonical_key == tax_key,
            Actor.id != actor.id,
        )
    )
    if taken is None:
        actor.canonical_key = tax_key


def assign_actor_tax_id(
    session: Session,
    actor: Actor,
    raw_tax_id: Any,
    *,
    provenance: dict[str, Any] | None = None,
    declared: str | None = None,
    allow_same: bool = True,
    bump_version: bool = True,
) -> bool:
    """Assign durable tax_id to actor.

    Returns True if the actor was mutated.
    Raises TaxIdValidationError or TaxIdConflictError.
    Never clears an existing different tax_id silently.

    When called from a generic PATCH that owns the version bump, pass
    ``bump_version=False`` so a single request does not double-increment.
    """

    tax_id = require_usable_company_tax_id(raw_tax_id, actor_type=actor.actor_type)
    declared_value = str(declared if declared is not None else raw_tax_id)[:80]

    current = usable_company_tax_id(getattr(actor, "tax_id", None))
    if current == tax_id:
        # Ensure identifiers/scheme stay coherent.
        identifiers = _sync_identifier_block(
            dict(actor.identifiers or {}),
            tax_id=tax_id,
            declared=declared_value,
            source=provenance,
        )
        changed = False
        if identifiers != (actor.identifiers or {}):
            actor.identifiers = identifiers
            changed = True
        if actor.tax_id_scheme != TAX_ID_SCHEME_ES_CIF:
            actor.tax_id_scheme = TAX_ID_SCHEME_ES_CIF
            changed = True
        if actor.tax_id_country != TAX_ID_COUNTRY_ES:
            actor.tax_id_country = TAX_ID_COUNTRY_ES
            changed = True
        if changed and bump_version:
            actor.version = int(actor.version or 1) + 1
        return changed

    if current and current != tax_id:
        if not allow_same:
            return False
        raise TaxIdValidationError(
            f"El actor ya tiene tax_id {current}; no se sobrescribe con {tax_id}. "
            "La corrección fiscal requiere un workflow explícito (no bypass JSONB)."
        )

    holder = find_actor_by_tax_id(session, tenant_id=actor.tenant_id, tax_id=tax_id)
    if holder is not None and holder.id != actor.id:
        raise TaxIdConflictError(
            f"El CIF {tax_id} ya está asignado al actor canónico.",
            tax_id=tax_id,
            canonical_actor_id=holder.id,
            canonical_actor_name=holder.canonical_name,
        )

    previous_key = actor.canonical_key
    previous_identifiers = dict(actor.identifiers or {})
    previous_provenance = dict(actor.provenance or {})
    previous_version = int(actor.version or 1)

    # Savepoint covers attribute mutation + flush so concurrent unique
    # violations become TaxIdConflictError without aborting the outer txn.
    try:
        with session.begin_nested():
            actor.tax_id = tax_id
            actor.tax_id_scheme = TAX_ID_SCHEME_ES_CIF
            actor.tax_id_country = TAX_ID_COUNTRY_ES
            actor.identifiers = _sync_identifier_block(
                previous_identifiers,
                tax_id=tax_id,
                declared=declared_value,
                source=provenance,
            )
            if provenance:
                prov = dict(previous_provenance)
                prov["tax_id_assignment"] = provenance
                actor.provenance = prov
            with session.no_autoflush:
                _maybe_set_tax_canonical_key(session, actor, tax_id)
            if bump_version:
                actor.version = previous_version + 1
            session.flush()
    except IntegrityError as error:
        # Nested rollback restores DB row; reset in-memory state on loser.
        actor.tax_id = current
        actor.tax_id_scheme = TAX_ID_SCHEME_ES_CIF if current else None
        actor.tax_id_country = TAX_ID_COUNTRY_ES if current else None
        actor.canonical_key = previous_key
        actor.identifiers = previous_identifiers
        actor.provenance = previous_provenance
        actor.version = previous_version
        holder = find_actor_by_tax_id(session, tenant_id=actor.tenant_id, tax_id=tax_id)
        if holder is not None and holder.id != actor.id:
            raise TaxIdConflictError(
                f"El CIF {tax_id} ya está asignado al actor canónico.",
                tax_id=tax_id,
                canonical_actor_id=holder.id,
                canonical_actor_name=holder.canonical_name,
            ) from error
        raise
    return True


_FISCAL_IDENTIFIER_KEYS = frozenset({"tax_id", "tax_id_scheme", "tax_id_declared", "tax_id_source"})


def _merge_non_fiscal_identifiers(
    base: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Partial merge of non-fiscal identifier keys.

    - Omitted keys are preserved from ``base``.
    - Present non-null values update/create the key.
    - Explicit JSON ``null`` removes that non-fiscal key.
    - Fiscal keys in ``patch`` are ignored (column-authoritative elsewhere).
    """

    out = {key: value for key, value in base.items() if key not in _FISCAL_IDENTIFIER_KEYS}
    for key, value in patch.items():
        if key in _FISCAL_IDENTIFIER_KEYS:
            continue
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def _preserve_orphan_fiscal_keys(
    merged: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Keep prior fiscal JSON keys when there is no durable column yet."""

    out = dict(merged)
    for key in _FISCAL_IDENTIFIER_KEYS:
        if key in previous and key not in out:
            out[key] = previous[key]
    return out


def apply_actor_identifiers_patch(
    session: Session,
    actor: Actor,
    incoming: dict[str, Any],
    *,
    bump_version: bool = False,
) -> None:
    """Apply PATCH identifiers as a partial merge without desyncing tax_id.

    Contract (G-16 identifiers merge rework):
    - Omitted keys are preserved (with or without durable tax_id).
    - Present non-fiscal keys are updated; explicit ``null`` deletes that key.
    - Fiscal block is column-authoritative and cannot be cleared/changed via JSON.
    - ``tax_id`` present + actor without column → ``assign_actor_tax_id`` (first CIF).
    - same CIF → idempotent sync via assign.
    - different CIF / clear / empty / invalid / masked / person / multi → 422
      (or 409 when occupied by another actor); no prior keys/version mutated.
    """

    if not isinstance(incoming, dict):
        raise TaxIdValidationError("identifiers debe ser un objeto.")

    payload = dict(incoming)
    current = usable_company_tax_id(getattr(actor, "tax_id", None))
    previous = dict(actor.identifiers or {}) if isinstance(actor.identifiers, dict) else {}

    if "tax_id" in payload:
        raw_tax = payload.get("tax_id")
        if raw_tax in (None, ""):
            if current:
                raise TaxIdValidationError(
                    "No se puede borrar el tax_id durable vía identifiers "
                    "(null/vacío). Requiere workflow de corrección fiscal."
                )
            # No durable column and client sent empty tax_id: drop fiscal keys,
            # partial-merge non-fiscal over previous (null deletes).
            actor.identifiers = _merge_non_fiscal_identifiers(previous, payload)
            return

        # Validate / assign fiscal first so invalid/conflict paths never touch
        # non-fiscal keys or version (assign owns its own mutations).
        normalized = require_usable_company_tax_id(raw_tax, actor_type=actor.actor_type)

        if current is None:
            assign_actor_tax_id(
                session,
                actor,
                raw_tax,
                declared=str(raw_tax)[:80],
                provenance={"source": "actor_patch", "via": "identifiers.tax_id"},
                bump_version=bump_version,
            )
        elif current == normalized:
            assign_actor_tax_id(
                session,
                actor,
                raw_tax,
                declared=str(raw_tax)[:80],
                provenance=None,
                bump_version=bump_version,
            )
        else:
            # Durable already set to a different CIF — no silent overwrite.
            raise TaxIdValidationError(
                f"El actor ya tiene tax_id {current}; no se sobrescribe con {normalized}. "
                "La corrección fiscal requiere un workflow explícito (no bypass JSONB)."
            )
    else:
        # tax_id key absent: partial merge; never drop durable fiscal block.
        merged = _merge_non_fiscal_identifiers(previous, payload)
        if current:
            source = (
                previous.get("tax_id_source")
                if isinstance(previous.get("tax_id_source"), dict)
                else None
            )
            actor.identifiers = _sync_identifier_block(
                merged,
                tax_id=current,
                declared=previous.get("tax_id_declared") or previous.get("tax_id") or current,
                source=source,
            )
            # Re-apply declared/source if _sync used setdefault-only paths.
            ids = dict(actor.identifiers or {})
            if previous.get("tax_id_declared") and "tax_id_declared" not in ids:
                ids["tax_id_declared"] = previous["tax_id_declared"]
            if previous.get("tax_id_source") is not None and "tax_id_source" not in ids:
                ids["tax_id_source"] = previous["tax_id_source"]
            actor.identifiers = ids
            return

        actor.identifiers = _preserve_orphan_fiscal_keys(merged, previous)
        return

    # After successful tax_id assign: merge non-fiscal over preserved previous.
    durable = usable_company_tax_id(getattr(actor, "tax_id", None))
    if durable:
        # assign_actor_tax_id already kept previous non-fiscal keys; apply patch
        # deltas (including null deletes) on top of that post-assign state.
        post = dict(actor.identifiers or {}) if isinstance(actor.identifiers, dict) else {}
        merged = _merge_non_fiscal_identifiers(post, payload)
        source = (
            post.get("tax_id_source")
            if isinstance(post.get("tax_id_source"), dict)
            else (
                previous.get("tax_id_source")
                if isinstance(previous.get("tax_id_source"), dict)
                else None
            )
        )
        actor.identifiers = _sync_identifier_block(
            merged,
            tax_id=durable,
            declared=post.get("tax_id_declared") or previous.get("tax_id_declared") or durable,
            source=source,
        )


def assert_actor_type_compatible_with_tax_id(
    actor: Actor,
    new_actor_type: str,
) -> None:
    """Block demotion of a fiscal company actor to a non-company type."""

    durable = usable_company_tax_id(getattr(actor, "tax_id", None))
    if durable and new_actor_type not in COMPANY_ACTOR_TYPES:
        raise TaxIdValidationError(
            "No se puede cambiar actor_type a persona/programa/other mientras "
            f"el actor conserva tax_id fiscal {durable}."
        )


def resolve_or_create_actor(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    canonical_name: str,
    actor_type: str = "organization",
    aliases: list[str] | None = None,
    identifiers: dict[str, Any] | None = None,
    actor_metadata: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> Actor:
    """Resolve actor by tax_id first, then name; create if missing.

    When tax_id is provided and free, the new actor gets tax-based canonical_key.
    When tax_id is occupied, returns the canonical holder (does not create a twin).
    """

    from opn_oracle.oracle.actor_candidates import actor_canonical_key

    name = " ".join(str(canonical_name).strip().split())[:300]
    ids = dict(identifiers or {})
    raw_tax = ids.get("tax_id") or extract_company_tax_id(ids)
    tax_id = usable_company_tax_id(raw_tax) if raw_tax not in (None, "") else None

    if tax_id and actor_type in COMPANY_ACTOR_TYPES:
        holder = find_actor_by_tax_id(session, tenant_id=tenant_id, tax_id=tax_id)
        if holder is not None:
            # Enrich aliases / provenance lightly; never fork identity.
            alias_set = {str(a) for a in (holder.aliases or []) if a}
            if name and name not in alias_set and name != holder.canonical_name:
                holder.aliases = sorted({*alias_set, name})
                holder.version = int(holder.version or 1) + 1
            return holder

        # Name-match without tax_id: claim the durable identity.
        name_key = actor_canonical_key(name)
        by_name = session.scalar(
            select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key == name_key)
        )
        if by_name is not None and not usable_company_tax_id(getattr(by_name, "tax_id", None)):
            assign_actor_tax_id(
                session,
                by_name,
                tax_id,
                declared=str(raw_tax) if raw_tax is not None else tax_id,
                provenance={"source": "resolve_or_create", "via": "name_claim"},
            )
            if ids:
                merged = dict(by_name.identifiers or {})
                for key, value in ids.items():
                    merged.setdefault(key, value)
                by_name.identifiers = _sync_identifier_block(
                    merged, tax_id=tax_id, declared=str(raw_tax) if raw_tax else tax_id
                )
            return by_name

        actor = Actor(
            tenant_id=tenant_id,
            actor_type=actor_type,
            canonical_name=name,
            canonical_key=tax_id_canonical_key(tax_id),
            tax_id=tax_id,
            tax_id_scheme=TAX_ID_SCHEME_ES_CIF,
            tax_id_country=TAX_ID_COUNTRY_ES,
            aliases=list(aliases or []),
            identifiers=_sync_identifier_block(
                ids, tax_id=tax_id, declared=str(raw_tax) if raw_tax else tax_id
            ),
            actor_metadata=dict(actor_metadata or {}),
            provenance=dict(provenance or {}),
        )
        session.add(actor)
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError as error:
            session.expunge(actor)
            holder = find_actor_by_tax_id(session, tenant_id=tenant_id, tax_id=tax_id)
            if holder is not None:
                return holder
            holder = session.scalar(
                select(Actor).where(
                    Actor.tenant_id == tenant_id,
                    Actor.canonical_key == tax_id_canonical_key(tax_id),
                )
            )
            if holder is not None:
                return holder
            raise TaxIdConflictError(
                f"Conflicto de identidad para CIF {tax_id}.",
                tax_id=tax_id,
                canonical_actor_id=uuid.UUID(int=0),
            ) from error
        return actor

    # No usable tax_id → name fallback (legacy path).
    name_key = actor_canonical_key(name)
    existing = session.scalar(
        select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key == name_key)
    )
    if existing is not None:
        return existing
    actor = Actor(
        tenant_id=tenant_id,
        actor_type=actor_type,
        canonical_name=name,
        canonical_key=name_key,
        aliases=list(aliases or []),
        identifiers=ids,
        actor_metadata=dict(actor_metadata or {}),
        provenance=dict(provenance or {}),
    )
    session.add(actor)
    session.flush()
    return actor


def select_backfill_winner(actors: list[Actor]) -> Actor:
    """Deterministic winner: earliest created_at, then smallest UUID."""

    return sorted(
        actors,
        key=lambda actor: (
            actor.created_at or datetime.min.replace(tzinfo=UTC),
            str(actor.id),
        ),
    )[0]


def record_tax_id_conflict(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    tax_id: str,
    winner: Actor,
    loser: Actor,
    declared_tax_id: str,
) -> ActorTaxIdConflict:
    """Insert or return existing open/known conflict (idempotent)."""

    existing = session.scalar(
        select(ActorTaxIdConflict).where(
            ActorTaxIdConflict.tenant_id == tenant_id,
            ActorTaxIdConflict.tax_id == tax_id,
            ActorTaxIdConflict.loser_actor_id == loser.id,
        )
    )
    if existing is not None:
        return existing
    conflict_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"opn-oracle:actor-tax-id-conflict:{tenant_id}:{tax_id}:{loser.id}",
    )
    row = ActorTaxIdConflict(
        id=conflict_id,
        tenant_id=tenant_id,
        tax_id=tax_id,
        winner_actor_id=winner.id,
        loser_actor_id=loser.id,
        declared_tax_id=str(declared_tax_id)[:80],
        declared_identifiers=dict(loser.identifiers or {}),
        status="open",
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(ActorTaxIdConflict).where(
                ActorTaxIdConflict.tenant_id == tenant_id,
                ActorTaxIdConflict.tax_id == tax_id,
                ActorTaxIdConflict.loser_actor_id == loser.id,
            )
        )
        if existing is not None:
            return existing
        raise
    return row


def backfill_actor_tax_ids_from_identifiers(
    session: Session,
    *,
    tenant_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Idempotent backfill of column tax_id from identifiers.tax_id.

    Safe with Capgemini-style collisions: winners materialize uniqueness;
    losers keep declared JSONB value and appear in the conflict ledger.
    Never deletes or merges actors.
    """

    query = select(Actor).order_by(Actor.tenant_id, Actor.created_at.asc(), Actor.id.asc())
    if tenant_id is not None:
        query = query.where(Actor.tenant_id == tenant_id)
    actors = list(session.scalars(query))

    groups: dict[tuple[uuid.UUID, str], list[tuple[Actor, str]]] = defaultdict(list)
    invalid = 0
    for actor in actors:
        identifiers = actor.identifiers if isinstance(actor.identifiers, dict) else {}
        declared = identifiers.get("tax_id")
        if declared in (None, ""):
            continue
        normalized = usable_company_tax_id(declared)
        if normalized is None:
            invalid += 1
            continue
        groups[(actor.tenant_id, normalized)].append((actor, str(declared)))

    applied = 0
    collisions = 0
    unchanged = 0
    for (tenant, tax_id), members in groups.items():
        ordered = [item[0] for item in members]
        winner = select_backfill_winner(ordered)
        declared_by_id = {actor.id: declared for actor, declared in members}

        if usable_company_tax_id(winner.tax_id) == tax_id:
            unchanged += 1
        else:
            try:
                if assign_actor_tax_id(
                    session,
                    winner,
                    tax_id,
                    declared=declared_by_id[winner.id],
                    provenance={
                        "source": "identifiers.tax_id",
                        "role": "winner",
                        "backfilled_at": datetime.now(UTC).isoformat(),
                    },
                ):
                    applied += 1
                else:
                    unchanged += 1
            except TaxIdConflictError:
                # Another actor already holds it; intended winner becomes loser below.
                pass

        holder = find_actor_by_tax_id(session, tenant_id=tenant, tax_id=tax_id) or winner
        for actor, declared in members:
            if actor.id == holder.id:
                continue
            collisions += 1
            record_tax_id_conflict(
                session,
                tenant_id=tenant,
                tax_id=tax_id,
                winner=holder,
                loser=actor,
                declared_tax_id=declared,
            )
            # Ensure loser column stays null (not unique holder) but JSONB preserved.
            if usable_company_tax_id(actor.tax_id) == tax_id and actor.id != holder.id:
                actor.tax_id = None
                actor.tax_id_scheme = None
                actor.tax_id_country = None
                actor.version = int(actor.version or 1) + 1
            prov = dict(actor.provenance or {})
            prov["tax_id_column_backfill"] = {
                "source": "identifiers.tax_id",
                "tax_id": tax_id,
                "declared_tax_id": declared,
                "role": "loser",
                "winner_actor_id": str(holder.id),
                "backfilled_at": datetime.now(UTC).isoformat(),
            }
            actor.provenance = prov

    session.flush()
    return {
        "applied": applied,
        "collisions": collisions,
        "invalid": invalid,
        "unchanged": unchanged,
        "groups": len(groups),
    }


def list_tax_id_conflicts(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    status: str | None = "open",
    limit: int = 100,
) -> list[ActorTaxIdConflict]:
    query = select(ActorTaxIdConflict).where(ActorTaxIdConflict.tenant_id == tenant_id)
    if status:
        query = query.where(ActorTaxIdConflict.status == status)
    query = query.order_by(ActorTaxIdConflict.created_at.desc()).limit(max(1, min(limit, 500)))
    return list(session.scalars(query))


def resolve_tax_id_conflict(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    conflict_id: uuid.UUID,
    action: str,
    note: str = "",
    actor_id: uuid.UUID | None = None,
) -> ActorTaxIdConflict:
    """Backend contract for later G-16-B/G-17 UI. Does not merge relations."""

    conflict = session.scalar(
        select(ActorTaxIdConflict).where(
            ActorTaxIdConflict.id == conflict_id,
            ActorTaxIdConflict.tenant_id == tenant_id,
        )
    )
    if conflict is None:
        raise LookupError("Conflicto de tax_id no encontrado.")
    if conflict.status != "open":
        return conflict
    normalized = str(action or "").strip().lower()
    if normalized not in {"keep_winner", "dismiss", "resolved"}:
        raise ValueError("action debe ser keep_winner, dismiss o resolved.")
    conflict.status = "dismissed" if normalized == "dismiss" else "resolved"
    conflict.resolution_note = (note or f"action={normalized}")[:2000]
    conflict.resolved_at = datetime.now(UTC)
    conflict.resolved_by_user_id = actor_id
    conflict.version = int(conflict.version or 1) + 1
    session.flush()
    return conflict


def _apply_tax_id(
    actor: Actor,
    *,
    tax_id: str,
    folder_id: str,
    winner_name: str,
    session: Session | None = None,
) -> bool:
    """Materializa tax_id + proveniencia. False si no muta.

    When ``session`` is provided, uses durable column assignment with conflict safety.
    Without session (unit tests with SimpleNamespace), keeps JSONB-only legacy path.
    """

    provenance_block = _tax_id_provenance(
        folder_id=folder_id, winner_name=winner_name, tax_id=tax_id
    )

    if session is not None and isinstance(actor, Actor):
        try:
            return assign_actor_tax_id(
                session,
                actor,
                tax_id,
                provenance=provenance_block,
                declared=tax_id,
                allow_same=True,
            )
        except TaxIdConflictError:
            # Another actor already holds this CIF — do not create twins via hydration.
            return False
        except TaxIdValidationError:
            return False

    identifiers = dict(actor.identifiers or {})
    existing = extract_company_tax_id(identifiers) or usable_company_tax_id(
        identifiers.get("tax_id")
    )

    if existing and existing != tax_id:
        return False

    if existing == tax_id:
        current_src = identifiers.get("tax_id_source")
        if isinstance(current_src, dict) and current_src.get("folder_id"):
            return False
        identifiers["tax_id"] = tax_id
        identifiers["tax_id_scheme"] = TAX_ID_SCHEME_ES_CIF
        identifiers["tax_id_source"] = provenance_block
        actor.identifiers = identifiers
        if hasattr(actor, "tax_id"):
            actor.tax_id = tax_id
            actor.tax_id_scheme = TAX_ID_SCHEME_ES_CIF
            actor.tax_id_country = TAX_ID_COUNTRY_ES
        actor.version = int(actor.version or 1) + 1
        return True

    identifiers["tax_id"] = tax_id
    identifiers["tax_id_scheme"] = TAX_ID_SCHEME_ES_CIF
    identifiers["tax_id_source"] = provenance_block
    actor.identifiers = identifiers
    if hasattr(actor, "tax_id"):
        actor.tax_id = tax_id
        actor.tax_id_scheme = TAX_ID_SCHEME_ES_CIF
        actor.tax_id_country = TAX_ID_COUNTRY_ES
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
        try:
            changed = _apply_tax_id(
                actor,
                tax_id=tax_id,
                folder_id=chosen["folder_id"],
                winner_name=chosen["winner_name"],
                session=session,
            )
            status = "hydrated" if changed else "unchanged"
        except TaxIdConflictError as error:
            status = "conflict"
            results.append(
                {
                    "actor_id": str(actor.id),
                    "name": actor.canonical_name,
                    "status": status,
                    "tax_id": tax_id,
                    "canonical_actor_id": str(error.canonical_actor_id),
                    "reason": str(error),
                }
            )
            continue
        results.append(
            {
                "actor_id": str(actor.id),
                "name": actor.canonical_name,
                "status": status,
                "tax_id": tax_id,
                "folder_id": chosen["folder_id"],
                "winner_name": chosen["winner_name"],
                "tax_id_source": (actor.identifiers or {}).get("tax_id_source"),
            }
        )

    return results
