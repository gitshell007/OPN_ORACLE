"""Runtime JSON contract validation shared by auth and administration routes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import Flask, request
from flask.typing import ResponseReturnValue

from opn_oracle.common.errors import problem_response

RULES: dict[tuple[str, str], tuple[dict[str, str], frozenset[str]]] = {
    ("/api/v1/auth/login", "POST"): (
        {"email": "email", "password": "password", "tenant_id": "uuid"},
        frozenset({"email", "password"}),
    ),
    ("/api/v1/auth/reauthenticate", "POST"): (
        {"password": "password"},
        frozenset({"password"}),
    ),
    ("/api/v1/auth/change-password", "POST"): (
        {"current_password": "password", "new_password": "password"},
        frozenset({"current_password", "new_password"}),
    ),
    ("/api/v1/auth/forgot-password", "POST"): (
        {"email": "email"},
        frozenset({"email"}),
    ),
    ("/api/v1/auth/reset-password", "POST"): (
        {"token": "token", "new_password": "password"},
        frozenset({"token", "new_password"}),
    ),
    ("/api/v1/auth/accept-invitation", "POST"): (
        {"token": "token", "new_password": "password"},
        frozenset({"token", "new_password"}),
    ),
    ("/api/v1/auth/switch-tenant", "POST"): (
        {"tenant_id": "uuid"},
        frozenset({"tenant_id"}),
    ),
    ("/api/v1/platform/tenants", "POST"): (
        {"name": "string", "slug": "string", "plan": "string"},
        frozenset({"name"}),
    ),
    ("/api/v1/platform/tenants/<uuid:tenant_id>", "PATCH"): (
        {"name": "string", "plan": "nullable_string"},
        frozenset(),
    ),
    ("/api/v1/platform/tenants/<uuid:tenant_id>/invite-owner", "POST"): (
        {"email": "email", "name": "string"},
        frozenset({"email"}),
    ),
    ("/api/v1/tenant-admin/members", "POST"): (
        {"email": "email", "name": "string", "role": "string"},
        frozenset({"email"}),
    ),
    ("/api/v1/tenant-admin/members/<uuid:member_id>", "PATCH"): (
        {"status": "member_status"},
        frozenset({"status"}),
    ),
    ("/api/v1/tenant-admin/members/<uuid:member_id>/roles", "PATCH"): (
        {"roles": "roles"},
        frozenset({"roles"}),
    ),
}


def _valid(value: Any, kind: str) -> bool:
    if kind == "nullable_string":
        return value is None or isinstance(value, str)
    if kind in {"string", "password", "token", "email"}:
        if not isinstance(value, str) or not value or len(value) > 1024:
            return False
        return kind != "email" or ("@" in value and len(value) <= 320)
    if kind == "uuid":
        try:
            UUID(str(value))
            return True
        except (TypeError, ValueError):
            return False
    if kind == "member_status":
        return value in {"active", "suspended"}
    if kind == "roles":
        return (
            isinstance(value, list)
            and bool(value)
            and len(value) <= 20
            and all(isinstance(item, str) and item for item in value)
            and len(set(value)) == len(value)
        )
    return False


def init_json_validation(app: Flask) -> None:
    @app.before_request
    def validate_json_contract() -> ResponseReturnValue | None:
        if request.url_rule is None:
            return None
        rule = RULES.get((request.url_rule.rule, request.method))
        if rule is None:
            return None
        fields, required = rule
        payload = request.get_json(silent=True)
        errors: dict[str, list[str]] = {}
        if not isinstance(payload, dict):
            errors["json"] = ["Se requiere un objeto JSON."]
        else:
            for name in required - payload.keys():
                errors[name] = ["Campo obligatorio."]
            for name in payload.keys() - fields.keys():
                errors[name] = ["Campo no permitido."]
            for name, value in payload.items():
                if name in fields and not _valid(value, fields[name]):
                    errors[name] = ["Valor no válido."]
        if errors:
            return problem_response(
                422,
                title="Datos no válidos",
                detail="Revisa los campos indicados.",
                code="validation_error",
                errors=errors,
            )
        return None
