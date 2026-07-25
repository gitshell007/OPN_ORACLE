from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from opn_oracle.extensions import db
from opn_oracle.jobs import service as jobs_service
from opn_oracle.jobs.tasks import execute_durable, investigation_run
from opn_oracle.oracle import investigations
from opn_oracle.oracle.investigations import (
    ProcurementParticipation,
    ResearchClaim,
    ResearchEntity,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.tenants.context import TenantContext, tenant_context
from tests.test_integration_oracle_domain import _client, _create_dossier, _csrf
from tests.test_integration_oracle_domain import (
    oracle_stack as _oracle_stack_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


@pytest.fixture
def oracle_stack(
    request: pytest.FixtureRequest,
) -> tuple[Any, dict[str, uuid.UUID], str]:
    return request.getfixturevalue("_oracle_stack_fixture")


def test_investigation_workbench_human_gate_job_and_report_preview(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, ids, _ = oracle_stack
    client = _client(oracle_stack)
    dossier = _create_dossier(client, ids, "Investigacion empresarial trazable")

    monkeypatch.setattr(jobs_service, "publish_job", lambda job: None)
    monkeypatch.setattr(
        investigations, "resolve_signal_external_tenant_id_for_tenant", lambda _: None
    )
    monkeypatch.setattr(
        investigations,
        "cached_graph",
        lambda **_: {
            "nodes": [
                {"id": "seed", "name": "ITURRI SA", "type": "company", "depth": 0},
                {"id": "manager", "name": "ITURRI FRANCO JUAN FRANCISCO", "type": "person"},
                {"id": "linked", "name": "ITURRI PARTICIPADAS SL", "type": "company"},
            ],
            "edges": [
                {
                    "source": "seed",
                    "target": "manager",
                    "role": "administrador",
                    "role_keys": ["registry_officer"],
                },
                {
                    "source": "manager",
                    "target": "linked",
                    "role": "administrador",
                    "role_keys": ["registry_officer"],
                },
            ],
            "truncated": False,
        },
    )
    monkeypatch.setattr(
        investigations,
        "cached_awards",
        lambda **_: {
            "items": [
                {
                    "folder_id": "PLACSP-2026-0001",
                    "lot_id": "1",
                    "winner_identifier": "A00000000",
                    "received_tender_quantity": 3,
                },
                {
                    "folder_id": "PLACSP-2026-0002",
                    "lot_id": "",
                    "winner_identifier": "A00000000",
                    "received_tender_quantity": "no-es-entero",
                },
            ]
        },
    )

    key = f"investigation-create-{uuid.uuid4()}"
    created = client.post(
        f"/api/v1/dossiers/{dossier['id']}/investigations",
        json={
            "question": "Investigar nexos empresariales y adjudicaciones relacionadas.",
            "seed_name": "ITURRI SA",
            "seed_kind": "company",
            "limits": {"max_depth": 2, "max_entities": 20},
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert created.status_code == 201, created.get_json()
    first_payload = created.get_json()
    assert first_payload["status"] == "awaiting_review"
    assert first_payload["counts"]["entities"] == 1

    replay = client.post(
        f"/api/v1/dossiers/{dossier['id']}/investigations",
        json={
            "question": "Otro texto ignorado por idempotencia.",
            "seed_name": "Otra SA",
            "seed_kind": "company",
        },
        headers={"X-CSRF-Token": _csrf(client), "Idempotency-Key": key},
    )
    assert replay.status_code == 201
    assert replay.get_json()["id"] == first_payload["id"]

    blocked = client.post(
        f"/api/v1/investigations/{first_payload['id']}/execute",
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"investigation-blocked-{uuid.uuid4()}",
        },
    )
    assert blocked.status_code == 409

    seed_id = first_payload["entities"][0]["id"]
    reviewed = client.post(
        f"/api/v1/investigations/{first_payload['id']}/entities/{seed_id}/reviews",
        json={"decision": "verify"},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert reviewed.status_code == 200, reviewed.get_json()
    assert reviewed.get_json()["status"] == "ready"

    queued = client.post(
        f"/api/v1/investigations/{first_payload['id']}/execute",
        headers={
            "X-CSRF-Token": _csrf(client),
            "Idempotency-Key": f"investigation-run-{uuid.uuid4()}",
        },
    )
    assert queued.status_code == 202, queued.get_json()
    job = queued.get_json()["job"]

    with app.app_context():
        executed = execute_durable(
            investigation_run,
            job_id=job["id"],
            tenant_id=str(ids["tenant_a"]),
            payload={"run_id": first_payload["id"]},
        )
        assert executed["status"] == "awaiting_review"
        with tenant_context(TenantContext(tenant_id=ids["tenant_a"], actor_id=ids["user"])):
            assert (
                db.session.scalar(
                    select(ResearchEntity).where(
                        ResearchEntity.run_id == uuid.UUID(first_payload["id"])
                    )
                )
                is not None
            )
            assert (
                db.session.scalar(
                    select(ProcurementParticipation).where(
                        ProcurementParticipation.run_id == uuid.UUID(first_payload["id"]),
                        ProcurementParticipation.received_tender_quantity == 3,
                    )
                )
                is not None
            )
            invalid_counter = db.session.scalar(
                select(ProcurementParticipation).where(
                    ProcurementParticipation.run_id == uuid.UUID(first_payload["id"]),
                    ProcurementParticipation.folder_id == "PLACSP-2026-0002",
                )
            )
            assert invalid_counter is not None
            assert invalid_counter.received_tender_quantity is None
            assert (
                db.session.scalar(
                    select(ResearchClaim).where(
                        ResearchClaim.run_id == uuid.UUID(first_payload["id"]),
                        ResearchClaim.claim_kind == "limitation",
                    )
                )
                is not None
            )
            assert db.session.get(BackgroundJob, uuid.UUID(job["id"])).status == "succeeded"

    fetched = client.get(f"/api/v1/investigations/{first_payload['id']}")
    assert fetched.status_code == 200
    fetched_payload = fetched.get_json()
    assert fetched_payload["counts"]["relations"] == 2
    assert fetched_payload["counts"]["procurement_participations"] == 2
    assert fetched_payload["procurement_participations"][0]["role"] == "awardee"

    report = client.get(f"/api/v1/investigations/{first_payload['id']}/report-preview")
    assert report.status_code == 200
    markdown = report.get_json()["report"]["markdown"]
    assert "La identidad de licitadores no adjudicatarios no se infiere" in markdown
    assert "PLACSP-2026-0001" in markdown


def test_actor_alias_candidates_are_organization_only_and_do_not_mutate(
    oracle_stack: tuple[Any, dict[str, uuid.UUID], str],
) -> None:
    client = _client(oracle_stack)
    csrf = _csrf(client)
    for payload in (
        {"canonical_name": "ITURRI SA", "actor_type": "organization"},
        {"canonical_name": "Iturri", "actor_type": "organization"},
        {"canonical_name": "ITURRI SL", "actor_type": "person"},
        {"canonical_name": "ITURRI FRANCO JUAN FRANCISCO", "actor_type": "person"},
    ):
        created = client.post("/api/v1/actors", json=payload, headers={"X-CSRF-Token": csrf})
        assert created.status_code == 201, created.get_json()

    response = client.get("/api/v1/actors/alias-candidates")
    assert response.status_code == 200
    candidates = response.get_json()["items"]
    iturri = next(item for item in candidates if item["identity_key"] == "ITURRI")
    assert {actor["name"] for actor in iturri["actors"]} == {"ITURRI SA", "Iturri"}
    assert all(actor["name"] != "ITURRI SL" for actor in iturri["actors"])
    assert all(actor["name"] != "ITURRI FRANCO JUAN FRANCISCO" for actor in iturri["actors"])

    repeated = client.get("/api/v1/actors/alias-candidates")
    assert repeated.status_code == 200
    assert repeated.get_json()["items"] == candidates
