"""OpenAPI post-processing for common Problem Details responses."""

from __future__ import annotations

from typing import Any


def declare_problem_responses(spec: dict[Any, Any] | str) -> dict[Any, Any] | str:
    """Declare common 500 and validation errors with the runtime media type."""

    if isinstance(spec, str):
        return spec
    problem_content = {
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}
    }
    components = spec.setdefault("components", {})
    components.setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "opn_oracle_session",
    }
    schemas = components.setdefault("schemas", {})
    schemas.update(_auth_input_schemas())
    schemas.update(_response_schemas())
    schemas.update(_oracle_schemas())
    schemas.update(_reporting_schemas())
    request_schemas = {
        ("/api/v1/auth/login", "post"): "LoginInput",
        ("/api/v1/auth/reauthenticate", "post"): "PasswordInput",
        ("/api/v1/auth/change-password", "post"): "ChangePasswordInput",
        ("/api/v1/auth/forgot-password", "post"): "ForgotPasswordInput",
        ("/api/v1/auth/reset-password", "post"): "ResetPasswordInput",
        ("/api/v1/auth/accept-invitation", "post"): "ResetPasswordInput",
        ("/api/v1/auth/switch-tenant", "post"): "SwitchTenantInput",
        ("/api/v1/platform/tenants", "post"): "TenantCreateInput",
        ("/api/v1/platform/tenants/{tenant_id}", "patch"): "TenantPatchInput",
        ("/api/v1/platform/tenants/{tenant_id}/invite-owner", "post"): "InviteMemberInput",
        ("/api/v1/tenant-admin/members", "post"): "InviteMemberInput",
        ("/api/v1/tenant-admin/members/{member_id}", "patch"): "MembershipPatchInput",
        ("/api/v1/tenant-admin/members/{member_id}/roles", "patch"): "RolesInput",
    }
    public = {
        "/health/live",
        "/health/ready",
        "/api/v1/meta",
        "/api/v1/auth/csrf",
        "/api/v1/auth/login",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/accept-invitation",
    }
    typed_responses = _typed_responses()
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            responses = operation.setdefault("responses", {})
            status_schema = typed_responses.get((path, method))
            if status_schema:
                status, response_schema = status_schema
                responses.pop("200", None)
                responses[status] = (
                    {"description": "Operación completada"}
                    if response_schema is None
                    else {
                        "description": "Operación completada",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"#/components/schemas/{response_schema}"}
                            }
                        },
                    }
                )
            else:
                responses.setdefault("200", {"description": "Operación completada"})
            schema_name = request_schemas.get((path, method))
            if schema_name:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{schema_name}"}
                        }
                    },
                }
            if path not in public:
                operation.setdefault("security", [{"cookieAuth": []}])
                responses.setdefault("401", _problem("Autenticación requerida", problem_content))
                responses.setdefault("403", _problem("Permiso denegado", problem_content))
            if method in {"post", "put", "patch", "delete"}:
                operation.setdefault("parameters", []).append(
                    {
                        "name": "X-CSRF-Token",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 32},
                    }
                )
                responses.setdefault("403", _problem("CSRF o permiso denegado", problem_content))
            responses.setdefault("422", _problem("Datos no válidos", problem_content))
            if path.endswith("/login") or path.endswith("forgot-password"):
                responses.setdefault("429", _problem("Límite de solicitudes", problem_content))
            if path.endswith("/login"):
                responses["409"] = {
                    "description": "Se debe seleccionar una organización",
                    "content": {
                        "application/problem+json": {
                            "schema": {"$ref": "#/components/schemas/TenantSelectionProblem"}
                        }
                    },
                }
            if any(
                marker in path for marker in ("/members", "/switch-tenant", "/platform/tenants")
            ):
                responses.setdefault("409", _problem("Conflicto de estado", problem_content))
            _declare_oracle_operation(path, method, operation, problem_content)
            _declare_reporting_operation(path, method, operation, problem_content)
            if path.startswith("/api/v1/jobs/{job_id}"):
                responses.setdefault("404", _problem("Job no encontrado", problem_content))
            if path.endswith(("/cancel", "/retry")) and path.startswith("/api/v1/jobs/"):
                _upsert_parameter(
                    operation,
                    {
                        "name": "If-Match",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "pattern": '^W/"[1-9][0-9]*"$'},
                    },
                )
                responses.setdefault("409", _problem("Conflicto de estado", problem_content))
                responses.setdefault(
                    "428", _problem("Se requiere la versión del job", problem_content)
                )
            validation = responses.get("422")
            if validation is not None:
                validation["content"] = problem_content
                validation["description"] = "Datos no válidos"
            responses.setdefault(
                "500",
                {
                    "description": "Error interno",
                    "content": problem_content,
                },
            )
    return spec


def _problem(description: str, content: dict[str, Any]) -> dict[str, Any]:
    return {"description": description, "content": content}


def _auth_input_schemas() -> dict[str, Any]:
    string = {"type": "string"}
    password = {"type": "string", "format": "password", "minLength": 1, "maxLength": 1024}
    email = {"type": "string", "format": "email", "maxLength": 320}
    uuid = {"type": "string", "format": "uuid"}
    return {
        "LoginInput": {
            "type": "object",
            "required": ["email", "password"],
            "properties": {"email": email, "password": password, "tenant_id": uuid},
            "additionalProperties": False,
        },
        "PasswordInput": {
            "type": "object",
            "required": ["password"],
            "properties": {"password": password},
            "additionalProperties": False,
        },
        "ChangePasswordInput": {
            "type": "object",
            "required": ["current_password", "new_password"],
            "properties": {"current_password": password, "new_password": password},
            "additionalProperties": False,
        },
        "ForgotPasswordInput": {
            "type": "object",
            "required": ["email"],
            "properties": {"email": email},
            "additionalProperties": False,
        },
        "ResetPasswordInput": {
            "type": "object",
            "required": ["token", "new_password"],
            "properties": {"token": string, "new_password": password},
            "additionalProperties": False,
        },
        "SwitchTenantInput": {
            "type": "object",
            "required": ["tenant_id"],
            "properties": {"tenant_id": uuid},
            "additionalProperties": False,
        },
        "TenantCreateInput": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": string, "slug": string, "plan": string},
            "additionalProperties": False,
        },
        "TenantPatchInput": {
            "type": "object",
            "properties": {"name": string, "plan": string},
            "additionalProperties": False,
        },
        "InviteMemberInput": {
            "type": "object",
            "required": ["email"],
            "properties": {"email": email, "name": string, "role": string},
            "additionalProperties": False,
        },
        "MembershipPatchInput": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string", "enum": ["active", "suspended"]}},
            "additionalProperties": False,
        },
        "RolesInput": {
            "type": "object",
            "required": ["roles"],
            "properties": {
                "roles": {"type": "array", "items": string, "minItems": 1, "uniqueItems": True}
            },
            "additionalProperties": False,
        },
    }


def _typed_responses() -> dict[tuple[str, str], tuple[str, str | None]]:
    no_content = ("204", None)
    return {
        ("/api/v1/auth/csrf", "get"): ("200", "CsrfResponse"),
        ("/api/v1/auth/login", "post"): ("200", "LoginResponse"),
        ("/api/v1/auth/me", "get"): ("200", "MeResponse"),
        ("/api/v1/auth/reauthenticate", "post"): ("200", "StatusResponse"),
        ("/api/v1/auth/switch-tenant", "post"): ("200", "SwitchTenantResponse"),
        ("/api/v1/auth/sessions", "get"): ("200", "SessionListResponse"),
        ("/api/v1/auth/logout", "post"): no_content,
        ("/api/v1/auth/change-password", "post"): no_content,
        ("/api/v1/auth/forgot-password", "post"): no_content,
        ("/api/v1/auth/reset-password", "post"): no_content,
        ("/api/v1/auth/accept-invitation", "post"): no_content,
        ("/api/v1/auth/sessions/{session_id}", "delete"): no_content,
        ("/api/v1/auth/sessions/revoke-others", "post"): no_content,
        ("/api/v1/platform/tenants", "get"): ("200", "TenantListResponse"),
        ("/api/v1/platform/tenants", "post"): ("201", "TenantResponse"),
        ("/api/v1/platform/tenants/{tenant_id}", "get"): ("200", "TenantResponse"),
        ("/api/v1/platform/tenants/{tenant_id}", "patch"): ("200", "TenantResponse"),
        ("/api/v1/platform/tenants/{tenant_id}/suspend", "post"): no_content,
        ("/api/v1/platform/tenants/{tenant_id}/reactivate", "post"): no_content,
        ("/api/v1/platform/tenants/{tenant_id}/invite-owner", "post"): (
            "201",
            "MembershipIdResponse",
        ),
        ("/api/v1/platform/users", "get"): ("200", "UserListResponse"),
        ("/api/v1/platform/audit", "get"): ("200", "AuditListResponse"),
        ("/api/v1/tenant-admin/members", "get"): ("200", "MemberListResponse"),
        ("/api/v1/tenant-admin/members", "post"): ("201", "IdResponse"),
        ("/api/v1/tenant-admin/members/{member_id}", "patch"): (
            "200",
            "StatusResponse",
        ),
        ("/api/v1/tenant-admin/members/{member_id}", "delete"): no_content,
        ("/api/v1/tenant-admin/members/{member_id}/resend-invite", "post"): no_content,
        ("/api/v1/tenant-admin/members/{member_id}/roles", "patch"): (
            "200",
            "RolesResponse",
        ),
        ("/api/v1/tenant-admin/roles", "get"): ("200", "RoleListResponse"),
        ("/api/v1/tenant-admin/audit", "get"): ("200", "AuditListResponse"),
        ("/api/v1/jobs", "get"): ("200", "JobListResponse"),
        ("/api/v1/jobs/{job_id}", "get"): ("200", "JobResponse"),
        ("/api/v1/jobs/{job_id}/cancel", "post"): ("202", "JobResponse"),
        ("/api/v1/jobs/{job_id}/retry", "post"): ("202", "JobResponse"),
    }


def _response_schemas() -> dict[str, Any]:
    uuid = {"type": "string", "format": "uuid"}
    nullable_uuid = {"type": "string", "format": "uuid", "nullable": True}

    def item_list(ref: str) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["items"],
            "properties": {"items": {"type": "array", "items": {"$ref": ref}}},
        }

    return {
        "IdResponse": {"type": "object", "required": ["id"], "properties": {"id": uuid}},
        "MembershipIdResponse": {
            "type": "object",
            "required": ["membership_id"],
            "properties": {"membership_id": uuid},
        },
        "StatusResponse": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}},
        },
        "SwitchTenantResponse": {
            "type": "object",
            "required": ["active_tenant_id"],
            "properties": {"active_tenant_id": uuid},
        },
        "RolesResponse": {
            "type": "object",
            "required": ["roles"],
            "properties": {"roles": {"type": "array", "items": {"type": "string"}}},
        },
        "CsrfResponse": {
            "type": "object",
            "required": ["csrf_token"],
            "properties": {"csrf_token": {"type": "string"}},
        },
        "LoginResponse": {
            "type": "object",
            "required": ["session_id", "requires_tenant_selection"],
            "properties": {"session_id": uuid, "requires_tenant_selection": {"type": "boolean"}},
        },
        "TenantChoiceResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tenant_id", "tenant_slug", "tenant_name"],
            "properties": {
                "tenant_id": uuid,
                "tenant_slug": {"type": "string"},
                "tenant_name": {"type": "string"},
            },
        },
        "TenantSelectionProblem": {
            "allOf": [
                {"$ref": "#/components/schemas/Problem"},
                {
                    "type": "object",
                    "required": ["errors"],
                    "properties": {
                        "errors": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["memberships"],
                            "properties": {
                                "memberships": {
                                    "type": "array",
                                    "minItems": 2,
                                    "items": {"$ref": "#/components/schemas/TenantChoiceResponse"},
                                }
                            },
                        }
                    },
                },
            ]
        },
        "SessionUserResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "email", "display_name", "platform_role"],
            "properties": {
                "id": uuid,
                "email": {"type": "string", "format": "email"},
                "display_name": {"type": "string"},
                "platform_role": {"type": "string", "nullable": True},
            },
        },
        "MembershipSummaryResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "membership_id",
                "tenant_id",
                "tenant_slug",
                "tenant_name",
                "membership_status",
            ],
            "properties": {
                "membership_id": uuid,
                "tenant_id": uuid,
                "tenant_slug": {"type": "string"},
                "tenant_name": {"type": "string"},
                "membership_status": {"type": "string"},
            },
        },
        "MeResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "user",
                "active_tenant_id",
                "memberships",
                "roles",
                "permissions",
            ],
            "properties": {
                "user": {"$ref": "#/components/schemas/SessionUserResponse"},
                "active_tenant_id": nullable_uuid,
                "memberships": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/MembershipSummaryResponse"},
                },
                "roles": {"type": "array", "items": {"type": "string"}},
                "permissions": {"type": "array", "items": {"type": "string"}},
            },
        },
        "SessionResponse": {
            "type": "object",
            "required": ["id", "current", "created_at", "expires_at"],
            "properties": {
                "id": uuid,
                "current": {"type": "boolean"},
                "active_tenant_id": nullable_uuid,
                "created_at": {"type": "string", "format": "date-time"},
                "expires_at": {"type": "string", "format": "date-time"},
            },
        },
        "TenantResponse": {
            "type": "object",
            "required": ["id", "name", "status"],
            "properties": {
                "id": uuid,
                "slug": {"type": "string"},
                "name": {"type": "string"},
                "status": {"type": "string"},
                "plan": {"type": "string", "nullable": True},
            },
        },
        "MemberResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["id", "user_id", "email", "display_name", "status", "roles"],
            "properties": {
                "id": uuid,
                "user_id": uuid,
                "email": {"type": "string", "format": "email"},
                "display_name": {"type": "string"},
                "status": {"type": "string"},
                "roles": {"type": "array", "items": {"type": "string"}},
            },
        },
        "RoleResponse": {
            "type": "object",
            "required": ["id", "key", "name"],
            "properties": {
                "id": uuid,
                "key": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
            },
        },
        "AuditResponse": {
            "type": "object",
            "required": ["id", "action", "result", "created_at"],
            "properties": {
                "id": uuid,
                "action": {"type": "string"},
                "result": {"type": "string"},
                "created_at": {"type": "string", "format": "date-time"},
            },
        },
        "UserResponse": {
            "type": "object",
            "required": ["id", "email", "display_name", "status"],
            "properties": {
                "id": uuid,
                "email": {"type": "string", "format": "email"},
                "display_name": {"type": "string"},
                "status": {"type": "string"},
                "platform_role": {"type": "string", "nullable": True},
            },
        },
        "SessionListResponse": item_list("#/components/schemas/SessionResponse"),
        "TenantListResponse": item_list("#/components/schemas/TenantResponse"),
        "MemberListResponse": item_list("#/components/schemas/MemberResponse"),
        "RoleListResponse": item_list("#/components/schemas/RoleResponse"),
        "AuditListResponse": item_list("#/components/schemas/AuditResponse"),
        "UserListResponse": item_list("#/components/schemas/UserResponse"),
        "JobResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "id",
                "tenant_id",
                "job_type",
                "queue",
                "status",
                "progress",
                "stage",
                "version",
            ],
            "properties": {
                "id": uuid,
                "tenant_id": uuid,
                "job_type": {"type": "string"},
                "queue": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["queued", "running", "retrying", "succeeded", "failed", "cancelled"],
                },
                "progress": {"type": "integer", "minimum": 0, "maximum": 100},
                "stage": {"type": "string"},
                "resource_type": {"type": "string", "nullable": True},
                "resource_id": nullable_uuid,
                "attempts": {"type": "integer"},
                "max_attempts": {"type": "integer"},
                "retryable": {"type": "boolean"},
                "started_at": {"type": "string", "format": "date-time", "nullable": True},
                "finished_at": {"type": "string", "format": "date-time", "nullable": True},
                "heartbeat_at": {"type": "string", "format": "date-time", "nullable": True},
                "error_code": {"type": "string", "nullable": True},
                "error_message": {"type": "string", "nullable": True},
                "cancel_requested": {"type": "boolean"},
                "result": {
                    "type": "object",
                    "additionalProperties": {"$ref": "#/components/schemas/JsonValue"},
                },
                "updated_at": {"type": "string", "format": "date-time"},
                "version": {"type": "integer", "minimum": 1},
            },
        },
        "JobListResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["data", "meta"],
            "properties": {
                "data": {"type": "array", "items": {"$ref": "#/components/schemas/JobResponse"}},
                "meta": {"$ref": "#/components/schemas/PageMeta"},
            },
        },
    }


def _declare_oracle_operation(
    path: str, method: str, operation: dict[str, Any], problem_content: dict[str, Any]
) -> None:
    if not path.startswith("/api/v1/") or not any(
        token in path
        for token in (
            "/dossiers",
            "/signals",
            "/opportunities",
            "/risks",
            "/actors",
            "/relationships",
            "/meetings",
            "/tasks",
            "/feedback",
            "/evidence",
            "/watchlists",
            "/briefings",
            "/insights",
            "/reports",
            "/objectives",
            "/hypotheses",
            "/signal-monitors",
            "/decisions",
            "/dossier-actors",
            "/collaborators",
            "/home",
            "/changes",
            "/search",
        )
    ):
        return
    if "/oracle-summary" in path:
        _declare_oracle_summary_operation(path, method, operation, problem_content)
        return
    if "/actor-candidates" in path:
        if method == "post":
            is_review = path.endswith("/review")
            operation["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/ActorCandidateReviewInput"
                                if is_review
                                else "#/components/schemas/ActorCandidateImportInput"
                            )
                        }
                    }
                },
            }
            operation.setdefault("responses", {})["200" if is_review else "201"] = {
                "description": (
                    "Revisión del candidato actualizada"
                    if is_review
                    else "Candidato importado y vinculado"
                ),
                "content": {
                    "application/json": {
                        "schema": {
                            "$ref": (
                                "#/components/schemas/ActorCandidateReviewResponse"
                                if is_review
                                else "#/components/schemas/ActorCandidateImportResponse"
                            )
                        }
                    }
                },
            }
            if not is_review:
                operation["responses"].pop("200", None)
        else:
            operation.setdefault("parameters", []).append(
                {
                    "name": "include_dismissed",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "boolean", "default": False},
                    "description": "Incluye candidatos descartados para permitir su restauración.",
                }
            )
            operation.setdefault("responses", {})["200"] = {
                "description": "Candidatos detectados en fuentes del expediente",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ActorCandidateListResponse"}
                    }
                },
            }
        operation.setdefault("responses", {})["404"] = _problem(
            "Expediente o candidato no encontrado", problem_content
        )
        operation["responses"]["422"] = _problem("Entrada no válida", problem_content)
        return
    resource = _oracle_resource_for_path(path)
    m2m_target = _oracle_m2m_target(path)
    signal_monitor_create = (
        path == "/api/v1/dossiers/{dossier_id}/signal-monitors" and method == "post"
    )
    signal_monitor_update = path == "/api/v1/signal-monitors/{monitor_id}" and method == "patch"
    signal_monitor_action = (
        path == "/api/v1/signal-monitors/{monitor_id}/{action}" and method == "post"
    )
    needs_body = (
        method in {"post", "put", "patch"}
        and not path.endswith("/archive")
        and not (m2m_target and path.endswith("/{target_id}"))
        and not signal_monitor_action
    )
    if needs_body:
        schema = f"{resource}WriteInput"
        if path == "/api/v1/dossiers" and method == "post":
            schema = "DossierCreateInput"
        elif path == "/api/v1/dossiers/bulk-delete" and method == "post":
            schema = "DossierBulkDeleteInput"
        elif path == "/api/v1/dossiers/{dossier_id}" and method == "patch":
            schema = "DossierPatchInput"
        elif path.endswith("/review"):
            schema = "SignalReviewInput"
        elif path.endswith("/promote"):
            schema = "SignalPromoteInput"
        elif path.endswith("/merge"):
            schema = "ActorMergeInput"
        elif path.endswith("/retriage"):
            schema = "AIRetriageInput"
        elif path == "/api/v1/watchlists/{watchlist_id}/monitors":
            schema = "SignalMonitorWriteInput"
        elif signal_monitor_create:
            schema = "SignalMonitorCreateInput"
        elif signal_monitor_update:
            schema = "SignalMonitorUpdateInput"
        elif path == "/api/v1/meetings/{meeting_id}/briefings":
            schema = "BriefingWriteInput"
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
        }
    if signal_monitor_create or signal_monitor_update or signal_monitor_action:
        status = "202"
    elif path == "/api/v1/dossiers/bulk-delete" and method == "post":
        status = "200"
    else:
        status = (
            "201"
            if method == "post" and not path.endswith(("/review", "/promote", "/archive", "/merge"))
            else "200"
        )
    if method == "delete":
        operation.setdefault("responses", {}).pop("200", None)
        operation["responses"]["204"] = {"description": "Recurso eliminado"}
    elif method in {"get", "post", "put", "patch"}:
        if signal_monitor_create or signal_monitor_update or signal_monitor_action:
            for existing_status in tuple(operation.setdefault("responses", {})):
                if existing_status.startswith("2") and existing_status != status:
                    operation["responses"].pop(existing_status)
        response: dict[str, Any]
        if path == "/api/v1/home" and method == "get":
            response = {"$ref": "#/components/schemas/HomeResponse"}
        elif path == "/api/v1/search" and method == "get":
            response = {"$ref": "#/components/schemas/GlobalSearchResponse"}
        elif path == "/api/v1/changes" and method == "get":
            response = {"$ref": "#/components/schemas/ChangeListResponse"}
        elif path == "/api/v1/signals" and method == "get":
            response = {"$ref": "#/components/schemas/GlobalSignalListResponse"}
        elif (
            path
            in {
                "/api/v1/opportunities",
                "/api/v1/risks",
                "/api/v1/meetings",
                "/api/v1/tasks",
            }
            and method == "get"
        ):
            response_name = {
                "/api/v1/opportunities": "GlobalOpportunityListResponse",
                "/api/v1/risks": "GlobalRiskListResponse",
                "/api/v1/meetings": "GlobalMeetingListResponse",
                "/api/v1/tasks": "GlobalTaskListResponse",
            }[path]
            response = {"$ref": f"#/components/schemas/{response_name}"}
        elif m2m_target and method == "put" and path.endswith("/{target_id}"):
            response = {"$ref": "#/components/schemas/LinkMutationResponse"}
        elif path == "/api/v1/dossiers/bulk-delete":
            response = {"$ref": "#/components/schemas/DossierBulkDeleteResponse"}
        elif path.endswith("/promote"):
            response = {"$ref": "#/components/schemas/PromotionResponse"}
        elif path.endswith("/retriage"):
            response = {"$ref": "#/components/schemas/AIJobEnqueueResponse"}
        elif method == "get" and _is_oracle_list_path(path):
            item_schema = (
                "DossierSignalEnvelope"
                if path == "/api/v1/dossiers/{dossier_id}/signals"
                else f"{resource}Resource"
            )
            response = {
                "type": "object",
                "additionalProperties": False,
                "required": ["data"],
                "properties": {
                    "data": {
                        "type": "array",
                        "items": {"$ref": f"#/components/schemas/{item_schema}"},
                    },
                    "meta": {"$ref": "#/components/schemas/PageMeta"},
                },
            }
        elif signal_monitor_create or signal_monitor_update or signal_monitor_action:
            response = {"$ref": "#/components/schemas/SignalMonitorCommandResponse"}
        else:
            response = {"$ref": f"#/components/schemas/{resource}Resource"}
        operation.setdefault("responses", {})[status] = {
            "description": "Operación de dominio completada",
            "content": {"application/json": {"schema": response}},
        }
        if status == "201":
            operation["responses"].pop("200", None)
            if path == "/api/v1/actors":
                operation["responses"]["200"] = {
                    "description": "Actor canónico ya existente",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ActorResource"}
                        }
                    },
                }
        if path.endswith("/living-summary") and method == "put":
            operation["responses"]["201"] = {
                "description": "Resumen vivo creado",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/LivingSummaryResource"}
                    }
                },
            }
    operation.setdefault("responses", {})["404"] = _problem(
        "Recurso no encontrado", problem_content
    )
    if path == "/api/v1/dossiers/{dossier_id}/archive" or signal_monitor_update:
        _upsert_parameter(
            operation,
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "pattern": '^W/"[1-9][0-9]*"$'},
            },
        )
    elif method == "patch" or (path.endswith("/living-summary") and method == "put"):
        _upsert_parameter(
            operation,
            {
                "name": "If-Match",
                "in": "header",
                "required": False,
                "description": (
                    "Versión ETag; puede enviarse `version` en el cuerpo como alternativa."
                ),
                "schema": {"type": "string", "pattern": '^W/"[1-9][0-9]*"$'},
            },
        )
    if path.endswith("/promote") or (
        method in {"post", "patch"}
        and (signal_monitor_create or signal_monitor_update or signal_monitor_action)
    ):
        _upsert_parameter(
            operation,
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "minLength": 8, "maxLength": 200},
            },
        )
    if path == "/api/v1/dossiers" and method == "get":
        for parameter in _dossier_list_parameters():
            _upsert_parameter(operation, parameter)
    elif path == "/api/v1/changes" and method == "get":
        for parameter in _changes_list_parameters():
            _upsert_parameter(operation, parameter)
    elif path == "/api/v1/search" and method == "get":
        for parameter in _global_search_parameters():
            _upsert_parameter(operation, parameter)
    elif method == "get" and _is_paginated_oracle_list_path(path):
        for parameter in _generic_list_parameters():
            _upsert_parameter(operation, parameter)
        if path in {
            "/api/v1/signals",
            "/api/v1/opportunities",
            "/api/v1/risks",
            "/api/v1/meetings",
            "/api/v1/tasks",
        }:
            _upsert_parameter(
                operation,
                {
                    "name": "filter[dossier_id]",
                    "in": "query",
                    "schema": {"type": "string", "format": "uuid"},
                },
            )
    operation.setdefault("responses", {}).setdefault(
        "409", _problem("Conflicto de versión o idempotencia", problem_content)
    )


def _declare_oracle_summary_operation(
    path: str, method: str, operation: dict[str, Any], problem_content: dict[str, Any]
) -> None:
    responses = operation.setdefault("responses", {})
    for status in tuple(responses):
        if status.startswith("2"):
            responses.pop(status)
    if method == "post" and path.endswith("/feedback"):
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryFeedbackInput"}
                }
            },
        }
        responses["201"] = {
            "description": "Feedback registrado",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryFeedbackResponse"}
                }
            },
        }
    elif method == "post":
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryRefreshInput"}
                }
            },
        }
        responses["202"] = {
            "description": "Refresh encolado",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AIJobEnqueueResponse"}
                }
            },
        }
        _upsert_parameter(
            operation,
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "minLength": 8, "maxLength": 200},
            },
        )
    elif path.endswith("/versions/{version_id}"):
        responses["200"] = {
            "description": "Versión del Oráculo",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryVersion"}
                }
            },
        }
    elif path.endswith("/versions"):
        responses["200"] = {
            "description": "Historial del Oráculo",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryVersionList"}
                }
            },
        }
    else:
        responses["200"] = {
            "description": "Resumen del Oráculo",
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/OracleSummaryCurrentResponse"}
                }
            },
        }
    responses["404"] = _problem("Recurso no encontrado", problem_content)


def _upsert_parameter(operation: dict[str, Any], parameter: dict[str, Any]) -> None:
    parameters = operation.setdefault("parameters", [])
    parameters[:] = [
        current
        for current in parameters
        if (current.get("name"), current.get("in")) != (parameter["name"], parameter["in"])
    ]
    parameters.append(parameter)


def _dossier_list_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "page[number]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "default": 1},
        },
        {
            "name": "page[size]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        },
        {
            "name": "sort",
            "in": "query",
            "schema": {
                "type": "string",
                "default": "-updated_at",
                "enum": [
                    "updated_at",
                    "-updated_at",
                    "title",
                    "-title",
                    "status",
                    "-status",
                    "health_score",
                    "-health_score",
                    "opportunity_score",
                    "-opportunity_score",
                    "risk_score",
                    "-risk_score",
                ],
            },
        },
        {"name": "filter[status]", "in": "query", "schema": {"type": "string"}},
        {"name": "filter[type]", "in": "query", "schema": {"type": "string"}},
        {
            "name": "filter[owner]",
            "in": "query",
            "schema": {"type": "string", "format": "uuid"},
        },
        {"name": "filter[search]", "in": "query", "schema": {"type": "string"}},
        *_typed_filter_parameters(exclude={"filter[type]", "filter[owner]"}),
    ]


def _generic_list_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "page[number]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "default": 1},
        },
        {
            "name": "page[size]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        },
        {"name": "sort", "in": "query", "schema": {"type": "string"}},
        {"name": "filter[status]", "in": "query", "schema": {"type": "string"}},
        {"name": "filter[search]", "in": "query", "schema": {"type": "string"}},
        *_typed_filter_parameters(),
    ]


def _changes_list_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "page[number]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "default": 1},
        },
        {
            "name": "page[size]",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        },
        {
            "name": "sort",
            "in": "query",
            "schema": {
                "type": "string",
                "enum": ["created_at", "-created_at"],
                "default": "-created_at",
            },
        },
        {
            "name": "filter[dossier_id]",
            "in": "query",
            "schema": {"type": "string", "format": "uuid"},
        },
        {"name": "filter[type]", "in": "query", "schema": {"type": "string"}},
        {
            "name": "filter[since]",
            "in": "query",
            "schema": {"type": "string", "format": "date-time"},
        },
        {"name": "filter[search]", "in": "query", "schema": {"type": "string"}},
    ]


def _global_search_parameters() -> list[dict[str, Any]]:
    return [
        {
            "name": "q",
            "in": "query",
            "required": True,
            "schema": {"type": "string", "minLength": 2, "maxLength": 100},
        },
        {
            "name": "types",
            "in": "query",
            "schema": {
                "type": "string",
                "description": ("Lista CSV: dossiers, actors, signals, opportunities, documents."),
            },
        },
        {
            "name": "limit",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
        },
    ]


def _typed_filter_parameters(*, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude or set()
    parameters = [
        {"name": "filter[selected_ids]", "schema": {"type": "string"}},
        {"name": "filter[type]", "schema": {"type": "string"}},
        {"name": "filter[owner]", "schema": {"type": "string", "format": "uuid"}},
        {
            "name": "filter[date_from]",
            "schema": {"type": "string", "format": "date-time"},
        },
        {
            "name": "filter[date_to]",
            "schema": {"type": "string", "format": "date-time"},
        },
        {
            "name": "filter[score_min]",
            "schema": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        {
            "name": "filter[score_max]",
            "schema": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    ]
    return [
        parameter | {"in": "query"} for parameter in parameters if parameter["name"] not in excluded
    ]


def _is_oracle_list_path(path: str) -> bool:
    if path in {
        "/api/v1/dossiers",
        "/api/v1/signals",
        "/api/v1/opportunities",
        "/api/v1/risks",
        "/api/v1/actors",
        "/api/v1/meetings",
        "/api/v1/tasks",
        "/api/v1/relationships",
        "/api/v1/changes",
    }:
        return True
    return path.endswith(
        (
            "/signals",
            "/monitors",
            "/briefings",
            "/objectives",
            "/hypotheses",
            "/watchlists",
            "/opportunities",
            "/risks",
            "/actors",
            "/meetings",
            "/decisions",
            "/tasks",
            "/insights",
            "/reports",
            "/evidence",
            "/feedback",
            "/collaborators",
            "/audit",
            "/status-history",
        )
    )


def _is_paginated_oracle_list_path(path: str) -> bool:
    return _is_oracle_list_path(path) and not path.endswith("/collaborators")


def _oracle_m2m_target(path: str) -> str | None:
    parts = path.strip("/").split("/")
    if len(parts) not in {5, 6} or parts[:2] != ["api", "v1"]:
        return None
    parent, resource_id, relation = parts[2:5]
    if resource_id != "{resource_id}" or parent not in {
        "opportunities",
        "risks",
        "meetings",
        "hypotheses",
        "dossier-actors",
        "relationships",
        "decisions",
        "insights",
        "reports",
    }:
        return None
    if len(parts) == 6 and parts[5] != "{target_id}":
        return None
    return {"actors": "Actor", "evidence": "Evidence", "signals": "Signal"}.get(relation)


def _oracle_resource_for_path(path: str) -> str:
    m2m_target = _oracle_m2m_target(path)
    if m2m_target is not None:
        return m2m_target
    nested = {
        "/objectives": "Objective",
        "/hypotheses": "Hypothesis",
        "/watchlists": "Watchlist",
        "/signal-monitors": "SignalMonitor",
        "/monitors": "SignalMonitor",
        "/opportunities": "Opportunity",
        "/risks": "Risk",
        "/dossier-actors": "DossierActor",
        "/meetings": "Meeting",
        "/briefings": "Briefing",
        "/decisions": "Decision",
        "/tasks": "Task",
        "/insights": "Insight",
        "/reports": "Report",
        "/evidence": "Evidence",
        "/relationships": "Relationship",
        "/feedback": "Feedback",
        "/collaborators": "Collaborator",
        "/living-summary": "LivingSummary",
        "/status-history": "StatusHistory",
    }
    if path == "/api/v1/signals":
        return "DossierSignal"
    if path == "/api/v1/home":
        return "Home"
    if path == "/api/v1/changes":
        return "Change"
    if path == "/api/v1/search":
        return "GlobalSearch"
    if "/dossiers/" in path and path.endswith("/signals"):
        return "DossierSignal"
    if "/dossiers/" in path and path.endswith("/actors"):
        return "DossierActor"
    if path.endswith("/briefings"):
        return "Briefing"
    if path.endswith("/monitors"):
        return "SignalMonitor"
    for token, name in nested.items():
        if token in path:
            return name
    if "/signals/" in path:
        return "DossierSignal" if path.endswith(("/review", "/promote")) else "Signal"
    if "/actors" in path:
        return "Actor"
    if path.endswith("/audit"):
        return "Audit"
    return "Dossier"


def _oracle_schemas() -> dict[str, Any]:
    score = {"type": "integer", "minimum": 0, "maximum": 100}
    version = {"type": "integer", "minimum": 1}
    uuid = {"type": "string", "format": "uuid"}
    string = {"type": "string"}
    nullable_uuid = {"type": "string", "format": "uuid", "nullable": True}
    json_object = {"$ref": "#/components/schemas/JsonObject"}
    json_array = {"$ref": "#/components/schemas/JsonArray"}
    string_array = {"type": "array", "items": string}
    uuid_array = {"type": "array", "items": uuid}
    common = {
        "id": uuid,
        "tenant_id": uuid,
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    }

    def resource(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": required or ["id", "tenant_id"],
            "properties": common | properties,
        }

    def write(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        value: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
        }
        if required:
            value["required"] = required
        return value

    schemas: dict[str, Any] = {
        "JsonValue": {
            "nullable": True,
            "oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {
                    "type": "object",
                    "additionalProperties": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                        ]
                    },
                },
                {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "number"},
                            {"type": "boolean"},
                        ]
                    },
                },
            ],
        },
        "JsonObject": {
            "type": "object",
            "additionalProperties": {"$ref": "#/components/schemas/JsonValue"},
        },
        "JsonArray": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/JsonValue"},
        },
        "PageMeta": write(
            {
                "page": {"type": "integer"},
                "size": {"type": "integer"},
                "total": {"type": "integer"},
            }
        ),
        "DossierCreateInput": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "type"],
            "properties": {
                "workspace_id": uuid,
                "title": {"type": "string", "minLength": 1, "maxLength": 240},
                "type": {"type": "string"},
                "description": {"type": "string"},
                "strategic_goal": {"type": "string"},
                "owner_user_id": uuid,
                "collaborator_user_ids": uuid_array,
                "geography": string_array,
                "sectors": string_array,
                "languages": string_array,
                "scoring_config": json_object,
                "create_starter_profile": {"type": "boolean"},
            },
        },
        "DossierPatchInput": write(
            {
                "version": {"type": "integer", "minimum": 1},
                "title": string,
                "description": string,
                "strategic_goal": string,
                "status": {
                    "type": "string",
                    "enum": ["draft", "active", "paused", "archived"],
                },
                "owner_user_id": uuid,
                "scoring_config": json_object,
            }
        ),
        "DossierBulkDeleteInput": {
            "type": "object",
            "additionalProperties": False,
            "required": ["dossier_ids"],
            "properties": {
                "dossier_ids": {
                    "type": "array",
                    "items": uuid,
                    "minItems": 1,
                    "maxItems": 100,
                    "uniqueItems": True,
                }
            },
        },
        "DossierBulkDeleteResponse": {
            "type": "object",
            "additionalProperties": False,
            "required": ["deleted_ids", "deleted_count"],
            "properties": {
                "deleted_ids": {"type": "array", "items": uuid},
                "deleted_count": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
        "SignalReviewInput": {
            "type": "object",
            "additionalProperties": False,
            "required": ["version", "relevance", "novelty", "confidence", "strategic_impact"],
            "properties": {
                "version": {"type": "integer", "minimum": 1},
                "relevance": score,
                "novelty": score,
                "confidence": score,
                "strategic_impact": score,
                "why_it_matters": {"type": "string"},
                "recommended_action": {"type": "string"},
            },
        },
        "SignalPromoteInput": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "title"],
            "properties": {
                "kind": {"type": "string", "enum": ["opportunity", "risk"]},
                "title": {"type": "string", "minLength": 1},
                "strategic_fit": score,
                "urgency": score,
                "expected_value": score,
                "actionability": score,
                "relationship_leverage": score,
                "timing": score,
                "confidence": score,
                "effort": score,
                "execution_effort": score,
                "blocking_risk": score,
                "impact": score,
                "likelihood": score,
                "velocity": score,
                "exposure": score,
                "uncertainty": score,
                "controllability": score,
                "score_override": score,
                "score_override_reason": string,
            },
        },
        "ActorMergeInput": write(
            {"source_actor_id": uuid, "reason": string}, ["source_actor_id", "reason"]
        ),
    }
    resource_properties: dict[str, dict[str, Any]] = {
        "Dossier": {
            "workspace_id": uuid,
            "title": string,
            "description": string,
            "dossier_type": string,
            "status": string,
            "strategic_goal": string,
            "owner_user_id": nullable_uuid,
            "collaborator_user_ids": uuid_array,
            "geography": string_array,
            "sectors": string_array,
            "languages": string_array,
            "score_explanation": json_object,
            "health_score": score,
            "opportunity_score": score,
            "risk_score": score,
            "version": {"type": "integer"},
            "synthetic_data": {"type": "boolean"},
        },
        "Objective": {
            "dossier_id": uuid,
            "title": string,
            "description": string,
            "status": string,
            "priority": string,
            "metrics": json_object,
            "target_date": {"type": "string", "format": "date", "nullable": True},
            "position": {"type": "integer"},
            "version": version,
        },
        "Hypothesis": {
            "dossier_id": uuid,
            "statement": string,
            "rationale": string,
            "status": string,
            "confidence": score,
            "version": version,
        },
        "Watchlist": {
            "dossier_id": uuid,
            "name": string,
            "status": string,
            "cadence": string,
            "query_config": json_object,
            "version": version,
        },
        "SignalMonitor": {
            "watchlist_id": uuid,
            "provider": string,
            "external_id": string | {"nullable": True},
            "status": string,
            "cursor": {"type": "string", "nullable": True},
            "last_synced_at": {"type": "string", "format": "date-time", "nullable": True},
            "last_error": {"type": "string", "nullable": True},
            "version": version,
        },
        "Signal": {
            "provider": string,
            "external_id": string,
            "title": string,
            "summary": string,
            "source_type": string,
            "source_name": string,
            "source_url": {"type": "string", "nullable": True},
            "published_at": {"type": "string", "format": "date-time", "nullable": True},
            "ingested_at": {"type": "string", "format": "date-time"},
            "language": {"type": "string", "nullable": True},
            "tags": string_array,
            "entities": json_array,
            "categories": string_array,
            "credibility": score,
            "raw_payload": json_object,
        },
        "DossierSignal": {
            "dossier_id": uuid,
            "signal_id": uuid,
            "status": string,
            "relevance": score,
            "novelty": score,
            "confidence": score,
            "strategic_impact": score,
            "overall_score": score,
            "scoring_state": {
                "type": "string",
                "enum": ["pending", "provisional", "reviewed"],
            },
            "triage_version": {"type": "integer"},
            "why_it_matters": string,
            "recommended_action": string,
        },
        "Opportunity": {
            "dossier_id": uuid,
            "title": string,
            "description": string,
            "opportunity_type": string,
            "status": string,
            "strategic_fit": score,
            "urgency": score,
            "expected_value": score,
            "actionability": score,
            "relationship_leverage": score,
            "timing": score,
            "effort": score,
            "blocking_risk": score,
            "confidence": score,
            "overall_score": score,
            "score_details": json_object,
            "score_override": score | {"nullable": True},
            "score_override_reason": {"type": "string", "nullable": True},
            "deadline": {"type": "string", "format": "date", "nullable": True},
            "next_action": string,
            "owner_user_id": nullable_uuid,
            "source_dossier_signal_id": nullable_uuid,
            "version": {"type": "integer"},
        },
        "Risk": {
            "dossier_id": uuid,
            "title": string,
            "description": string,
            "category": string,
            "status": string,
            "likelihood": score,
            "impact": score,
            "velocity": score,
            "exposure": score,
            "uncertainty": score,
            "controllability": score,
            "confidence": score,
            "overall_score": score,
            "score_details": json_object,
            "score_override": score | {"nullable": True},
            "score_override_reason": {"type": "string", "nullable": True},
            "mitigation": string,
            "owner_user_id": nullable_uuid,
            "due_date": {"type": "string", "format": "date", "nullable": True},
            "source_dossier_signal_id": nullable_uuid,
            "version": {"type": "integer"},
        },
        "Actor": {
            "actor_type": string,
            "canonical_name": string,
            "canonical_key": string,
            "aliases": string_array,
            "identifiers": json_object,
            "metadata": json_object,
            "provenance": json_object,
            "version": version,
        },
        "DossierActor": {
            "dossier_id": uuid,
            "actor_id": uuid,
            "roles": string_array,
            "influence": score,
            "relevance_to_dossier": score,
            "relationship_strength": score,
            "accessibility": score,
            "strategic_alignment": score,
            "recent_activity": score,
            "priority": score,
            "version": version,
        },
        "Relationship": {
            "from_actor_id": uuid,
            "to_actor_id": uuid,
            "dossier_id": nullable_uuid,
            "relationship_type": string,
            "strength": score,
            "direction": string,
            "confidence": score,
            "evidence_ids": uuid_array,
            "version": version,
        },
        "Meeting": {
            "dossier_id": uuid,
            "title": string,
            "status": string,
            "content": json_object,
            "scheduled_at": {"type": "string", "format": "date-time", "nullable": True},
            "objective": string,
            "notes": string,
            "version": {"type": "integer"},
        },
        "Briefing": {
            "meeting_id": uuid,
            "version": version,
            "content": json_object,
        },
        "Decision": {
            "dossier_id": uuid,
            "title": string,
            "status": string,
            "version": {"type": "integer"},
        },
        "Task": {
            "dossier_id": uuid,
            "title": string,
            "status": string,
            "content": json_object,
            "owner_user_id": nullable_uuid,
            "due_date": {"type": "string", "format": "date", "nullable": True},
            "priority": string,
            "linked_resource_type": {"type": "string", "nullable": True},
            "linked_resource_id": nullable_uuid,
            "origin": string,
            "version": {"type": "integer"},
        },
        "Insight": {
            "dossier_id": uuid,
            "title": string,
            "status": string,
            "confidence": score,
            "version": version,
        },
        "Report": {
            "dossier_id": uuid,
            "title": string,
            "status": string,
            "version": {"type": "integer"},
        },
        "Evidence": {
            "signal_id": uuid,
            "document_id": nullable_uuid,
            "source_url": {"type": "string", "nullable": True},
            "extract": string,
            "locator": json_object,
            "classification": string,
            "provenance": json_object,
            "version": version,
        },
        "Feedback": {
            "target_type": string,
            "target_id": uuid,
            "actor_user_id": uuid,
            "rating": {"type": "integer", "minimum": -1, "maximum": 1},
            "correction": json_object,
            "comment": string,
            "version": version,
        },
        "Collaborator": {"dossier_id": uuid, "user_id": uuid, "role": string},
        "LivingSummary": {
            "dossier_id": uuid,
            "version": {"type": "integer", "minimum": 1},
            "summary": json_object,
            "last_refreshed_at": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
            },
        },
        "OracleSummaryCitation": {
            "source_kind": string,
            "source_url": {"type": "string", "nullable": True},
            "locator": json_object,
            "extract": string,
            "classification": string,
        },
        "OracleSummaryAudit": {
            "provider": string,
            "model": string,
            "prompt_name": string,
            "prompt_version": string,
            "prompt_hash": string,
            "context_hash": {"type": "string", "nullable": True},
            "input_tokens": {"type": "integer"},
            "output_tokens": {"type": "integer"},
            "cost_micros": {"type": "integer"},
            "latency_ms": {"type": "integer", "nullable": True},
            "status": string,
        },
        "StatusHistory": {
            "dossier_id": uuid,
            "resource_type": string,
            "resource_id": uuid,
            "from_status": string,
            "to_status": string,
            "actor_user_id": uuid,
            "reason": string,
        },
        "Audit": {"action": string, "result": string, "dossier_id": uuid},
    }
    for name, properties in resource_properties.items():
        schemas[f"{name}Resource"] = resource(properties)

    schemas["OracleSummaryVersion"] = resource(
        {
            "dossier_id": uuid,
            "version": {"type": "integer", "minimum": 1},
            "status": string,
            "output": json_object,
            "citations": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/OracleSummaryCitationResource"},
            },
            "audit": {"$ref": "#/components/schemas/OracleSummaryAuditResource"},
            "snapshot": json_object,
        }
    )
    schemas["OracleSummaryCurrentResponse"] = write(
        {
            "state": {"type": "string", "enum": ["empty", "ready"]},
            "summary": {
                "oneOf": [
                    {"$ref": "#/components/schemas/OracleSummaryVersion"},
                    {"type": "null"},
                ]
            },
            "living_summary_version": {"type": "integer", "nullable": True},
            "generation_trigger": {
                "type": "string",
                "enum": ["manual", "nightly"],
                "nullable": True,
            },
            "last_refreshed_at": {
                "type": "string",
                "format": "date-time",
                "nullable": True,
            },
            "job": {
                "oneOf": [
                    {"$ref": "#/components/schemas/JobResponse"},
                    {"type": "null"},
                ]
            },
        },
        ["state"],
    )
    schemas["OracleSummaryVersionList"] = write(
        {
            "data": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/OracleSummaryVersion"},
            }
        },
        ["data"],
    )
    schemas["OracleSummaryRefreshInput"] = write({})
    schemas["OracleSummaryFeedbackInput"] = write(
        {
            "rating": {"type": "integer"},
            "correction": json_object,
            "comment": string,
        }
    )
    schemas["OracleSummaryFeedbackResponse"] = write({"feedback_id": uuid}, ["feedback_id"])
    schemas["ActorCandidateSource"] = write(
        {
            "dossier_signal_id": uuid,
            "signal_id": uuid,
            "title": string,
            "source_name": string,
            "source_url": {"type": "string", "nullable": True},
            "excerpt": string,
            "published_at": {"type": "string", "format": "date-time", "nullable": True},
        },
        ["dossier_signal_id", "signal_id", "title", "source_name", "excerpt"],
    )
    schemas["ActorCandidate"] = write(
        {
            "id": uuid,
            "canonical_key": string,
            "name": string,
            "suggested_actor_type": {
                "type": "string",
                "enum": ["person", "organization", "institution", "program", "other"],
            },
            "suggested_labels": string_array,
            "labels": string_array,
            "status": {
                "type": "string",
                "enum": ["candidate", "existing", "linked", "dismissed"],
            },
            "extraction_methods": string_array,
            "source_count": {"type": "integer", "minimum": 1},
            "existing_actor_id": nullable_uuid,
            "sources": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ActorCandidateSource"},
            },
        },
        [
            "id",
            "canonical_key",
            "name",
            "suggested_actor_type",
            "suggested_labels",
            "labels",
            "status",
            "source_count",
            "extraction_methods",
            "sources",
        ],
    )
    schemas["ActorCandidateListResponse"] = write(
        {
            "data": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/ActorCandidate"},
            },
            "meta": write({"total": {"type": "integer", "minimum": 0}}, ["total"]),
        },
        ["data", "meta"],
    )
    schemas["ActorCandidateImportInput"] = write(
        {
            "actor_type": {
                "type": "string",
                "enum": ["person", "organization", "institution", "program", "other"],
            },
            "tags": string_array,
            "roles": string_array,
        }
    )
    schemas["ActorCandidateImportResponse"] = write(
        {
            "actor": {"$ref": "#/components/schemas/ActorResource"},
            "link": {"$ref": "#/components/schemas/DossierActorResource"},
        },
        ["actor", "link"],
    )
    schemas["ActorCandidateReviewInput"] = write(
        {"status": {"type": "string", "enum": ["candidate", "dismissed"]}},
        ["status"],
    )
    schemas["ActorCandidateReviewResponse"] = write(
        {"candidate": {"$ref": "#/components/schemas/ActorCandidate"}},
        ["candidate"],
    )

    common_child = {"title": string, "status": string, "content": json_object}
    write_properties: dict[str, dict[str, Any]] = {
        "Objective": common_child | {"priority": string, "metrics": json_object},
        "Hypothesis": {
            "statement": string,
            "rationale": string,
            "status": string,
            "confidence": score,
        },
        "Watchlist": {"name": string, "cadence": string, "query_config": json_object},
        "SignalMonitor": {"provider": string, "external_id": string, "status": string},
        "Opportunity": schemas["SignalPromoteInput"]["properties"]
        | {
            "version": {"type": "integer"},
            "status": string,
            "description": string,
            "opportunity_type": string,
            "next_action": string,
        },
        "Risk": schemas["SignalPromoteInput"]["properties"]
        | {
            "version": {"type": "integer"},
            "status": string,
            "description": string,
            "category": string,
            "mitigation": string,
        },
        "Actor": {
            "canonical_name": string,
            "actor_type": string,
            "aliases": string_array,
            "identifiers": json_object,
            "metadata": json_object,
            "provenance": json_object,
        },
        "DossierActor": {
            "actor_id": uuid,
            "canonical_name": string,
            "actor_type": {
                "type": "string",
                "enum": ["person", "organization", "institution", "program", "other"],
            },
            "tags": string_array,
            "provenance": json_object,
            "roles": string_array,
        }
        | {
            key: score
            for key in (
                "influence",
                "relevance_to_dossier",
                "relationship_strength",
                "accessibility",
                "strategic_alignment",
                "recent_activity",
            )
        },
        "Relationship": {
            "from_actor_id": uuid,
            "to_actor_id": uuid,
            "dossier_id": uuid,
            "relationship_type": string,
            "strength": score,
            "confidence": score,
        },
        "Meeting": common_child | {"version": {"type": "integer"}, "objective": string},
        "Briefing": {"content": json_object},
        "Decision": common_child | {"version": {"type": "integer"}, "rationale": string},
        "Task": common_child
        | {"version": {"type": "integer"}, "priority": string, "owner_user_id": uuid},
        "Insight": common_child
        | {"facts": json_array, "inferences": json_array, "recommendation": string},
        "Report": common_child | {"report_type": string, "template_key": string},
        "Evidence": {
            "signal_id": uuid,
            "extract": string,
            "source_url": string,
            "dossier_id": uuid,
            "locator": json_object,
            "classification": string,
            "provenance": json_object,
        },
        "Feedback": {
            "target_type": string,
            "target_id": uuid,
            "rating": {"type": "integer"},
            "correction": json_object,
            "comment": string,
        },
        "Collaborator": {
            "role": {"type": "string", "enum": ["owner", "editor", "collaborator", "viewer"]}
        },
        "LivingSummary": {
            "version": {"type": "integer", "minimum": 1},
            "summary": json_object,
        },
        "DossierSignal": schemas["SignalReviewInput"]["properties"],
    }
    for name, properties in write_properties.items():
        if name not in {"Collaborator", "DossierSignal"}:
            properties = properties | {"version": version}
        schemas[f"{name}WriteInput"] = write(properties)
    schemas["SignalMonitorCreateInput"] = write(
        {
            "connection_id": uuid,
            "query": string,
            "name": string,
            "cadence": {"type": "string", "enum": ["hourly", "daily", "weekly"]},
            "keywords": string_array,
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["company", "person", "topic"],
                        },
                        "name": string,
                    },
                    "required": ["type", "name"],
                },
            },
            "languages": string_array,
            "geographies": string_array,
            "source_types": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "news",
                        "social_signal",
                        "company_signal",
                        "official_publication",
                        "regulatory_signal",
                    ],
                },
            },
            "retention_days": {"type": "integer", "minimum": 1, "maximum": 3650},
        },
        ["connection_id", "query"],
    )
    schemas["SignalMonitorUpdateInput"] = write(
        {
            "query": string,
            "cadence": {"type": "string", "enum": ["hourly", "daily", "weekly"]},
            "keywords": string_array,
            "entities": schemas["SignalMonitorCreateInput"]["properties"]["entities"],
            "languages": string_array,
            "geographies": string_array,
            "source_types": schemas["SignalMonitorCreateInput"]["properties"]["source_types"],
            "retention_days": {"type": "integer", "minimum": 1, "maximum": 3650},
            "version": version,
        }
    )
    schemas["SignalMonitorCommandResponse"] = write(
        {
            "id": uuid,
            "monitor_id": uuid,
            "version": version,
            "desired_status": string,
            "outbox_event_id": uuid,
            "job_id": uuid,
            "status": string,
            "duplicate": {"type": "boolean"},
        }
    )
    schemas["DossierWriteInput"] = schemas["DossierPatchInput"]
    schemas["PromotionResponse"] = write(
        {
            "kind": {"type": "string", "enum": ["opportunity", "risk"]},
            "resource": {
                "oneOf": [
                    {"$ref": "#/components/schemas/OpportunityResource"},
                    {"$ref": "#/components/schemas/RiskResource"},
                ]
            },
        },
        ["kind", "resource"],
    )
    schemas["DossierSignalEnvelope"] = write(
        {
            "link": {"$ref": "#/components/schemas/DossierSignalResource"},
            "signal": {"$ref": "#/components/schemas/SignalResource"},
        },
        ["link", "signal"],
    )
    schemas["DossierReference"] = write(
        {"id": uuid, "title": string, "status": string},
        ["id", "title", "status"],
    )
    schemas["DossierIncludes"] = write(
        {
            "dossiers": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/DossierReference"},
            }
        },
        ["dossiers"],
    )
    schemas["GlobalSignalListResponse"] = write(
        {
            "data": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/DossierSignalEnvelope"},
            },
            "included": {"$ref": "#/components/schemas/DossierIncludes"},
            "meta": {"$ref": "#/components/schemas/PageMeta"},
        },
        ["data", "included", "meta"],
    )
    for global_name, resource_name in (
        ("GlobalOpportunityListResponse", "Opportunity"),
        ("GlobalRiskListResponse", "Risk"),
        ("GlobalMeetingListResponse", "Meeting"),
        ("GlobalTaskListResponse", "Task"),
    ):
        schemas[global_name] = write(
            {
                "data": {
                    "type": "array",
                    "items": {"$ref": f"#/components/schemas/{resource_name}Resource"},
                },
                "included": {"$ref": "#/components/schemas/DossierIncludes"},
                "meta": {"$ref": "#/components/schemas/PageMeta"},
            },
            ["data", "included", "meta"],
        )
    schemas["HomeMetric"] = write(
        {
            "key": string,
            "label": string,
            "count": {"type": "integer", "minimum": 0, "nullable": True},
            "href": string,
            "available": {"type": "boolean"},
        },
        ["key", "label", "count", "href", "available"],
    )
    schemas["HomeAttentionItem"] = write(
        {
            "kind": {
                "type": "string",
                "enum": ["signals", "opportunities", "risks", "meetings", "tasks"],
            },
            "id": uuid,
            "dossier_id": uuid,
            "dossier_title": string,
            "title": string,
            "status": string,
            "score": score | {"nullable": True},
            "due_at": {"type": "string", "nullable": True},
            "updated_at": {"type": "string", "format": "date-time"},
            "href": string,
        },
        [
            "kind",
            "id",
            "dossier_id",
            "dossier_title",
            "title",
            "status",
            "score",
            "due_at",
            "updated_at",
            "href",
        ],
    )
    schemas["HomeResponse"] = write(
        {
            "generated_at": {"type": "string", "format": "date-time"},
            "dossier_total": {"type": "integer", "minimum": 0},
            "metrics": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/HomeMetric"},
            },
            "attention": {
                "type": "array",
                "maxItems": 10,
                "items": {"$ref": "#/components/schemas/HomeAttentionItem"},
            },
        },
        ["generated_at", "dossier_total", "metrics", "attention"],
    )
    schemas["GlobalSearchResult"] = write(
        {
            "kind": {
                "type": "string",
                "enum": ["dossier", "actor", "signal", "opportunity", "document"],
            },
            "id": uuid,
            "title": string,
            "subtitle": string,
            "href": string,
            "dossier_id": nullable_uuid,
            "dossier_title": {"type": "string", "nullable": True},
        },
        ["kind", "id", "title", "subtitle", "href", "dossier_id", "dossier_title"],
    )
    search_results = {
        "type": "array",
        "items": {"$ref": "#/components/schemas/GlobalSearchResult"},
    }
    schemas["GlobalSearchGroups"] = write(
        {
            "dossiers": search_results,
            "actors": search_results,
            "signals": search_results,
            "opportunities": search_results,
            "documents": search_results,
        }
    )
    schemas["GlobalSearchResponse"] = write(
        {
            "query": string,
            "limit_per_group": {"type": "integer", "minimum": 1, "maximum": 10},
            "groups": {"$ref": "#/components/schemas/GlobalSearchGroups"},
            "items": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/GlobalSearchResult"},
            },
        },
        ["query", "limit_per_group", "groups", "items"],
    )
    schemas["ChangeItem"] = write(
        {
            "id": uuid,
            "dossier_id": uuid,
            "dossier_title": string,
            "resource_type": string,
            "resource_id": uuid,
            "from_status": string,
            "to_status": string,
            "reason": string,
            "actor_user_id": uuid,
            "occurred_at": {"type": "string", "format": "date-time"},
            "href": string,
        },
        [
            "id",
            "dossier_id",
            "dossier_title",
            "resource_type",
            "resource_id",
            "from_status",
            "to_status",
            "reason",
            "actor_user_id",
            "occurred_at",
            "href",
        ],
    )
    schemas["ChangeMeta"] = write(
        {
            "page": {"type": "integer", "minimum": 1},
            "size": {"type": "integer", "minimum": 1, "maximum": 50},
            "total": {"type": "integer", "minimum": 0},
            "review_supported": {"type": "boolean", "enum": [False]},
        },
        ["page", "size", "total", "review_supported"],
    )
    schemas["ChangeListResponse"] = write(
        {
            "data": {"type": "array", "items": {"$ref": "#/components/schemas/ChangeItem"}},
            "meta": {"$ref": "#/components/schemas/ChangeMeta"},
        },
        ["data", "meta"],
    )
    schemas["LinkMutationResponse"] = write(
        {"linked": {"type": "boolean", "enum": [True]}}, ["linked"]
    )
    schemas["AIRetriageInput"] = write({})
    schemas["AIJobEnqueueResponse"] = write(
        {
            "job_id": {"type": "string", "format": "uuid"},
            "status": {"type": "string"},
        },
        ["job_id", "status"],
    )
    schemas["CollaboratorResource"]["required"] = [
        "tenant_id",
        "dossier_id",
        "user_id",
        "role",
    ]
    return schemas


def _reporting_schemas() -> dict[str, Any]:
    uuid = {"type": "string", "format": "uuid"}
    nullable_uuid = {"type": "string", "format": "uuid", "nullable": True}
    date_time = {"type": "string", "format": "date-time", "nullable": True}
    string = {"type": "string"}
    json_object = {"$ref": "#/components/schemas/JsonObject"}

    def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required or [],
        }

    artifact = obj(
        {
            "id": uuid,
            "format": string,
            "status": string,
            "byte_size": {"type": "integer", "minimum": 0},
            "checksum": string,
            "media_type": string,
        },
        ["id", "format", "status", "byte_size", "checksum", "media_type"],
    )
    report = obj(
        {
            "id": uuid,
            "dossier_id": uuid,
            "title": string,
            "status": {
                "type": "string",
                "enum": [
                    "draft",
                    "generating",
                    "ready",
                    "reviewed",
                    "published",
                    "failed",
                    "superseded",
                ],
            },
            "report_type": string,
            "template_key": string,
            "template_version": string,
            "generation_version": {"type": "integer", "minimum": 1},
            "classification": {"type": "string", "enum": ["public", "internal"]},
            "confidentiality_label": string,
            "job_id": nullable_uuid,
            "parent_report_id": nullable_uuid,
            "ready_at": date_time,
            "reviewed_at": date_time,
            "published_at": date_time,
            "error_code": {"type": "string", "nullable": True},
            "version": {"type": "integer", "minimum": 1},
            "revision": {"oneOf": [json_object, {"type": "null"}]},
            "artifacts": {"type": "array", "items": artifact},
            "reviews": {"type": "array", "items": json_object},
            "evidence": {"type": "array", "items": json_object},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
        [
            "id",
            "dossier_id",
            "title",
            "status",
            "template_key",
            "template_version",
            "generation_version",
            "version",
            "artifacts",
        ],
    )
    notification = obj(
        {
            "id": uuid,
            "type": string,
            "severity": {"type": "string", "enum": ["info", "success", "warning", "critical"]},
            "title": string,
            "body": string,
            "link": {"type": "string", "nullable": True},
            "read_at": date_time,
            "dismissed_at": date_time,
            "expires_at": date_time,
            "resource_type": {"type": "string", "nullable": True},
            "resource_id": nullable_uuid,
            "created_at": {"type": "string", "format": "date-time"},
        },
        ["id", "type", "severity", "title", "body", "created_at"],
    )
    preference = obj(
        {
            "id": uuid,
            "notification_type": string,
            "channels": obj(
                {"in_app": {"type": "boolean"}, "email": {"type": "boolean"}}, ["in_app", "email"]
            ),
            "digest_cadence": {"type": "string", "enum": ["instant", "daily", "weekly", "off"]},
            "timezone": string,
            "local_time": string,
            "weekday": {"type": "integer", "minimum": 0, "maximum": 6, "nullable": True},
            "quiet_hours_start": {"type": "string", "nullable": True},
            "quiet_hours_end": {"type": "string", "nullable": True},
            "minimum_severity": string,
            "security_locked": {"type": "boolean"},
            "version": {"type": "integer", "minimum": 1},
        },
        ["id", "notification_type", "channels", "digest_cadence", "timezone", "version"],
    )
    export = obj(
        {
            "id": uuid,
            "dataset": string,
            "format": {"type": "string", "enum": ["csv"]},
            "status": {
                "type": "string",
                "enum": ["queued", "generating", "ready", "failed", "expired", "purged"],
            },
            "dossier_id": nullable_uuid,
            "job_id": nullable_uuid,
            "filters": json_object,
            "columns": {"type": "array", "items": string},
            "watermark": string,
            "byte_size": {"type": "integer", "nullable": True},
            "checksum": {"type": "string", "nullable": True},
            "expires_at": date_time,
            "error_code": {"type": "string", "nullable": True},
            "version": {"type": "integer", "minimum": 1},
            "created_at": {"type": "string", "format": "date-time"},
            "updated_at": {"type": "string", "format": "date-time"},
        },
        ["id", "dataset", "format", "status", "filters", "columns", "version"],
    )
    return {
        "ReportTemplate": obj(
            {
                "key": string,
                "version": string,
                "label": string,
                "report_type": string,
                "input_contract": json_object,
                "sections": {"type": "array", "items": string},
                "evidence_policy": string,
                "output_schema": string,
                "permissions": json_object,
                "formats": {"type": "array", "items": string},
                "changelog": {"type": "array", "items": string},
                "sha256": string,
            },
            ["key", "version", "label", "sections", "evidence_policy", "formats", "sha256"],
        ),
        "ReportTemplateListResponse": obj(
            {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/ReportTemplate"},
                },
                "capabilities": obj({"pdf": {"type": "boolean"}}, ["pdf"]),
            },
            ["items", "capabilities"],
        ),
        "ReportResponse": report,
        "ReportListResponse": obj(
            {
                "data": {"type": "array", "items": {"$ref": "#/components/schemas/ReportResponse"}},
                "meta": {"$ref": "#/components/schemas/PageMeta"},
            },
            ["data", "meta"],
        ),
        "ReportGenerateInput": obj(
            {"template_key": string, "options": json_object}, ["template_key"]
        ),
        "ReportRevisionInput": obj(
            {
                "version": {"type": "integer", "minimum": 1},
                "content": json_object,
                "change_summary": string,
            },
            ["version", "content", "change_summary"],
        ),
        "ReportReviewInput": obj(
            {
                "version": {"type": "integer", "minimum": 1},
                "revision_id": uuid,
                "decision": {
                    "type": "string",
                    "enum": ["approved", "changes_requested", "comment"],
                },
                "comment": string,
            },
            ["version", "revision_id", "decision"],
        ),
        "ReportPublishInput": obj({"version": {"type": "integer", "minimum": 1}}, ["version"]),
        "ReportEnqueueResponse": obj(
            {
                "report": {"$ref": "#/components/schemas/ReportResponse"},
                "job_id": uuid,
                "replayed": {"type": "boolean"},
            },
            ["report", "job_id", "replayed"],
        ),
        "ReportReviewResponse": obj(
            {"review_id": uuid, "report": {"$ref": "#/components/schemas/ReportResponse"}},
            ["review_id", "report"],
        ),
        "DownloadLinkResponse": obj(
            {"url": string, "expires_at": {"type": "string", "format": "date-time"}},
            ["url", "expires_at"],
        ),
        "NotificationResponse": notification,
        "NotificationListResponse": obj(
            {
                "data": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/NotificationResponse"},
                },
                "meta": obj(
                    {
                        "page": {"type": "integer"},
                        "size": {"type": "integer"},
                        "total": {"type": "integer"},
                        "unread_count": {"type": "integer"},
                    },
                    ["page", "size", "total", "unread_count"],
                ),
            },
            ["data", "meta"],
        ),
        "NotificationReadAllResponse": obj(
            {"updated": {"type": "integer"}, "unread_count": {"type": "integer"}},
            ["updated", "unread_count"],
        ),
        "NotificationPreferenceResponse": preference,
        "NotificationPreferenceListResponse": obj(
            {
                "items": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/NotificationPreferenceResponse"},
                }
            },
            ["items"],
        ),
        "NotificationPreferenceInput": obj(
            {
                "notification_type": string,
                "channels": obj(
                    {"in_app": {"type": "boolean"}, "email": {"type": "boolean"}},
                    ["in_app", "email"],
                ),
                "digest_cadence": {"type": "string", "enum": ["instant", "daily", "weekly", "off"]},
                "timezone": string,
                "local_time": string,
                "weekday": {"type": "integer", "minimum": 0, "maximum": 6, "nullable": True},
                "quiet_hours_start": {"type": "string", "nullable": True},
                "quiet_hours_end": {"type": "string", "nullable": True},
                "minimum_severity": string,
                "version": {"type": "integer", "minimum": 1},
            },
            ["notification_type", "channels", "digest_cadence", "timezone", "local_time"],
        ),
        "AlertPolicyResponse": obj(
            {
                "id": uuid,
                "scope": {"type": "string", "enum": ["tenant", "dossier"]},
                "inherited": {"type": "boolean"},
                "dossier_id": nullable_uuid,
                "signal_score_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
                "risk_score_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
                "opportunity_deadline_days": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 365,
                },
                "meeting_upcoming_hours": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 720,
                },
                "cooldown_minutes": {"type": "integer", "minimum": 0, "maximum": 10080},
                "enabled_types": json_object,
                "severity_map": json_object,
                "quiet_hours_start": {"type": "string", "nullable": True},
                "quiet_hours_end": {"type": "string", "nullable": True},
                "timezone": string,
                "version": {"type": "integer", "minimum": 1},
            },
            [
                "id",
                "scope",
                "inherited",
                "dossier_id",
                "signal_score_threshold",
                "risk_score_threshold",
                "opportunity_deadline_days",
                "meeting_upcoming_hours",
                "cooldown_minutes",
                "enabled_types",
                "severity_map",
                "timezone",
                "version",
            ],
        ),
        "AlertPolicyInput": obj(
            {
                "version": {"type": "integer", "minimum": 1},
                "signal_score_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
                "risk_score_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
                "opportunity_deadline_days": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 365,
                },
                "meeting_upcoming_hours": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 720,
                },
                "cooldown_minutes": {"type": "integer", "minimum": 0, "maximum": 10080},
                "enabled_types": json_object,
                "severity_map": json_object,
                "quiet_hours_start": {"type": "string", "nullable": True},
                "quiet_hours_end": {"type": "string", "nullable": True},
                "timezone": string,
            },
            ["version"],
        ),
        "ExportResponse": export,
        "ExportListResponse": obj(
            {
                "data": {"type": "array", "items": {"$ref": "#/components/schemas/ExportResponse"}},
                "meta": {"$ref": "#/components/schemas/PageMeta"},
            },
            ["data", "meta"],
        ),
        "ExportCreateInput": obj(
            {
                "dataset": {
                    "type": "string",
                    "enum": [
                        "signals",
                        "opportunities",
                        "risks",
                        "actors",
                        "tasks",
                        "reports",
                        "audit",
                    ],
                },
                "dossier_id": nullable_uuid,
                "columns": {"type": "array", "items": string, "maxItems": 30},
                "filters": json_object,
            },
            ["dataset"],
        ),
        "ExportEnqueueResponse": obj(
            {
                "export": {"$ref": "#/components/schemas/ExportResponse"},
                "job_id": uuid,
                "replayed": {"type": "boolean"},
            },
            ["export", "job_id", "replayed"],
        ),
    }


def _declare_reporting_operation(
    path: str, method: str, operation: dict[str, Any], problem_content: dict[str, Any]
) -> None:
    response_map: dict[tuple[str, str], tuple[str, str | None]] = {
        ("/api/v1/report-templates", "get"): ("200", "ReportTemplateListResponse"),
        ("/api/v1/reports", "get"): ("200", "ReportListResponse"),
        ("/api/v1/dossiers/{dossier_id}/reports", "get"): ("200", "ReportListResponse"),
        ("/api/v1/dossiers/{dossier_id}/reports", "post"): ("202", "ReportEnqueueResponse"),
        ("/api/v1/reports/{resource_id}", "get"): ("200", "ReportResponse"),
        ("/api/v1/reports/{report_id}/retry", "post"): ("202", "ReportEnqueueResponse"),
        ("/api/v1/reports/{report_id}/revisions", "post"): ("201", "ReportResponse"),
        ("/api/v1/reports/{report_id}/reviews", "post"): ("201", "ReportReviewResponse"),
        ("/api/v1/reports/{report_id}/publish", "post"): ("200", "ReportResponse"),
        ("/api/v1/reports/{report_id}/artifacts/{artifact_id}/download-link", "post"): (
            "200",
            "DownloadLinkResponse",
        ),
        ("/api/v1/notifications", "get"): ("200", "NotificationListResponse"),
        ("/api/v1/notifications/{notification_id}/read", "post"): ("200", "NotificationResponse"),
        ("/api/v1/notifications/read-all", "post"): ("200", "NotificationReadAllResponse"),
        ("/api/v1/notifications/{notification_id}/dismiss", "post"): (
            "200",
            "NotificationResponse",
        ),
        ("/api/v1/notification-preferences", "get"): ("200", "NotificationPreferenceListResponse"),
        ("/api/v1/notification-preferences", "patch"): ("200", "NotificationPreferenceResponse"),
        ("/api/v1/dossiers/{dossier_id}/alert-policy", "get"): ("200", "AlertPolicyResponse"),
        ("/api/v1/dossiers/{dossier_id}/alert-policy", "patch"): ("200", "AlertPolicyResponse"),
        ("/api/v1/alert-policy", "get"): ("200", "AlertPolicyResponse"),
        ("/api/v1/alert-policy", "patch"): ("200", "AlertPolicyResponse"),
        ("/api/v1/exports", "get"): ("200", "ExportListResponse"),
        ("/api/v1/exports", "post"): ("202", "ExportEnqueueResponse"),
        ("/api/v1/exports/{export_id}", "get"): ("200", "ExportResponse"),
        ("/api/v1/exports/{export_id}/download-link", "post"): ("200", "DownloadLinkResponse"),
    }
    request_map = {
        ("/api/v1/dossiers/{dossier_id}/reports", "post"): "ReportGenerateInput",
        ("/api/v1/reports/{report_id}/revisions", "post"): "ReportRevisionInput",
        ("/api/v1/reports/{report_id}/reviews", "post"): "ReportReviewInput",
        ("/api/v1/reports/{report_id}/publish", "post"): "ReportPublishInput",
        ("/api/v1/notification-preferences", "patch"): "NotificationPreferenceInput",
        ("/api/v1/dossiers/{dossier_id}/alert-policy", "patch"): "AlertPolicyInput",
        ("/api/v1/alert-policy", "patch"): "AlertPolicyInput",
        ("/api/v1/exports", "post"): "ExportCreateInput",
    }
    response = response_map.get((path, method))
    if response:
        status, schema = response
        for candidate in tuple(operation.setdefault("responses", {})):
            if candidate.startswith("2"):
                operation["responses"].pop(candidate, None)
        operation["responses"][status] = {
            "description": "Operación completada",
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
        }
    request_schema = request_map.get((path, method))
    if request_schema:
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": f"#/components/schemas/{request_schema}"}}
            },
        }
    if (path, method) in {
        ("/api/v1/dossiers/{dossier_id}/reports", "post"),
        ("/api/v1/reports/{report_id}/retry", "post"),
        ("/api/v1/exports", "post"),
    }:
        _upsert_parameter(
            operation,
            {
                "name": "Idempotency-Key",
                "in": "header",
                "required": True,
                "schema": {"type": "string", "minLength": 8, "maxLength": 200},
            },
        )
        operation.setdefault("responses", {}).setdefault(
            "409", _problem("Conflicto de idempotencia", problem_content)
        )
    if path.endswith("/download") and path.startswith(
        ("/api/v1/report-artifacts/", "/api/v1/export-artifacts/")
    ):
        operation["responses"]["200"] = {
            "description": "Artefacto autorizado",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
