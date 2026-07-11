"""Structured logging with recursive, central secret redaction."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from flask import Flask

from opn_oracle.common.request_context import request_log_fields

SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|password|passwd|token|secret|api[_-]?key|credential|csrf|session)"
)
KEY_VALUE_SECRET = re.compile(
    r"(?i)(authorization|cookie|set-cookie|password|passwd|token|secret|api[_-]?key|"
    r"credential|csrf|session)(\s*[:=]\s*)([^\s,;&]+)"
)
URL_CREDENTIALS = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)([^@/\s]+)(@)")
SENSITIVE_QUERY = re.compile(
    r"(?i)([?&](?:access_token|refresh_token|token|password|secret|api[_-]?key|"
    r"credential|csrf|session)=)([^&#\s]+)"
)


def redact(value: str) -> str:
    """Redact secrets embedded in prose, DSNs and URL query strings."""

    value = URL_CREDENTIALS.sub(r"\1[REDACTED]\3", value)
    value = SENSITIVE_QUERY.sub(r"\1[REDACTED]", value)
    return KEY_VALUE_SECRET.sub(r"\1\2[REDACTED]", value)


def sanitize(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize values before they enter any formatter."""

    if key is not None and SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize(item, key=str(item_key)) for item_key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(sanitize(item) for item in value)
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, set):
        return sorted((sanitize(item) for item in value), key=str)
    if isinstance(value, str):
        return redact(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = sanitize(record.args)
        if hasattr(record, "event_fields"):
            record.event_fields = sanitize(record.event_fields)
        return True


class SafeFormatter(logging.Formatter):
    def formatException(self, exc_info: Any) -> str:
        return redact(super().formatException(exc_info))


class JsonFormatter(SafeFormatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        fields = sanitize(getattr(record, "event_fields", None))
        if isinstance(fields, Mapping):
            payload.update(fields)
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(sanitize(payload), ensure_ascii=False, default=str)


def configure_logging(app: Flask) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    if app.config["LOG_FORMAT"] == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(app.config["LOG_LEVEL"])
    app.logger.handlers.clear()
    app.logger.propagate = True

    @app.after_request
    def log_response(response: Any) -> Any:
        app.logger.info("request_completed", extra={"event_fields": request_log_fields(response)})
        return response
