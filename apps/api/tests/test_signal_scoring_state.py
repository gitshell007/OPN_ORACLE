from __future__ import annotations

import uuid

from opn_oracle.oracle.models import DossierSignal
from opn_oracle.oracle.routes import _serialize


def _link(*, status: str = "new", score_details: dict[str, object] | None = None) -> DossierSignal:
    return DossierSignal(
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        status=status,
        score_details=score_details or {},
    )


def test_signal_serialization_marks_untriaged_signal_as_pending() -> None:
    assert _serialize(_link())["scoring_state"] == "pending"


def test_signal_serialization_marks_ai_triage_as_provisional() -> None:
    serialized = _serialize(_link(score_details={"triage": {"artifact_id": "example"}}))
    assert serialized["scoring_state"] == "provisional"


def test_signal_serialization_marks_human_review_as_reviewed() -> None:
    assert _serialize(_link(status="reviewed"))["scoring_state"] == "reviewed"
