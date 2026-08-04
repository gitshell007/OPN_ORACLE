"""Contrato de priorización de actores y resolución de entidades (confirmación humana)."""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.ai.routes import (
    ACTOR_PARTNERSHIP_AGENT,
    ENTITY_RESOLUTION_AGENT,
    _serialize_agent_artifact,
    enqueue_actor_partnership,
    enqueue_entity_resolution,
    latest_actor_partnership,
    latest_entity_resolution,
)


class _FakeArtifact:
    def __init__(self, agent: str) -> None:
        self.id = uuid.uuid4()
        self.dossier_id = uuid.uuid4()
        self.agent = agent
        self.schema_name = agent
        self.schema_version = "v1"
        self.status = "pending_review"
        self.output = {
            "facts": [],
            "inferences": [],
            "recommendations": [],
            "confidence": 50,
            "open_questions": [],
            "warnings": [],
        }
        self.audit_log_id = uuid.uuid4()
        self.created_at = MagicMock()
        self.created_at.isoformat.return_value = "2026-08-04T03:00:00+00:00"
        self.updated_at = MagicMock()
        self.updated_at.isoformat.return_value = "2026-08-04T03:00:00+00:00"
        self.version = 1


@pytest.mark.unit
def test_agent_constants() -> None:
    assert ACTOR_PARTNERSHIP_AGENT == "actor_partnership"
    assert ENTITY_RESOLUTION_AGENT == "entity_resolution"


@pytest.mark.unit
def test_serialize_actor_partnership_artifact() -> None:
    payload = _serialize_agent_artifact(_FakeArtifact(ACTOR_PARTNERSHIP_AGENT))
    assert payload is not None
    assert payload["agent"] == "actor_partnership"
    assert payload["audit_log_id"]


@pytest.mark.unit
def test_serialize_entity_resolution_artifact() -> None:
    payload = _serialize_agent_artifact(_FakeArtifact(ENTITY_RESOLUTION_AGENT))
    assert payload is not None
    assert payload["agent"] == "entity_resolution"


@pytest.mark.unit
def test_enqueue_actor_partnership_no_mutate() -> None:
    doc = inspect.getdoc(enqueue_actor_partnership) or ""
    assert "no muta" in doc.lower()


@pytest.mark.unit
def test_enqueue_entity_resolution_no_merge() -> None:
    doc = inspect.getdoc(enqueue_entity_resolution) or ""
    assert "no fusiona" in doc.lower()


@pytest.mark.unit
def test_latest_actor_partnership_requires_confirm() -> None:
    doc = inspect.getdoc(latest_actor_partnership) or ""
    assert "confirma" in doc.lower()


@pytest.mark.unit
def test_latest_entity_resolution_requires_confirm() -> None:
    doc = inspect.getdoc(latest_entity_resolution) or ""
    assert "confirma" in doc.lower()
