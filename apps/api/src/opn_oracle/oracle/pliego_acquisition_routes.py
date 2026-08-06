"""HTTP API G-11 · estado honesto de pliego y subida manual de PCAP."""

from __future__ import annotations

import uuid
from typing import Any, BinaryIO, cast

from apiflask import APIBlueprint
from flask import g, request
from flask_login import current_user
from sqlalchemy import select

from opn_oracle.auth.permissions import require_permission
from opn_oracle.common.errors import problem_response
from opn_oracle.documents.routes import _serialize as serialize_document
from opn_oracle.extensions import db, limiter
from opn_oracle.oracle.models import StrategicDossier
from opn_oracle.oracle.pliego_acquisition import (
    PliegoAcquisitionError,
    resolve_dossier_pliego_acquisition,
    upload_manual_pcap,
)
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.tenants.context import require_tenant_id

bp = APIBlueprint(
    "pliego_acquisition",
    __name__,
    url_prefix="/api/v1",
    tag="Adquisición de pliego",
)


def _dossier_or_404(dossier_id: uuid.UUID, *, write: bool) -> StrategicDossier | None:
    tenant_id = require_tenant_id()
    row = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if row is None or not dossier_accessible(db.session(), row, current_user.id, write=write):
        return None
    return row


def _domain_error(error: PliegoAcquisitionError):
    status = 404 if error.code in {
        "not_found",
        "opportunity_not_found",
        "procurement_item_not_found",
    } else 422
    return problem_response(status, detail=str(error), code=error.code)


@bp.get("/dossiers/<uuid:dossier_id>/pliego-acquisition")
@require_permission("documents.read")
@limiter.limit("60/minute")
def get_pliego_acquisition(dossier_id: uuid.UUID) -> Any:
    """Estado durable/honesto de adquisición de pliego (G-11).

    Siempre ofrece CTA de subida manual; no confunde documents=[] con éxito.
    """
    if _dossier_or_404(dossier_id, write=False) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    opportunity_raw = (request.args.get("opportunity_id") or "").strip()
    opportunity_id: uuid.UUID | None = None
    if opportunity_raw:
        try:
            opportunity_id = uuid.UUID(opportunity_raw)
        except ValueError:
            return problem_response(
                422, detail="opportunity_id no es un UUID válido.", code="validation_error"
            )
    payload = resolve_dossier_pliego_acquisition(
        tenant_id=g.active_tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    return payload


@bp.post("/dossiers/<uuid:dossier_id>/pliego-pcap")
@require_permission("documents.manage")
@limiter.limit("20/minute")
def upload_pliego_pcap(dossier_id: uuid.UUID) -> Any:
    """Subida manual del PCAP: pipeline real de parsing/chunking/evidencia + auditoría."""
    if _dossier_or_404(dossier_id, write=True) is None:
        return problem_response(404, detail="Expediente no encontrado.", code="not_found")
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return problem_response(422, detail="Selecciona un archivo PCAP.", code="validation_error")

    def _opt_uuid(name: str) -> uuid.UUID | None:
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError as error:
            raise PliegoAcquisitionError(
                f"{name} no es un UUID válido.", code="validation_error"
            ) from error

    try:
        opportunity_id = _opt_uuid("opportunity_id")
        procurement_item_id = _opt_uuid("procurement_item_id")
        folder_id = (request.form.get("folder_id") or "").strip() or None
        classification = str(request.form.get("classification") or "internal")
        document, _version, job_id = upload_manual_pcap(
            tenant_id=g.active_tenant_id,
            dossier_id=dossier_id,
            uploader_id=current_user.id,
            filename=upload.filename,
            media_type=str(upload.mimetype or "application/octet-stream").lower(),
            source=cast(BinaryIO, upload.stream),
            classification=classification,
            opportunity_id=opportunity_id,
            procurement_item_id=procurement_item_id,
            folder_id=folder_id,
            process_inline=False,
        )
    except PliegoAcquisitionError as error:
        db.session.rollback()
        return _domain_error(error)
    except Exception:
        db.session.rollback()
        raise

    acquisition = resolve_dossier_pliego_acquisition(
        tenant_id=g.active_tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    return {
        "document": serialize_document(document),
        "job_id": job_id,
        "acquisition_status": "subido",
        "message": (
            "PCAP recibido. Oracle lo procesa en segundo plano "
            "(troceo, puntuación y esqueleto cuando el pipeline esté listo)."
        ),
        "pliego_acquisition": acquisition,
    }, 202
