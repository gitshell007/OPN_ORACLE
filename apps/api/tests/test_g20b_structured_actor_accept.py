"""G-20-B Oracle: structured candidate snapshot, durable IDs on accept, CAS, reject.

Unit/ORM tests (SQLite). PostgreSQL integration reuses G-19 fixture when available.
"""
from __future__ import annotations

import uuid
from typing import Any

from opn_oracle.ai.citable_sources import content_checksum, server_owned_candidate_id
from opn_oracle.ai.market_materialize import (
    _merge_actor_identifiers,
    _structured_identifier_snapshot,
)
from opn_oracle.ai.schemas import MarketActorCandidate, MarketActorDiscoveryOutput


def test_schema_accepts_structured_snapshot_fields() -> None:
    sid = uuid.uuid4()
    cand = MarketActorCandidate.model_validate(
        {
            "actor_type": "research_group",
            "organization": "Institut Néel",
            "affiliation": "CNRS",
            "country": "FR",
            "summary": "Graphene lab",
            "evidence_ids": [sid],
            "confidence": 70,
            "ids": {"rnsr": "200717524X", "ror": "04dbzz632"},
            "identity_status": "validated",
            "identity_reasons": ["ror_exact"],
            "rank": 1,
            "score": 70.0,
            "score_breakdown": {"identity": 40.0, "country": 10.0},
            "ranking_reasons": ["identity_validated"],
            "parent_organization": "CNRS",
            "merge_rules_applied": ["same_rnsr"],
            "candidate_key": "rnsr:200717524X",
        }
    )
    assert cand.ids["rnsr"] == "200717524X"
    assert cand.identity_status == "validated"
    assert cand.score_breakdown["identity"] == 40.0
    out = MarketActorDiscoveryOutput(candidates=[cand], warnings=[])
    assert len(out.candidates) == 1


def test_merge_identifiers_never_overwrites() -> None:
    existing = {"rnsr": "200717524X", "ror": "04dbzz632"}
    merged = _merge_actor_identifiers(existing, {"rnsr": "OTHER", "hal_structure": "1043183"})
    assert merged["rnsr"] == "200717524X"
    assert merged["ror"] == "04dbzz632"
    assert merged["hal_structure"] == "1043183"
    assert any(c["key"] == "rnsr" for c in merged.get("identifier_conflicts") or [])


def test_structured_identifier_snapshot_filters() -> None:
    snap = _structured_identifier_snapshot(
        {
            "ids": {
                "rnsr": "200717524X",
                "ror": "04dbzz632",
                "evil": "nope",
                "hal_structure": "1043183",
            }
        }
    )
    assert snap == {
        "rnsr": "200717524X",
        "ror": "04dbzz632",
        "hal_structure": "1043183",
    }


def test_unresolved_not_validated_label() -> None:
    """UI contract: unresolved must never be serialized as validated."""
    cand = MarketActorCandidate.model_validate(
        {
            "actor_type": "research_group",
            "organization": "NEEL Trimarans",
            "country": "FR",
            "summary": "boat company homonym",
            "evidence_ids": [uuid.uuid4()],
            "confidence": 10,
            "ids": {"ror": "05neelt99"},
            "identity_status": "unresolved",
            "unresolved_reason": "no_strong_crosswalk_to_neel_lab",
        }
    )
    assert cand.identity_status != "validated"
    assert cand.identity_status == "unresolved"


def _build_artifact_row(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    candidates: list[dict[str, Any]],
    reserved: list[dict[str, Any]],
    version: int = 1,
) -> Any:
    from opn_oracle.ai.models import AIArtifact

    art = AIArtifact(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        agent="market_actor_discovery",
        schema_name="MarketActorDiscoveryOutput",
        schema_version="1",
        status="candidate",
        version=version,
        input={},
        output={
            "candidates": candidates,
            "warnings": [],
            "reserved_citable_sources": reserved,
        },
        provenance={},
    )
    return art


def test_content_checksum_formula_aligned() -> None:
    title = "Institut Néel"
    snippet = "graphene"
    url = "https://aurehal.archives-ouvertes.fr/structure/1043183"
    ck = content_checksum(title=title, snippet=snippet, url=url)
    assert ck.startswith("sha256:")
    assert len(ck) == len("sha256:") + 64


def test_server_owned_candidate_id_stable() -> None:
    sid = str(uuid.uuid4())
    a = server_owned_candidate_id(execution_key="run-1", name="Institut Néel", evidence_ids=[sid])
    b = server_owned_candidate_id(execution_key="run-1", name="Institut Néel", evidence_ids=[sid])
    c = server_owned_candidate_id(execution_key="run-1", name="NEEL Trimarans", evidence_ids=[sid])
    assert a == b
    assert a != c
