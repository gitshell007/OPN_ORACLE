"""Human-triggered saved-search attachment for an accepted procurement plan."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from opn_oracle.oracle.procurement_search_preview import saved_search_payload
from opn_oracle.oracle.procurement_search_profiles import (
    ProcurementSearchProfile,
    ProcurementSearchProfileValidationError,
    ProcurementSearchProfileVersionConflict,
)
from opn_oracle.platform.audit import append_audit_event

SavedSearchCreator = Callable[..., dict[str, Any]]


def save_profile_watch(
    session: Session,
    profile: ProcurementSearchProfile,
    *,
    expected_version: int,
    name: str,
    create_search: SavedSearchCreator,
    request_id: str | None = None,
) -> tuple[ProcurementSearchProfile, dict[str, Any]]:
    """Create one active-only Signal search and attach its external identifier."""

    if profile.version != expected_version:
        raise ProcurementSearchProfileVersionConflict("El perfil cambió desde la última lectura.")
    if profile.tender_search_id:
        raise ProcurementSearchProfileVersionConflict("El perfil ya tiene una vigilancia guardada.")
    clean_name = " ".join(name.split())
    if not 2 <= len(clean_name) <= 120:
        raise ProcurementSearchProfileValidationError(
            "El nombre de la vigilancia debe tener entre 2 y 120 caracteres.",
            errors={"name": ["Debe contener entre 2 y 120 caracteres."]},
        )
    payload = saved_search_payload(name=clean_name, plan=profile.accepted_plan)
    created = create_search(payload=payload)
    external_id = created.get("id")
    if not isinstance(external_id, str) or not external_id.strip():
        raise ProcurementSearchProfileValidationError(
            "Signal no devolvió el identificador de la vigilancia creada.",
            errors={
                "saved_search": [
                    "Signal no devolvió el identificador de la vigilancia creada.",
                ]
            },
        )
    profile.tender_search_id = external_id.strip()[:120]
    append_audit_event(
        session,
        action="procurement.search_profile.watch_saved",
        resource_type="procurement_search_profile",
        resource_id=profile.id,
        result="success",
        request_id=request_id,
        metadata={
            "version": profile.version,
            "tender_search_id": profile.tender_search_id,
            "scope": "active",
        },
    )
    session.commit()
    return profile, created
