from __future__ import annotations

import copy
import uuid
from types import SimpleNamespace
from typing import Any

from opn_oracle.oracle.procurement_search_feedback import (
    procurement_search_feedback_digest_payload,
)


def _profile(*, version: int = 2) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), version=version)


def _feedback(
    *,
    folder_id: str,
    verdict: str,
    title: str,
    cpvs: list[str],
    plan_version: int = 2,
    reason: str | None = None,
    note: str = "",
    user_id: uuid.UUID | None = None,
    superseded: bool = False,
    withdrawn: bool = False,
) -> Any:
    return SimpleNamespace(
        plan_version=plan_version,
        folder_id=folder_id,
        actor_user_id=user_id or uuid.uuid4(),
        verdict=verdict,
        reason=reason,
        note=note,
        tender_title=title,
        tender_cpvs=cpvs,
        superseded_at=object() if superseded else None,
        withdrawn_at=object() if withdrawn else None,
    )


def test_feedback_digest_is_stable_and_explains_term_and_cpv_differences() -> None:
    profile = _profile()
    rejected = _feedback(
        folder_id="EXP-1",
        verdict="not_relevant",
        reason="wrong_sector",
        title="Mantenimiento y limpieza técnica",
        cpvs=["18100000"],
        note="No fabricamos este servicio.",
    )
    relevant = _feedback(
        folder_id="EXP-2",
        verdict="relevant",
        title="Vehículos de emergencia",
        cpvs=["35110000"],
    )

    first = procurement_search_feedback_digest_payload(
        profile,
        [rejected, relevant],
    )
    second = procurement_search_feedback_digest_payload(
        profile,
        [relevant, rejected],
    )

    assert first == second
    assert first["counts"] == {
        "total": 2,
        "distinct_folders": 2,
        "relevant": 1,
        "not_relevant": 1,
    }
    assert first["reasons"]["wrong_sector"] == 1
    assert {item["value"] for item in first["exclusion_candidates"]["terms"]} >= {
        "mantenimiento",
        "limpieza",
        "tecnica",
    }
    assert {item["value"] for item in first["reinforcement_candidates"]["terms"]} >= {
        "vehiculos",
        "emergencia",
    }
    assert first["exclusion_candidates"]["cpvs"][0]["code"] == "18100000"
    assert first["reinforcement_candidates"]["cpvs"][0]["code"] == "35110000"
    assert len(first["digest_hash"]) == 64
    assert len(first["feedback_state_hash"]) == 64


def test_feedback_digest_hash_changes_with_feedback_but_ignores_history() -> None:
    profile = _profile()
    current = _feedback(
        folder_id="EXP-1",
        verdict="not_relevant",
        reason="other",
        title="Limpieza industrial",
        cpvs=["18100000"],
        note="Fuera de foco.",
    )
    superseded = _feedback(
        folder_id="EXP-OLD",
        verdict="relevant",
        title="No debe entrar",
        cpvs=["35110000"],
        superseded=True,
    )
    withdrawn = _feedback(
        folder_id="EXP-WITHDRAWN",
        verdict="relevant",
        title="Tampoco debe entrar",
        cpvs=["35110000"],
        withdrawn=True,
    )
    baseline = procurement_search_feedback_digest_payload(
        profile,
        [current, superseded, withdrawn],
    )
    without_history = procurement_search_feedback_digest_payload(
        profile,
        [current],
    )
    changed = copy.copy(current)
    changed.note = "Motivo corregido."
    changed_digest = procurement_search_feedback_digest_payload(
        profile,
        [changed],
    )

    assert baseline == without_history
    assert baseline["counts"]["total"] == 1
    assert baseline["digest_hash"] != changed_digest["digest_hash"]


def test_feedback_digest_counts_only_current_plan_as_new() -> None:
    profile = _profile(version=3)
    rows = [
        _feedback(
            folder_id="EXP-OLD",
            verdict="not_relevant",
            reason="buyer",
            title="Compra anterior",
            cpvs=[],
            plan_version=2,
        ),
        _feedback(
            folder_id="EXP-NEW",
            verdict="relevant",
            title="Compra actual",
            cpvs=[],
            plan_version=3,
        ),
    ]

    digest = procurement_search_feedback_digest_payload(profile, rows)

    assert digest["plan_version"] == 3
    assert digest["new_feedback_count"] == 1
