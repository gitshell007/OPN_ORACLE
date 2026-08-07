"""HTTP API G-10 · ciclo de vida comercial de la oferta (por oportunidad)."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Decimal as FieldDecimal
from apiflask.fields import Integer, List, String
from flask import g
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.offer_lifecycle import (
    OFFER_LIFECYCLE_STATUSES,
    OfferLifecycleError,
    load_offer_lifecycle,
    make_etag,
    parse_expected_version,
    serialize_offer_lifecycle,
    update_offer_lifecycle,
    virtual_offer_lifecycle,
)
from opn_oracle.oracle.service import DomainValidationError, ResourceNotFound, VersionConflict
from opn_oracle.tenants.context import require_tenant_id

bp = APIBlueprint(
    "opportunity_offer_lifecycle",
    __name__,
    url_prefix="/api/v1",
    tag="Ciclo de vida de la oferta",
)


class OfferLifecyclePatchSchema(Schema):
    version = Integer(load_default=None, allow_none=True)
    status = String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(sorted(OFFER_LIFECYCLE_STATUSES)),
    )
    importe_ofertado = FieldDecimal(as_string=True, load_default=None, allow_none=True, places=2)
    baja_porcentaje = FieldDecimal(as_string=True, load_default=None, allow_none=True, places=2)
    lotes = List(String(), load_default=None, allow_none=True)
    garantia_provisional = FieldDecimal(
        as_string=True, load_default=None, allow_none=True, places=2
    )
    fecha_mesa = String(load_default=None, allow_none=True)
    motivo_exclusion = String(load_default=None, allow_none=True)


def _domain_error(error: Exception) -> Any:
    if isinstance(error, OfferLifecycleError):
        body, status, headers = problem_response(
            422,
            detail=str(error),
            code=getattr(error, "code", "offer_lifecycle_validation"),
            errors=getattr(error, "errors", None),
        )
        return body, status, headers
    if isinstance(error, VersionConflict):
        return problem_response(409, detail=str(error), code="version_conflict")
    if isinstance(error, ResourceNotFound):
        return problem_response(404, detail=str(error), code="not_found")
    if isinstance(error, DomainValidationError):
        return problem_response(422, detail=str(error), code="domain_validation")
    return problem_response(400, detail=str(error), code="bad_request")


_EDITABLE_KEYS = frozenset(
    {
        "status",
        "importe_ofertado",
        "baja_porcentaje",
        "lotes",
        "garantia_provisional",
        "fecha_mesa",
        "motivo_exclusion",
    }
)
_ALLOWED_BODY_KEYS = _EDITABLE_KEYS | {"version"}


def _payload_from_request(raw_body: dict[str, Any]) -> dict[str, Any]:
    """Only commercial keys explicitly sent by the client (true partial PATCH)."""

    out: dict[str, Any] = {}
    for key in _EDITABLE_KEYS:
        if key in raw_body:
            out[key] = raw_body[key]
    return out


def _reject_unknown_or_empty_patch(raw_body: dict[str, Any]) -> Any:
    """Strict PATCH gate: unknown keys → 422; no commercial field → 422 no-op."""

    if "actor_id" in raw_body or "last_edited_by_user_id" in raw_body:
        return problem_response(
            422,
            detail="actor_id / last_edited_by_user_id no son aceptados del cliente.",
            code="actor_not_client_owned",
        )

    # Typos and other unknown keys (including actor spoofing already handled above).
    unknown = sorted(set(raw_body.keys()) - _ALLOWED_BODY_KEYS)
    if unknown:
        return problem_response(
            422,
            detail="Campos desconocidos en el seguimiento de oferta.",
            code="unknown_fields",
            errors={"unknown_fields": unknown},
        )

    commercial = [key for key in _EDITABLE_KEYS if key in raw_body]
    if not commercial:
        return problem_response(
            422,
            detail=(
                "El PATCH debe incluir al menos un campo comercial editable "
                "(status, importe_ofertado, baja_porcentaje, lotes, "
                "garantia_provisional, fecha_mesa o motivo_exclusion)."
            ),
            code="patch_no_commercial_fields",
            errors={
                "offer_lifecycle": [
                    "Se requiere al menos un campo comercial editable; "
                    "version sola no es suficiente."
                ]
            },
        )
    return None


@bp.get("/dossiers/<uuid:dossier_id>/opportunities/<uuid:opportunity_id>/offer-lifecycle")
@limiter.limit("120/minute")
@require_permission("opportunity.read")
def get_offer_lifecycle(dossier_id: uuid.UUID, opportunity_id: uuid.UUID) -> Any:
    """Consulta de solo lectura del seguimiento comercial de la oferta.

    Nunca INSERT/UPDATE/COMMIT ni crea auditoría. Si aún no hay fila, devuelve un
    contrato virtual (materialized=false, version=0, campos vacíos) útil para la UI.
    Independiente de artifacts IA, fit o verdict: basta con la oportunidad CRM.
    """

    try:
        row = load_offer_lifecycle(
            db.session(),
            dossier_id=dossier_id,
            opportunity_id=opportunity_id,
            actor_id=current_user.id,
            write=False,
        )
    except (ResourceNotFound, DomainValidationError, OfferLifecycleError) as error:
        return _domain_error(error)

    if row is None:
        tenant_id = require_tenant_id()
        life = virtual_offer_lifecycle(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            opportunity_id=opportunity_id,
        )
        body = {"lifecycle": life, "materialized": False}
        return body, 200, {"ETag": make_etag(0)}

    body = {
        "lifecycle": serialize_offer_lifecycle(row),
        "materialized": True,
    }
    return body, 200, {"ETag": make_etag(row.version)}


@bp.patch("/dossiers/<uuid:dossier_id>/opportunities/<uuid:opportunity_id>/offer-lifecycle")
@limiter.limit("60/minute")
@require_permission("opportunity.write")
def patch_offer_lifecycle(dossier_id: uuid.UUID, opportunity_id: uuid.UUID) -> Any:
    """Edita o materializa el seguimiento con CAS (version / If-Match).

    - version=0 (o If-Match ool-v0) materializa la primera fila de forma atómica.
    - Campos desconocidos / typos → 422; PATCH sin campo comercial → 422 (no-op).
    - Actor server-owned vía TenantContext + current_user.
    - No modifica Opportunity.status (CRM).
    """

    from flask import request

    raw_body = request.get_json(silent=True) or {}
    if not isinstance(raw_body, dict):
        return problem_response(
            422,
            detail="El cuerpo debe ser un objeto JSON.",
            code="validation_error",
        )

    rejected = _reject_unknown_or_empty_patch(raw_body)
    if rejected is not None:
        return rejected

    # Validate known fields via schema (OpenAPI contract); unknowns already rejected.
    try:
        json_data = OfferLifecyclePatchSchema().load(
            {k: v for k, v in raw_body.items() if k in OfferLifecyclePatchSchema().fields}
        )
    except Exception as error:  # marshmallow ValidationError
        detail = getattr(error, "messages", None) or str(error)
        return problem_response(
            422,
            detail="Datos no válidos en el seguimiento de oferta.",
            code="validation_error",
            errors=detail if isinstance(detail, dict) else None,
        )

    try:
        expected = parse_expected_version(
            body_version=raw_body.get("version") if "version" in raw_body else None,
            if_match=request.headers.get("If-Match"),
        )
        if expected is None:
            raise OfferLifecycleError(
                "Se requiere version o cabecera If-Match para guardar el seguimiento.",
                errors={"version": ["Obligatorio (body.version o If-Match)."]},
            )
        payload = _payload_from_request(raw_body)
        _ = json_data  # schema-validated; payload uses raw partial keys

        row = update_offer_lifecycle(
            db.session(),
            dossier_id=dossier_id,
            opportunity_id=opportunity_id,
            payload=payload,
            actor_id=current_user.id,
            expected_version=expected,
            partial=True,
        )
    except (
        ResourceNotFound,
        DomainValidationError,
        OfferLifecycleError,
        VersionConflict,
    ) as error:
        db.session.rollback()
        return _domain_error(error)

    body = {
        "lifecycle": serialize_offer_lifecycle(row),
        "materialized": True,
    }
    _ = g  # request-scoped tenant context established by auth middleware
    return body, 200, {"ETag": make_etag(row.version)}
