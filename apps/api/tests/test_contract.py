from __future__ import annotations

from typing import Any

import pytest
from flask import Flask


def assert_problem(response: Any, status: int) -> dict[str, Any]:
    body = response.get_json()
    assert response.status_code == status
    assert response.content_type == "application/problem+json"
    assert body["status"] == status
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["instance"].startswith("/")
    return body


ORACLE_PATH_MARKERS = (
    "/home",
    "/changes",
    "/search",
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
)


def _oracle_operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, path_item in spec["paths"].items()
        if path.startswith("/api/v1/") and any(marker in path for marker in ORACLE_PATH_MARKERS)
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]


def _assert_closed_schema_tree(node: Any, schemas: dict[str, Any], visited_refs: set[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _assert_closed_schema_tree(item, schemas, visited_refs)
        return
    if not isinstance(node, dict):
        return
    reference = node.get("$ref")
    if reference:
        prefix = "#/components/schemas/"
        assert reference.startswith(prefix)
        name = reference.removeprefix(prefix)
        assert name in schemas
        if name not in visited_refs:
            visited_refs.add(name)
            _assert_closed_schema_tree(schemas[name], schemas, visited_refs)
        return
    if node.get("type") == "object":
        assert "additionalProperties" in node
        assert node["additionalProperties"] is False or isinstance(
            node["additionalProperties"], dict
        )
    for value in node.values():
        _assert_closed_schema_tree(value, schemas, visited_refs)


@pytest.mark.unit
def test_meta_contract(client: Any) -> None:
    response = client.get("/api/v1/meta")
    assert response.status_code == 200
    assert response.get_json() == {
        "name": "OPN Oracle API",
        "version": "0.1.0",
        "release": "development",
        "environment": "test",
        "capabilities": ["health", "openapi"],
    }


@pytest.mark.unit
def test_404_problem(client: Any) -> None:
    assert_problem(client.get("/missing"), 404)


@pytest.mark.unit
def test_405_problem(client: Any) -> None:
    assert_problem(client.post("/health/live"), 405)


@pytest.mark.unit
def test_422_validation_problem(client: Any) -> None:
    body = assert_problem(client.get("/api/v1/meta?verbose=not-a-boolean"), 422)
    assert body["code"] == "validation_error"
    assert body["errors"]


@pytest.mark.unit
def test_openapi_is_generated(app: Flask, client: Any) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    spec = response.get_json()
    assert spec["openapi"].startswith("3.0")
    assert "/api/v1/meta" in spec["paths"]
    assert "/health/live" in spec["paths"]
    assert "Problem" in spec["components"]["schemas"]
    validation = spec["paths"]["/api/v1/meta"]["get"]["responses"]["422"]
    assert set(validation["content"]) == {"application/problem+json"}
    assert validation["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/Problem"
    }
    readiness = spec["paths"]["/health/ready"]["get"]["responses"]["503"]
    assert "application/json" in readiness["content"]
    me_schema = spec["components"]["schemas"]["MeResponse"]
    assert me_schema["properties"]["user"] == {"$ref": "#/components/schemas/SessionUserResponse"}
    assert me_schema["properties"]["memberships"]["items"] == {
        "$ref": "#/components/schemas/MembershipSummaryResponse"
    }
    assert "active_tenant_id" in me_schema["required"]
    tenant_selection = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["409"]
    assert tenant_selection["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/TenantSelectionProblem"
    }
    for path_item in spec["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            internal_error = operation["responses"]["500"]
            assert set(internal_error["content"]) == {"application/problem+json"}
    assert app.spec["info"]["title"] == "OPN Oracle API"


@pytest.mark.unit
def test_oracle_openapi_contract_is_typed(client: Any) -> None:
    spec = client.get("/api/v1/openapi.json").get_json()
    required_paths = {
        "/api/v1/home",
        "/api/v1/changes",
        "/api/v1/changes/digest",
        "/api/v1/search",
        "/api/v1/signals",
        "/api/v1/opportunities",
        "/api/v1/risks",
        "/api/v1/meetings",
        "/api/v1/tasks",
        "/api/v1/dossiers",
        "/api/v1/dossiers/{dossier_id}",
        "/api/v1/signals/{link_id}/review",
        "/api/v1/signals/{link_id}/promote",
        "/api/v1/relationships",
        "/api/v1/feedback",
        "/api/v1/evidence",
        "/api/v1/actors/{target_id}/merge",
        "/api/v1/watchlists/{watchlist_id}/monitors",
        "/api/v1/meetings/{meeting_id}/briefings",
        "/api/v1/meetings/{meeting_id}/briefing-state",
        "/api/v1/objectives/{resource_id}",
        "/api/v1/hypotheses/{resource_id}",
        "/api/v1/signal-monitors/{monitor_id}",
        "/api/v1/decisions/{resource_id}",
        "/api/v1/dossier-actors/{resource_id}",
        "/api/v1/dossiers/{dossier_id}/living-summary",
        "/api/v1/dossiers/{dossier_id}/status-history",
        "/api/v1/opportunities/{resource_id}/actors",
        "/api/v1/opportunities/{resource_id}/actors/{target_id}",
        "/api/v1/dossiers/{dossier_id}/actor-candidates",
        "/api/v1/dossiers/{dossier_id}/actor-candidates/{candidate_id}/import",
        "/api/v1/dossiers/{dossier_id}/actor-candidates/{candidate_id}/review",
    }
    assert required_paths.issubset(spec["paths"])
    expected_global_responses = {
        "/api/v1/home": "HomeResponse",
        "/api/v1/changes": "ChangeListResponse",
        "/api/v1/search": "GlobalSearchResponse",
        "/api/v1/signals": "GlobalSignalListResponse",
        "/api/v1/opportunities": "GlobalOpportunityListResponse",
        "/api/v1/risks": "GlobalRiskListResponse",
        "/api/v1/meetings": "GlobalMeetingListResponse",
        "/api/v1/tasks": "GlobalTaskListResponse",
    }
    for path, schema_name in expected_global_responses.items():
        assert spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ] == {"$ref": f"#/components/schemas/{schema_name}"}
    assert spec["paths"]["/api/v1/dossiers"]["post"]["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/DossierCreateInput"}
    bulk_delete = spec["paths"]["/api/v1/dossiers/bulk-delete"]["post"]
    assert bulk_delete["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DossierBulkDeleteInput"
    }
    assert bulk_delete["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/DossierBulkDeleteResponse"
    }
    assert spec["paths"]["/api/v1/signals/{link_id}/promote"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/SignalPromoteInput"}
    assert "409" in spec["paths"]["/api/v1/dossiers/{dossier_id}"]["patch"]["responses"]
    schemas = spec["components"]["schemas"]
    assert "OracleResource" not in schemas
    assert "OracleWriteInput" not in schemas
    for name in (
        "DossierResource",
        "OpportunityResource",
        "RiskResource",
        "ActorResource",
        "EvidenceResource",
    ):
        assert schemas[name]["additionalProperties"] is False
    opportunity_input = spec["paths"]["/api/v1/dossiers/{dossier_id}/opportunities"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert opportunity_input == {"$ref": "#/components/schemas/OpportunityWriteInput"}
    assert spec["components"]["schemas"]["DossierSignalResource"]["properties"]["scoring_state"][
        "enum"
    ] == ["pending", "provisional", "reviewed"]
    actor_candidates = spec["paths"]["/api/v1/dossiers/{dossier_id}/actor-candidates"]
    assert any(
        parameter["name"] == "include_dismissed"
        for parameter in actor_candidates["get"]["parameters"]
    )
    actor_candidate_review = spec["paths"][
        "/api/v1/dossiers/{dossier_id}/actor-candidates/{candidate_id}/review"
    ]["post"]
    assert actor_candidate_review["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ActorCandidateReviewInput"
    }
    assert actor_candidate_review["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ActorCandidateReviewResponse"
    }

    expected_write_schemas = {
        "/api/v1/objectives/{resource_id}": "ObjectiveWriteInput",
        "/api/v1/hypotheses/{resource_id}": "HypothesisWriteInput",
        "/api/v1/signal-monitors/{monitor_id}": "SignalMonitorUpdateInput",
        "/api/v1/decisions/{resource_id}": "DecisionWriteInput",
        "/api/v1/dossier-actors/{resource_id}": "DossierActorWriteInput",
    }
    for path, schema_name in expected_write_schemas.items():
        body_schema = spec["paths"][path]["patch"]["requestBody"]["content"]["application/json"][
            "schema"
        ]
        assert body_schema == {"$ref": f"#/components/schemas/{schema_name}"}

    signal_create = spec["paths"]["/api/v1/dossiers/{dossier_id}/signal-monitors"]["post"]
    assert signal_create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMonitorCreateInput"
    }
    for operation in (
        signal_create,
        spec["paths"]["/api/v1/signal-monitors/{monitor_id}"]["patch"],
        spec["paths"]["/api/v1/signal-monitors/{monitor_id}/{action}"]["post"],
    ):
        assert any(
            parameter["name"] == "Idempotency-Key" and parameter["required"] is True
            for parameter in operation["parameters"]
        )

    for action in ("cancel", "retry"):
        operation = spec["paths"][f"/api/v1/jobs/{{job_id}}/{action}"]["post"]
        assert any(
            parameter["name"] == "If-Match" and parameter["required"] is True
            for parameter in operation["parameters"]
        )
        assert {"409", "428"}.issubset(operation["responses"])
        assert operation["responses"]["202"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/JobResponse"
        }

    monitor_create = spec["paths"]["/api/v1/watchlists/{watchlist_id}/monitors"]["post"]
    assert monitor_create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMonitorWriteInput"
    }
    assert monitor_create["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMonitorResource"
    }
    briefing_create = spec["paths"]["/api/v1/meetings/{meeting_id}/briefings"]["post"]
    assert briefing_create["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BriefingWriteInput"
    }
    assert briefing_create["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MeetingBriefingGenerationResponse"
    }
    living_summary = spec["paths"]["/api/v1/dossiers/{dossier_id}/living-summary"]
    assert living_summary["put"]["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LivingSummaryWriteInput"
    }
    assert {status for status in living_summary["put"]["responses"] if status.startswith("2")} == {
        "200",
        "201",
    }
    oracle_refresh = spec["paths"]["/api/v1/dossiers/{dossier_id}/oracle-summary/refresh"]["post"]
    assert any(
        parameter["name"] == "Idempotency-Key" and parameter["required"] is True
        for parameter in oracle_refresh["parameters"]
    )

    status_history = spec["paths"]["/api/v1/dossiers/{dossier_id}/status-history"]["get"]
    assert status_history["responses"]["200"]["content"]["application/json"]["schema"][
        "properties"
    ]["data"]["items"] == {"$ref": "#/components/schemas/StatusHistoryResource"}

    m2m_expectations = {
        "/api/v1/opportunities/{resource_id}/actors": "ActorResource",
        "/api/v1/opportunities/{resource_id}/evidence": "EvidenceResource",
        "/api/v1/opportunities/{resource_id}/signals": "SignalResource",
        "/api/v1/risks/{resource_id}/actors": "ActorResource",
        "/api/v1/meetings/{resource_id}/evidence": "EvidenceResource",
        "/api/v1/hypotheses/{resource_id}/evidence": "EvidenceResource",
        "/api/v1/decisions/{resource_id}/evidence": "EvidenceResource",
    }
    for path, item_schema in m2m_expectations.items():
        list_schema = spec["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        assert list_schema["properties"]["data"]["items"] == {
            "$ref": f"#/components/schemas/{item_schema}"
        }
        mutation = spec["paths"][f"{path}/{{target_id}}"]["put"]
        assert "requestBody" not in mutation
        assert mutation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/LinkMutationResponse"
        }

    dossier_parameters = {
        (parameter["in"], parameter["name"])
        for parameter in spec["paths"]["/api/v1/dossiers"]["get"]["parameters"]
    }
    assert {
        ("query", "page[number]"),
        ("query", "page[size]"),
        ("query", "sort"),
        ("query", "filter[status]"),
        ("query", "filter[type]"),
        ("query", "filter[owner]"),
        ("query", "filter[search]"),
        ("query", "filter[selected_ids]"),
        ("query", "filter[date_from]"),
        ("query", "filter[date_to]"),
        ("query", "filter[score_min]"),
        ("query", "filter[score_max]"),
    }.issubset(dossier_parameters)

    generic_parameters = {
        (parameter["in"], parameter["name"])
        for parameter in spec["paths"]["/api/v1/dossiers/{dossier_id}/opportunities"]["get"][
            "parameters"
        ]
    }
    assert {
        ("query", "filter[selected_ids]"),
        ("query", "filter[type]"),
        ("query", "filter[owner]"),
        ("query", "filter[date_from]"),
        ("query", "filter[date_to]"),
        ("query", "filter[score_min]"),
        ("query", "filter[score_max]"),
    }.issubset(generic_parameters)

    evidence_resource = schemas["EvidenceResource"]
    assert "dossier_id" not in evidence_resource["properties"]
    assert "dossier_id" in schemas["EvidenceWriteInput"]["properties"]

    operations = _oracle_operations(spec)
    assert operations
    for path, method, operation in operations:
        success_responses = {
            status: response
            for status, response in operation["responses"].items()
            if status.startswith("2")
        }
        assert success_responses, (path, method)
        for status, response in success_responses.items():
            if status == "204":
                assert "content" not in response
                continue
            schema = response.get("content", {}).get("application/json", {}).get("schema")
            assert schema, (path, method, status)
            _assert_closed_schema_tree(schema, schemas, set())

        bodyless_m2m_put = method == "put" and path.endswith("/{target_id}")
        bodyless_monitor_action = (
            method == "post" and path == "/api/v1/signal-monitors/{monitor_id}/{action}"
        )
        if (
            method in {"post", "put", "patch"}
            and not path.endswith("/archive")
            and not bodyless_m2m_put
            and not bodyless_monitor_action
        ):
            body_schema = (
                operation.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            assert body_schema, (path, method)
            _assert_closed_schema_tree(body_schema, schemas, set())

        if method == "patch":
            if_match = [
                parameter
                for parameter in operation["parameters"]
                if parameter["in"] == "header" and parameter["name"] == "If-Match"
            ]
            assert len(if_match) == 1, (path, method)
            body_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
            write_schema = schemas[body_ref.removeprefix("#/components/schemas/")]
            assert "version" in write_schema["properties"], (path, method)

    collaborator_delete = spec["paths"]["/api/v1/dossiers/{dossier_id}/collaborators/{user_id}"][
        "delete"
    ]
    assert set(status for status in collaborator_delete["responses"] if status.startswith("2")) == {
        "204"
    }


@pytest.mark.unit
def test_jobs_openapi_contract_is_typed(client: Any) -> None:
    spec = client.get("/api/v1/openapi.json").get_json()
    schemas = spec["components"]["schemas"]
    assert schemas["JobResponse"]["additionalProperties"] is False
    expected = {
        ("/api/v1/jobs", "get", "200", "JobListResponse"),
        ("/api/v1/jobs/{job_id}", "get", "200", "JobResponse"),
        ("/api/v1/jobs/{job_id}/cancel", "post", "202", "JobResponse"),
        ("/api/v1/jobs/{job_id}/retry", "post", "202", "JobResponse"),
    }
    for path, method, status, schema_name in expected:
        operation = spec["paths"][path][method]
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{schema_name}"
        }
        assert operation["security"] == [{"cookieAuth": []}]
