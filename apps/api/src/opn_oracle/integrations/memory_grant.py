"""ORA-AUTOGRANT · Signal memory dossier scope ensure (consumer grants).

Why this hook point
-------------------
Authorization is requested when a dossier memory profile is saved into an
operational mode (shadow|augment) — i.e. when the product «connects» that
dossier to Signal memory. That is a deliberate user action, not every
retrieve/ingest/UI refresh.

Fail-closed and cheap:
- no active Signal connection → do nothing (normal for tenants without
  integration; not an error banner)
- stable terminal Signal outcomes (authorized / manual_required / rejected)
  are stored and not re-POSTed until the connection changes or force=True
- unknown / transport failures store status=unknown without inventing
  authorized=true
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flask import current_app, g
from sqlalchemy.orm import Session

from opn_oracle.integrations.memory_http_client import (
    HttpxTransport,
    MemoryHttpError,
    MockTransport,
    Transport,
)
from opn_oracle.integrations.memory_profile import (
    OPERATIONAL_MODES,
    build_client_for_connection,
    normalize_operational_mode,
    resolve_signal_memory_connection,
)

logger = logging.getLogger(__name__)

# Durable profile statuses (DB check constraint + public DTO).
GRANT_AUTHORIZED = "authorized"
GRANT_MANUAL_REQUIRED = "manual_required"
GRANT_REJECTED = "rejected"
GRANT_UNKNOWN = "unknown"
GRANT_NO_CONNECTION = "no_connection"

# Machine-stable codes (job UI contract; never show raw to end users).
CODE_MANUAL_REQUIRED = "memory_grant_manual_required"
CODE_REJECTED = "memory_grant_rejected"
CODE_NOT_AUTHORIZED = "memory_dossier_not_authorized"
CODE_UNKNOWN = "memory_grant_unknown"

# Terminal outcomes: do not re-call Signal for the same connection.
_STABLE_STATUSES = frozenset({GRANT_AUTHORIZED, GRANT_MANUAL_REQUIRED, GRANT_REJECTED})

# Signal live error_code from POST /dossiers/{id}/authorize when autogrant is off.
SIGNAL_MANUAL_REQUIRED = "dossier_authorization_manual_required"
SIGNAL_TENANT_NOT_ALLOWED = "tenant_not_allowed"

_MANUAL_SIGNAL_CODES = frozenset(
    {
        CODE_MANUAL_REQUIRED,
        SIGNAL_MANUAL_REQUIRED,
        "grant_manual_required",
        "manual_authorization_required",
        "consumer_grant_manual_required",
        "authorization_manual_required",
    }
)

GRANT_STATUS_LABELS_ES = {
    GRANT_AUTHORIZED: "Autorizada en Signal",
    GRANT_MANUAL_REQUIRED: "Pendiente de autorización en Signal",
    GRANT_REJECTED: "Autorización rechazada por Signal",
    GRANT_UNKNOWN: "Estado de autorización desconocido",
    GRANT_NO_CONNECTION: "Sin conexión Signal activa",
}


@dataclass(frozen=True)
class GrantEnsureResult:
    status: str
    code: str | None
    detail: str | None
    attempted: bool
    cached: bool
    connection_id: uuid.UUID | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "status_label_es": GRANT_STATUS_LABELS_ES.get(self.status, self.status),
            "code": self.code,
            "detail": self.detail,
            "attempted": self.attempted,
            "cached": self.cached,
            "connection_id": str(self.connection_id) if self.connection_id else None,
            # Fail-closed: only explicit authorized is usable.
            "usable": self.status == GRANT_AUTHORIZED,
            "pending_manual": self.status == GRANT_MANUAL_REQUIRED,
        }


def grant_public_from_row(row: Any) -> dict[str, Any] | None:
    """Project stored grant fields for API/UI. None when never evaluated."""
    status = getattr(row, "signal_grant_status", None)
    if not status:
        return None
    code = getattr(row, "signal_grant_code", None)
    detail = getattr(row, "signal_grant_detail", None)
    at = getattr(row, "signal_grant_at", None)
    conn_id = getattr(row, "signal_grant_connection_id", None)
    return {
        "status": status,
        "status_label_es": GRANT_STATUS_LABELS_ES.get(str(status), str(status)),
        "code": code,
        "detail": detail,
        "checked_at": at.isoformat() if at is not None else None,
        "connection_id": str(conn_id) if conn_id else None,
        "usable": status == GRANT_AUTHORIZED,
        "pending_manual": status == GRANT_MANUAL_REQUIRED,
        "message_es": _message_es(str(status), detail),
    }


def _message_es(status: str, detail: str | None) -> str:
    if status == GRANT_MANUAL_REQUIRED:
        return (
            "Este expediente está pendiente de autorización en Signal. "
            "La memoria no se usará hasta que un administrador de Signal "
            "autorice el expediente o active la autorización automática."
        )
    if status == GRANT_REJECTED:
        return (
            "Signal rechazó la autorización de este expediente para Oracle. "
            "Revise la lista de clientes autorizados en Signal."
        )
    if status == GRANT_AUTHORIZED:
        return "Signal ha autorizado la memoria de este expediente."
    if status == GRANT_UNKNOWN:
        return (
            "No se pudo confirmar la autorización en Signal. "
            "No se asume que esté autorizada." + (f" Detalle: {detail}" if detail else "")
        )
    if status == GRANT_NO_CONNECTION:
        return "No hay conexión Signal activa; no se ha solicitado autorización."
    return detail or GRANT_STATUS_LABELS_ES.get(status, status)


def _stamp_row(
    row: Any,
    *,
    status: str,
    code: str | None,
    detail: str | None,
    connection_id: uuid.UUID | None,
) -> None:
    row.signal_grant_status = status
    row.signal_grant_code = code[:80] if code else None
    row.signal_grant_detail = detail[:500] if detail else None
    row.signal_grant_at = datetime.now(UTC)
    row.signal_grant_connection_id = connection_id


def _resolve_transport() -> tuple[Transport, bool]:
    """Return (transport, synthetic). Prefer test injection; never invent HTTP."""
    test_transport = current_app.config.get("MEMORY_CONTEXT_TEST_TRANSPORT")
    host_mode = str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled")
    if test_transport is not None:
        return test_transport, True
    if host_mode == "mock":
        return MockTransport(), True
    if host_mode == "disabled":
        raise MemoryHttpError("host_disabled", "MEMORY_CONTEXT_MODE=disabled", retryable=False)
    return HttpxTransport(), False


def _interpret_authorize_success(data: dict[str, Any]) -> GrantEnsureResult:
    """Map live authorize 200 body → durable grant status.

    Real Signal success body (not ScopeStatus): authorized + reason + granted_by.
    """
    if data.get("authorized") is True:
        reason = str(data.get("reason") or "granted")
        detail = f"Signal autorizó el expediente ({reason})."
        return GrantEnsureResult(
            status=GRANT_AUTHORIZED,
            code=None,
            detail=detail,
            attempted=True,
            cached=False,
        )
    # Fail-closed: a 200 without authorized:true is not usable.
    return GrantEnsureResult(
        status=GRANT_UNKNOWN,
        code=CODE_UNKNOWN,
        detail="Respuesta de autorización sin authorized=true.",
        attempted=True,
        cached=False,
    )


def _interpret_authorize_error(exc: MemoryHttpError) -> GrantEnsureResult:
    """Map live authorize 4xx envelope.error_code → durable codes."""
    code = str(exc.code or "")
    # Primary: Signal's machine code when autogrant flag is off.
    if code in _MANUAL_SIGNAL_CODES or code == SIGNAL_MANUAL_REQUIRED:
        return GrantEnsureResult(
            status=GRANT_MANUAL_REQUIRED,
            code=CODE_MANUAL_REQUIRED,
            detail=exc.message or "La autorización de expedientes es manual para este consumidor.",
            attempted=True,
            cached=False,
        )
    if code in {
        SIGNAL_TENANT_NOT_ALLOWED,
        "auth_or_scope",
        "insufficient_scope",
        "credential_tenant_mismatch",
    }:
        return GrantEnsureResult(
            status=GRANT_REJECTED,
            code=CODE_REJECTED,
            detail=exc.message or "Signal rechazó la autorización (cliente no permitido).",
            attempted=True,
            cached=False,
        )
    if code == "dossier_not_authorized":
        # Generic runtime denial — not the same as manual-required.
        return GrantEnsureResult(
            status=GRANT_REJECTED,
            code=CODE_NOT_AUTHORIZED,
            detail=exc.message or "Expediente no autorizado en Signal.",
            attempted=True,
            cached=False,
        )
    return GrantEnsureResult(
        status=GRANT_UNKNOWN,
        code=CODE_UNKNOWN,
        detail=f"{code}:{exc.message}"[:500],
        attempted=True,
        cached=False,
    )


def ensure_dossier_memory_grant(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    row: Any,
    force: bool = False,
    transport: Transport | None = None,
) -> GrantEnsureResult:
    """Ensure Signal scope grant for a dossier memory profile (idempotent).

    Caller owns the transaction commit. Only runs for operational modes.
    """
    mode = normalize_operational_mode(getattr(row, "mode", None))
    if mode not in OPERATIONAL_MODES or mode == "disabled":
        return GrantEnsureResult(
            status="not_applicable",
            code=None,
            detail=None,
            attempted=False,
            cached=True,
        )

    try:
        connection = resolve_signal_memory_connection(session, tenant_id=tenant_id)
    except MemoryHttpError as exc:
        if exc.code in {"connection_missing", "connection_conflict"}:
            # Normal for tenants without Signal: not an error to surface as failure.
            _stamp_row(
                row,
                status=GRANT_NO_CONNECTION,
                code=None,
                detail=exc.message,
                connection_id=None,
            )
            return GrantEnsureResult(
                status=GRANT_NO_CONNECTION,
                code=None,
                detail=exc.message,
                attempted=False,
                cached=False,
            )
        _stamp_row(
            row,
            status=GRANT_UNKNOWN,
            code=CODE_UNKNOWN,
            detail=exc.message,
            connection_id=None,
        )
        return GrantEnsureResult(
            status=GRANT_UNKNOWN,
            code=CODE_UNKNOWN,
            detail=exc.message,
            attempted=False,
            cached=False,
        )

    prev_status = getattr(row, "signal_grant_status", None)
    prev_conn = getattr(row, "signal_grant_connection_id", None)
    if (
        not force
        and prev_status in _STABLE_STATUSES
        and prev_conn is not None
        and prev_conn == connection.id
    ):
        return GrantEnsureResult(
            status=str(prev_status),
            code=getattr(row, "signal_grant_code", None),
            detail=getattr(row, "signal_grant_detail", None),
            attempted=False,
            cached=True,
            connection_id=connection.id,
        )

    try:
        if transport is None:
            transport, synthetic = _resolve_transport()
        else:
            synthetic = isinstance(transport, MockTransport)
        client = build_client_for_connection(
            connection,
            transport=transport,
            require_https=not synthetic,
        )
        external = str(getattr(g, "external_tenant_id", None) or tenant_id)
        # Real path: POST /memory/v1/dossiers/{id}/authorize (not scopes/ensure stub).
        status, data = client.authorize_dossier(
            external_tenant_id=external,
            dossier_id=str(dossier_id),
        )
        del status  # interpretation uses body
        result = _interpret_authorize_success(data if isinstance(data, dict) else {})
    except MemoryHttpError as exc:
        result = _interpret_authorize_error(exc)
    except Exception as exc:
        logger.warning(
            "memory_grant_ensure_failed tenant_id=%s dossier_id=%s err_type=%s",
            tenant_id,
            dossier_id,
            type(exc).__name__,
        )
        result = GrantEnsureResult(
            status=GRANT_UNKNOWN,
            code=CODE_UNKNOWN,
            detail=type(exc).__name__,
            attempted=True,
            cached=False,
        )

    _stamp_row(
        row,
        status=result.status,
        code=result.code,
        detail=result.detail,
        connection_id=connection.id,
    )
    return GrantEnsureResult(
        status=result.status,
        code=result.code,
        detail=result.detail,
        attempted=result.attempted,
        cached=False,
        connection_id=connection.id,
    )


def require_usable_memory_grant(row: Any | None) -> None:
    """Raise MemoryHttpError if operational profile is not granted (fail-closed)."""
    if row is None:
        raise MemoryHttpError(
            CODE_NOT_AUTHORIZED,
            "Sin perfil de memoria; no se asume autorización.",
            retryable=False,
        )
    mode = normalize_operational_mode(getattr(row, "mode", None))
    if mode == "disabled":
        return
    status = getattr(row, "signal_grant_status", None)
    if status == GRANT_AUTHORIZED:
        return
    if status == GRANT_MANUAL_REQUIRED:
        raise MemoryHttpError(
            CODE_MANUAL_REQUIRED,
            "Expediente pendiente de autorización manual en Signal.",
            retryable=False,
        )
    if status == GRANT_REJECTED:
        raise MemoryHttpError(
            CODE_REJECTED,
            "Signal rechazó la autorización del expediente.",
            retryable=False,
        )
    # unknown / no_connection / never checked → fail-closed
    raise MemoryHttpError(
        CODE_NOT_AUTHORIZED if status != GRANT_NO_CONNECTION else CODE_UNKNOWN,
        "No hay autorización confirmada de memoria en Signal.",
        retryable=False,
    )
