"""HTTP read model de Actividad del expediente (MEMSOL-04)."""

from __future__ import annotations

import uuid
from typing import Any

from apiflask import APIBlueprint, Schema
from apiflask.fields import Integer, String
from flask import Response
from flask_login import current_user
from marshmallow import validate

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.activity import build_dossier_activity
from opn_oracle.oracle.service import ResourceNotFound

bp = APIBlueprint(
    "dossier_activity",
    __name__,
    url_prefix="/api/v1",
    tag="Actividad del expediente",
)


class ActivityQuerySchema(Schema):
    kind = String(
        load_default=None,
        validate=validate.OneOf(
            ["watchlist", "signal_monitor", "procurement_watch", "background_job"]
        ),
        allow_none=True,
    )
    limit = Integer(load_default=100, validate=validate.Range(min=1, max=200))
    offset = Integer(load_default=0, validate=validate.Range(min=0))


def _problem(status: int, *, detail: str, code: str) -> Response:
    response, response_status, headers = problem_response(status, detail=detail, code=code)
    response.status_code = response_status
    response.headers.update(headers)
    return response


@bp.get("/dossiers/<uuid:dossier_id>/activity")
@require_permission("dossier.read")
@bp.input(ActivityQuerySchema, location="query")
@limiter.limit("60/minute")
def dossier_activity(
    query_data: dict[str, Any],
    dossier_id: uuid.UUID,
) -> dict[str, Any] | Response:
    """Read model agregado: intención, vigilancias, monitores, jobs."""
    try:
        return build_dossier_activity(
            db.session(),
            dossier_id,
            current_user.id,
            kind=query_data.get("kind"),
            limit=int(query_data.get("limit") or 100),
            offset=int(query_data.get("offset") or 0),
        )
    except ResourceNotFound:
        return _problem(404, detail="Expediente no encontrado.", code="not_found")
    except ValueError as error:
        return _problem(422, detail=str(error), code="validation_error")
