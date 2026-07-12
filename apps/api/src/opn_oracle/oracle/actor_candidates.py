"""Source-backed actor candidates for a single strategic dossier."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.oracle.models import (
    Actor,
    ActorCandidateReview,
    DossierActor,
    DossierSignal,
    Signal,
)

ACTOR_TYPES = frozenset({"person", "organization", "institution", "program", "other"})

_TYPE_MAP = {
    "company": "organization",
    "empresa": "organization",
    "organization": "organization",
    "organisation": "organization",
    "organizacion": "organization",
    "organización": "organization",
    "person": "person",
    "persona": "person",
    "institution": "institution",
    "institucion": "institution",
    "institución": "institution",
    "agency": "institution",
    "government": "institution",
    "organismo": "institution",
    "program": "program",
    "programa": "program",
}

_ENTITY_CONTAINER_KEYS = frozenset(
    {
        "actors",
        "companies",
        "entities",
        "mentioned_entities",
        "organizations",
        "organisations",
        "people",
        "persons",
    }
)
_ORGANIZATION_NAME = (
    r"[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ&-]{1,}"
    r"(?:\s+[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ&-]{1,}){0,3}"
)
_CONTEXT_PATTERNS = (
    re.compile(
        rf"\b(?P<name>{_ORGANIZATION_NAME})\s+"
        r"(?i:anuncia|defiende|desarrolla|firma|impulsa|invierte|lanza|presenta|produce)\b",
    ),
    re.compile(
        rf"\b(?i:alianza con|en colaboración con|junto a|junto con|por parte de)\s+"
        rf"(?P<name>{_ORGANIZATION_NAME})\b",
    ),
    re.compile(
        rf"\b(?P<name>{_ORGANIZATION_NAME}\s+"
        r"(?i:GmbH|Inc\.?|Ltd\.?|PLC|S\.?A\.?|S\.?L\.?))\b",
    ),
)


def actor_canonical_key(value: str) -> str:
    return "-".join(str(value).casefold().split())[:320]


def clean_labels(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for item in value:
        label = " ".join(str(item).strip().split())[:80]
        key = label.casefold()
        if not label or key in seen:
            continue
        labels.append(label)
        seen.add(key)
        if len(labels) >= limit:
            break
    return labels


def _suggested_type(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    return _TYPE_MAP.get(normalized, "other")


def _candidate_id(dossier_id: uuid.UUID, canonical_key: str) -> uuid.UUID:
    value = f"opn-oracle:actor-candidate:{dossier_id}:{canonical_key}"
    return uuid.uuid5(uuid.NAMESPACE_URL, value)


def _normalize_entity(value: Any, *, extraction_method: str) -> dict[str, Any] | None:
    if isinstance(value, str):
        name = " ".join(value.strip().split())
        entity_type = "organization"
        labels: list[str] = []
    elif isinstance(value, dict):
        name = " ".join(
            str(value.get("name") or value.get("label") or value.get("title") or "").strip().split()
        )
        entity_type = str(value.get("type") or value.get("entity_type") or "other")
        labels = clean_labels(value.get("tags") or value.get("labels") or [])
    else:
        return None
    if len(name) < 2 or len(name) > 300:
        return None
    return {
        "name": name,
        "type": _suggested_type(entity_type),
        "tags": labels,
        "extraction_method": extraction_method,
    }


def _payload_entity_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.casefold() in _ENTITY_CONTAINER_KEYS:
                found.extend(nested if isinstance(nested, list) else [nested])
            elif isinstance(nested, (dict, list)):
                found.extend(_payload_entity_values(nested))
    elif isinstance(value, list):
        for nested in value:
            if isinstance(nested, (dict, list)):
                found.extend(_payload_entity_values(nested))
    return found


def extract_signal_entities(
    entities: Any,
    *,
    raw_payload: Any,
    title: str,
    summary: str,
) -> list[dict[str, Any]]:
    """Normalize provider entities and recover conservative organization mentions."""
    normalized: dict[str, dict[str, Any]] = {}

    def add(value: Any, method: str) -> None:
        entity = _normalize_entity(value, extraction_method=method)
        if entity is None:
            return
        key = actor_canonical_key(entity["name"])
        current = normalized.get(key)
        if current is None or (current["type"] == "other" and entity["type"] != "other"):
            normalized[key] = entity

    for entity in entities if isinstance(entities, list) else []:
        add(entity, "provider")
    for entity in _payload_entity_values(raw_payload):
        add(entity, "payload")
    text = ". ".join(part.rstrip(". ") for part in (title, summary) if part)
    for pattern in _CONTEXT_PATTERNS:
        for match in pattern.finditer(text):
            add({"name": match.group("name"), "type": "organization"}, "text_pattern")
    return list(normalized.values())[:100]


def set_actor_candidate_review(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    candidate: dict[str, Any],
    status: str | None,
    reviewed_by_user_id: uuid.UUID,
) -> ActorCandidateReview | None:
    review = session.scalar(
        select(ActorCandidateReview).where(
            ActorCandidateReview.tenant_id == tenant_id,
            ActorCandidateReview.dossier_id == dossier_id,
            ActorCandidateReview.canonical_key == candidate["canonical_key"],
        )
    )
    if status is None:
        if review is not None:
            session.delete(review)
        return None
    if status not in {"dismissed", "imported"}:
        raise ValueError("Estado de revisión no válido.")
    source_signal_ids = [source["signal_id"] for source in candidate["sources"]]
    if review is None:
        review = ActorCandidateReview(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            canonical_key=candidate["canonical_key"],
            candidate_name=candidate["name"],
            status=status,
            source_signal_ids=source_signal_ids,
            reviewed_by_user_id=reviewed_by_user_id,
        )
        session.add(review)
    else:
        review.candidate_name = candidate["name"]
        review.status = status
        review.source_signal_ids = source_signal_ids
        review.reviewed_by_user_id = reviewed_by_user_id
        review.reviewed_at = datetime.now(UTC)
        review.version += 1
    return review


def list_actor_candidates(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    include_dismissed: bool = False,
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(DossierSignal, Signal)
        .join(
            Signal,
            (Signal.id == DossierSignal.signal_id) & (Signal.tenant_id == DossierSignal.tenant_id),
        )
        .where(
            DossierSignal.tenant_id == tenant_id,
            DossierSignal.dossier_id == dossier_id,
            DossierSignal.status != "dismissed",
        )
        .order_by(Signal.published_at.desc().nullslast(), Signal.created_at.desc())
    ).all()
    candidates: dict[str, dict[str, Any]] = {}
    for link, signal in rows:
        source_entities = extract_signal_entities(
            signal.entities,
            raw_payload=signal.raw_payload,
            title=signal.title,
            summary=signal.summary,
        )
        for entity in source_entities:
            name = " ".join(str(entity.get("name") or entity.get("label") or "").strip().split())
            if len(name) < 2:
                continue
            canonical_key = actor_canonical_key(name)
            if not canonical_key:
                continue
            suggested_type = _suggested_type(entity.get("type"))
            candidate = candidates.setdefault(
                canonical_key,
                {
                    "id": str(_candidate_id(dossier_id, canonical_key)),
                    "canonical_key": canonical_key,
                    "name": name[:300],
                    "suggested_actor_type": suggested_type,
                    "suggested_labels": [],
                    "extraction_methods": [],
                    "sources": [],
                },
            )
            if candidate["suggested_actor_type"] == "other" and suggested_type != "other":
                candidate["suggested_actor_type"] = suggested_type
            candidate["suggested_labels"] = clean_labels(
                [
                    *candidate["suggested_labels"],
                    *clean_labels(entity.get("tags", [])),
                    *clean_labels(signal.categories),
                    *clean_labels(signal.tags),
                ]
            )
            method = str(entity.get("extraction_method") or "provider")
            if method not in candidate["extraction_methods"]:
                candidate["extraction_methods"].append(method)
            if len(candidate["sources"]) < 10:
                candidate["sources"].append(
                    {
                        "dossier_signal_id": str(link.id),
                        "signal_id": str(signal.id),
                        "title": signal.title,
                        "source_name": signal.source_name,
                        "source_url": signal.source_url,
                        "excerpt": signal.summary[:500],
                        "published_at": (
                            signal.published_at.isoformat() if signal.published_at else None
                        ),
                    }
                )

    if not candidates:
        return []
    keys = list(candidates)
    actor_rows = session.scalars(
        select(Actor).where(Actor.tenant_id == tenant_id, Actor.canonical_key.in_(keys))
    ).all()
    actors_by_key = {actor.canonical_key: actor for actor in actor_rows}
    review_rows = session.scalars(
        select(ActorCandidateReview).where(
            ActorCandidateReview.tenant_id == tenant_id,
            ActorCandidateReview.dossier_id == dossier_id,
            ActorCandidateReview.canonical_key.in_(keys),
        )
    ).all()
    reviews_by_key = {review.canonical_key: review for review in review_rows}
    linked_actor_ids = set(
        session.scalars(
            select(DossierActor.actor_id).where(
                DossierActor.tenant_id == tenant_id,
                DossierActor.dossier_id == dossier_id,
                DossierActor.actor_id.in_([actor.id for actor in actor_rows]),
            )
        ).all()
    )
    result: list[dict[str, Any]] = []
    for canonical_key, candidate in candidates.items():
        actor = actors_by_key.get(canonical_key)
        review = reviews_by_key.get(canonical_key)
        candidate["existing_actor_id"] = str(actor.id) if actor else None
        if actor and actor.id in linked_actor_ids:
            candidate["status"] = "linked"
        elif review and review.status == "dismissed":
            candidate["status"] = "dismissed"
        else:
            candidate["status"] = "existing" if actor else "candidate"
        candidate["source_count"] = len(candidate["sources"])
        if actor:
            metadata = actor.actor_metadata if isinstance(actor.actor_metadata, dict) else {}
            candidate["labels"] = clean_labels(metadata.get("tags", []))
        else:
            candidate["labels"] = []
        if candidate["status"] != "dismissed" or include_dismissed:
            result.append(candidate)
    return sorted(result, key=lambda item: (item["status"] == "linked", item["name"].casefold()))
