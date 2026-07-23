"""Tenant-scoped memory for explicitly accepted procurement search plans."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql.elements import ColumnElement

from opn_oracle.ai.models import AIArtifact
from opn_oracle.extensions import Base
from opn_oracle.oracle.models import TenantDomainMixin
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

PROCUREMENT_SEARCH_PROFILE_SCHEMA = "procurement-search-profile-v1"
TENDER_SEARCH_WIZARD_AGENT = "tender_search_wizard"


class ProcurementSearchProfile(TenantDomainMixin, Base):
    """The human-approved search intent; generated candidates never write this table."""

    __tablename__ = "procurement_search_profiles"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_procurement_search_profiles_id_tenant"),
        ForeignKeyConstraint(
            ("ai_artifact_id", "tenant_id"),
            ("ai_artifacts.id", "ai_artifacts.tenant_id"),
            name="fk_procurement_search_profiles_artifact_tenant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "accepted_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            name="fk_procurement_search_profiles_acceptor_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "char_length(original_description) BETWEEN 2 AND 5000",
            name="procurement_search_profile_description",
        ),
        CheckConstraint(
            "jsonb_typeof(comparables)='array'",
            name="procurement_search_profile_comparables",
        ),
        CheckConstraint(
            "jsonb_typeof(accepted_plan)='object'",
            name="procurement_search_profile_plan",
        ),
        CheckConstraint(
            "octet_length(accepted_plan_hash)=32",
            name="procurement_search_profile_hash",
        ),
        CheckConstraint("version >= 1", name="procurement_search_profile_version"),
        Index(
            "ix_procurement_search_profiles_tenant_accepted",
            "tenant_id",
            "last_accepted_at",
        ),
    )

    original_description: Mapped[str] = mapped_column(Text, nullable=False)
    comparables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    accepted_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    accepted_plan_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ai_artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tender_search_id: Mapped[str | None] = mapped_column(String(120))
    accepted_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    last_accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ProcurementSearchProfileValidationError(ValueError):
    """A profile payload error with stable field paths for API consumers."""

    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"profile": [message]})


class ProcurementSearchProfileNotFound(LookupError):
    pass


class ProcurementSearchProfileVersionConflict(RuntimeError):
    pass


def _bounded_description(value: Any) -> str:
    description = " ".join(str(value or "").strip().split())
    if not 2 <= len(description) <= 5000:
        raise ProcurementSearchProfileValidationError(
            "original_description debe contener entre 2 y 5000 caracteres.",
            errors={
                "original_description": [
                    "Debe contener entre 2 y 5000 caracteres.",
                ]
            },
        )
    return description


def _comparables(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ProcurementSearchProfileValidationError(
            "comparables debe ser una lista.",
            errors={"comparables": ["Debe ser una lista."]},
        )
    cleaned: list[str] = []
    for item in value:
        name = " ".join(str(item).strip().split())
        if not name:
            continue
        if len(name) > 250:
            raise ProcurementSearchProfileValidationError(
                "Cada comparable admite como máximo 250 caracteres.",
                errors={
                    f"comparables.{len(cleaned)}": [
                        "Admite como máximo 250 caracteres.",
                    ]
                },
            )
        if name.casefold() not in {existing.casefold() for existing in cleaned}:
            cleaned.append(name)
    if len(cleaned) > 10:
        raise ProcurementSearchProfileValidationError(
            "comparables admite como máximo 10 empresas.",
            errors={"comparables": ["Admite como máximo 10 empresas."]},
        )
    return cleaned


def _plan_errors(error: Exception) -> dict[str, list[str]]:
    """Preserve Pydantic locations and classify deterministic semantic failures."""

    details = getattr(error, "errors", None)
    if callable(details):
        structured: dict[str, list[str]] = {}
        for item in details():
            raw_location = item.get("loc", ())
            location = ".".join(str(part) for part in raw_location)
            path = f"accepted_plan.{location}" if location else "accepted_plan"
            structured.setdefault(path, []).append(str(item.get("msg") or error))
        if structured:
            return structured

    message = str(error)
    lowered = message.casefold()
    if "cpv" in lowered:
        path = "accepted_plan.candidate_cpv"
    elif "importe mínimo" in lowered or "importe max" in lowered:
        path = "accepted_plan.min_amount"
    elif "término" in lowered or "term_" in lowered:
        path = "accepted_plan.include_terms"
    else:
        path = "accepted_plan"
    return {path: [message]}


def _canonical_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Use the wizard's deterministic post-validation as the only plan contract."""

    from opn_oracle.ai.tender_search_wizard import postvalidate_tender_search_plan

    try:
        validated = postvalidate_tender_search_plan(dict(plan), reject_discards=True)
    except (TypeError, ValueError) as error:
        raise ProcurementSearchProfileValidationError(
            str(error),
            errors=_plan_errors(error),
        ) from error
    if not isinstance(validated, dict):
        raise ProcurementSearchProfileValidationError(
            "El plan aceptado no cumple el contrato del wizard.",
            errors={"accepted_plan": ["No cumple el contrato del wizard."]},
        )
    return validated


def accepted_plan_digest(plan: Mapping[str, Any]) -> bytes:
    payload = json.dumps(
        plan,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _artifact_id(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    value: Any,
    profile_id: uuid.UUID | None = None,
) -> uuid.UUID:
    if value in (None, ""):
        raise ProcurementSearchProfileValidationError(
            "ai_artifact_id es obligatorio para aceptar un plan.",
            errors={"ai_artifact_id": ["Es obligatorio para aceptar un plan."]},
        )
    try:
        artifact_id = uuid.UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ProcurementSearchProfileValidationError(
            "ai_artifact_id debe ser UUID.",
            errors={"ai_artifact_id": ["Debe ser un UUID."]},
        ) from error
    allowed_target: ColumnElement[bool] = (AIArtifact.target_type == "tenant_search_profile") & (
        AIArtifact.target_id == tenant_id
    )
    if profile_id is not None:
        allowed_target = or_(
            allowed_target,
            (AIArtifact.target_type == "procurement_search_profile")
            & (AIArtifact.target_id == profile_id),
        )
    artifact = session.scalar(
        select(AIArtifact).where(
            AIArtifact.id == artifact_id,
            AIArtifact.tenant_id == tenant_id,
            AIArtifact.agent == TENDER_SEARCH_WIZARD_AGENT,
            AIArtifact.dossier_id.is_(None),
            allowed_target,
        )
    )
    if artifact is None:
        raise ProcurementSearchProfileValidationError(
            "El artefacto del wizard no existe en este tenant.",
            errors={
                "ai_artifact_id": [
                    "No identifica un artefacto enlazable del wizard en este tenant.",
                ]
            },
        )
    return artifact_id


def create_procurement_search_profile(
    session: Session,
    payload: Mapping[str, Any],
    *,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> ProcurementSearchProfile:
    tenant_id = require_tenant_id()
    raw_plan = payload.get("accepted_plan")
    if not isinstance(raw_plan, Mapping):
        raise ProcurementSearchProfileValidationError(
            "accepted_plan debe ser un objeto.",
            errors={"accepted_plan": ["Debe ser un objeto."]},
        )
    plan = _canonical_plan(raw_plan)
    profile = ProcurementSearchProfile(
        tenant_id=tenant_id,
        original_description=_bounded_description(payload.get("original_description")),
        comparables=_comparables(payload.get("comparables")),
        accepted_plan=plan,
        accepted_plan_hash=accepted_plan_digest(plan),
        version=1,
        ai_artifact_id=_artifact_id(
            session,
            tenant_id=tenant_id,
            value=payload.get("ai_artifact_id"),
        ),
        tender_search_id=None,
        accepted_by_user_id=actor_id,
        last_accepted_at=datetime.now(UTC),
    )
    session.add(profile)
    session.flush()
    append_audit_event(
        session,
        action="procurement.search_profile.accept",
        resource_type="procurement_search_profile",
        resource_id=profile.id,
        result="success",
        request_id=request_id,
        metadata={"version": 1, "schema": PROCUREMENT_SEARCH_PROFILE_SCHEMA},
    )
    session.commit()
    return profile


def get_procurement_search_profile(
    session: Session,
    profile_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> ProcurementSearchProfile:
    tenant_id = require_tenant_id()
    statement = select(ProcurementSearchProfile).where(
        ProcurementSearchProfile.id == profile_id,
        ProcurementSearchProfile.tenant_id == tenant_id,
    )
    if for_update:
        statement = statement.with_for_update()
    profile = session.scalar(statement)
    if profile is None:
        raise ProcurementSearchProfileNotFound("Perfil de búsqueda no encontrado.")
    return profile


def list_procurement_search_profiles(session: Session) -> list[ProcurementSearchProfile]:
    tenant_id = require_tenant_id()
    return list(
        session.scalars(
            select(ProcurementSearchProfile)
            .where(ProcurementSearchProfile.tenant_id == tenant_id)
            .order_by(
                ProcurementSearchProfile.last_accepted_at.desc(),
                ProcurementSearchProfile.id.desc(),
            )
        )
    )


def get_artifact_acceptance(
    session: Session,
    artifact_id: uuid.UUID,
) -> ProcurementSearchProfile | None:
    """Return the latest acceptance of an artifact within the active tenant."""

    tenant_id = require_tenant_id()
    return session.scalar(
        select(ProcurementSearchProfile)
        .where(
            ProcurementSearchProfile.tenant_id == tenant_id,
            ProcurementSearchProfile.ai_artifact_id == artifact_id,
        )
        .order_by(
            ProcurementSearchProfile.last_accepted_at.desc(),
            ProcurementSearchProfile.id.desc(),
        )
        .limit(1)
    )


def accept_procurement_search_profile(
    session: Session,
    profile_id: uuid.UUID,
    payload: Mapping[str, Any],
    *,
    actor_id: uuid.UUID,
    request_id: str | None = None,
) -> ProcurementSearchProfile:
    profile = get_procurement_search_profile(session, profile_id, for_update=True)
    raw_expected_version = payload.get("expected_version")
    if not isinstance(raw_expected_version, int) or isinstance(raw_expected_version, bool):
        raise ProcurementSearchProfileValidationError(
            "expected_version es obligatorio y debe ser entero.",
            errors={"expected_version": ["Es obligatorio y debe ser entero."]},
        )
    expected_version = raw_expected_version
    if expected_version != profile.version:
        raise ProcurementSearchProfileVersionConflict("El perfil cambió desde la última lectura.")
    raw_plan = payload.get("accepted_plan")
    if not isinstance(raw_plan, Mapping):
        raise ProcurementSearchProfileValidationError(
            "accepted_plan debe ser un objeto.",
            errors={"accepted_plan": ["Debe ser un objeto."]},
        )
    plan = _canonical_plan(raw_plan)
    tenant_id = require_tenant_id()
    profile.accepted_plan = plan
    profile.accepted_plan_hash = accepted_plan_digest(plan)
    profile.ai_artifact_id = _artifact_id(
        session,
        tenant_id=tenant_id,
        value=payload.get("ai_artifact_id"),
        profile_id=profile.id,
    )
    profile.accepted_by_user_id = actor_id
    profile.version += 1
    profile.last_accepted_at = datetime.now(UTC)
    append_audit_event(
        session,
        action="procurement.search_profile.accept",
        resource_type="procurement_search_profile",
        resource_id=profile.id,
        result="success",
        request_id=request_id,
        metadata={"version": profile.version, "schema": PROCUREMENT_SEARCH_PROFILE_SCHEMA},
    )
    session.commit()
    return profile


def serialize_procurement_search_profile(
    profile: ProcurementSearchProfile,
) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "schema": PROCUREMENT_SEARCH_PROFILE_SCHEMA,
        "original_description": profile.original_description,
        "comparables": list(profile.comparables),
        "accepted_plan": dict(profile.accepted_plan),
        "accepted_plan_hash": profile.accepted_plan_hash.hex(),
        "version": profile.version,
        "ai_artifact_id": (
            str(profile.ai_artifact_id) if profile.ai_artifact_id is not None else None
        ),
        "tender_search_id": profile.tender_search_id,
        "accepted_by_user_id": str(profile.accepted_by_user_id),
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
        "last_accepted_at": profile.last_accepted_at.isoformat(),
    }


PROCUREMENT_SEARCH_PROFILE_MODELS = (ProcurementSearchProfile,)
