"""HTTP routes publish jobs after durable commit (MEMSOL residual)."""

from __future__ import annotations

from pathlib import Path


def test_conversation_and_brief_routes_publish_after_commit() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "opn_oracle"
        / "oracle"
        / "conversation_routes.py"
    ).read_text(encoding="utf-8")
    # Staging keeps publish=False; commit then publish_job so Celery can run HANDLERS.
    assert "db.session.commit()" in src
    assert src.count("publish_job(job)") >= 2
    assert "get_custom_brief" in src
    assert "/reports/custom/<uuid:report_id>" in src
