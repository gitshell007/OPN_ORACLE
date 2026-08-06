"""G-10 · ciclo de vida comercial de la oferta (separado del estado CRM).

La oportunidad conserva su estado CRM (identified/qualified/pursuing/…).
Este módulo persiste el seguimiento de la oferta presentada a licitación:
estado comercial, importe, baja, lotes, garantía provisional, fecha de mesa
y motivo de exclusión.

No inventa importes, fechas ni lotes desde el pliego: todo campo comercial es
entrada humana explícita (nullable hasta que el operador lo rellene).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from opn_oracle.extensions import Base
from opn_oracle.oracle.models import Opportunity, StrategicDossier, TenantDomainMixin
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.service import DomainValidationError, ResourceNotFound, VersionConflict
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

OFFER_LIFECYCLE_STATUSES = frozenset(
    {
        "preparando",
        "presentada",
        "en_evaluacion",
        "adjudicada",
        "perdida",
        "excluida",
    }
)

# Etiquetas UI (fuente de verdad backend; el FE puede espejar).
OFFER_LIFECYCLE_STATUS_LABELS: dict[str, str] = {
    "preparando": "Preparando",
    "presentada": "Presentada",
    "en_evaluacion": "En evaluación",
    "adjudicada": "Adjudicada",
    "perdida": "Perdida",
    "excluida": "Excluida",
}

# Transiciones libres entre estados comerciales (Excel-replacement): el operador
# puede corregir el estado sin FSM rígida. Validación de campos es la barrera.
DEFAULT_STATUS = "preparando"
MAX_LOTS = 40
MAX_LOT_LEN = 120
MAX_MOTIVO_LEN = 2000
MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.01")
MONEY_MAX = Decimal("999999999999.99")
PERCENT_MIN = Decimal("0")
PERCENT_MAX = Decimal("100")


class OfferLifecycleError(DomainValidationError):
    """Validación de ciclo de oferta con mapa de errores de campo."""

    def __init__(
        self,
        message: str,
        *,
        errors: Mapping[str, list[str]] | None = None,
        code: str = "offer_lifecycle_validation",
    ) -> None:
        super().__init__(message)
        self.errors = dict(errors or {"offer_lifecycle": [message]})
        self.code = code


class OpportunityOfferLifecycle(TenantDomainMixin, Base):
    """Seguimiento comercial de la oferta de una oportunidad (1:1 por opportunity)."""

    __tablename__ = "opportunity_offer_lifecycles"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_opportunity_offer_lifecycles_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "opportunity_id",
            name="uq_opportunity_offer_lifecycles_tenant_opportunity",
        ),
        ForeignKeyConstraint(
            ("dossier_id", "tenant_id"),
            ("strategic_dossiers.id", "strategic_dossiers.tenant_id"),
            ondelete="CASCADE",
            name="fk_ool_dossier_tenant",
        ),
        ForeignKeyConstraint(
            ("opportunity_id", "tenant_id"),
            ("opportunities.id", "opportunities.tenant_id"),
            ondelete="CASCADE",
            name="fk_ool_opportunity_tenant",
        ),
        ForeignKeyConstraint(
            ("tenant_id", "last_edited_by_user_id"),
            ("tenant_memberships.tenant_id", "tenant_memberships.user_id"),
            ondelete="RESTRICT",
            name="fk_ool_editor_membership",
        ),
        CheckConstraint("version >= 1", name="ool_version_positive"),
        CheckConstraint(
            "status IN ("
            "'preparando','presentada','en_evaluacion','adjudicada','perdida','excluida'"
            ")",
            name="ool_status",
        ),
        CheckConstraint(
            "importe_ofertado IS NULL OR importe_ofertado >= 0",
            name="ool_importe_non_negative",
        ),
        CheckConstraint(
            "baja_porcentaje IS NULL OR (baja_porcentaje >= 0 AND baja_porcentaje <= 100)",
            name="ool_baja_range",
        ),
        CheckConstraint(
            "garantia_provisional IS NULL OR garantia_provisional >= 0",
            name="ool_garantia_non_negative",
        ),
        CheckConstraint("jsonb_typeof(lotes) = 'array'", name="ool_lotes_array"),
        Index("ix_ool_tenant_dossier", "tenant_id", "dossier_id"),
        Index("ix_ool_tenant_opportunity", "tenant_id", "opportunity_id"),
    )

    dossier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=DEFAULT_STATUS)
    importe_ofertado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    baja_porcentaje: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    lotes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    garantia_provisional: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    fecha_mesa: Mapped[date | None] = mapped_column(Date, nullable=True)
    motivo_exclusion: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_edited_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


def utc_now() -> datetime:
    return datetime.now(UTC)


def make_etag(version: int) -> str:
    return f'W/"ool-v{int(version)}"'


def parse_expected_version(
    *, body_version: Any = None, if_match: str | None = None
) -> int | None:
    """Accept version from body or If-Match (W/\"ool-vN\" or raw integer)."""

    if body_version is not None and body_version != "":
        try:
            return int(body_version)
        except (TypeError, ValueError) as exc:
            raise OfferLifecycleError(
                "version debe ser un entero.",
                errors={"version": ["Debe ser un entero."]},
            ) from exc
    if if_match:
        raw = if_match.strip().removeprefix("W/").strip().strip('"')
        if raw.startswith("ool-v"):
            raw = raw.removeprefix("ool-v")
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise OfferLifecycleError(
                "If-Match no es una versión válida.",
                errors={"version": ["If-Match inválido."]},
            ) from exc
    return None


def _money(value: Any, *, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, TypeError, ValueError) as exc:
        raise OfferLifecycleError(
            f"{field} debe ser un importe válido.",
            errors={field: ["Debe ser un número decimal válido."]},
        ) from exc
    if not parsed.is_finite():
        raise OfferLifecycleError(
            f"{field} debe ser un importe finito.",
            errors={field: ["Debe ser un número finito."]},
        )
    if parsed < 0:
        raise OfferLifecycleError(
            f"{field} no puede ser negativo.",
            errors={field: ["No puede ser negativo."]},
        )
    if parsed > MONEY_MAX:
        raise OfferLifecycleError(
            f"{field} excede el máximo permitido.",
            errors={field: ["Excede el máximo permitido."]},
        )
    return parsed.quantize(MONEY_QUANTUM)


def _percent(value: Any, *, field: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, TypeError, ValueError) as exc:
        raise OfferLifecycleError(
            f"{field} debe ser un porcentaje válido.",
            errors={field: ["Debe ser un número decimal válido."]},
        ) from exc
    if not parsed.is_finite():
        raise OfferLifecycleError(
            f"{field} debe ser un porcentaje finito.",
            errors={field: ["Debe ser un número finito."]},
        )
    if parsed < PERCENT_MIN or parsed > PERCENT_MAX:
        raise OfferLifecycleError(
            f"{field} debe estar entre 0 y 100.",
            errors={field: ["Debe estar entre 0 y 100."]},
        )
    return parsed.quantize(PERCENT_QUANTUM)


def _date(value: Any, *, field: str) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        raise OfferLifecycleError(
            f"{field} debe ser una fecha ISO (YYYY-MM-DD).",
            errors={field: ["Formato de fecha inválido (YYYY-MM-DD)."]},
        ) from exc


def _lotes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # UI convenience: comma/newline separated.
        parts = [p.strip() for p in value.replace("\n", ",").split(",")]
        items = [p for p in parts if p]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = []
        for item in value:
            text = str(item or "").strip()
            if text:
                items.append(text)
    else:
        raise OfferLifecycleError(
            "lotes debe ser una lista de textos.",
            errors={"lotes": ["Debe ser una lista de textos."]},
        )
    if len(items) > MAX_LOTS:
        raise OfferLifecycleError(
            f"lotes admite como máximo {MAX_LOTS} entradas.",
            errors={"lotes": [f"Máximo {MAX_LOTS} lotes."]},
        )
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        short = item[:MAX_LOT_LEN]
        key = short.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(short)
    return cleaned


def _status(value: Any) -> str:
    status = str(value or "").strip()
    if status not in OFFER_LIFECYCLE_STATUSES:
        raise OfferLifecycleError(
            "Estado de oferta no válido.",
            errors={
                "status": [
                    "Debe ser uno de: "
                    + ", ".join(sorted(OFFER_LIFECYCLE_STATUSES))
                    + "."
                ]
            },
        )
    return status


def _motivo_for_status(status: str, value: Any) -> str | None:
    raw = None if value is None else str(value).strip()
    if status == "excluida":
        if not raw:
            raise OfferLifecycleError(
                "motivo_exclusion es obligatorio cuando el estado es excluida.",
                errors={"motivo_exclusion": ["Obligatorio en estado excluida."]},
            )
        return raw[:MAX_MOTIVO_LEN]
    # Fuera de excluida: se limpia (no se conserva residual).
    if raw:
        # Rechazo explícito si el caller envía motivo con otro estado.
        raise OfferLifecycleError(
            "motivo_exclusion solo aplica en estado excluida.",
            errors={"motivo_exclusion": ["Solo permitido en estado excluida."]},
        )
    return None


def _decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    quantized = value.quantize(MONEY_QUANTUM) if value == value.quantize(MONEY_QUANTUM) else value
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _percent_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    quantized = value.quantize(PERCENT_QUANTUM)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


CRM_STATUS_NOTE = (
    "El estado CRM de la oportunidad (identified/qualified/pursuing/…) "
    "es independiente de este ciclo de oferta."
)


def serialize_offer_lifecycle(row: OpportunityOfferLifecycle) -> dict[str, Any]:
    lotes = row.lotes if isinstance(row.lotes, list) else []
    lotes_out = [str(item) for item in lotes if str(item).strip()]
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "dossier_id": str(row.dossier_id),
        "opportunity_id": str(row.opportunity_id),
        "status": row.status,
        "status_label": OFFER_LIFECYCLE_STATUS_LABELS.get(row.status, row.status),
        "importe_ofertado": _decimal_str(
            Decimal(row.importe_ofertado) if row.importe_ofertado is not None else None
        ),
        "baja_porcentaje": _percent_str(
            Decimal(row.baja_porcentaje) if row.baja_porcentaje is not None else None
        ),
        "lotes": lotes_out,
        "garantia_provisional": _decimal_str(
            Decimal(row.garantia_provisional) if row.garantia_provisional is not None else None
        ),
        "fecha_mesa": row.fecha_mesa.isoformat() if row.fecha_mesa else None,
        "motivo_exclusion": row.motivo_exclusion if row.status == "excluida" else None,
        "version": int(row.version),
        "etag": make_etag(row.version),
        "last_edited_by_user_id": str(row.last_edited_by_user_id),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "materialized": True,
        # Explicit separation: CRM lives on Opportunity; never mirrored here.
        "crm_status_note": CRM_STATUS_NOTE,
    }


def virtual_offer_lifecycle(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
) -> dict[str, Any]:
    """Explicit non-persisted contract for UI defaults (GET never writes).

    Does not invent durable identifiers, editor or timestamps.
    Logical version 0 is the CAS token for the first write under opportunity.write.
    """

    return {
        "id": None,
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "opportunity_id": str(opportunity_id),
        "status": DEFAULT_STATUS,
        "status_label": OFFER_LIFECYCLE_STATUS_LABELS[DEFAULT_STATUS],
        "importe_ofertado": None,
        "baja_porcentaje": None,
        "lotes": [],
        "garantia_provisional": None,
        "fecha_mesa": None,
        "motivo_exclusion": None,
        "version": 0,
        "etag": make_etag(0),
        "last_edited_by_user_id": None,
        "created_at": None,
        "updated_at": None,
        "materialized": False,
        "crm_status_note": CRM_STATUS_NOTE,
    }


def _default_virtual_row(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
) -> Any:
    """In-memory row defaults used only to validate the first write payload."""

    from types import SimpleNamespace

    return SimpleNamespace(
        id=None,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
        status=DEFAULT_STATUS,
        importe_ofertado=None,
        baja_porcentaje=None,
        lotes=[],
        garantia_provisional=None,
        fecha_mesa=None,
        motivo_exclusion=None,
        version=0,
        last_edited_by_user_id=None,
    )


def _load_opportunity(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
) -> Opportunity:
    row = session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == tenant_id,
            Opportunity.dossier_id == dossier_id,
        )
    )
    if row is None:
        raise ResourceNotFound("Oportunidad no encontrada en este expediente.")
    return row


def _require_dossier(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    actor_id: uuid.UUID,
    write: bool,
) -> StrategicDossier:
    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(session, dossier, actor_id, write=write):
        raise ResourceNotFound("Expediente no encontrado.")
    return dossier


def load_offer_lifecycle(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    actor_id: uuid.UUID,
    write: bool = False,
) -> OpportunityOfferLifecycle | None:
    """Read-only load. Never INSERT/UPDATE/COMMIT or append audit.

    Returns None when the commercial tracking row does not exist yet. Callers that
    only hold opportunity.read can safely surface virtual defaults.
    """

    tenant_id = require_tenant_id()
    _require_dossier(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_id=actor_id,
        write=write,
    )
    _load_opportunity(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    return session.scalar(
        select(OpportunityOfferLifecycle).where(
            OpportunityOfferLifecycle.tenant_id == tenant_id,
            OpportunityOfferLifecycle.opportunity_id == opportunity_id,
        )
    )


def materialize_offer_lifecycle(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: Mapping[str, Any],
    actor_id: uuid.UUID,
    expected_version: int,
    partial: bool = True,
) -> OpportunityOfferLifecycle:
    """First write under opportunity.write with logical CAS version=0.

    Exactly one concurrent first writer succeeds; the other receives VersionConflict
    (mapped to HTTP 409) without 500/IntegrityError leak or double audit.
    """

    if int(expected_version) != 0:
        raise VersionConflict(
            "El seguimiento de oferta fue modificado por otro usuario."
        )

    tenant_id = require_tenant_id()
    dossier = _require_dossier(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_id=actor_id,
        write=True,
    )
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    opportunity = _load_opportunity(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    crm_status = opportunity.status

    existing = session.scalar(
        select(OpportunityOfferLifecycle).where(
            OpportunityOfferLifecycle.tenant_id == tenant_id,
            OpportunityOfferLifecycle.opportunity_id == opportunity_id,
        )
    )
    if existing is not None:
        raise VersionConflict(
            "El seguimiento de oferta fue modificado por otro usuario."
        )

    virtual = _default_virtual_row(
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        opportunity_id=opportunity_id,
    )
    fields = apply_offer_lifecycle_payload(virtual, payload, partial=partial)
    now = utc_now()
    row = OpportunityOfferLifecycle(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier.id,
        opportunity_id=opportunity_id,
        status=fields["status"],
        importe_ofertado=fields["importe_ofertado"],
        baja_porcentaje=fields["baja_porcentaje"],
        lotes=fields["lotes"],
        garantia_provisional=fields["garantia_provisional"],
        fecha_mesa=fields["fecha_mesa"],
        motivo_exclusion=fields["motivo_exclusion"],
        version=1,
        last_edited_by_user_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    append_audit_event(
        session,
        action="opportunity.offer_lifecycle.create",
        resource_type="opportunity_offer_lifecycle",
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
        metadata={
            "opportunity_id": str(opportunity_id),
            "status": row.status,
            "version": row.version,
            "crm_status_untouched": crm_status,
            "first_write": True,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # UNIQUE(tenant_id, opportunity_id) race: peer already materialised.
        raise VersionConflict(
            "El seguimiento de oferta fue modificado por otro usuario."
        ) from exc
    session.refresh(row)
    session.refresh(opportunity)
    if opportunity.status != crm_status:
        # Should be unreachable; defensive CRM isolation.
        raise DomainValidationError(
            "Invariante violada: el estado CRM de la oportunidad no debe cambiar "
            "al editar el ciclo de oferta."
        )
    return row


def apply_offer_lifecycle_payload(
    row: OpportunityOfferLifecycle,
    payload: Mapping[str, Any],
    *,
    partial: bool = True,
) -> dict[str, Any]:
    """Validate and return field updates without mutating the row.

    When ``partial`` is True, only keys present in payload are applied.
    When False (PUT-style), missing keys clear to null/default (except status).
    """

    errors: dict[str, list[str]] = {}

    def _get(key: str, default: Any = ...) -> Any:
        if key in payload:
            return payload[key]
        if partial:
            return default
        return None if default is ... else default

    status_raw = _get("status", row.status if partial else DEFAULT_STATUS)
    try:
        status = (
            row.status
            if status_raw is ...
            else _status(status_raw if status_raw is not None else DEFAULT_STATUS)
        )
    except OfferLifecycleError as exc:
        errors.update(exc.errors)
        status = row.status

    importe = row.importe_ofertado
    if "importe_ofertado" in payload or not partial:
        try:
            importe = _money(_get("importe_ofertado", None), field="importe_ofertado")
        except OfferLifecycleError as exc:
            errors.update(exc.errors)

    baja = row.baja_porcentaje
    if "baja_porcentaje" in payload or not partial:
        try:
            baja = _percent(_get("baja_porcentaje", None), field="baja_porcentaje")
        except OfferLifecycleError as exc:
            errors.update(exc.errors)

    lotes = list(row.lotes) if isinstance(row.lotes, list) else []
    if "lotes" in payload or not partial:
        try:
            lotes = _lotes(_get("lotes", []))
        except OfferLifecycleError as exc:
            errors.update(exc.errors)

    garantia = row.garantia_provisional
    if "garantia_provisional" in payload or not partial:
        try:
            garantia = _money(_get("garantia_provisional", None), field="garantia_provisional")
        except OfferLifecycleError as exc:
            errors.update(exc.errors)

    fecha = row.fecha_mesa
    if "fecha_mesa" in payload or not partial:
        try:
            fecha = _date(_get("fecha_mesa", None), field="fecha_mesa")
        except OfferLifecycleError as exc:
            errors.update(exc.errors)

    # motivo: if status becomes non-excluida, clear; if excluida, require.
    motivo_in_payload = "motivo_exclusion" in payload
    if status == "excluida":
        motivo_source = (
            payload.get("motivo_exclusion")
            if motivo_in_payload
            else (row.motivo_exclusion if partial else None)
        )
        try:
            motivo = _motivo_for_status(status, motivo_source)
        except OfferLifecycleError as exc:
            errors.update(exc.errors)
            motivo = None
    else:
        if motivo_in_payload and payload.get("motivo_exclusion") not in (None, ""):
            try:
                _motivo_for_status(status, payload.get("motivo_exclusion"))
            except OfferLifecycleError as exc:
                errors.update(exc.errors)
        motivo = None

    if errors:
        raise OfferLifecycleError(
            "Validación del ciclo de oferta fallida.",
            errors=errors,
        )

    return {
        "status": status,
        "importe_ofertado": importe,
        "baja_porcentaje": baja,
        "lotes": lotes,
        "garantia_provisional": garantia,
        "fecha_mesa": fecha,
        "motivo_exclusion": motivo,
    }


def cas_update_offer_lifecycle_sql(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    expected_version: int,
    fields: Mapping[str, Any],
    actor_id: uuid.UUID,
) -> int:
    """Optimistic CAS update; returns rows matched (0 = conflict)."""

    now = utc_now()
    stmt = (
        update(OpportunityOfferLifecycle)
        .where(
            OpportunityOfferLifecycle.tenant_id == tenant_id,
            OpportunityOfferLifecycle.opportunity_id == opportunity_id,
            OpportunityOfferLifecycle.version == int(expected_version),
        )
        .values(
            status=fields["status"],
            importe_ofertado=fields["importe_ofertado"],
            baja_porcentaje=fields["baja_porcentaje"],
            lotes=fields["lotes"],
            garantia_provisional=fields["garantia_provisional"],
            fecha_mesa=fields["fecha_mesa"],
            motivo_exclusion=fields["motivo_exclusion"],
            version=int(expected_version) + 1,
            last_edited_by_user_id=actor_id,
            updated_at=now,
        )
    )
    result = session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


def update_offer_lifecycle(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: Mapping[str, Any],
    actor_id: uuid.UUID,
    expected_version: int,
    partial: bool = True,
) -> OpportunityOfferLifecycle:
    """Apply validated patch with CAS; first write uses logical version=0.

    Never mutates Opportunity.status (CRM). Invalid/no-op requests must be rejected
    by the HTTP layer before calling this function so version/audit stay untouched.
    """

    tenant_id = require_tenant_id()
    dossier = _require_dossier(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        actor_id=actor_id,
        write=True,
    )
    if dossier.status == "archived":
        raise DomainValidationError("Un expediente archivado es de solo lectura.")
    opportunity = _load_opportunity(
        session,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    crm_status_before = opportunity.status

    row = session.scalar(
        select(OpportunityOfferLifecycle).where(
            OpportunityOfferLifecycle.tenant_id == tenant_id,
            OpportunityOfferLifecycle.opportunity_id == opportunity_id,
        )
    )
    if row is None:
        # First materialisation: only accepted with logical CAS version=0.
        return materialize_offer_lifecycle(
            session,
            dossier_id=dossier_id,
            opportunity_id=opportunity_id,
            payload=payload,
            actor_id=actor_id,
            expected_version=expected_version,
            partial=partial,
        )

    if int(expected_version) == 0:
        # Client still thinks row is virtual but a peer already materialised.
        raise VersionConflict("El seguimiento de oferta fue modificado por otro usuario.")

    if int(row.version) != int(expected_version):
        raise VersionConflict("El seguimiento de oferta fue modificado por otro usuario.")

    fields = apply_offer_lifecycle_payload(row, payload, partial=partial)
    matched = cas_update_offer_lifecycle_sql(
        session,
        tenant_id=tenant_id,
        opportunity_id=opportunity_id,
        expected_version=expected_version,
        fields=fields,
        actor_id=actor_id,
    )
    if matched != 1:
        session.rollback()
        raise VersionConflict("El seguimiento de oferta fue modificado por otro usuario.")

    # Prove CRM isolation in the same transaction.
    session.refresh(opportunity)
    if opportunity.status != crm_status_before:
        session.rollback()
        raise DomainValidationError(
            "Invariante violada: el estado CRM de la oportunidad no debe cambiar "
            "al editar el ciclo de oferta."
        )

    append_audit_event(
        session,
        action="opportunity.offer_lifecycle.update",
        resource_type="opportunity_offer_lifecycle",
        resource_id=row.id,
        dossier_id=dossier_id,
        result="success",
        metadata={
            "opportunity_id": str(opportunity_id),
            "status": fields["status"],
            "version": int(expected_version) + 1,
            "crm_status": crm_status_before,
            "crm_status_untouched": True,
        },
    )
    session.commit()
    saved = session.scalar(
        select(OpportunityOfferLifecycle).where(
            OpportunityOfferLifecycle.tenant_id == tenant_id,
            OpportunityOfferLifecycle.opportunity_id == opportunity_id,
        )
    )
    if saved is None:
        raise ResourceNotFound("Seguimiento de oferta no encontrado tras guardar.")
    return saved
