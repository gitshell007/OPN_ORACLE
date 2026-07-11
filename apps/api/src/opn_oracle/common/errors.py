"""RFC 9457-compatible API errors."""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from apiflask import HTTPError
from flask import Flask, Response, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from opn_oracle.common.request_context import get_request_id
from opn_oracle.extensions import db

PROBLEM_BASE = "https://oracle.opnconsultoria.com/problems"


def problem_response(
    status: int,
    *,
    title: str | None = None,
    detail: str | None = None,
    code: str | None = None,
    errors: Any = None,
) -> tuple[Response, int, Mapping[str, str]]:
    phrase = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Error"
    stable_code = code or phrase.lower().replace(" ", "_")
    payload: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}/{stable_code.replace('_', '-')}",
        "title": title or phrase,
        "status": status,
        "detail": detail or phrase,
        "instance": request.path,
        "code": stable_code,
        "request_id": get_request_id(),
    }
    if errors:
        payload["errors"] = errors
    return jsonify(payload), status, {"Content-Type": "application/problem+json"}


def _validation_errors(detail: Any, extra_data: Mapping[str, Any] | None) -> Any:
    if isinstance(detail, Mapping) and detail:
        return detail
    if not extra_data:
        return None
    return extra_data.get("messages") or extra_data.get("errors")


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPError)
    def handle_api_error(error: HTTPError) -> tuple[Response, int, Mapping[str, str]]:
        status = error.status_code
        is_validation = status == 422
        return problem_response(
            status,
            title="Datos no válidos" if is_validation else error.message,
            detail=(
                "Revisa los campos indicados."
                if is_validation
                else str(error.detail or error.message)
            ),
            code="validation_error" if is_validation else None,
            errors=_validation_errors(error.detail, error.extra_data),
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException) -> tuple[Response, int, Mapping[str, str]]:
        return problem_response(
            error.code or 500,
            title=error.name,
            detail=str(error.description),
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> tuple[Response, int, Mapping[str, str]]:
        db.session.rollback()
        current_app.logger.exception(
            "unhandled_exception", extra={"event_fields": {"request_id": get_request_id()}}
        )
        return problem_response(
            500,
            title="Error interno",
            detail="No se pudo completar la solicitud.",
            code="internal_error",
        )
