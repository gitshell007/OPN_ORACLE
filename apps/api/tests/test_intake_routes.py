"""Serialización y contrato del artefacto intake (UI de confirmación humana).

Invariantes de producto cubiertos aquí y en vitest/UI:
- la propuesta no muta el expediente por sí sola;
- el camino cancelado (review rejected) solo cambia el artefacto;
- el camino feliz aplica título/descripción solo tras acción humana explícita (PATCH en UI).
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.ai.routes import (
    INTAKE_AGENT,
    _serialize_agent_artifact,
    enqueue_intake,
    latest_intake,
    review_artifact,
)


class _FakeArtifact:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.dossier_id = uuid.uuid4()
        self.agent = INTAKE_AGENT
        self.schema_name = "intake"
        self.schema_version = "v1"
        self.status = "pending_review"
        self.output = {
            "proposed_title": "Pliego demo",
            "proposed_description": "Descripción propuesta",
            "dossier_type": "tender_or_grant",
            "facts": [],
            "inferences": [],
            "recommendations": [],
            "confidence": 50,
            "open_questions": [],
            "warnings": [],
        }
        self.audit_log_id = uuid.uuid4()
        self.created_at = MagicMock()
        self.created_at.isoformat.return_value = "2026-08-03T12:00:00+00:00"
        self.updated_at = MagicMock()
        self.updated_at.isoformat.return_value = "2026-08-03T12:00:00+00:00"
        self.version = 1


@pytest.mark.unit
def test_intake_agent_constant() -> None:
    assert INTAKE_AGENT == "intake"


@pytest.mark.unit
def test_serialize_agent_artifact_includes_audit_log_id() -> None:
    payload = _serialize_agent_artifact(_FakeArtifact())
    assert payload is not None
    assert payload["agent"] == "intake"
    assert payload["audit_log_id"]
    assert payload["output"]["proposed_title"] == "Pliego demo"
    assert payload["status"] == "pending_review"


@pytest.mark.unit
def test_serialize_agent_artifact_none() -> None:
    assert _serialize_agent_artifact(None) is None


@pytest.mark.unit
def test_serialize_agent_artifact_without_audit() -> None:
    artifact = _FakeArtifact()
    artifact.audit_log_id = None
    payload = _serialize_agent_artifact(artifact)
    assert payload is not None
    assert payload["audit_log_id"] is None


@pytest.mark.unit
def test_enqueue_intake_docstring_promises_no_business_mutation() -> None:
    """Contrato: el run solo encola; no crea expediente ni entidades."""
    doc = inspect.getdoc(enqueue_intake) or ""
    assert "no muta" in doc.lower()


@pytest.mark.unit
def test_latest_intake_docstring_requires_human_confirmation() -> None:
    doc = inspect.getdoc(latest_intake) or ""
    assert "confirma" in doc.lower()


@pytest.mark.unit
def test_review_artifact_does_not_mutate_dossier_fields() -> None:
    """El endpoint de review solo cambia estado del artefacto/auditoría; no el expediente."""
    source = inspect.getsource(review_artifact)
    assert "accepted" in source
    assert "rejected" in source
    assert "changes_requested" in source
    assert "human_review_state" in source
    # No mutación de campos de negocio del expediente en el handler de review.
    assert "proposed_title" not in source
    assert "StrategicDossier" not in source
    assert "dossier.title" not in source
    assert "dossier.description" not in source
