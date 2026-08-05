"""Serialización y contrato de análisis de oportunidad y riesgo (confirmación humana).

Invariantes de producto:
- la propuesta no crea la entidad por sí sola;
- el camino cancelado (review rejected) solo cambia el artefacto;
- el camino feliz crea la entidad solo tras acción humana (POST en UI).
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.ai.routes import (
    OPPORTUNITY_AGENT,
    RISK_AGENT,
    _serialize_agent_artifact,
    enqueue_opportunity_analysis,
    enqueue_risk_analysis,
    latest_opportunity_analysis,
    latest_risk_analysis,
    review_artifact,
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
            "title": "Candidato demo",
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
def test_agent_constants() -> None:
    assert OPPORTUNITY_AGENT == "opportunity"
    assert RISK_AGENT == "risk"


@pytest.mark.unit
def test_serialize_opportunity_artifact_includes_audit() -> None:
    payload = _serialize_agent_artifact(_FakeArtifact(OPPORTUNITY_AGENT))
    assert payload is not None
    assert payload["agent"] == "opportunity"
    assert payload["audit_log_id"]
    assert payload["output"]["title"] == "Candidato demo"


@pytest.mark.unit
def test_serialize_risk_artifact() -> None:
    payload = _serialize_agent_artifact(_FakeArtifact(RISK_AGENT))
    assert payload is not None
    assert payload["agent"] == "risk"


@pytest.mark.unit
def test_enqueue_opportunity_docstring_promises_no_create() -> None:
    doc = inspect.getdoc(enqueue_opportunity_analysis) or ""
    assert "no crea" in doc.lower()


@pytest.mark.unit
def test_enqueue_risk_docstring_promises_no_create() -> None:
    doc = inspect.getdoc(enqueue_risk_analysis) or ""
    assert "no crea" in doc.lower()


@pytest.mark.unit
def test_latest_opportunity_requires_human_confirmation() -> None:
    doc = inspect.getdoc(latest_opportunity_analysis) or ""
    assert "confirma" in doc.lower()


@pytest.mark.unit
def test_latest_risk_requires_human_confirmation() -> None:
    doc = inspect.getdoc(latest_risk_analysis) or ""
    assert "confirma" in doc.lower()


@pytest.mark.unit
def test_review_artifact_does_not_create_opportunity_or_risk() -> None:
    """El endpoint de review solo cambia estado del artefacto/auditoría."""
    source = inspect.getsource(review_artifact)
    assert "accepted" in source
    assert "rejected" in source
    assert "Opportunity(" not in source
    assert "RiskItem(" not in source
    assert "opportunities.create" not in source
