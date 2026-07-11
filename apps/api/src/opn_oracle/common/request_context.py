"""Safe request and correlation identifier handling."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from flask import Flask, Response, g, request

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def _safe_identifier(value: str | None) -> str:
    if value and SAFE_ID.fullmatch(value):
        return value
    return uuid.uuid4().hex


def get_request_id() -> str:
    return str(getattr(g, "request_id", "unknown"))


def get_correlation_id() -> str:
    return str(getattr(g, "correlation_id", get_request_id()))


def init_request_context(app: Flask) -> None:
    @app.before_request
    def set_request_context() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = _safe_identifier(request.headers.get("X-Request-ID"))
        g.correlation_id = _safe_identifier(request.headers.get("X-Correlation-ID") or g.request_id)

    @app.after_request
    def attach_context_headers(response: Response) -> Response:
        response.headers["X-Request-ID"] = get_request_id()
        response.headers["X-Correlation-ID"] = get_correlation_id()
        return response


def request_log_fields(response: Response) -> dict[str, Any]:
    started_at = getattr(g, "request_started_at", time.perf_counter())
    # Use the route template so invitation tokens and resource identifiers in
    # concrete URL segments never enter request logs.
    safe_path = request.url_rule.rule if request.url_rule is not None else "<unmatched>"
    return {
        "request_id": get_request_id(),
        "correlation_id": get_correlation_id(),
        "method": request.method,
        "path": safe_path,
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
    }
